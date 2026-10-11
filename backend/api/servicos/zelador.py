"""Zelador de fontes: roda a verificação do catálogo sozinho, sem depender de o
usuário abrir a Galeria.

Uma passada (`executar_passada`) faz o mesmo que a carona `?aquecer=true`
(`api/servicos/aquecimento.py`), só que disparada pelo relógio e limitada por um
orçamento por hora. A política de QUEM verificar e QUANDO é de
`core/ciclo_de_vida.py`; o backoff de quem falhou, de `verificacao_de_anime`; o
que o zelador pode fazer (ligado/desligado) vem do arquivo de horários
(`api/servicos/horarios.py`), relido a cada passada.

Único caso em que ele abre o navegador (Chrome visível, para o Turnstile): renovar
a sessão de um site que o cliente leve não passa mais. Só dentro das janelas de
`config/horarios.toml` e até o teto diário de aberturas; fora disso o anime fica
pendente (`PRECISA_SESSAO`) até a próxima janela.

Fire-and-forget como o resto: `executar_passada` agenda as sondagens e volta — o
resultado entra no banco e aparece na leitura seguinte do catálogo.
"""

import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.servicos import aquecimento
from api.servicos import catalogo as servico_catalogo
from api.servicos import sondagem as servico_sondagem
from api.servicos.horarios import LeitorDeHorarios
from core.enums import TarefaDeVerificacao
from core.erros import FalhaDeExtracao
from db import aberturas_de_navegador, verificacao
from extractors import circuit_breaker, sessao_cache
from extractors.servico import listar_episodios_em
from models.anime import Anime
from models.fonte_anime import FonteAnime

logger = logging.getLogger(__name__)

_SessionMaker = async_sessionmaker[AsyncSession]

# Teto de sondagens (scrapes de site) por hora, independente da política: se um
# bug de agendamento gerar rajada, é aqui que ela para. Medida pelas tentativas
# registradas em `verificacao_de_anime` mais as que ainda estão em voo.
TETO_DE_SONDAGENS_POR_HORA = 30

# Intervalo entre passadas e espera antes da primeira: ao subir a API, a Home
# ainda está aquecendo o cache de feeds (AniList + TMDB) e uma rajada de
# sondagens competiria com ela — a primeira passada espera.
INTERVALO_ENTRE_PASSADAS_S = 60
ESPERA_INICIAL_S = 120


class Zelador:
    def __init__(
        self,
        sessionmaker: _SessionMaker,
        leitor: LeitorDeHorarios | None = None,
        *,
        intervalo_s: float = INTERVALO_ENTRE_PASSADAS_S,
        espera_inicial_s: float = ESPERA_INICIAL_S,
    ):
        self._sessionmaker = sessionmaker
        self._leitor = leitor or LeitorDeHorarios()
        self._intervalo_s = intervalo_s
        self._espera_inicial_s = espera_inicial_s

    async def rodar(self) -> None:
        """Laço do zelador: espera a partida da API assentar e então executa uma
        passada a cada intervalo, até ser cancelado (desligamento da API). Uma
        passada que falha é registrada e o laço segue — o zelador não pode morrer
        em silêncio por um erro de banco ou de rede."""
        logger.info(
            "zelador de fontes iniciado (primeira passada em %ss, depois a cada %ss)",
            self._espera_inicial_s,
            self._intervalo_s,
        )
        await asyncio.sleep(self._espera_inicial_s)
        while True:
            try:
                await self.executar_passada()
            except Exception:
                logger.exception("zelador: passada falhou")
            await asyncio.sleep(self._intervalo_s)

    async def executar_passada(self, agora: datetime | None = None) -> None:
        """No-op com o zelador desligado no arquivo de horários ou com o orçamento
        da hora esgotado. `agora` é o relógio LOCAL com fuso (as janelas de
        horário são locais); o padrão é `datetime.now().astimezone()`, e o
        parâmetro existe para teste."""
        if not self._leitor.atual().ativo:
            return
        agora = agora or datetime.now().astimezone()
        await self._renovar_sessao_se_permitido(agora)
        async with self._sessionmaker() as sessao:
            restante = await self._orcamento_de_sondagens(sessao, agora)
            if restante <= 0:
                logger.info("zelador: orçamento de sondagens da hora esgotado")
                return
            animes, grupos = await servico_catalogo.animes_do_catalogo(sessao)
            com_episodios = await servico_catalogo.ids_com_episodios(
                sessao, [anime.id for anime in animes]
            )
            await aquecimento.aquecer_catalogo(
                self._sessionmaker,
                sessao,
                animes,
                grupos,
                com_episodios,
                max_sondagens=restante,
            )

    async def _orcamento_de_sondagens(self, sessao: AsyncSession, agora: datetime) -> int:
        usadas = await verificacao.tentativas_desde(
            sessao, TarefaDeVerificacao.FONTE, agora - timedelta(hours=1)
        )
        return TETO_DE_SONDAGENS_POR_HORA - usadas - servico_sondagem.quantidade_em_voo()

    async def _renovar_sessao_se_permitido(self, agora: datetime) -> None:
        """Renova no máximo UM site por passada, e só se: a janela de horário
        está aberta, o teto diário não estourou e o site não está em cooldown.
        Se já existe sessão válida (ex. o usuário usou o site), basta liberar os
        animes da espera — sem abrir navegador."""
        config = self._leitor.atual()
        if not config.navegador_liberado_em(agora):
            return
        meia_noite_local = agora.replace(hour=0, minute=0, second=0, microsecond=0)
        async with self._sessionmaker() as sessao:
            if (
                await aberturas_de_navegador.aberturas_desde(sessao, meia_noite_local)
                >= config.teto_diario_de_aberturas
            ):
                return
            aguardando = await verificacao.dominios_aguardando_sessao(
                sessao, TarefaDeVerificacao.FONTE
            )
        for dominio, anime_id in aguardando:
            if await circuit_breaker.esta_em_cooldown(self._sessionmaker, dominio):
                continue
            if await sessao_cache.carregar(self._sessionmaker, dominio) is None:
                if not await self._abrir_navegador_e_renovar(dominio, anime_id, agora):
                    return  # uma tentativa por passada, mesmo que falhe
            await self._liberar(dominio, agora)
            return

    async def _abrir_navegador_e_renovar(
        self, dominio: str, anime_id: int, agora: datetime
    ) -> bool:
        """Lista os episódios do anime que falhou, SEM o modo de segundo plano: o
        cliente leve é rejeitado e `resiliencia.chamar` escala para o navegador,
        que resolve o Turnstile e guarda a sessão. A abertura é registrada antes
        — uma que falhou também incomodou e conta no teto."""
        async with self._sessionmaker() as sessao:
            linha = (
                await sessao.execute(
                    select(FonteAnime.identificador_no_site, Anime.numero_temporada)
                    .join(Anime, Anime.id == FonteAnime.anime_id)
                    .where(FonteAnime.anime_id == anime_id, FonteAnime.site_dominio == dominio)
                    .limit(1)
                )
            ).first()
        if linha is None:
            return False
        identificador, temporada = linha
        await aberturas_de_navegador.registrar_abertura(self._sessionmaker, dominio, agora)
        logger.info("zelador: abrindo o navegador para renovar a sessão de %s", dominio)
        try:
            await listar_episodios_em(self._sessionmaker, dominio, identificador, temporada)
        except FalhaDeExtracao as excecao:
            logger.warning("zelador: renovação de sessão de %s falhou: %s", dominio, excecao)
            return False
        return True

    async def _liberar(self, dominio: str, agora: datetime) -> None:
        liberados = await verificacao.liberar_espera_por_sessao(
            self._sessionmaker, TarefaDeVerificacao.FONTE, dominio, agora
        )
        logger.info("zelador: %d anime(s) de %s liberados da espera", liberados, dominio)

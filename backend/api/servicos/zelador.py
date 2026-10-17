"""Zelador de fontes: roda a verificação do catálogo sozinho, sem depender de o
usuário abrir a Galeria.

Uma passada (`executar_passada`) agenda a sondagem das fontes e o aquecimento do
status (`api/servicos/aquecimento.py`), limitada por um orçamento por hora. A
política de QUEM verificar e QUANDO é de `core/ciclo_de_vida.py`; o backoff de
quem falhou, de `verificacao_de_anime`. A sondagem roda em segundo plano
(`resiliencia.em_segundo_plano`): nunca abre navegador.

Fire-and-forget como o resto: `executar_passada` agenda as sondagens e volta — o
resultado entra no banco e aparece na leitura seguinte do catálogo.
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.servicos import aquecimento
from api.servicos import catalogo as servico_catalogo
from api.servicos import sondagem as servico_sondagem
from core.enums import TarefaDeVerificacao
from db import verificacao

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
        *,
        intervalo_s: float = INTERVALO_ENTRE_PASSADAS_S,
        espera_inicial_s: float = ESPERA_INICIAL_S,
    ):
        self._sessionmaker = sessionmaker
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
        """No-op com o orçamento da hora esgotado. `agora` existe para teste."""
        agora = agora or datetime.now(UTC)
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

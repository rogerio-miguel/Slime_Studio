"""Zelador de fontes: roda a verificação do catálogo sozinho, sem depender de o
usuário abrir a Galeria.

Uma passada (`executar_passada`) faz o mesmo que a carona `?aquecer=true`
(`api/servicos/aquecimento.py`), só que disparada pelo relógio e limitada por um
orçamento por hora. A política de QUEM verificar e QUANDO é de
`core/ciclo_de_vida.py`; o backoff de quem falhou, de `verificacao_de_anime`; o
que o zelador pode fazer (ligado/desligado) vem do arquivo de horários
(`api/servicos/horarios.py`), relido a cada passada.

Fire-and-forget como o resto: `executar_passada` agenda as sondagens e volta — o
resultado entra no banco e aparece na leitura seguinte do catálogo.
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.servicos import aquecimento
from api.servicos import catalogo as servico_catalogo
from api.servicos import sondagem as servico_sondagem
from api.servicos.horarios import LeitorDeHorarios
from core.enums import TarefaDeVerificacao
from db import verificacao

logger = logging.getLogger(__name__)

_SessionMaker = async_sessionmaker[AsyncSession]

# Teto de sondagens (scrapes de site) por hora, independente da política: se um
# bug de agendamento gerar rajada, é aqui que ela para. Medida pelas tentativas
# registradas em `verificacao_de_anime` mais as que ainda estão em voo.
TETO_DE_SONDAGENS_POR_HORA = 30


class Zelador:
    def __init__(self, sessionmaker: _SessionMaker, leitor: LeitorDeHorarios | None = None):
        self._sessionmaker = sessionmaker
        self._leitor = leitor or LeitorDeHorarios()

    async def executar_passada(self, agora: datetime | None = None) -> None:
        """No-op com o zelador desligado no arquivo de horários ou com o orçamento
        da hora esgotado. `agora` existe para teste."""
        if not self._leitor.atual().ativo:
            return
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

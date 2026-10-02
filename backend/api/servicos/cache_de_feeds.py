"""Persistência dos feeds de descoberta da Home (`models/cache_de_feed.py`).

`integrations/servico.py` não conhece banco: a API injeta `gravar_feed` no lifespan e
semeia os caches de memória com `carregar_feeds_persistidos` (ver
`integrations.servico.instalar_persistencia_de_feeds`/`restaurar_feeds_persistidos`).
"""

import logging
from datetime import UTC, datetime, timedelta

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from integrations.base import AnimeEmAlta
from models.cache_de_feed import CacheDeFeed

logger = logging.getLogger(__name__)

_SessionMaker = async_sessionmaker[AsyncSession]

_ITENS = TypeAdapter(list[AnimeEmAlta])

# Feed mais velho que isto não vale como "dado velho útil" (capa/ranking de semanas
# atrás enganaria mais do que ajudaria): vira cache-miss normal e espera a busca real.
_IDADE_MAXIMA = timedelta(days=7)


async def gravar_feed(sessionmaker: _SessionMaker, chave: str, itens: list[AnimeEmAlta]) -> None:
    async with sessionmaker() as sessao, sessao.begin():
        await sessao.merge(
            CacheDeFeed(
                chave=chave,
                itens_json=_ITENS.dump_json(itens).decode(),
                atualizado_em=datetime.now(UTC),
            )
        )


async def carregar_feeds_persistidos(sessionmaker: _SessionMaker) -> dict[str, list[AnimeEmAlta]]:
    limite = datetime.now(UTC) - _IDADE_MAXIMA
    async with sessionmaker() as sessao:
        linhas = (await sessao.execute(select(CacheDeFeed))).scalars().all()

    feeds: dict[str, list[AnimeEmAlta]] = {}
    for linha in linhas:
        if linha.atualizado_em < limite:
            continue
        try:
            feeds[linha.chave] = _ITENS.validate_json(linha.itens_json)
        except ValidationError as excecao:
            # Formato de `AnimeEmAlta` mudou desde a gravação: descarta, a busca real refaz.
            logger.warning("feed persistido %r ilegível, descartado: %s", linha.chave, excecao)
    return feeds

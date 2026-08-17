"""Dependências de injeção do FastAPI: config e sessão de banco por request."""

from collections.abc import AsyncIterator

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config import Config

_SessionMaker = async_sessionmaker[AsyncSession]


def obter_config(request: Request) -> Config:
    return request.app.state.config


def obter_sessionmaker(request: Request) -> _SessionMaker:
    return request.app.state.sessionmaker


async def obter_sessao(
    sessionmaker: _SessionMaker = Depends(obter_sessionmaker),
) -> AsyncIterator[AsyncSession]:
    async with sessionmaker() as sessao:
        yield sessao

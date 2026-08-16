"""Dependências de injeção do FastAPI: config/sessão de banco por request, e os
dois gates de autenticação (HTTP e WebSocket — ESPECIFICACAO.md §5/§8.2).

`exigir_autenticacao`/`exigir_autenticacao_ws` comparam o mesmo cookie contra o
mesmo `admin_access_token`, mas levantam tipos diferentes: uma rota WS que
levantasse `HTTPException` daria um erro de handshake obscuro no cliente — tem
que ser `WebSocketException(code=1008)`.
"""

from collections.abc import AsyncIterator

from fastapi import Depends, HTTPException, Request, WebSocket, WebSocketException, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.seguranca import NOME_COOKIE, token_valido
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


def exigir_autenticacao(request: Request, config: Config = Depends(obter_config)) -> None:
    cookie = request.cookies.get(NOME_COOKIE)
    if config.admin_access_token is None or not token_valido(cookie, config.admin_access_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="não autenticado")


async def exigir_autenticacao_ws(websocket: WebSocket) -> None:
    config: Config = websocket.app.state.config
    cookie = websocket.cookies.get(NOME_COOKIE)
    if config.admin_access_token is None or not token_valido(cookie, config.admin_access_token):
        raise WebSocketException(code=1008)

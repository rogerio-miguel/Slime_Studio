"""Defesas de fronteira da API local (sem auth, uso pessoal): `TrustedHostMiddleware`
(no `main.py`) barra DNS rebinding pelo `Host`; `ProtecaoDeOrigem` barra CSRF e
cross-site WebSocket hijacking pelo `Origin`. O CORS sozinho não basta: ele impede a
*leitura* da resposta, não o envio de uma escrita sem preflight. `CabecalhosDeSeguranca`
e `limitar` completam: nosniff nas respostas e teto de taxa nas rotas que disparam
scraping/rede.
"""

import time
from collections import deque
from collections.abc import Sequence

from fastapi import Depends, HTTPException, Request, status
from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_METODOS_SEGUROS = frozenset({"GET", "HEAD", "OPTIONS"})
_CODIGO_WS_VIOLACAO_DE_POLITICA = 1008


class ProtecaoDeOrigem:
    """Middleware ASGI puro (cobre HTTP e WebSocket, o que `BaseHTTPMiddleware` não faz).

    Escrita HTTP (método não seguro) e handshake WebSocket com `Origin` presente só
    passam se ele estiver na allowlist exata. `Origin` ausente passa: navegador sempre
    o envia em escrita cross-origin, então a ausência indica cliente não-navegador
    (script, CLI), que não é o vetor de CSRF. Leituras HTTP e o preflight `OPTIONS`
    ficam com o CORS.
    """

    def __init__(self, app: ASGIApp, origens_permitidas: Sequence[str]) -> None:
        self._app = app
        self._origens_permitidas = frozenset(origens_permitidas)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket") and not self._permitida(scope):
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": _CODIGO_WS_VIOLACAO_DE_POLITICA})
            else:
                resposta = JSONResponse({"detail": "origem não permitida"}, status_code=403)
                await resposta(scope, receive, send)
            return
        await self._app(scope, receive, send)

    def _permitida(self, scope: Scope) -> bool:
        if scope["type"] == "http" and scope["method"] in _METODOS_SEGUROS:
            return True
        origem = Headers(scope=scope).get("origin")
        return origem is None or origem in self._origens_permitidas


class CabecalhosDeSeguranca:
    """Middleware ASGI puro que acrescenta `X-Content-Type-Options: nosniff` (segmentos
    HLS, thumbs e JSON não devem ser reinterpretados pelo navegador) e
    `Referrer-Policy: no-referrer` a toda resposta HTTP. Sem `Cross-Origin-Resource-Policy`:
    o front pode rodar em `127.0.0.1` e a API em `localhost` (sites diferentes), e um CORP
    `same-site` derrubaria esse fluxo por um ganho pequeno (Host/Origin/CORS já cobrem)."""

    _CABECALHOS = {"x-content-type-options": "nosniff", "referrer-policy": "no-referrer"}

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        async def enviar_com_cabecalhos(mensagem: Message) -> None:
            if mensagem["type"] == "http.response.start":
                cabecalhos = MutableHeaders(scope=mensagem)
                for nome, valor in self._CABECALHOS.items():
                    cabecalhos[nome] = valor
            await send(mensagem)

        await self._app(scope, receive, enviar_com_cabecalhos)


class LimitesDeTaxa:
    """Janela deslizante em memória de processo, um balde por nome de rota. Uso pessoal,
    um usuário: o balde é global à rota (não por cliente). Vive em `app.state.limites`
    (criado no lifespan), então cada app — inclusive o de cada teste — começa zerado."""

    def __init__(self) -> None:
        self._marcas: dict[str, deque[float]] = {}

    def verificar(self, nome: str, maximo: int, janela_s: float) -> None:
        agora = time.monotonic()
        marcas = self._marcas.setdefault(nome, deque())
        while marcas and agora - marcas[0] >= janela_s:
            marcas.popleft()
        if len(marcas) >= maximo:
            espera = max(1, int(janela_s - (agora - marcas[0])) + 1)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"muitas requisições; tente de novo em {espera}s",
                headers={"Retry-After": str(espera)},
            )
        marcas.append(agora)


def limitar(nome: str, *, maximo: int, janela_s: float = 60.0):
    """Dependência FastAPI: `dependencies=[limitar("buscar-fontes", maximo=30)]` na rota."""

    def _dependencia(request: Request) -> None:
        request.app.state.limites.verificar(nome, maximo, janela_s)

    return Depends(_dependencia)

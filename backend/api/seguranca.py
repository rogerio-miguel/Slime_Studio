"""Defesas de fronteira da API local (sem auth, uso pessoal): `TrustedHostMiddleware`
(no `main.py`) barra DNS rebinding pelo `Host`; `ProtecaoDeOrigem` barra CSRF e
cross-site WebSocket hijacking pelo `Origin`. O CORS sozinho não basta: ele impede a
*leitura* da resposta, não o envio de uma escrita sem preflight.
"""

from collections.abc import Sequence

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

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

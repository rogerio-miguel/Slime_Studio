"""Testes de `api/seguranca.py` e da allowlist de `Host` em `api/main.py`."""

from httpx import AsyncClient

from api.seguranca import ProtecaoDeOrigem

_ORIGEM_DO_FRONTEND = "http://localhost:5173"
_ORIGEM_ESTRANHA = "http://evil.example"
# Corpo vazio: a validação do Pydantic devolve 422 antes de qualquer efeito colateral
# da rota, o que basta pra distinguir "passou pelo middleware" (422) de "barrado" (403).
_ESCRITA = "/api/admin/animes"


async def test_host_estranho_e_rejeitado(cliente: AsyncClient):
    resposta = await cliente.get("/api/health", headers={"Host": "evil.example"})

    assert resposta.status_code == 400


async def test_host_local_com_porta_do_vite_passa(cliente: AsyncClient):
    resposta = await cliente.get("/api/health", headers={"Host": "localhost:5173"})

    assert resposta.status_code == 200


async def test_escrita_com_origem_estranha_e_barrada(cliente: AsyncClient):
    resposta = await cliente.post(_ESCRITA, json={}, headers={"Origin": _ORIGEM_ESTRANHA})

    assert resposta.status_code == 403


async def test_escrita_com_origem_null_e_barrada(cliente: AsyncClient):
    resposta = await cliente.post(_ESCRITA, json={}, headers={"Origin": "null"})

    assert resposta.status_code == 403


async def test_delete_com_origem_estranha_e_barrado(cliente: AsyncClient):
    resposta = await cliente.delete("/api/admin/animes/1", headers={"Origin": _ORIGEM_ESTRANHA})

    assert resposta.status_code == 403


async def test_escrita_com_origem_do_frontend_passa(cliente: AsyncClient):
    resposta = await cliente.post(_ESCRITA, json={}, headers={"Origin": _ORIGEM_DO_FRONTEND})

    assert resposta.status_code == 422


async def test_escrita_sem_origem_passa_cliente_nao_navegador(cliente: AsyncClient):
    resposta = await cliente.post(_ESCRITA, json={})

    assert resposta.status_code == 422


async def test_leitura_com_origem_estranha_nao_e_barrada_pelo_middleware(cliente: AsyncClient):
    resposta = await cliente.get("/api/health", headers={"Origin": _ORIGEM_ESTRANHA})

    assert resposta.status_code == 200
    assert "access-control-allow-origin" not in resposta.headers


async def _handshake_websocket(origem: str | None) -> list[dict]:
    """Roda `ProtecaoDeOrigem` sobre um app-sentinela e devolve o que foi enviado."""
    chamado = False

    async def app_sentinela(scope, receive, send):
        nonlocal chamado
        chamado = True

    enviados: list[dict] = []

    async def enviar(mensagem):
        enviados.append(mensagem)

    async def receber():
        return {"type": "websocket.connect"}

    cabecalhos = [(b"origin", origem.encode())] if origem is not None else []
    escopo = {"type": "websocket", "path": "/ws/admin", "headers": cabecalhos}
    await ProtecaoDeOrigem(app_sentinela, [_ORIGEM_DO_FRONTEND])(escopo, receber, enviar)
    return [{"chamado": chamado}, *enviados]


async def test_websocket_com_origem_estranha_e_fechado_sem_chegar_ao_app():
    resultado = await _handshake_websocket(_ORIGEM_ESTRANHA)

    assert resultado[0] == {"chamado": False}
    assert resultado[1]["type"] == "websocket.close"


async def test_websocket_com_origem_do_frontend_chega_ao_app():
    resultado = await _handshake_websocket(_ORIGEM_DO_FRONTEND)

    assert resultado == [{"chamado": True}]

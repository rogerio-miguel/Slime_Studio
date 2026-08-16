"""Testes de `api/rotas/auth.py` + gate de autenticação (`api/dependencias.py`).
`httpx.AsyncClient` + `ASGITransport` — sem servidor real (fixtures em
`tests/conftest.py`)."""

from httpx import AsyncClient

from api.seguranca import NOME_COOKIE
from tests.conftest import TOKEN_ADMIN_TESTE


async def test_desbloquear_com_token_correto_seta_cookie(cliente: AsyncClient):
    resposta = await cliente.post("/api/auth/desbloquear", json={"token": TOKEN_ADMIN_TESTE})

    assert resposta.status_code == 204
    assert NOME_COOKIE in resposta.cookies


async def test_desbloquear_com_token_errado_devolve_401(cliente: AsyncClient):
    resposta = await cliente.post("/api/auth/desbloquear", json={"token": "token-errado-qualquer"})

    assert resposta.status_code == 401
    assert NOME_COOKIE not in resposta.cookies


async def test_estado_sem_cookie_nao_autenticado(cliente: AsyncClient):
    resposta = await cliente.get("/api/auth/estado")

    assert resposta.status_code == 200
    assert resposta.json() == {"autenticado": False}


async def test_estado_com_cookie_valido_autenticado(cliente_autenticado: AsyncClient):
    resposta = await cliente_autenticado.get("/api/auth/estado")

    assert resposta.json() == {"autenticado": True}


async def test_sair_apaga_cookie(cliente_autenticado: AsyncClient):
    resposta = await cliente_autenticado.post("/api/auth/sair")

    assert resposta.status_code == 204
    # `httpx` reflete `Set-Cookie` com `max-age=0` como remoção do cookie do jar.
    assert resposta.cookies.get(NOME_COOKIE) is None


async def test_health_nao_exige_autenticacao(cliente: AsyncClient):
    resposta = await cliente.get("/api/health")

    assert resposta.status_code == 200
    assert resposta.json() == {"status": "ok"}


async def test_rota_admin_sem_cookie_devolve_401(cliente: AsyncClient):
    resposta = await cliente.get("/api/admin/jobs")

    assert resposta.status_code == 401


async def test_rota_admin_com_cookie_valido_autoriza(cliente_autenticado: AsyncClient):
    resposta = await cliente_autenticado.get("/api/admin/jobs")

    assert resposta.status_code == 200
    assert resposta.json() == []

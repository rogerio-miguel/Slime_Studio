"""Testes de `api/rotas/saude.py`."""

from httpx import AsyncClient


async def test_health_nao_exige_autenticacao(cliente: AsyncClient):
    resposta = await cliente.get("/api/health")

    assert resposta.status_code == 200
    assert resposta.json() == {"status": "ok"}

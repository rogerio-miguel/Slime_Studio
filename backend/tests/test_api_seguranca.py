"""Testes de `api/seguranca.py` e da allowlist de `Host` em `api/main.py`."""

import pytest
from fastapi import HTTPException
from httpx import AsyncClient

from api import seguranca
from api.seguranca import LimitesDeTaxa, ProtecaoDeOrigem, limitar
from core.erros import FalhaDeExtracao, FalhaDeMetadados

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


async def test_preflight_do_frontend_nao_libera_credenciais(cliente: AsyncClient):
    resposta = await cliente.options(
        _ESCRITA,
        headers={
            "Origin": _ORIGEM_DO_FRONTEND,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert resposta.status_code == 200
    assert resposta.headers["access-control-allow-origin"] == _ORIGEM_DO_FRONTEND
    assert "access-control-allow-credentials" not in resposta.headers


async def test_preflight_com_header_fora_da_lista_e_recusado(cliente: AsyncClient):
    resposta = await cliente.options(
        _ESCRITA,
        headers={
            "Origin": _ORIGEM_DO_FRONTEND,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-outro-header",
        },
    )

    assert resposta.status_code == 400


async def test_502_de_extracao_nao_vaza_detalhe_interno(app_pronto, cliente: AsyncClient):
    async def _falha():
        raise FalhaDeExtracao(
            "yt-dlp falhou em /tmp/.ytdl-x — stderr: token=segredo", dominio="animefire.one"
        )

    app_pronto.add_api_route("/_teste/falha-de-extracao", _falha)

    resposta = await cliente.get("/_teste/falha-de-extracao")

    assert resposta.status_code == 502
    assert resposta.json() == {"detail": "falha ao extrair de fonte externa em animefire.one"}
    assert "segredo" not in resposta.text


async def test_502_de_metadados_nao_vaza_detalhe_interno(app_pronto, cliente: AsyncClient):
    async def _falha():
        raise FalhaDeMetadados("AniList: HTTP 500 em https://graphql.anilist.co?key=segredo")

    app_pronto.add_api_route("/_teste/falha-de-metadados", _falha)

    resposta = await cliente.get("/_teste/falha-de-metadados")

    assert resposta.status_code == 502
    assert resposta.json() == {"detail": "falha ao consultar provedores de metadados"}


async def test_respostas_levam_nosniff_e_referrer_policy(cliente: AsyncClient):
    resposta = await cliente.get("/api/health")

    assert resposta.headers["x-content-type-options"] == "nosniff"
    assert resposta.headers["referrer-policy"] == "no-referrer"


async def test_resposta_barrada_pela_origem_tambem_leva_os_cabecalhos(cliente: AsyncClient):
    resposta = await cliente.post(_ESCRITA, json={}, headers={"Origin": _ORIGEM_ESTRANHA})

    assert resposta.status_code == 403
    assert resposta.headers["x-content-type-options"] == "nosniff"


def test_limite_de_taxa_barra_acima_do_maximo_com_retry_after():
    limites = LimitesDeTaxa()
    limites.verificar("rota", 2, 60.0)
    limites.verificar("rota", 2, 60.0)

    with pytest.raises(HTTPException) as erro:
        limites.verificar("rota", 2, 60.0)

    assert erro.value.status_code == 429
    assert int(erro.value.headers["Retry-After"]) >= 1


def test_limite_de_taxa_libera_de_novo_depois_da_janela(monkeypatch):
    agora = [1000.0]
    monkeypatch.setattr(seguranca.time, "monotonic", lambda: agora[0])
    limites = LimitesDeTaxa()
    limites.verificar("rota", 1, 60.0)

    agora[0] += 61.0

    limites.verificar("rota", 1, 60.0)


def test_limite_de_taxa_tem_balde_por_rota():
    limites = LimitesDeTaxa()
    limites.verificar("a", 1, 60.0)

    limites.verificar("b", 1, 60.0)


async def test_rota_com_limitar_responde_429_no_excesso(app_pronto, cliente: AsyncClient):
    async def _rota():
        return {"ok": True}

    app_pronto.add_api_route("/_teste/limitada", _rota, dependencies=[limitar("t", maximo=2)])

    respostas = [await cliente.get("/_teste/limitada") for _ in range(3)]

    assert [r.status_code for r in respostas] == [200, 200, 429]

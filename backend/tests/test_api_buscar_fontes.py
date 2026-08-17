"""Testes de `GET /api/animes/buscar-fontes` (`api/rotas/animes.py` ->
`extractors/servico.py::buscar_em_todas_as_fontes`). `buscar_em` é
monkeypatchado em `extractors.servico` (mesmo módulo que a rota chama via
`servico_extractors`, então o patch vale pros dois nomes) — mesmo padrão de
`test_api_animes.py` para resolução de fonte."""

import pytest
from httpx import AsyncClient

from extractors.base import ResultadoBusca


async def test_buscar_fontes_titulo_vazio_nao_chama_extrator(
    cliente: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    async def _falha_se_chamado(sessionmaker, dominio, titulo):
        raise AssertionError("buscar_em não deveria ser chamado para título vazio")

    monkeypatch.setattr("extractors.servico.buscar_em", _falha_se_chamado)

    resposta = await cliente.get("/api/animes/buscar-fontes", params={"titulo": "   "})

    assert resposta.status_code == 200
    assert resposta.json() == []


async def test_buscar_fontes_falha_de_um_extrator_nao_derruba_resposta(
    cliente: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    async def _buscar_em_fake(sessionmaker, dominio, titulo):
        if dominio == "animefire.io":
            raise RuntimeError("site fora do ar")
        return [ResultadoBusca(titulo_exibicao="Naruto", identificador="1", url="https://x/1")]

    monkeypatch.setattr("extractors.servico.buscar_em", _buscar_em_fake)

    resposta = await cliente.get("/api/animes/buscar-fontes", params={"titulo": "naruto"})

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert len(corpo) == 1
    assert corpo[0]["dominio"] == "animesdrive.online"
    assert corpo[0]["titulo_exibicao"] == "Naruto"


async def test_buscar_fontes_registrada_antes_do_catch_all_anime_id(
    cliente: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """Se `/buscar-fontes` estivesse declarada depois de `/{anime_id}`, esta
    chamada cairia no handler de `obter_anime` (que rejeitaria "buscar-fontes"
    como `anime_id: int` com 422) em vez de bater na busca em fontes."""

    async def _buscar_em_fake(sessionmaker, dominio, titulo):
        return []

    monkeypatch.setattr("extractors.servico.buscar_em", _buscar_em_fake)

    resposta = await cliente.get("/api/animes/buscar-fontes", params={"titulo": "naruto"})

    assert resposta.status_code == 200
    assert resposta.json() == []

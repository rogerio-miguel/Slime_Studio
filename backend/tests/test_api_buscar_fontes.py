"""Testes de `GET /api/animes/buscar-fontes` (`api/rotas/animes.py` ->
`extractors/servico.py::buscar_em_todas_as_fontes` ->
`api/servicos/busca.py::enriquecer_capas`). `buscar_em` é monkeypatchado em
`extractors.servico` (mesmo módulo que a rota chama via `servico_extractors`,
então o patch vale pros dois nomes) — mesmo padrão de `test_api_animes.py`
para resolução de fonte. Testes cujos candidatos falsos saem sem `capa_url`
também monkeypatcham `integrations.servico.buscar_por_titulo` — sem isso,
`enriquecer_capas` tentaria consultar AniList/Kitsu de verdade."""

from datetime import UTC, datetime

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
    assert resposta.json() == {"resultados": [], "fontes": []}


async def test_buscar_fontes_falha_de_um_extrator_nao_derruba_resposta(
    cliente: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    async def _buscar_em_fake(sessionmaker, dominio, titulo):
        if dominio == "animefire.io":
            raise RuntimeError("site fora do ar")
        return [ResultadoBusca(titulo_exibicao="Naruto", identificador="1", url="https://x/1")]

    async def _buscar_por_titulo_fake(titulo):
        return None

    monkeypatch.setattr("extractors.servico.buscar_em", _buscar_em_fake)
    monkeypatch.setattr("integrations.servico.buscar_por_titulo", _buscar_por_titulo_fake)

    resposta = await cliente.get("/api/animes/buscar-fontes", params={"titulo": "naruto"})

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert len(corpo["resultados"]) == 1
    assert corpo["resultados"][0]["dominio"] == "animesdrive.online"
    assert corpo["resultados"][0]["titulo_exibicao"] == "Naruto"

    fontes_por_dominio = {fonte["dominio"]: fonte for fonte in corpo["fontes"]}
    assert fontes_por_dominio["animefire.io"]["indisponivel"] is True
    assert fontes_por_dominio["animefire.io"]["motivo"] == "site fora do ar"
    assert fontes_por_dominio["animesdrive.online"]["indisponivel"] is False


async def test_buscar_fontes_fonte_em_cooldown_aparece_como_indisponivel(
    cliente: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """Cobre o pré-filtro de cooldown de `buscar_em_todas_as_fontes`: um
    extrator em cooldown nunca chega a `buscar_em`, mas ainda assim entra em
    `fontes` como indisponível com o motivo formatado a partir do timestamp —
    branch que não tinha teste até aqui."""

    cooldown_ate = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

    async def _esta_em_cooldown_fake(sessionmaker, dominio):
        return dominio == "animefire.io"

    async def _obter_cooldown_ate_fake(sessionmaker, dominio):
        assert dominio == "animefire.io"
        return cooldown_ate

    async def _buscar_em_fake(sessionmaker, dominio, titulo):
        assert dominio != "animefire.io", "extrator em cooldown não deveria ser chamado"
        return [ResultadoBusca(titulo_exibicao="Naruto", identificador="1", url="https://x/1")]

    async def _buscar_por_titulo_fake(titulo):
        return None

    monkeypatch.setattr("extractors.circuit_breaker.esta_em_cooldown", _esta_em_cooldown_fake)
    monkeypatch.setattr("extractors.circuit_breaker.obter_cooldown_ate", _obter_cooldown_ate_fake)
    monkeypatch.setattr("extractors.servico.buscar_em", _buscar_em_fake)
    monkeypatch.setattr("integrations.servico.buscar_por_titulo", _buscar_por_titulo_fake)

    resposta = await cliente.get("/api/animes/buscar-fontes", params={"titulo": "naruto"})

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert len(corpo["resultados"]) == 1
    assert corpo["resultados"][0]["dominio"] == "animesdrive.online"

    fontes_por_dominio = {fonte["dominio"]: fonte for fonte in corpo["fontes"]}
    assert fontes_por_dominio["animefire.io"]["indisponivel"] is True
    assert fontes_por_dominio["animefire.io"]["motivo"] == "em cooldown até 2026-01-01 12:00:00 UTC"
    assert fontes_por_dominio["animesdrive.online"]["indisponivel"] is False


async def test_buscar_fontes_cooldown_sem_timestamp_usa_motivo_generico(
    cliente: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """`obter_cooldown_ate` pode devolver `None` numa janela de corrida entre a
    checagem de `esta_em_cooldown` e a leitura do timestamp — `_formatar_motivo_
    cooldown` precisa cair pro motivo genérico em vez de chamar `.strftime()`
    em `None`."""

    async def _esta_em_cooldown_fake(sessionmaker, dominio):
        return dominio == "animefire.io"

    async def _obter_cooldown_ate_fake(sessionmaker, dominio):
        return None

    async def _buscar_em_fake(sessionmaker, dominio, titulo):
        return []

    monkeypatch.setattr("extractors.circuit_breaker.esta_em_cooldown", _esta_em_cooldown_fake)
    monkeypatch.setattr("extractors.circuit_breaker.obter_cooldown_ate", _obter_cooldown_ate_fake)
    monkeypatch.setattr("extractors.servico.buscar_em", _buscar_em_fake)

    resposta = await cliente.get("/api/animes/buscar-fontes", params={"titulo": "naruto"})

    assert resposta.status_code == 200
    fontes_por_dominio = {fonte["dominio"]: fonte for fonte in resposta.json()["fontes"]}
    assert fontes_por_dominio["animefire.io"]["motivo"] == "em cooldown"


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
    corpo = resposta.json()
    assert corpo["resultados"] == []
    assert {fonte["dominio"] for fonte in corpo["fontes"]} == {
        "animefire.io",
        "animesdrive.online",
    }

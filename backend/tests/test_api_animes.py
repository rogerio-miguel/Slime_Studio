"""Testes de `GET /api/admin/animes/{id}/episodios-remotos`
(`api/rotas/animes.py` -> `api/servicos/fontes.py`). Resolução de fonte remota é
monkeypatchada nos nomes importados em `api.servicos.fontes` — mesmo padrão de
`tests/test_api_jobs.py` para o modo "site" de criação de job."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from extractors.base import EpisodioRemoto, ResultadoBusca
from extractors.resolucao import ConfirmacaoNecessaria, FonteResolvida
from models.anime import Anime

_SessionMaker = async_sessionmaker[AsyncSession]


async def _criar_anime(sessionmaker: _SessionMaker, titulo: str) -> int:
    async with sessionmaker() as sessao:
        anime = Anime(titulo=titulo, slug=titulo.lower().replace(" ", "-"))
        sessao.add(anime)
        await sessao.commit()
        return anime.id


async def test_listar_episodios_remotos_caminho_feliz(
    cliente_autenticado: AsyncClient,
    sessionmaker_api: _SessionMaker,
    monkeypatch: pytest.MonkeyPatch,
):
    anime_id = await _criar_anime(sessionmaker_api, "Anime Remoto")

    async def _resolver_fake(sessionmaker, anime):
        return FonteResolvida(dominio="animefire.io", identificador="42")

    async def _listar_fake(sessionmaker, dominio, identificador):
        return [
            EpisodioRemoto(numero=1, url="https://x/ep1"),
            EpisodioRemoto(numero=2, url="https://x/ep2"),
        ]

    monkeypatch.setattr("api.servicos.fontes.resolver_fonte_do_anime", _resolver_fake)
    monkeypatch.setattr("api.servicos.fontes.listar_episodios_em", _listar_fake)

    resposta = await cliente_autenticado.get(f"/api/admin/animes/{anime_id}/episodios-remotos")

    assert resposta.status_code == 200
    assert resposta.json() == [{"numero": 1}, {"numero": 2}]


async def test_listar_episodios_remotos_fonte_ambigua_409(
    cliente_autenticado: AsyncClient,
    sessionmaker_api: _SessionMaker,
    monkeypatch: pytest.MonkeyPatch,
):
    anime_id = await _criar_anime(sessionmaker_api, "Anime Remoto Ambíguo")

    async def _resolver_fake(sessionmaker, anime):
        return ConfirmacaoNecessaria(
            dominio="animefire.io",
            candidatos=[
                ResultadoBusca(titulo_exibicao="A", identificador="1", url="https://x/1"),
                ResultadoBusca(titulo_exibicao="B", identificador="2", url="https://x/2"),
            ],
        )

    monkeypatch.setattr("api.servicos.fontes.resolver_fonte_do_anime", _resolver_fake)

    resposta = await cliente_autenticado.get(f"/api/admin/animes/{anime_id}/episodios-remotos")

    assert resposta.status_code == 409
    assert resposta.json()["detail"]["motivo"] == "fonte_ambigua"


async def test_listar_episodios_remotos_anime_inexistente_404(cliente_autenticado: AsyncClient):
    resposta = await cliente_autenticado.get("/api/admin/animes/999999/episodios-remotos")

    assert resposta.status_code == 404


async def test_listar_episodios_remotos_sem_cookie_401(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker
):
    anime_id = await _criar_anime(sessionmaker_api, "Anime Remoto Sem Auth")

    resposta = await cliente.get(f"/api/admin/animes/{anime_id}/episodios-remotos")

    assert resposta.status_code == 401

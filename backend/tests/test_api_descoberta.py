"""Testes de `GET /api/animes/em-alta`, `GET /api/animes/{anime_id}` e
`POST /api/admin/animes` (`api/rotas/animes.py` -> `api/servicos/descoberta.py`).

A maioria dos testes de `/em-alta` monkeypatcha
`api.servicos.descoberta.listar_em_alta_com_catalogo` diretamente (mesmo
padrão de `tests/test_api_animes.py` para `api.servicos.fontes`) — nunca bate
na API real do AniList/Kitsu em teste. Os testes marcados "cruzamento real"
monkeypatcham uma camada abaixo (`integrations.servico.listar_em_alta` /
`integrations.servico.buscar_por_titulo`), deixando a lógica de cruzamento de
`api/servicos/descoberta.py` rodar de verdade contra o banco de teste.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.servicos import descoberta as servico_descoberta
from core.erros import FalhaDeMetadados
from core.texto import slugificar
from integrations.base import AnimeEmAlta, MetadadosDeAnime
from models.anime import Anime

_SessionMaker = async_sessionmaker[AsyncSession]


async def _criar_anime(sessionmaker: _SessionMaker, titulo: str, slug: str, **campos) -> int:
    async with sessionmaker() as sessao:
        anime = Anime(titulo=titulo, slug=slug, **campos)
        sessao.add(anime)
        await sessao.commit()
        return anime.id


async def test_em_alta_propaga_502_se_todos_provedores_falham(
    cliente: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    async def _listar_fake(sessionmaker):
        raise FalhaDeMetadados("todos os provedores de metadados falharam")

    monkeypatch.setattr("api.servicos.descoberta.listar_em_alta_com_catalogo", _listar_fake)

    resposta = await cliente.get("/api/animes/em-alta")

    assert resposta.status_code == 502


async def test_em_alta_cruza_com_anime_existente_no_catalogo_local(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker, monkeypatch: pytest.MonkeyPatch
):
    anime_id = await _criar_anime(sessionmaker_api, "Tensei Shitara Slime Datta Ken", "tensei")

    item = AnimeEmAlta(
        titulo_romaji="Tensei",
        titulo_ingles="That Time I Got Reincarnated as a Slime",
        capa_url="https://img/1.jpg",
        banner_url="https://img/1-banner.jpg",
        anilist_id=1,
    )

    async def _listar_fake(sessionmaker):
        return [(item, anime_id)]

    monkeypatch.setattr("api.servicos.descoberta.listar_em_alta_com_catalogo", _listar_fake)

    resposta = await cliente.get("/api/animes/em-alta")

    assert resposta.status_code == 200
    assert resposta.json() == [
        {
            "titulo_romaji": "Tensei",
            "titulo_ingles": "That Time I Got Reincarnated as a Slime",
            "capa_url": "https://img/1.jpg",
            "banner_url": "https://img/1-banner.jpg",
            "anilist_id": 1,
            "anime_id": anime_id,
        }
    ]


async def test_em_alta_sem_correspondencia_local_devolve_anime_id_none(
    cliente: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    item = AnimeEmAlta(
        titulo_romaji="Ainda Nao Catalogado",
        titulo_ingles=None,
        capa_url=None,
        banner_url=None,
        anilist_id=99,
    )

    async def _listar_fake(sessionmaker):
        return [(item, None)]

    monkeypatch.setattr("api.servicos.descoberta.listar_em_alta_com_catalogo", _listar_fake)

    resposta = await cliente.get("/api/animes/em-alta")

    assert resposta.status_code == 200
    assert resposta.json()[0]["anime_id"] is None


async def test_ordem_de_rotas_em_alta_nao_e_interpretado_como_anime_id(
    cliente: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    async def _listar_fake(sessionmaker):
        return []

    monkeypatch.setattr("api.servicos.descoberta.listar_em_alta_com_catalogo", _listar_fake)

    resposta = await cliente.get("/api/animes/em-alta")

    assert resposta.status_code == 200
    assert resposta.json() == []


async def test_obter_anime_detalhe_caminho_feliz(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker
):
    anime_id = await _criar_anime(sessionmaker_api, "Anime Detalhado", "anime-detalhado")

    resposta = await cliente.get(f"/api/animes/{anime_id}")

    assert resposta.status_code == 200
    assert resposta.json()["id"] == anime_id
    assert resposta.json()["titulo"] == "Anime Detalhado"


async def test_obter_anime_404_para_id_inexistente(cliente: AsyncClient):
    resposta = await cliente.get("/api/animes/999999")

    assert resposta.status_code == 404


# --- cruzamento real (sem mock de `listar_em_alta_com_catalogo`) ---
#
# Os testes acima mockam o serviço de descoberta inteiro; os dois abaixo
# mockam uma camada mais funda (`integrations.servico.listar_em_alta`),
# deixando a lógica de cruzamento por anilist_id/slug de
# `api/servicos/descoberta.py::listar_em_alta_com_catalogo` rodar de verdade
# contra o catálogo local em teste.


async def test_em_alta_cruzamento_real_por_slug_contra_anime_pre_inserido(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker, monkeypatch: pytest.MonkeyPatch
):
    titulo = "Tensei Shitara Slime Datta Ken"
    anime_id = await _criar_anime(sessionmaker_api, titulo, slugificar(titulo))

    item = AnimeEmAlta(
        titulo_romaji=titulo,
        titulo_ingles="That Time I Got Reincarnated as a Slime",
        capa_url="https://img/1.jpg",
        banner_url="https://img/1-banner.jpg",
        anilist_id=None,  # força o cruzamento a cair no fallback de slug
    )

    async def _listar_em_alta_fake():
        return [item]

    monkeypatch.setattr("integrations.servico.listar_em_alta", _listar_em_alta_fake)

    resposta = await cliente.get("/api/animes/em-alta")

    assert resposta.status_code == 200
    assert resposta.json()[0]["anime_id"] == anime_id


async def test_listar_em_alta_com_catalogo_prioriza_anilist_id_sobre_slug(
    sessionmaker_api: _SessionMaker, monkeypatch: pytest.MonkeyPatch
):
    """`anilist_id` bate mas o slug do título romaji do provedor diverge do
    slug local (subtítulo diferente) — o cruzamento deve resolver via
    `anilist_id` mesmo assim, sem depender do slug."""
    anime_id = await _criar_anime(
        sessionmaker_api,
        "Slime - Título Cadastrado Localmente",
        "slime-titulo-cadastrado-localmente",
        anilist_id=555,
    )

    item = AnimeEmAlta(
        titulo_romaji="Tensei Shitara Slime Datta Ken",  # slug não bate com o local
        titulo_ingles=None,
        capa_url=None,
        banner_url=None,
        anilist_id=555,  # mas o anilist_id bate
    )

    async def _listar_em_alta_fake():
        return [item]

    monkeypatch.setattr("integrations.servico.listar_em_alta", _listar_em_alta_fake)

    pares = await servico_descoberta.listar_em_alta_com_catalogo(sessionmaker_api)

    assert pares == [(item, anime_id)]


# --- POST /api/admin/animes: enriquecimento best-effort ---


async def test_criar_anime_sem_metadado_tenta_enriquecer_via_provedor(
    cliente: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    chamadas = []

    async def _buscar_fake(titulo):
        chamadas.append(titulo)
        return MetadadosDeAnime(
            capa_url="https://img/capa.jpg", sinopse="Sinopse.", anilist_id=7, kitsu_id=None
        )

    monkeypatch.setattr("integrations.servico.buscar_por_titulo", _buscar_fake)

    resposta = await cliente.post("/api/admin/animes", json={"titulo": "Slime Enriquecido"})

    assert resposta.status_code == 200
    assert chamadas == ["Slime Enriquecido"]
    assert resposta.json()["capa_path"] == "https://img/capa.jpg"


async def test_criar_anime_com_metadado_persiste_direto_sem_chamar_provedor(
    cliente: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    chamadas = []

    async def _buscar_fake(titulo):
        chamadas.append(titulo)
        return None

    monkeypatch.setattr("integrations.servico.buscar_por_titulo", _buscar_fake)

    resposta = await cliente.post(
        "/api/admin/animes",
        json={
            "titulo": "Slime Com Metadado No Payload",
            "anilist_id": 10,
            "capa_url": "https://img/direto.jpg",
        },
    )

    assert resposta.status_code == 200
    assert chamadas == []
    assert resposta.json()["capa_path"] == "https://img/direto.jpg"


async def test_criar_anime_enriquecimento_falho_nao_bloqueia_criacao(
    cliente: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    async def _buscar_fake(titulo):
        raise FalhaDeMetadados("todos os provedores falharam")

    monkeypatch.setattr("integrations.servico.buscar_por_titulo", _buscar_fake)

    resposta = await cliente.post("/api/admin/animes", json={"titulo": "Slime Sem Sorte"})

    assert resposta.status_code == 200
    assert resposta.json()["capa_path"] is None

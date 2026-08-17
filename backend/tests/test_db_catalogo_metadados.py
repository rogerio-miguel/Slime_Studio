"""Testes de `db/catalogo.py`: `aplicar_metadados` (idempotência, rollback
isolado em conflito de `anilist_id`) e os lookups em lote usados pelo
cruzamento do feed "em alta" (`api/servicos/descoberta.py`). Arquivo SQLite
real (mesmo padrão de `tests/test_fila.py`) — WAL não funciona em `:memory:`.
"""

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config import Config
from db.catalogo import (
    aplicar_metadados,
    localizar_animes_por_anilist_id,
    localizar_animes_por_slug,
)
from db.engine import criar_engine, criar_sessionmaker
from integrations.base import MetadadosDeAnime
from models.anime import Anime
from models.base import Base

_SessionMaker = async_sessionmaker[AsyncSession]


@pytest.fixture
async def sessionmaker(tmp_path: Path) -> _SessionMaker:
    caminho_db = tmp_path / "test.db"
    config = Config(
        database_url=f"sqlite+aiosqlite:///{caminho_db}",
        media_root=tmp_path,
        raiz_repo=tmp_path,
        ffmpeg=Path("/usr/bin/ffmpeg"),
        ffprobe=Path("/usr/bin/ffprobe"),
        caminho_lock=tmp_path / "worker.lock",
    )
    engine = criar_engine(config)
    async with engine.begin() as conexao:
        await conexao.run_sync(Base.metadata.create_all)

    fabrica = criar_sessionmaker(engine)
    yield fabrica

    await engine.dispose()


async def _criar_anime(fabrica: _SessionMaker, **campos: object) -> int:
    async with fabrica() as sessao:
        anime = Anime(**campos)
        sessao.add(anime)
        await sessao.commit()
        return anime.id


# --- aplicar_metadados ---


async def test_aplicar_metadados_preenche_campos_vazios(sessionmaker: _SessionMaker):
    anime_id = await _criar_anime(sessionmaker, titulo="Slime", slug="slime")

    await aplicar_metadados(
        sessionmaker,
        anime_id,
        MetadadosDeAnime(
            capa_url="https://img/capa.jpg", sinopse="Sinopse.", anilist_id=1, kitsu_id=2
        ),
    )

    async with sessionmaker() as sessao:
        anime = await sessao.get(Anime, anime_id)
        assert anime.capa_path == "https://img/capa.jpg"
        assert anime.sinopse == "Sinopse."
        assert anime.anilist_id == 1
        assert anime.kitsu_id == 2


async def test_aplicar_metadados_e_idempotente_nao_sobrescreve_campo_preenchido(
    sessionmaker: _SessionMaker,
):
    anime_id = await _criar_anime(
        sessionmaker,
        titulo="Slime",
        slug="slime",
        capa_path="https://original/capa.jpg",
        sinopse="Sinopse original.",
    )

    await aplicar_metadados(
        sessionmaker,
        anime_id,
        MetadadosDeAnime(
            capa_url="https://novo/capa.jpg",
            sinopse="Sinopse nova.",
            anilist_id=5,
            kitsu_id=None,
        ),
    )

    async with sessionmaker() as sessao:
        anime = await sessao.get(Anime, anime_id)
        # Campos já preenchidos não são sobrescritos...
        assert anime.capa_path == "https://original/capa.jpg"
        assert anime.sinopse == "Sinopse original."
        # ...mas o que estava NULL foi preenchido.
        assert anime.anilist_id == 5


async def test_aplicar_metadados_anime_inexistente_nao_levanta(sessionmaker: _SessionMaker):
    metadados = MetadadosDeAnime(
        capa_url="https://img/x.jpg", sinopse=None, anilist_id=None, kitsu_id=None
    )
    await aplicar_metadados(sessionmaker, 999999, metadados)


async def test_aplicar_metadados_rollback_isolado_em_anilist_id_duplicado(
    sessionmaker: _SessionMaker, caplog: pytest.LogCaptureFixture
):
    outro_id = await _criar_anime(sessionmaker, titulo="Outro", slug="outro", anilist_id=1)
    anime_id = await _criar_anime(sessionmaker, titulo="Slime", slug="slime")

    with caplog.at_level("WARNING"):
        await aplicar_metadados(
            sessionmaker,
            anime_id,
            MetadadosDeAnime(
                capa_url="https://img/capa.jpg", sinopse=None, anilist_id=1, kitsu_id=None
            ),
        )

    async with sessionmaker() as sessao:
        # A escrita inteira desta chamada (um único commit) foi revertida —
        # nenhum campo desta operação persiste quando `anilist_id` conflita.
        anime = await sessao.get(Anime, anime_id)
        assert anime.anilist_id is None
        assert anime.capa_path is None

        # O anime que já detinha o anilist_id não foi afetado.
        outro = await sessao.get(Anime, outro_id)
        assert outro.anilist_id == 1

    assert "anilist_id" in caplog.text


# --- lookups em lote (cruzamento do feed "em alta") ---


async def test_localizar_animes_por_slug(sessionmaker: _SessionMaker):
    anime_id = await _criar_anime(sessionmaker, titulo="Slime", slug="slime")
    await _criar_anime(sessionmaker, titulo="Outro", slug="outro")

    resultado = await localizar_animes_por_slug(sessionmaker, ["slime", "nao-catalogado"])

    assert resultado == {"slime": anime_id}


async def test_localizar_animes_por_slug_lista_vazia_nao_bate_no_banco(
    sessionmaker: _SessionMaker,
):
    assert await localizar_animes_por_slug(sessionmaker, []) == {}


async def test_localizar_animes_por_anilist_id(sessionmaker: _SessionMaker):
    anime_id = await _criar_anime(sessionmaker, titulo="Slime", slug="slime", anilist_id=42)
    await _criar_anime(sessionmaker, titulo="Outro", slug="outro", anilist_id=99)

    resultado = await localizar_animes_por_anilist_id(sessionmaker, [42, 1000])

    assert resultado == {42: anime_id}


async def test_localizar_animes_por_anilist_id_lista_vazia_nao_bate_no_banco(
    sessionmaker: _SessionMaker,
):
    assert await localizar_animes_por_anilist_id(sessionmaker, []) == {}

"""`db/franquias.py` — agrupamento de franquia e aritmética de temporadas."""

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config import Config
from db.engine import criar_engine, criar_sessionmaker
from db.franquias import offset_de_temporada, total_das_partes_irmas
from models.anime import Anime
from models.base import Base


@pytest.fixture
async def sessionmaker(tmp_path: Path) -> async_sessionmaker[AsyncSession]:
    config = Config(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        media_root=tmp_path,
        raiz_repo=tmp_path,
        ffmpeg=Path("/usr/bin/ffmpeg"),
        ffprobe=Path("/usr/bin/ffprobe"),
        caminho_lock=tmp_path / "worker.lock",
    )
    engine = criar_engine(config)
    async with engine.begin() as conexao:
        await conexao.run_sync(Base.metadata.create_all)
    yield criar_sessionmaker(engine)
    await engine.dispose()


async def _catalogar(sessionmaker, *linhas: dict) -> list[Anime]:
    async with sessionmaker() as sessao:
        animes = [
            Anime(slug=linha["titulo"].lower().replace(" ", "-"), **linha) for linha in linhas
        ]
        sessao.add_all(animes)
        await sessao.commit()
        for anime in animes:
            await sessao.refresh(anime)
        return animes


async def test_offset_soma_as_temporadas_anteriores_mesmo_com_ancoras_diferentes(sessionmaker):
    # Slime: o provedor ancora T1 e as demais em âncoras distintas; só o título base
    # (slug de franquia) as reúne. Somar só pela âncora da própria temporada perdia a T1.
    t1, t2, t3 = await _catalogar(
        sessionmaker,
        {
            "titulo": "Slime",
            "numero_temporada": 1,
            "total_episodios_anilist": 24,
            "serie_ancora": 1,
        },
        {
            "titulo": "Slime 2nd Season",
            "numero_temporada": 2,
            "total_episodios_anilist": 12,
            "serie_ancora": 2,
        },
        {
            "titulo": "Slime 3rd Season",
            "numero_temporada": 3,
            "total_episodios_anilist": 24,
            "serie_ancora": 2,
        },
    )

    assert await offset_de_temporada(sessionmaker, t1) == 0
    assert await offset_de_temporada(sessionmaker, t2) == 24
    assert await offset_de_temporada(sessionmaker, t3) == 36


async def test_offset_ignora_filme_e_temporada_sem_contagem(sessionmaker):
    _, filme, t2 = await _catalogar(
        sessionmaker,
        {"titulo": "Obra", "numero_temporada": 1},
        {"titulo": "Obra Movie", "formato_midia": "MOVIE", "total_episodios_anilist": 1},
        {"titulo": "Obra 2nd Season", "numero_temporada": 2, "total_episodios_anilist": 12},
    )

    assert await offset_de_temporada(sessionmaker, t2) == 0
    assert await offset_de_temporada(sessionmaker, filme) == 0


async def test_total_das_partes_irmas_soma_so_a_mesma_temporada(sessionmaker):
    _, parte1, parte2 = await _catalogar(
        sessionmaker,
        {"titulo": "Obra", "numero_temporada": 1, "total_episodios_anilist": 12},
        {"titulo": "Obra 2nd Season", "numero_temporada": 2, "total_episodios_anilist": 12},
        {"titulo": "Obra 2nd Season Part 2", "numero_temporada": 2, "total_episodios_anilist": 11},
    )

    assert await total_das_partes_irmas(sessionmaker, parte1) == 11
    assert await total_das_partes_irmas(sessionmaker, parte2) == 12

"""Testes de `scripts/backfill_capa_anilist.py`: exercitam `_carregar_candidatos`/
`_passo_backfill_capa` direto, com um sessionmaker de SQLite real (mesmo padrão de
`tests/test_db_catalogo_metadados.py` — WAL não funciona em `:memory:`) e
`integrations.servico.buscar_metadados_por_anilist_id` monkeypatchado (sem rede).
`backfill()`/`main()` (que chamam `core.config.carregar_config()`) não são
exercitados aqui — dependem de ambiente, mesma fronteira que os dois scripts de
backfill existentes já deixam de fora dos próprios testes.
"""

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config import Config
from core.erros import FalhaDeMetadados
from db.engine import criar_engine, criar_sessionmaker
from integrations import servico
from integrations.base import MetadadosDeAnime
from models.anime import Anime
from models.base import Base
from scripts.backfill_capa_anilist import (
    Argumentos,
    _carregar_candidatos,
    _passo_backfill_capa,
    analisar_argumentos,
)

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


def _metadados(capa_url: str | None) -> MetadadosDeAnime:
    return MetadadosDeAnime(capa_url=capa_url, sinopse=None, anilist_id=1, kitsu_id=None)


async def _sem_pausa(_segundos: float) -> None:
    """Substitui `asyncio.sleep` nos testes com mais de um candidato — evita
    esperar de verdade a pausa real entre chamadas de rede do script."""


# --- analisar_argumentos ---


def test_analisar_argumentos_defaults():
    assert analisar_argumentos([]) == Argumentos(dry_run=False, anime_id=None)


def test_analisar_argumentos_dry_run_e_anime_id():
    assert analisar_argumentos(["--dry-run", "--anime-id", "42"]) == Argumentos(
        dry_run=True, anime_id=42
    )


# --- _carregar_candidatos ---


async def test_carregar_candidatos_so_pega_com_anilist_id(sessionmaker: _SessionMaker):
    com_id = await _criar_anime(sessionmaker, titulo="Slime", slug="slime", anilist_id=7)
    await _criar_anime(sessionmaker, titulo="Sem Id", slug="sem-id")

    candidatos = await _carregar_candidatos(sessionmaker, anime_id=None)

    assert candidatos == [(com_id, 7, "Slime")]


async def test_carregar_candidatos_restringe_por_anime_id(sessionmaker: _SessionMaker):
    alvo = await _criar_anime(sessionmaker, titulo="Slime", slug="slime", anilist_id=7)
    await _criar_anime(sessionmaker, titulo="Outro", slug="outro", anilist_id=9)

    candidatos = await _carregar_candidatos(sessionmaker, anime_id=alvo)

    assert candidatos == [(alvo, 7, "Slime")]


async def test_carregar_candidatos_anime_id_sem_anilist_id_devolve_vazio(
    sessionmaker: _SessionMaker,
):
    anime_id = await _criar_anime(sessionmaker, titulo="Sem Id", slug="sem-id")

    assert await _carregar_candidatos(sessionmaker, anime_id=anime_id) == []


async def test_carregar_candidatos_anime_id_inexistente_devolve_vazio(
    sessionmaker: _SessionMaker,
):
    assert await _carregar_candidatos(sessionmaker, anime_id=999999) == []


# --- _passo_backfill_capa ---


async def test_passo_backfill_capa_sobrescreve_capa_existente(
    sessionmaker: _SessionMaker, monkeypatch: pytest.MonkeyPatch
):
    anime_id = await _criar_anime(
        sessionmaker,
        titulo="Slime",
        slug="slime",
        anilist_id=7,
        capa_path="https://tmdb/capa-serie.jpg",
        banner_path="https://tmdb/banner.jpg",
    )

    async def _fake(anilist_id: int):
        assert anilist_id == 7
        return _metadados("https://anilist/capa.jpg")

    monkeypatch.setattr(servico, "buscar_metadados_por_anilist_id", _fake)

    resolvidos = await _passo_backfill_capa(sessionmaker, anime_id=None, dry_run=False)

    assert resolvidos == 1
    async with sessionmaker() as sessao:
        anime = await sessao.get(Anime, anime_id)
        assert anime.capa_path == "https://anilist/capa.jpg"
        # banner_path não é tocado por este backfill.
        assert anime.banner_path == "https://tmdb/banner.jpg"


async def test_passo_backfill_capa_dry_run_bate_rede_mas_nao_grava(
    sessionmaker: _SessionMaker, monkeypatch: pytest.MonkeyPatch
):
    anime_id = await _criar_anime(
        sessionmaker,
        titulo="Slime",
        slug="slime",
        anilist_id=7,
        capa_path="https://tmdb/capa-serie.jpg",
    )

    chamadas = []

    async def _fake(anilist_id: int):
        chamadas.append(anilist_id)
        return _metadados("https://anilist/capa.jpg")

    monkeypatch.setattr(servico, "buscar_metadados_por_anilist_id", _fake)

    resolvidos = await _passo_backfill_capa(sessionmaker, anime_id=None, dry_run=True)

    assert resolvidos == 1
    assert chamadas == [7]  # dry-run BATE a rede (ao contrário do outro backfill)
    async with sessionmaker() as sessao:
        anime = await sessao.get(Anime, anime_id)
        assert anime.capa_path == "https://tmdb/capa-serie.jpg"  # não gravado


async def test_passo_backfill_capa_sem_anilist_id_e_pulado(
    sessionmaker: _SessionMaker, monkeypatch: pytest.MonkeyPatch
):
    await _criar_anime(sessionmaker, titulo="Sem Id", slug="sem-id")

    async def _fake(anilist_id: int):
        raise AssertionError("não deveria bater rede para anime sem anilist_id")

    monkeypatch.setattr(servico, "buscar_metadados_por_anilist_id", _fake)

    assert await _passo_backfill_capa(sessionmaker, anime_id=None, dry_run=False) == 0


async def test_passo_backfill_capa_provedor_none_nao_conta(
    sessionmaker: _SessionMaker, monkeypatch: pytest.MonkeyPatch
):
    await _criar_anime(sessionmaker, titulo="Slime", slug="slime", anilist_id=7)

    async def _fake(anilist_id: int):
        return None

    monkeypatch.setattr(servico, "buscar_metadados_por_anilist_id", _fake)

    assert await _passo_backfill_capa(sessionmaker, anime_id=None, dry_run=False) == 0


async def test_passo_backfill_capa_sem_capa_url_nao_sobrescreve(
    sessionmaker: _SessionMaker, monkeypatch: pytest.MonkeyPatch
):
    anime_id = await _criar_anime(
        sessionmaker,
        titulo="Slime",
        slug="slime",
        anilist_id=7,
        capa_path="https://original/capa.jpg",
    )

    async def _fake(anilist_id: int):
        return _metadados(None)

    monkeypatch.setattr(servico, "buscar_metadados_por_anilist_id", _fake)

    resolvidos = await _passo_backfill_capa(sessionmaker, anime_id=None, dry_run=False)

    assert resolvidos == 0
    async with sessionmaker() as sessao:
        anime = await sessao.get(Anime, anime_id)
        assert anime.capa_path == "https://original/capa.jpg"


async def test_passo_backfill_capa_falha_de_um_anime_nao_aborta_o_lote(
    sessionmaker: _SessionMaker, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    falha_id = await _criar_anime(sessionmaker, titulo="Falha", slug="falha", anilist_id=1)
    ok_id = await _criar_anime(sessionmaker, titulo="Ok", slug="ok", anilist_id=2)

    # Evita o `asyncio.sleep(1.0)` real entre os dois candidatos deste teste.
    monkeypatch.setattr("scripts.backfill_capa_anilist.asyncio.sleep", _sem_pausa)

    async def _fake(anilist_id: int):
        if anilist_id == 1:
            raise FalhaDeMetadados("provedores falharam")
        return _metadados("https://anilist/capa-ok.jpg")

    monkeypatch.setattr(servico, "buscar_metadados_por_anilist_id", _fake)

    with caplog.at_level("WARNING"):
        resolvidos = await _passo_backfill_capa(sessionmaker, anime_id=None, dry_run=False)

    assert resolvidos == 1
    async with sessionmaker() as sessao:
        falha = await sessao.get(Anime, falha_id)
        assert falha.capa_path is None
        ok = await sessao.get(Anime, ok_id)
        assert ok.capa_path == "https://anilist/capa-ok.jpg"
    assert "provedores falharam" in caplog.text

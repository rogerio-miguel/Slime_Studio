"""Testes de `db/catalogo.py`: `aplicar_metadados` (idempotência, rollback
isolado em conflito de `anilist_id`) e os lookups em lote usados pelo
cruzamento do feed "em alta" (`api/servicos/descoberta.py`). Arquivo SQLite
real (mesmo padrão de `tests/test_fila.py`) — WAL não funciona em `:memory:`.
"""

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config import Config
from core.enums import StatusLancamento
from db.catalogo import (
    aplicar_metadados,
    atualizar_lancamento,
    atualizar_lancamentos_em_lote,
    localizar_animes_por_anilist_id,
    localizar_animes_por_slug,
)
from db.engine import criar_engine, criar_sessionmaker
from integrations.base import LancamentoDeAnime, MetadadosDeAnime
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


async def test_aplicar_metadados_com_lancamento_grava_campos_de_lancamento(
    sessionmaker: _SessionMaker,
):
    anime_id = await _criar_anime(sessionmaker, titulo="Slime", slug="slime")
    proximo_em = datetime(2026, 10, 1, 18, 30, tzinfo=UTC)

    await aplicar_metadados(
        sessionmaker,
        anime_id,
        MetadadosDeAnime(
            capa_url="https://img/capa.jpg",
            sinopse="Sinopse.",
            anilist_id=10,
            kitsu_id=None,
            lancamento=LancamentoDeAnime(
                status=StatusLancamento.EM_LANCAMENTO,
                total_episodios=24,
                proximo_ep_numero=9,
                proximo_ep_em=proximo_em,
            ),
        ),
    )

    async with sessionmaker() as sessao:
        anime = await sessao.get(Anime, anime_id)
        # Metadado comum entrou...
        assert anime.capa_path == "https://img/capa.jpg"
        # ...e o bloco de lançamento também.
        assert anime.status_lancamento == StatusLancamento.EM_LANCAMENTO
        assert anime.proximo_ep_numero == 9
        assert anime.proximo_ep_em == proximo_em
        assert anime.total_episodios_anilist == 24
        assert anime.lancamento_atualizado_em is not None


async def test_aplicar_metadados_sem_lancamento_nao_toca_colunas_de_lancamento(
    sessionmaker: _SessionMaker,
):
    anime_id = await _criar_anime(
        sessionmaker,
        titulo="Slime",
        slug="slime",
        status_lancamento=StatusLancamento.HIATO,
        proximo_ep_numero=3,
    )

    await aplicar_metadados(
        sessionmaker,
        anime_id,
        MetadadosDeAnime(
            capa_url="https://img/capa.jpg", sinopse=None, anilist_id=None, kitsu_id=None
        ),
    )

    async with sessionmaker() as sessao:
        anime = await sessao.get(Anime, anime_id)
        assert anime.capa_path == "https://img/capa.jpg"
        assert anime.status_lancamento == StatusLancamento.HIATO
        assert anime.proximo_ep_numero == 3
        assert anime.lancamento_atualizado_em is None


# --- atualizar_lancamento / atualizar_lancamentos_em_lote ---


async def test_atualizar_lancamento_grava_campos_em_linha_nova(sessionmaker: _SessionMaker):
    anime_id = await _criar_anime(sessionmaker, titulo="Slime", slug="slime")
    proximo_em = datetime(2026, 9, 5, 15, 0, tzinfo=UTC)

    await atualizar_lancamento(
        sessionmaker,
        anime_id,
        LancamentoDeAnime(
            status=StatusLancamento.EM_LANCAMENTO,
            total_episodios=24,
            proximo_ep_numero=7,
            proximo_ep_em=proximo_em,
        ),
    )

    async with sessionmaker() as sessao:
        anime = await sessao.get(Anime, anime_id)
        assert anime.status_lancamento == StatusLancamento.EM_LANCAMENTO
        assert anime.proximo_ep_numero == 7
        assert anime.proximo_ep_em == proximo_em
        assert anime.total_episodios_anilist == 24
        assert anime.lancamento_atualizado_em is not None


async def test_atualizar_lancamento_zera_proximo_ep_na_transicao_para_finalizado(
    sessionmaker: _SessionMaker,
):
    anime_id = await _criar_anime(
        sessionmaker,
        titulo="Slime",
        slug="slime",
        status_lancamento=StatusLancamento.EM_LANCAMENTO,
        proximo_ep_numero=5,
        proximo_ep_em=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
    )

    await atualizar_lancamento(
        sessionmaker,
        anime_id,
        LancamentoDeAnime(
            status=StatusLancamento.FINALIZADO,
            total_episodios=12,
            proximo_ep_numero=None,
            proximo_ep_em=None,
        ),
    )

    async with sessionmaker() as sessao:
        anime = await sessao.get(Anime, anime_id)
        # Sobrescrita real: os None entram, o badge não fica preso no ep 5.
        assert anime.status_lancamento == StatusLancamento.FINALIZADO
        assert anime.proximo_ep_numero is None
        assert anime.proximo_ep_em is None
        assert anime.total_episodios_anilist == 12


async def test_atualizar_lancamento_nao_apaga_total_episodios_conhecido(
    sessionmaker: _SessionMaker,
):
    anime_id = await _criar_anime(
        sessionmaker, titulo="Slime", slug="slime", total_episodios_anilist=24
    )

    await atualizar_lancamento(
        sessionmaker,
        anime_id,
        LancamentoDeAnime(
            status=StatusLancamento.EM_LANCAMENTO,
            total_episodios=None,
            proximo_ep_numero=3,
            proximo_ep_em=None,
        ),
    )

    async with sessionmaker() as sessao:
        anime = await sessao.get(Anime, anime_id)
        assert anime.total_episodios_anilist == 24


async def test_atualizar_lancamento_carimba_mesmo_sem_mudanca_de_valor(
    sessionmaker: _SessionMaker,
):
    anime_id = await _criar_anime(sessionmaker, titulo="Slime", slug="slime")
    lancamento = LancamentoDeAnime(
        status=StatusLancamento.EM_LANCAMENTO,
        total_episodios=24,
        proximo_ep_numero=7,
        proximo_ep_em=datetime(2026, 9, 5, 15, 0, tzinfo=UTC),
    )

    await atualizar_lancamento(sessionmaker, anime_id, lancamento)
    async with sessionmaker() as sessao:
        primeiro = (await sessao.get(Anime, anime_id)).lancamento_atualizado_em

    await asyncio.sleep(0.001)
    await atualizar_lancamento(sessionmaker, anime_id, lancamento)
    async with sessionmaker() as sessao:
        segundo = (await sessao.get(Anime, anime_id)).lancamento_atualizado_em

    assert segundo > primeiro


async def test_atualizar_lancamento_anime_inexistente_nao_levanta(sessionmaker: _SessionMaker):
    await atualizar_lancamento(
        sessionmaker,
        999999,
        LancamentoDeAnime(
            status=StatusLancamento.EM_LANCAMENTO,
            total_episodios=None,
            proximo_ep_numero=1,
            proximo_ep_em=None,
        ),
    )


async def test_atualizar_lancamentos_em_lote_aplica_valores_por_anime(sessionmaker: _SessionMaker):
    id_com_total = await _criar_anime(sessionmaker, titulo="A", slug="a")
    id_sem_total = await _criar_anime(
        sessionmaker, titulo="B", slug="b", total_episodios_anilist=13
    )

    await atualizar_lancamentos_em_lote(
        sessionmaker,
        {
            id_com_total: LancamentoDeAnime(
                status=StatusLancamento.EM_LANCAMENTO,
                total_episodios=24,
                proximo_ep_numero=4,
                proximo_ep_em=None,
            ),
            id_sem_total: LancamentoDeAnime(
                status=StatusLancamento.FINALIZADO,
                total_episodios=None,
                proximo_ep_numero=None,
                proximo_ep_em=None,
            ),
        },
    )

    async with sessionmaker() as sessao:
        com_total = await sessao.get(Anime, id_com_total)
        assert com_total.status_lancamento == StatusLancamento.EM_LANCAMENTO
        assert com_total.proximo_ep_numero == 4
        assert com_total.total_episodios_anilist == 24
        assert com_total.lancamento_atualizado_em is not None

        sem_total = await sessao.get(Anime, id_sem_total)
        assert sem_total.status_lancamento == StatusLancamento.FINALIZADO
        assert sem_total.proximo_ep_numero is None
        assert sem_total.total_episodios_anilist == 13  # preservado
        assert sem_total.lancamento_atualizado_em is not None


async def test_atualizar_lancamentos_em_lote_dict_vazio_nao_levanta(sessionmaker: _SessionMaker):
    assert await atualizar_lancamentos_em_lote(sessionmaker, {}) is None


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

"""Testes de `db/catalogo.py`: `aplicar_metadados` (idempotência, rollback
isolado em conflito de `anilist_id`) e os lookups em lote usados pelo
cruzamento do feed "em alta" (`api/servicos/descoberta.py`). Arquivo SQLite
real (mesmo padrão de `tests/test_fila.py`) — WAL não funciona em `:memory:`.
"""

import asyncio
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config import Config
from core.enums import StatusLancamento
from db.catalogo import (
    aplicar_lancamento_descoberto_por_titulo,
    aplicar_metadados,
    atualizar_lancamento,
    atualizar_lancamentos_em_lote,
    localizar_animes_por_anilist_id,
    localizar_animes_por_slug,
    obter_ou_criar_anime_id,
    sobrescrever_arte,
    sobrescrever_capa,
)
from db.engine import criar_engine, criar_sessionmaker
from integrations.base import ArteDeAnime, LancamentoDeAnime, MetadadosDeAnime
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


async def test_aplicar_metadados_preenche_banner_e_capa_cor(sessionmaker: _SessionMaker):
    anime_id = await _criar_anime(sessionmaker, titulo="Slime", slug="slime")

    await aplicar_metadados(
        sessionmaker,
        anime_id,
        MetadadosDeAnime(
            capa_url="https://img/capa.jpg",
            sinopse=None,
            anilist_id=None,
            kitsu_id=None,
            banner_url="https://img/banner.jpg",
            capa_cor="#e4a15d",
        ),
    )

    async with sessionmaker() as sessao:
        anime = await sessao.get(Anime, anime_id)
        assert anime.banner_path == "https://img/banner.jpg"
        assert anime.capa_cor == "#e4a15d"


async def test_aplicar_metadados_nao_sobrescreve_banner_nem_com_none(sessionmaker: _SessionMaker):
    """Preenchimento só-quando-nulo: banner/cor já gravados não são tocados, e um
    metadado com `banner_url=None` não zera a coluna."""
    anime_id = await _criar_anime(
        sessionmaker,
        titulo="Slime",
        slug="slime",
        banner_path="https://original/banner.jpg",
        capa_cor="#000000",
    )

    await aplicar_metadados(
        sessionmaker,
        anime_id,
        MetadadosDeAnime(
            capa_url=None,
            sinopse=None,
            anilist_id=None,
            kitsu_id=None,
            banner_url="https://novo/banner.jpg",
            capa_cor=None,
        ),
    )

    async with sessionmaker() as sessao:
        anime = await sessao.get(Anime, anime_id)
        assert anime.banner_path == "https://original/banner.jpg"
        assert anime.capa_cor == "#000000"


async def test_aplicar_metadados_preenche_generos_e_ano(sessionmaker: _SessionMaker):
    anime_id = await _criar_anime(sessionmaker, titulo="Slime", slug="slime")

    await aplicar_metadados(
        sessionmaker,
        anime_id,
        MetadadosDeAnime(
            capa_url=None,
            sinopse=None,
            anilist_id=None,
            kitsu_id=None,
            generos=["Action", "Comedy"],
            ano=2018,
        ),
    )

    async with sessionmaker() as sessao:
        anime = await sessao.get(Anime, anime_id)
        assert anime.generos == ["Action", "Comedy"]
        assert anime.ano == 2018


async def test_aplicar_metadados_nao_sobrescreve_generos_nem_ano(sessionmaker: _SessionMaker):
    """Preenchimento só-quando-nulo: gêneros/ano já gravados não são substituídos
    pelos do metadado novo."""
    anime_id = await _criar_anime(
        sessionmaker,
        titulo="Slime",
        slug="slime",
        generos=["Slice of Life"],
        ano=2015,
    )

    await aplicar_metadados(
        sessionmaker,
        anime_id,
        MetadadosDeAnime(
            capa_url=None,
            sinopse=None,
            anilist_id=None,
            kitsu_id=None,
            generos=["Action", "Comedy"],
            ano=2018,
        ),
    )

    async with sessionmaker() as sessao:
        anime = await sessao.get(Anime, anime_id)
        assert anime.generos == ["Slice of Life"]
        assert anime.ano == 2015


async def test_aplicar_metadados_generos_lista_vazia_nao_grava(sessionmaker: _SessionMaker):
    """`generos=[]` do provedor ("sem gêneros conhecidos") não vira uma lista
    vazia gravada — a coluna fica `NULL`, distinta de "gêneros = nenhum"."""
    anime_id = await _criar_anime(sessionmaker, titulo="Slime", slug="slime")

    await aplicar_metadados(
        sessionmaker,
        anime_id,
        MetadadosDeAnime(
            capa_url=None, sinopse=None, anilist_id=None, kitsu_id=None, generos=[]
        ),
    )

    async with sessionmaker() as sessao:
        anime = await sessao.get(Anime, anime_id)
        assert anime.generos is None


# --- sobrescrever_arte (Fatia 4 do PLANO_ARTE_TMDB.md; só banner_path desde a
# reversão de capa pra AniList) ---


async def test_sobrescrever_arte_substitui_banner_ja_preenchido(sessionmaker: _SessionMaker):
    """Ao contrário de `aplicar_metadados`, aqui o valor já existente É
    substituído — é o comportamento que a Fatia 4 pede."""
    anime_id = await _criar_anime(
        sessionmaker,
        titulo="Slime",
        slug="slime",
        capa_path="https://anilist/capa.jpg",
        banner_path="https://anilist/banner.jpg",
    )

    await sobrescrever_arte(sessionmaker, anime_id, ArteDeAnime(banner_url="https://tmdb/banner.jpg"))

    async with sessionmaker() as sessao:
        anime = await sessao.get(Anime, anime_id)
        # capa_path não é campo de `ArteDeAnime` mais — permanece intocado.
        assert anime.capa_path == "https://anilist/capa.jpg"
        assert anime.banner_path == "https://tmdb/banner.jpg"


async def test_sobrescrever_arte_banner_none_preserva_valor_existente(
    sessionmaker: _SessionMaker,
):
    """`banner_url=None` (TMDB não achou backdrop) não pode zerar o banner já
    confirmado — mesma regra de `_com_arte` em `integrations/servico.py`."""
    anime_id = await _criar_anime(
        sessionmaker,
        titulo="Slime",
        slug="slime",
        banner_path="https://anilist/banner.jpg",
    )

    await sobrescrever_arte(sessionmaker, anime_id, ArteDeAnime(banner_url=None))

    async with sessionmaker() as sessao:
        anime = await sessao.get(Anime, anime_id)
        assert anime.banner_path == "https://anilist/banner.jpg"


async def test_sobrescrever_arte_anime_inexistente_nao_levanta(sessionmaker: _SessionMaker):
    await sobrescrever_arte(sessionmaker, 999999, ArteDeAnime(banner_url="https://tmdb/b.jpg"))


# --- sobrescrever_capa (reversão de capa pra AniList) ---


async def test_sobrescrever_capa_substitui_capa_ja_preenchida(sessionmaker: _SessionMaker):
    anime_id = await _criar_anime(
        sessionmaker,
        titulo="Slime",
        slug="slime",
        capa_path="https://tmdb/capa-serie.jpg",
        banner_path="https://tmdb/banner.jpg",
    )

    await sobrescrever_capa(sessionmaker, anime_id, "https://anilist/capa.jpg")

    async with sessionmaker() as sessao:
        anime = await sessao.get(Anime, anime_id)
        assert anime.capa_path == "https://anilist/capa.jpg"
        # banner_path não é tocado por `sobrescrever_capa`.
        assert anime.banner_path == "https://tmdb/banner.jpg"


async def test_sobrescrever_capa_anime_inexistente_nao_levanta(sessionmaker: _SessionMaker):
    await sobrescrever_capa(sessionmaker, 999999, "https://anilist/capa.jpg")


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


async def test_atualizar_lancamento_grava_estreia_em_e_preenche_ano_nulo(
    sessionmaker: _SessionMaker,
):
    """Bookmark de "Próximas estreias": nasce sem `ano`. O refresh de lançamento
    grava `estreia_em` (sobrescrita) e preenche `ano` a partir de `ano_estreia`
    (exceção só-quando-nulo)."""
    anime_id = await _criar_anime(sessionmaker, titulo="Estreia", slug="estreia")

    await atualizar_lancamento(
        sessionmaker,
        anime_id,
        LancamentoDeAnime(
            status=StatusLancamento.NAO_LANCADO,
            total_episodios=None,
            proximo_ep_numero=None,
            proximo_ep_em=None,
            estreia_em=date(2027, 4, 15),
            ano_estreia=2027,
        ),
    )

    async with sessionmaker() as sessao:
        anime = await sessao.get(Anime, anime_id)
        assert anime.estreia_em == date(2027, 4, 15)
        assert anime.ano == 2027


async def test_atualizar_lancamento_nao_sobrescreve_ano_ja_setado(sessionmaker: _SessionMaker):
    """`ano` já preenchido (cadastro manual) não é tocado pelo `ano_estreia` do
    provedor — `estreia_em`, que é estado de lançamento, entra normalmente."""
    anime_id = await _criar_anime(sessionmaker, titulo="Slime", slug="slime", ano=2018)

    await atualizar_lancamento(
        sessionmaker,
        anime_id,
        LancamentoDeAnime(
            status=StatusLancamento.EM_LANCAMENTO,
            total_episodios=12,
            proximo_ep_numero=3,
            proximo_ep_em=None,
            estreia_em=date(2024, 1, 6),
            ano_estreia=2024,
        ),
    )

    async with sessionmaker() as sessao:
        anime = await sessao.get(Anime, anime_id)
        assert anime.ano == 2018  # preservado
        assert anime.estreia_em == date(2024, 1, 6)


async def test_atualizar_lancamento_estreia_em_none_zera_a_coluna(sessionmaker: _SessionMaker):
    """`estreia_em` segue a semântica de SOBRESCRITA do resto do bloco: um
    refresh sem data (provedor deixou de expor `startDate` completo) zera a
    coluna, não a mantém presa no último valor."""
    anime_id = await _criar_anime(
        sessionmaker, titulo="Slime", slug="slime", estreia_em=date(2027, 4, 15)
    )

    await atualizar_lancamento(
        sessionmaker,
        anime_id,
        LancamentoDeAnime(
            status=StatusLancamento.EM_LANCAMENTO,
            total_episodios=12,
            proximo_ep_numero=1,
            proximo_ep_em=None,
            estreia_em=None,
            ano_estreia=None,
        ),
    )

    async with sessionmaker() as sessao:
        anime = await sessao.get(Anime, anime_id)
        assert anime.estreia_em is None


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


# --- aplicar_lancamento_descoberto_por_titulo (F14: aquecimento por título) ---


async def test_aplicar_lancamento_descoberto_por_titulo_nao_toca_capa_sinopse_kitsu(
    sessionmaker: _SessionMaker,
):
    anime_id = await _criar_anime(sessionmaker, titulo="Slime", slug="slime")

    await aplicar_lancamento_descoberto_por_titulo(
        sessionmaker,
        anime_id,
        anilist_id=42,
        lancamento=LancamentoDeAnime(
            status=StatusLancamento.EM_LANCAMENTO,
            total_episodios=12,
            proximo_ep_numero=5,
            proximo_ep_em=None,
        ),
    )

    async with sessionmaker() as sessao:
        anime = await sessao.get(Anime, anime_id)
        assert anime.anilist_id == 42
        assert anime.status_lancamento == StatusLancamento.EM_LANCAMENTO
        assert anime.proximo_ep_numero == 5
        assert anime.total_episodios_anilist == 12
        assert anime.lancamento_atualizado_em is not None
        # match por título é heurístico — estes campos permanentes nunca entram
        assert anime.capa_path is None
        assert anime.sinopse is None
        assert anime.kitsu_id is None


async def test_aplicar_lancamento_descoberto_por_titulo_id_duplicado_grava_bloco_e_descarta_id(
    sessionmaker: _SessionMaker, caplog: pytest.LogCaptureFixture
):
    """Regressão do bug de rollback de D2: quando o `anilist_id` já pertence a
    outra linha, o id é descartado mas o bloco de lançamento persiste mesmo
    assim (o `except IntegrityError` de `aplicar_metadados` reverteria os dois)."""
    dono_id = await _criar_anime(sessionmaker, titulo="Dono", slug="dono", anilist_id=7)
    anime_id = await _criar_anime(sessionmaker, titulo="Irmao Dublado", slug="irmao-dublado")

    with caplog.at_level("WARNING"):
        await aplicar_lancamento_descoberto_por_titulo(
            sessionmaker,
            anime_id,
            anilist_id=7,
            lancamento=LancamentoDeAnime(
                status=StatusLancamento.EM_LANCAMENTO,
                total_episodios=24,
                proximo_ep_numero=9,
                proximo_ep_em=None,
            ),
        )

    async with sessionmaker() as sessao:
        anime = await sessao.get(Anime, anime_id)
        assert anime.anilist_id is None  # descartado — id pertence a outro anime
        assert anime.status_lancamento == StatusLancamento.EM_LANCAMENTO  # bloco persiste
        assert anime.proximo_ep_numero == 9
        assert anime.total_episodios_anilist == 24
        assert anime.lancamento_atualizado_em is not None

        dono = await sessao.get(Anime, dono_id)
        assert dono.anilist_id == 7  # dono original intacto

    assert "anilist_id" in caplog.text


async def test_aplicar_lancamento_descoberto_por_titulo_sem_lancamento_so_carimba(
    sessionmaker: _SessionMaker,
):
    anime_id = await _criar_anime(
        sessionmaker,
        titulo="Slime",
        slug="slime",
        status_lancamento=StatusLancamento.HIATO,
        proximo_ep_numero=3,
    )

    await aplicar_lancamento_descoberto_por_titulo(
        sessionmaker, anime_id, anilist_id=None, lancamento=None
    )

    async with sessionmaker() as sessao:
        anime = await sessao.get(Anime, anime_id)
        assert anime.lancamento_atualizado_em is not None  # cache negativo
        assert anime.status_lancamento == StatusLancamento.HIATO  # intacto
        assert anime.proximo_ep_numero == 3


async def test_aplicar_lancamento_descoberto_por_titulo_anime_inexistente_nao_levanta(
    sessionmaker: _SessionMaker,
):
    await aplicar_lancamento_descoberto_por_titulo(
        sessionmaker, 999999, anilist_id=1, lancamento=None
    )


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


async def test_obter_ou_criar_anime_id_deriva_numero_temporada_do_titulo(
    sessionmaker: _SessionMaker,
):
    anime_id = await obter_ou_criar_anime_id(sessionmaker, "Slime Datta Ken 3rd Season", 2024)

    async with sessionmaker() as sessao:
        anime = await sessao.get(Anime, anime_id)
        assert anime.numero_temporada == 3


async def test_obter_ou_criar_anime_id_sem_marcador_de_temporada_fica_none(
    sessionmaker: _SessionMaker,
):
    anime_id = await obter_ou_criar_anime_id(sessionmaker, "Slime Datta Ken", 2018)

    async with sessionmaker() as sessao:
        anime = await sessao.get(Anime, anime_id)
        assert anime.numero_temporada is None


async def test_obter_ou_criar_anime_id_existente_nao_recalcula_numero_temporada(
    sessionmaker: _SessionMaker,
):
    anime_id = await _criar_anime(
        sessionmaker, titulo="Slime", slug="slime", ano=2018, numero_temporada=1
    )

    resultado = await obter_ou_criar_anime_id(sessionmaker, "Slime", 2018)

    assert resultado == anime_id
    async with sessionmaker() as sessao:
        anime = await sessao.get(Anime, anime_id)
        assert anime.numero_temporada == 1

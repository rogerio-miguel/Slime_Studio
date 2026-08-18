"""Testes de `extractors/servico.py::_proximo_com_episodio`, sem rede —
`listar_episodios_em` é substituído por uma versão que devolve uma lista fixa;
a resolução do próximo site usa `FonteAnime` já mapeada no banco (mesmo padrão
de `tests/test_resolucao.py::test_proximo_site_para_prefere_mapeamento_ja_existente`),
sem precisar de extrator falso nem de `resiliencia.chamar`.
"""

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config import Config
from core.enums import VersaoDeFonte, VersaoEpisodio
from db.engine import criar_engine, criar_sessionmaker
from extractors import servico
from extractors.base import EpisodioRemoto
from models.anime import Anime
from models.base import Base
from models.fonte_anime import FonteAnime


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

    fabrica = criar_sessionmaker(engine)
    yield fabrica

    await engine.dispose()


async def _criar_anime(fabrica, titulo: str) -> Anime:
    async with fabrica() as sessao:
        anime = Anime(titulo=titulo, slug=titulo.lower().replace(" ", "-"))
        sessao.add(anime)
        await sessao.commit()
        await sessao.refresh(anime)
        return anime


async def test_proximo_com_episodio_colisao_de_numero_escolhe_primeiro_e_loga(
    sessionmaker, monkeypatch, caplog
):
    """Dois rótulos remotos ("7"/"07") mapeiam pro mesmo `numero=7` — regressão
    da ambiguidade introduzida por dedup-por-rótulo (extractors/base.py::
    EpisodioRemoto). Escolha determinística (1ª ocorrência) e log de aviso,
    nunca silenciosa (CLAUDE.md §4)."""
    anime = await _criar_anime(sessionmaker, "Slime Datta Ken")
    async with sessionmaker() as sessao:
        sessao.add_all(
            [
                FonteAnime(
                    anime_id=anime.id,
                    site_dominio="site-a.io",
                    versao=VersaoDeFonte.NAO_DIFERENCIADA,
                    identificador_no_site="a",
                    prioridade=0,
                ),
                FonteAnime(
                    anime_id=anime.id,
                    site_dominio="site-b.io",
                    versao=VersaoDeFonte.NAO_DIFERENCIADA,
                    identificador_no_site="b",
                    prioridade=1,
                ),
            ]
        )
        await sessao.commit()

    colidentes = [
        EpisodioRemoto(rotulo="7", numero=7, url="https://x/ep7"),
        EpisodioRemoto(rotulo="07", numero=7, url="https://x/ep07"),
    ]

    async def _listar_fake(sessionmaker, dominio, identificador):
        return colidentes

    monkeypatch.setattr(servico, "listar_episodios_em", _listar_fake)

    with caplog.at_level("WARNING"):
        resultado = await servico._proximo_com_episodio(
            sessionmaker, anime, 7, "site-a.io", {"site-a.io"}, VersaoEpisodio.DESCONHECIDA
        )

    assert resultado == ("site-b.io", "https://x/ep7")
    assert "07" in caplog.text
    assert "site-b.io" in caplog.text


async def test_proximo_com_episodio_sem_colisao_nao_loga(sessionmaker, monkeypatch, caplog):
    anime = await _criar_anime(sessionmaker, "Slime Datta Ken")
    async with sessionmaker() as sessao:
        sessao.add_all(
            [
                FonteAnime(
                    anime_id=anime.id,
                    site_dominio="site-a.io",
                    versao=VersaoDeFonte.NAO_DIFERENCIADA,
                    identificador_no_site="a",
                    prioridade=0,
                ),
                FonteAnime(
                    anime_id=anime.id,
                    site_dominio="site-b.io",
                    versao=VersaoDeFonte.NAO_DIFERENCIADA,
                    identificador_no_site="b",
                    prioridade=1,
                ),
            ]
        )
        await sessao.commit()

    async def _listar_fake(sessionmaker, dominio, identificador):
        return [EpisodioRemoto(rotulo="7", numero=7, url="https://x/ep7")]

    monkeypatch.setattr(servico, "listar_episodios_em", _listar_fake)

    with caplog.at_level("WARNING"):
        resultado = await servico._proximo_com_episodio(
            sessionmaker, anime, 7, "site-a.io", {"site-a.io"}, VersaoEpisodio.DESCONHECIDA
        )

    assert resultado == ("site-b.io", "https://x/ep7")
    assert "episódios remotos com numero" not in caplog.text


async def test_proximo_com_episodio_prefere_versao_pedida_quando_listagem_rotula_as_duas(
    sessionmaker, monkeypatch
):
    """Listagem do site de fallback tem episódio 7 rotulado nas duas versões
    (site que diferencia, ex. AnimesDrive) — o fallback pra DUBLADO precisa
    escolher a URL dublada, não a primeira da lista."""
    anime = await _criar_anime(sessionmaker, "Slime Datta Ken")
    async with sessionmaker() as sessao:
        sessao.add_all(
            [
                # `site-a.io` só precisa existir pra `dominio_que_falhou` ser
                # achado em `mapeadas` (localiza `prioridade_falhou`) — versão
                # gravada aqui é irrelevante, esta linha nunca é candidata a
                # próxima fonte (`prioridade > prioridade_falhou` a exclui).
                FonteAnime(
                    anime_id=anime.id,
                    site_dominio="site-a.io",
                    versao=VersaoDeFonte.NAO_DIFERENCIADA,
                    identificador_no_site="a",
                    prioridade=0,
                ),
                FonteAnime(
                    anime_id=anime.id,
                    site_dominio="site-b.io",
                    versao=VersaoDeFonte.DUBLADO,
                    identificador_no_site="b",
                    prioridade=1,
                ),
            ]
        )
        await sessao.commit()

    async def _listar_fake(sessionmaker, dominio, identificador):
        return [
            EpisodioRemoto(
                rotulo="7", numero=7, url="https://x/ep7-leg", versao=VersaoEpisodio.LEGENDADO
            ),
            EpisodioRemoto(
                rotulo="7", numero=7, url="https://x/ep7-dub", versao=VersaoEpisodio.DUBLADO
            ),
        ]

    monkeypatch.setattr(servico, "listar_episodios_em", _listar_fake)

    resultado = await servico._proximo_com_episodio(
        sessionmaker, anime, 7, "site-a.io", {"site-a.io"}, VersaoEpisodio.DUBLADO
    )

    assert resultado == ("site-b.io", "https://x/ep7-dub")

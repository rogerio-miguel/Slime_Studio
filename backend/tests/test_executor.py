"""Testes de `worker/executor.py::processar` — orquestração completa do fluxo,
do claim até `pronto`/`falhou` (ESPECIFICACAO.md §3B).
"""

import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config import Config
from core.enums import StatusEpisodio, StatusJob, TipoEpisodio, VersaoEpisodio
from core.erros import EstruturaDoSiteMudou, FalhaDeExtracao
from db.engine import criar_engine, criar_sessionmaker
from models.anime import Anime
from models.base import Base
from models.episodio import Episodio
from models.job import Job
from worker import executor
from worker.executor import processar
from worker.pipeline.ferramentas import executar

_FFMPEG = shutil.which("ffmpeg")
_FFPROBE = shutil.which("ffprobe")


@pytest.fixture
async def config(tmp_path: Path) -> Config:
    return Config(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        media_root=tmp_path / "media",
        raiz_repo=tmp_path,
        ffmpeg=Path(_FFMPEG or "/usr/bin/ffmpeg"),
        ffprobe=Path(_FFPROBE or "/usr/bin/ffprobe"),
        caminho_lock=tmp_path / "worker.lock",
    )


@pytest.fixture
async def sessionmaker(config: Config) -> async_sessionmaker[AsyncSession]:
    engine = criar_engine(config)
    async with engine.begin() as conexao:
        await conexao.run_sync(Base.metadata.create_all)

    fabrica = criar_sessionmaker(engine)
    yield fabrica

    await engine.dispose()


async def _criar_job(
    fabrica: async_sessionmaker[AsyncSession], *, url_fonte: str, site_origem: str = "local"
) -> tuple[int, int]:
    async with fabrica() as sessao:
        anime = Anime(titulo="Anime Teste", slug="anime-teste")
        sessao.add(anime)
        await sessao.flush()

        episodio = Episodio(
            anime_id=anime.id,
            numero=1,
            tipo=TipoEpisodio.REGULAR,
            versao=VersaoEpisodio.LEGENDADO,
            url_fonte=url_fonte,
            site_origem=site_origem,
        )
        sessao.add(episodio)
        await sessao.flush()

        job = Job(episodio_id=episodio.id, status=StatusJob.BAIXANDO)
        sessao.add(job)
        await sessao.commit()
        return job.id, episodio.id


async def _gerar_clipe_sintetico(ffmpeg: Path, destino: Path) -> None:
    await executar(
        [
            str(ffmpeg),
            "-nostdin",
            "-hide_banner",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=2:size=320x240:rate=24",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-profile:v",
            "high",
            str(destino),
        ],
        timeout_s=60,
    )


@pytest.mark.integracao
@pytest.mark.skipif(_FFMPEG is None or _FFPROBE is None, reason="ffmpeg/ffprobe não está no PATH")
async def test_processar_caminho_feliz_marca_job_e_episodio_prontos(tmp_path, sessionmaker, config):
    fonte = tmp_path / "fonte.mp4"
    await _gerar_clipe_sintetico(config.ffmpeg, fonte)
    job_id, episodio_id = await _criar_job(sessionmaker, url_fonte=str(fonte))

    await processar(job_id, sessionmaker, config)

    async with sessionmaker() as sessao:
        job = await sessao.get(Job, job_id)
        episodio = await sessao.get(Episodio, episodio_id)

    assert job.status == StatusJob.PRONTO
    assert episodio.status == StatusEpisodio.PRONTO
    assert episodio.hls_path is not None


async def test_processar_com_fonte_ausente_marca_job_e_episodio_falhos(
    tmp_path, sessionmaker, config
):
    job_id, episodio_id = await _criar_job(
        sessionmaker, url_fonte=str(tmp_path / "nao-existe.mkv")
    )

    await processar(job_id, sessionmaker, config)

    async with sessionmaker() as sessao:
        job = await sessao.get(Job, job_id)
        episodio = await sessao.get(Episodio, episodio_id)

    assert job.status == StatusJob.FALHOU
    assert job.erro_msg
    assert job.etapa_atual
    assert episodio.status == StatusEpisodio.FALHOU


async def test_processar_com_job_inexistente_nao_propaga_excecao(sessionmaker, config):
    """Regressão do item 3 do reviewer: `_carregar_job_e_episodio` roda dentro do
    `try` de `processar()` — se estivesse fora, a exceção de job/episódio/anime não
    encontrado escaparia sem tratamento até `worker/__main__.py`."""
    await processar(999_999, sessionmaker, config)


async def test_processar_com_falha_de_extracao_retentavel_reagenda_job(
    tmp_path, sessionmaker, config, monkeypatch
):
    job_id, episodio_id = await _criar_job(
        sessionmaker, url_fonte="https://animefire.one/animes/x/1", site_origem="animefire.one"
    )

    async def _resolver_fonte_falso(sessionmaker, config, *, anime, episodio):
        raise FalhaDeExtracao("falha de rede", permite_retentativa=True)

    monkeypatch.setattr(executor, "resolver_fonte", _resolver_fonte_falso)

    await processar(job_id, sessionmaker, config)

    async with sessionmaker() as sessao:
        job = await sessao.get(Job, job_id)
        episodio = await sessao.get(Episodio, episodio_id)

    assert job.status == StatusJob.FALHOU_EXTRACAO
    assert job.proxima_tentativa_em is not None
    assert job.proxima_tentativa_em > datetime.now(UTC)
    assert job.tentativas == 1
    assert job.finalizado_em is None
    assert episodio.status == StatusEpisodio.PENDENTE


async def test_processar_com_falha_de_extracao_nao_retentavel_aguarda_intervencao(
    tmp_path, sessionmaker, config, monkeypatch
):
    job_id, episodio_id = await _criar_job(
        sessionmaker, url_fonte="https://animefire.one/animes/x/1", site_origem="animefire.one"
    )

    async def _resolver_fonte_falso(sessionmaker, config, *, anime, episodio):
        raise EstruturaDoSiteMudou("estrutura do site mudou")

    monkeypatch.setattr(executor, "resolver_fonte", _resolver_fonte_falso)

    await processar(job_id, sessionmaker, config)

    async with sessionmaker() as sessao:
        job = await sessao.get(Job, job_id)
        episodio = await sessao.get(Episodio, episodio_id)

    assert job.status == StatusJob.AGUARDANDO_INTERVENCAO
    assert job.finalizado_em is not None
    assert episodio.status == StatusEpisodio.FALHOU

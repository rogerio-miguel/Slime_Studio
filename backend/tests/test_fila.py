"""Testes de `db/fila.py` contra um arquivo SQLite real — WAL exige
arquivo, `:memory:` não serve para exercitar o claim atômico."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config import Config
from core.enums import StatusJob, TipoEpisodio, VersaoEpisodio
from db.engine import criar_engine, criar_sessionmaker
from db.fila import reciclar_jobs_orfaos, reivindicar_proximo
from models.anime import Anime
from models.base import Base
from models.episodio import Episodio
from models.job import Job


@pytest.fixture
async def sessionmaker(tmp_path: Path) -> async_sessionmaker[AsyncSession]:
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


async def _criar_job(
    fabrica: async_sessionmaker[AsyncSession],
    *,
    status: StatusJob,
    heartbeat_em: datetime | None = None,
    proxima_tentativa_em: datetime | None = None,
) -> int:
    async with fabrica() as sessao:
        anime = Anime(titulo="Anime Teste", slug="anime-teste")
        sessao.add(anime)
        await sessao.flush()

        episodio = Episodio(
            anime_id=anime.id,
            numero=1,
            tipo=TipoEpisodio.REGULAR,
            versao=VersaoEpisodio.LEGENDADO,
            url_fonte="/tmp/fake.mkv",
            site_origem="local",
        )
        sessao.add(episodio)
        await sessao.flush()

        job = Job(
            episodio_id=episodio.id,
            status=status,
            heartbeat_em=heartbeat_em,
            proxima_tentativa_em=proxima_tentativa_em,
        )
        sessao.add(job)
        await sessao.commit()
        return job.id


async def test_reivindicar_proximo_concorrente_so_um_vence(sessionmaker):
    job_id = await _criar_job(sessionmaker, status=StatusJob.NA_FILA)

    resultados = await asyncio.gather(
        reivindicar_proximo(sessionmaker, worker_id="worker-a"),
        reivindicar_proximo(sessionmaker, worker_id="worker-b"),
    )

    vencedores = [resultado for resultado in resultados if resultado is not None]
    assert vencedores == [job_id]
    assert resultados.count(None) == 1


async def test_reciclar_jobs_orfaos_devolve_job_com_heartbeat_velho(sessionmaker):
    heartbeat_velho = datetime.now(UTC) - timedelta(seconds=300)
    job_id = await _criar_job(
        sessionmaker, status=StatusJob.BAIXANDO, heartbeat_em=heartbeat_velho
    )

    reciclados = await reciclar_jobs_orfaos(sessionmaker, limiar_s=120)
    assert reciclados == 1

    async with sessionmaker() as sessao:
        job = await sessao.get(Job, job_id)
        assert job.status == StatusJob.NA_FILA
        assert job.worker_id is None
        assert job.heartbeat_em is None
        assert job.tentativas == 1


async def test_reivindicar_proximo_pega_falhou_extracao_com_retentativa_vencida(sessionmaker):
    job_id = await _criar_job(
        sessionmaker,
        status=StatusJob.FALHOU_EXTRACAO,
        proxima_tentativa_em=datetime.now(UTC) - timedelta(seconds=1),
    )

    reivindicado = await reivindicar_proximo(sessionmaker, worker_id="worker-a")

    assert reivindicado == job_id
    async with sessionmaker() as sessao:
        job = await sessao.get(Job, job_id)
        assert job.status == StatusJob.BAIXANDO
        assert job.worker_id == "worker-a"


async def test_reivindicar_proximo_ignora_falhou_extracao_com_retentativa_futura(sessionmaker):
    await _criar_job(
        sessionmaker,
        status=StatusJob.FALHOU_EXTRACAO,
        proxima_tentativa_em=datetime.now(UTC) + timedelta(hours=1),
    )

    reivindicado = await reivindicar_proximo(sessionmaker, worker_id="worker-a")

    assert reivindicado is None

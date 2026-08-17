"""Testes de `api/eventos.py`: (a) unitários de `Assinantes`/`MonitorDeFila`,
sem WebSocket real — via um `_WebSocketFalso` stub e chamada direta a
`monitor._pollar()`; (b) handshake de `/ws/admin` via
`starlette.testclient.TestClient` (a única que fala WS de verdade — o
`httpx.ASGITransport` usado no resto dos testes de API não suporta), como
`def` síncrona (não `async def`) para não conflitar o event loop do
`TestClient` com o do pytest-asyncio (`asyncio_mode = "auto"` só afeta
`async def`)."""

import asyncio
import itertools
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.testclient import TestClient

from api.eventos import _TAMANHO_FILA_POR_CONEXAO, Assinantes, MonitorDeFila
from api.main import criar_app
from core.config import Config
from core.enums import StatusJob, TipoEpisodio, VersaoEpisodio
from db.engine import criar_engine, criar_sessionmaker
from db.fila import atualizar_status
from models.anime import Anime
from models.base import Base
from models.episodio import Episodio
from models.job import Job

_SessionMaker = async_sessionmaker[AsyncSession]


class _WebSocketFalso:
    """Só precisa ser hashável (chave de `Assinantes._filas`) e ter `close`
    assíncrono — `Assinantes.publicar` chama `ws.close(code=1013)` na fila cheia."""

    def __init__(self) -> None:
        self.fechado_com_codigo: int | None = None

    async def close(self, code: int) -> None:
        self.fechado_com_codigo = code


@pytest.fixture
async def sessionmaker_eventos(tmp_path: Path) -> _SessionMaker:
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


_contador_anime = itertools.count(1)


async def _criar_job(sessionmaker: _SessionMaker, *, status: StatusJob = StatusJob.NA_FILA) -> int:
    async with sessionmaker() as sessao:
        n = next(_contador_anime)
        anime = Anime(titulo=f"Anime Eventos {n}", slug=f"anime-eventos-{n}")
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

        job = Job(episodio_id=episodio.id, status=status)
        sessao.add(job)
        await sessao.commit()
        return job.id


# --- unitários: Assinantes ---


async def test_assinar_e_cancelar_atualiza_contagem():
    assinantes = Assinantes()
    ws = _WebSocketFalso()

    await assinantes.assinar("admin", ws)
    assert assinantes.total_assinantes() == 1

    assinantes.cancelar("admin", ws)
    assert assinantes.total_assinantes() == 0


async def test_publicar_entrega_mensagem_na_fila_do_assinante():
    assinantes = Assinantes()
    fila = await assinantes.assinar("admin", _WebSocketFalso())

    await assinantes.publicar("admin", {"tipo": "job_atualizado"})

    assert fila.get_nowait() == {"tipo": "job_atualizado"}


async def test_publicar_fila_cheia_fecha_conexao_com_1013():
    assinantes = Assinantes()
    ws = _WebSocketFalso()
    fila = await assinantes.assinar("admin", ws)
    for _ in range(_TAMANHO_FILA_POR_CONEXAO):
        fila.put_nowait({"tipo": "enchendo"})

    await assinantes.publicar("admin", {"tipo": "job_atualizado"})

    assert ws.fechado_com_codigo == 1013
    assert assinantes.total_assinantes() == 0


# --- unitários: MonitorDeFila._pollar ---


async def test_pollar_primeira_chamada_e_baseline_nao_emite(sessionmaker_eventos: _SessionMaker):
    await _criar_job(sessionmaker_eventos)
    assinantes = Assinantes()
    fila = await assinantes.assinar("admin", _WebSocketFalso())
    monitor = MonitorDeFila(sessionmaker_eventos, assinantes)

    await monitor._pollar()

    assert fila.empty()


async def test_pollar_emite_evento_quando_status_muda(sessionmaker_eventos: _SessionMaker):
    job_id = await _criar_job(sessionmaker_eventos)
    assinantes = Assinantes()
    fila_admin = await assinantes.assinar("admin", _WebSocketFalso())
    fila_job = await assinantes.assinar(f"job:{job_id}", _WebSocketFalso())
    monitor = MonitorDeFila(sessionmaker_eventos, assinantes)

    await monitor._pollar()  # baseline: não emite

    await atualizar_status(sessionmaker_eventos, job_id, StatusJob.BAIXANDO)
    await monitor._pollar()

    mensagem_admin = fila_admin.get_nowait()
    assert mensagem_admin["tipo"] == "job_atualizado"
    assert mensagem_admin["job"]["status"] == StatusJob.BAIXANDO
    assert fila_job.get_nowait() == mensagem_admin


async def test_pollar_isola_por_canal_de_job(sessionmaker_eventos: _SessionMaker):
    job_id_alvo = await _criar_job(sessionmaker_eventos)
    job_id_outro = await _criar_job(sessionmaker_eventos)
    assinantes = Assinantes()
    fila_outro = await assinantes.assinar(f"job:{job_id_outro}", _WebSocketFalso())
    monitor = MonitorDeFila(sessionmaker_eventos, assinantes)

    await monitor._pollar()  # baseline

    await atualizar_status(sessionmaker_eventos, job_id_alvo, StatusJob.BAIXANDO)
    await monitor._pollar()

    assert fila_outro.empty()


# --- handshake WS: starlette.testclient.TestClient ---


def _preparar_config(tmp_path: Path) -> Config:
    config = Config(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        media_root=tmp_path / "media",
        raiz_repo=tmp_path,
        ffmpeg=Path("/usr/bin/ffmpeg"),
        ffprobe=Path("/usr/bin/ffprobe"),
        caminho_lock=tmp_path / "worker.lock",
    )

    async def _criar_schema() -> None:
        engine = criar_engine(config)
        async with engine.begin() as conexao:
            await conexao.run_sync(Base.metadata.create_all)
        await engine.dispose()

    asyncio.run(_criar_schema())
    return config


def test_ws_admin_recebe_snapshot(tmp_path: Path):
    app = criar_app(_preparar_config(tmp_path))

    with TestClient(app) as client:
        with client.websocket_connect("/ws/admin") as websocket:
            mensagem = websocket.receive_json()

    assert mensagem == {"tipo": "snapshot", "jobs": []}

"""Testes de `extractors/circuit_breaker.py` contra SQLite real, sem rede."""

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config import Config
from db.engine import criar_engine, criar_sessionmaker
from extractors import circuit_breaker
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

    fabrica = criar_sessionmaker(engine)
    yield fabrica

    await engine.dispose()


async def test_site_sem_registro_nao_esta_em_cooldown(sessionmaker):
    assert await circuit_breaker.esta_em_cooldown(sessionmaker, "animefire.one") is False


async def test_registrar_sucesso_sem_registro_previo_nao_falha(sessionmaker):
    await circuit_breaker.registrar_sucesso(sessionmaker, "animefire.one")
    assert await circuit_breaker.esta_em_cooldown(sessionmaker, "animefire.one") is False


async def test_falhas_abaixo_do_limite_nao_abrem_cooldown_longo(sessionmaker):
    await circuit_breaker.registrar_falha(sessionmaker, "animefire.one", RuntimeError("x"))
    await circuit_breaker.registrar_falha(sessionmaker, "animefire.one", RuntimeError("x"))

    # Ainda dentro do backoff curto (30s/120s) — não é o cooldown de 1h.
    assert await circuit_breaker.esta_em_cooldown(sessionmaker, "animefire.one") is True


async def test_falhas_alem_do_limite_abrem_cooldown(sessionmaker):
    for _ in range(4):
        await circuit_breaker.registrar_falha(sessionmaker, "animefire.one", RuntimeError("x"))

    assert await circuit_breaker.esta_em_cooldown(sessionmaker, "animefire.one") is True


async def test_registrar_sucesso_depois_de_falha_fecha_cooldown(sessionmaker):
    await circuit_breaker.registrar_falha(sessionmaker, "animefire.one", RuntimeError("x"))
    assert await circuit_breaker.esta_em_cooldown(sessionmaker, "animefire.one") is True

    await circuit_breaker.registrar_sucesso(sessionmaker, "animefire.one")

    assert await circuit_breaker.esta_em_cooldown(sessionmaker, "animefire.one") is False


async def test_registrar_falha_grava_mensagem_de_erro(sessionmaker):
    from models.estado_site import EstadoSite

    await circuit_breaker.registrar_falha(sessionmaker, "animefire.one", RuntimeError("boom"))

    async with sessionmaker() as sessao:
        estado = await sessao.get(EstadoSite, "animefire.one")
        assert estado.falhas_consecutivas == 1
        assert estado.ultimo_erro == "boom"
        assert estado.ultima_falha_em is not None

"""Testes de `fontes/rede/sessao_cache.py` contra SQLite real (mesmo padrão de
`tests/test_fila.py`), sem rede."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config import Config
from db.engine import criar_engine, criar_sessionmaker
from fontes.rede import sessao_cache
from models.base import Base
from models.sessao_bypass import SessaoBypass


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


async def test_carregar_sem_sessao_devolve_none(sessionmaker):
    assert await sessao_cache.carregar(sessionmaker, "animefire.one") is None


async def test_salvar_e_carregar_devolve_cookies_e_user_agent(sessionmaker):
    await sessao_cache.salvar(
        sessionmaker,
        "animefire.one",
        {"cf_clearance": "abc123"},
        "Mozilla/5.0 teste",
        ttl_s=3600,
    )

    contexto = await sessao_cache.carregar(sessionmaker, "animefire.one")

    assert contexto is not None
    assert contexto.cookies == {"cf_clearance": "abc123"}
    assert contexto.user_agent == "Mozilla/5.0 teste"


async def test_salvar_duas_vezes_faz_upsert(sessionmaker):
    await sessao_cache.salvar(
        sessionmaker, "animefire.one", {"a": "1"}, "ua-antigo", ttl_s=3600
    )
    await sessao_cache.salvar(
        sessionmaker, "animefire.one", {"b": "2"}, "ua-novo", ttl_s=3600
    )

    contexto = await sessao_cache.carregar(sessionmaker, "animefire.one")

    assert contexto.cookies == {"b": "2"}
    assert contexto.user_agent == "ua-novo"


async def test_carregar_sessao_vencida_devolve_none(sessionmaker):
    async with sessionmaker() as sessao:
        sessao.add(
            SessaoBypass(
                site_dominio="animefire.one",
                cookies_json='{"a": "1"}',
                user_agent="ua",
                expira_estimado_em=datetime.now(UTC) - timedelta(seconds=1),
            )
        )
        await sessao.commit()

    assert await sessao_cache.carregar(sessionmaker, "animefire.one") is None


async def test_invalidar_remove_sessao(sessionmaker):
    await sessao_cache.salvar(sessionmaker, "animefire.one", {"a": "1"}, "ua", ttl_s=3600)

    await sessao_cache.invalidar(sessionmaker, "animefire.one")

    assert await sessao_cache.carregar(sessionmaker, "animefire.one") is None


async def test_invalidar_sem_sessao_nao_falha(sessionmaker):
    await sessao_cache.invalidar(sessionmaker, "nao-existe.io")

"""Engine/sessionmaker assíncronos do SQLAlchemy, com os pragmas do SQLite fixados
por conexão (ESPECIFICACAO.md §4)."""

import sqlite3

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from core.config import Config


def criar_engine(config: Config) -> AsyncEngine:
    engine = create_async_engine(config.database_url)

    @event.listens_for(engine.sync_engine, "connect")
    def _fixar_pragmas(conexao_dbapi: sqlite3.Connection, _registro) -> None:
        cursor = conexao_dbapi.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def criar_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


def url_sincrona(database_url: str) -> str:
    """`sqlite+aiosqlite://...` -> `sqlite://...`, para uso do Alembic (engine síncrono)."""
    return database_url.replace("sqlite+aiosqlite://", "sqlite://", 1)

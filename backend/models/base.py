"""Base declarativa do SQLAlchemy, compartilhada por todos os modelos.

`naming_convention` nomeada é obrigatória: sem ela, o batch mode do Alembic no
SQLite não consegue recriar constraints por nome em migrations futuras (toda
ALTER no SQLite recria a tabela).
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, MetaData
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import TypeDecorator

_NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=_NAMING_CONVENTION)


class ColunaDataHoraUTC(TypeDecorator):
    """`DateTime(timezone=True)` que sobrevive ao round-trip pelo SQLite.

    SQLite (via `aiosqlite`) não preserva timezone em colunas `DateTime(timezone=True)`
    — um valor gravado como `datetime.now(UTC)` (aware) volta **naive** depois de um
    `SELECT`, quebrando qualquer comparação em Python puro contra outro datetime aware.
    Este tipo normaliza a fronteira do ORM nos dois sentidos, sem exigir migração: o
    formato gravado no SQLite (TEXT) não muda, só o que o SQLAlchemy devolve em Python.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is not None:
            return value.astimezone(UTC).replace(tzinfo=None)
        return value

    def process_result_value(self, value: Any, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value

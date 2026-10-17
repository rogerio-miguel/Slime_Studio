"""Testes de `db/engine.py`: pragmas fixados por conexão."""

import pytest
from sqlalchemy import text

from core.config import Config
from db.engine import criar_engine


@pytest.mark.parametrize(
    ("pragma", "esperado"),
    [
        ("foreign_keys", 1),
        ("trusted_schema", 0),
        ("cell_size_check", 1),
        ("busy_timeout", 5000),
    ],
)
async def test_criar_engine_fixa_pragmas_por_conexao(
    config_api: Config, pragma: str, esperado: int
):
    engine = criar_engine(config_api)
    try:
        async with engine.connect() as conexao:
            valor = (await conexao.execute(text(f"PRAGMA {pragma}"))).scalar_one()
    finally:
        await engine.dispose()

    assert valor == esperado

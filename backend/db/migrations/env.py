"""Ambiente de migrations do Alembic.

Roda em engine **síncrono** (`sqlite3` da stdlib) — não vale a pena trazer o
boilerplate de `greenlet`/`run_sync` do template async para uma operação
offline one-shot. A URL do banco vem de `carregar_config()`, nunca fixa no
`alembic.ini` (mesma fonte de verdade que a API/worker usam).
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from core.config import carregar_config
from db.engine import url_sincrona
from models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _obter_url() -> str:
    return url_sincrona(carregar_config().database_url)


def run_migrations_offline() -> None:
    context.configure(
        url=_obter_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuracao = config.get_section(config.config_ini_section, {})
    configuracao["sqlalchemy.url"] = _obter_url()
    conectavel = engine_from_config(configuracao, prefix="sqlalchemy.", poolclass=pool.NullPool)

    with conectavel.connect() as conexao:
        context.configure(
            connection=conexao,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

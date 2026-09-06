"""adiciona numero_temporada em anime

Fatia 2 do bugfix de capa de anime multi-temporada: a resolução de arte via
TMDB busca por *série*, não por temporada, então sem saber qual temporada
(`n` do endpoint `/tv/{id}/season/{n}`) o título representa, a capa sempre
resolve pro pôster da temporada 1. `anime` ganha:

- `numero_temporada`: o `n` literal do endpoint TMDB de temporada — NÃO é
  ordinal narrativo arbitrário. `NULL` significa "desconhecido" e nunca é
  tratado como `1` (preserva o comportamento atual de cair no pôster geral
  da série quando não se sabe qual temporada é).

Sem backfill nesta migration: o preenchimento de dados históricos é feito
por um script separado (`scripts/backfill_arte_por_temporada.py`, ainda a
ser criado em fatia futura), não aqui — migrations deste projeto são
puro-schema, sem I/O de rede. Nullable, sem default e sem `server_default`:
animes já cadastrados ficam `NULL` até o backfill. `ADD COLUMN` nullable é
suportado nativamente pelo SQLite, sem `op.batch_alter_table`.

Revision ID: f19a3c6d8b2e
Revises: 292444de7e7e
Create Date: 2026-09-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f19a3c6d8b2e'
down_revision: Union[str, None] = '292444de7e7e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('anime', sa.Column('numero_temporada', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('anime', 'numero_temporada')

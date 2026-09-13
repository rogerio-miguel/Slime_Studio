"""adiciona titulo_ingles em anime

Linha secundária do hero da página do anime (título em inglês sob o título
local, mesmo par título/subtítulo do carrossel da Home). `anime` ganha uma
coluna alimentada por `db.catalogo.aplicar_metadados` a partir de
`title.english` da AniList:

- `titulo_ingles`: SÓ exibição — ao contrário de `titulo` (canônico, local),
  este é o do provedor. Preenchido só-quando-nulo.

Nullable, sem default e sem `server_default`: animes já cadastrados ficam
`NULL` até o primeiro enriquecimento de metadados — não há backfill. `ADD
COLUMN` nullable é suportado nativamente pelo SQLite, sem
`op.batch_alter_table`.

Revision ID: c1e5b9a34d70
Revises: d7e1a4c802fb
Create Date: 2026-09-10 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c1e5b9a34d70'
down_revision: Union[str, None] = 'd7e1a4c802fb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('anime', sa.Column('titulo_ingles', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('anime', 'titulo_ingles')

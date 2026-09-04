"""adiciona generos em anime

Lista de gêneros crus da AniList (`genres`, ex. `["Action", "Comedy"]`) no card
e na página do anime — a tradução pt-BR é no frontend. `anime` ganha uma coluna
`JSON` alimentada pelos mesmos caminhos que já preenchem `capa_path`/`sinopse`
(`db.catalogo.aplicar_metadados` a partir do `genres` da AniList).

Nullable, sem default e sem `server_default`: animes já cadastrados ficam `NULL`
até o backfill único (`scripts/backfill_metadados_visuais.py`) ou o próximo
enriquecimento por id/título. `ADD COLUMN` nullable é suportado nativamente pelo
SQLite, sem `op.batch_alter_table`.

Revision ID: e7c4b1a9d2f0
Revises: d4b7e2f019ac
Create Date: 2026-09-04 11:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e7c4b1a9d2f0'
down_revision: Union[str, None] = 'd4b7e2f019ac'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('anime', sa.Column('generos', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('anime', 'generos')

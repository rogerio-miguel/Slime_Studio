"""adiciona banner e capa_cor em anime

Imagem panorâmica (hero) na página do anime. `anime` ganha duas colunas
alimentadas pelos mesmos caminhos que já preenchem `capa_path`/`sinopse`
(`db.catalogo.aplicar_metadados` a partir do `bannerImage`/`coverImage.color`
da AniList) e pelo cruzamento com o feed "em alta":

- `banner_path`: URL da arte horizontal (`bannerImage` da AniList) — mesma
  convenção de `capa_path` (URL do provedor, não caminho em disco).
- `capa_cor`: cor dominante da capa (`coverImage.color` da AniList, ex.
  "#e4a15d") — fundo do fallback do hero quando não há `banner_path`.

Ambas nullable, sem default e sem `server_default`: animes já cadastrados
ficam `NULL` até o backfill único (`scripts/backfill_metadados_visuais.py`) ou
o próximo cruzamento com o feed. `ADD COLUMN` nullable é suportado nativamente
pelo SQLite, sem `op.batch_alter_table`.

Revision ID: d4b7e2f019ac
Revises: a3e9d1f47b02
Create Date: 2026-09-04 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4b7e2f019ac'
down_revision: Union[str, None] = 'a3e9d1f47b02'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('anime', sa.Column('banner_path', sa.String(), nullable=True))
    op.add_column('anime', sa.Column('capa_cor', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('anime', 'capa_cor')
    op.drop_column('anime', 'banner_path')

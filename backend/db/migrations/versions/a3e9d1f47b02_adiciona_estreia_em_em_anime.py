"""adiciona estreia_em em anime

Data de estreia real no card de bookmark do catálogo. `anime` ganha uma
coluna alimentada por `db.catalogo._aplicar_lancamento_no_anime` a partir do
`startDate` da AniList:

- `estreia_em`: data completa (ano+mês+dia) de estreia — `DATE` puro, sem
  timezone (ao contrário de `proximo_ep_em`, que é um instante). Só é gravada
  quando os três componentes vieram da AniList; `startDate` parcial (só ano)
  alimenta `Anime.ano` e deixa esta coluna `NULL`.

Nullable, sem default e sem `server_default`: animes já cadastrados ficam
`NULL` até o primeiro refresh de lançamento — não há backfill. `ADD COLUMN`
nullable é suportado nativamente pelo SQLite, sem `op.batch_alter_table`.

Revision ID: a3e9d1f47b02
Revises: b2d5f8a4c1e6
Create Date: 2026-09-02 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3e9d1f47b02'
down_revision: Union[str, None] = 'b2d5f8a4c1e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('anime', sa.Column('estreia_em', sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column('anime', 'estreia_em')

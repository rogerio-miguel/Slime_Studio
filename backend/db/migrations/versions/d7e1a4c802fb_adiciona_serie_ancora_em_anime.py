"""adiciona serie_ancora em anime

Fase 3 do plano de limpeza do sistema: separar descoberta (AniList) de
resolução de fonte (scraping) e agrupar temporadas da mesma franquia. `anime`
ganha:

- `serie_ancora`: o `anilist_id` da temporada 1 da franquia (a própria linha
  quando não há prequel). É um `anilist_id`, NÃO um `Anime.id` local, e pode
  apontar para uma temporada fora do catálogo — por isso não é FK. Índice
  não-único (`ix_anime_serie_ancora`) para o agrupamento por franquia da
  camada de apresentação.

Sem backfill nesta migration (schema puro, sem I/O de rede — padrão do
projeto): o preenchimento histórico é feito por `scripts/backfill_serie.py`,
que consulta a AniList. Nullable, sem default: animes já cadastrados ficam
`NULL` até o backfill. `ADD COLUMN` nullable e `CREATE INDEX` são suportados
nativamente pelo SQLite, sem `op.batch_alter_table`.

Revision ID: d7e1a4c802fb
Revises: f19a3c6d8b2e
Create Date: 2026-09-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd7e1a4c802fb'
down_revision: Union[str, None] = 'f19a3c6d8b2e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('anime', sa.Column('serie_ancora', sa.Integer(), nullable=True))
    op.create_index('ix_anime_serie_ancora', 'anime', ['serie_ancora'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_anime_serie_ancora', table_name='anime')
    op.drop_column('anime', 'serie_ancora')

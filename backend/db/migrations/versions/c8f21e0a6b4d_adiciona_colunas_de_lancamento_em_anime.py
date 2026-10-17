"""adiciona colunas de lancamento em anime

Fatia F1 do detector de episódios novos. `anime` ganha quatro colunas para o
sinal de lançamento vindo da AniList (`MediaStatus` + `nextAiringEpisode`):

- `status_lancamento`: enum gravado como name (`EM_LANCAMENTO`, `FINALIZADO`,
  `NAO_LANCADO`, `CANCELADO`, `HIATO`) — VARCHAR sem CHECK no SQLite
  (`native_enum=False`, sem `create_constraint`), mesma convenção de
  `episodio.status`.
- `proximo_ep_numero` / `proximo_ep_em`: número do próximo episódio a ir ao ar
  e quando.
- `lancamento_atualizado_em`: carimbo do último refresh de lançamento.

Todas nullable, sem default e sem `server_default`: animes já cadastrados
ficam NULL até o primeiro refresh (fatia F4) — não há backfill. `ADD COLUMN`
nullable é suportado nativamente pelo SQLite, sem `op.batch_alter_table`.

Revision ID: c8f21e0a6b4d
Revises: 74dcc7485153
Create Date: 2026-08-30 14:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c8f21e0a6b4d'
down_revision: Union[str, None] = '74dcc7485153'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'anime',
        sa.Column(
            'status_lancamento',
            sa.Enum(
                'EM_LANCAMENTO',
                'FINALIZADO',
                'NAO_LANCADO',
                'CANCELADO',
                'HIATO',
                name='statuslancamento',
                native_enum=False,
            ),
            nullable=True,
        ),
    )
    op.add_column('anime', sa.Column('proximo_ep_numero', sa.Integer(), nullable=True))
    op.add_column(
        'anime', sa.Column('proximo_ep_em', sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        'anime',
        sa.Column('lancamento_atualizado_em', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('anime', 'lancamento_atualizado_em')
    op.drop_column('anime', 'proximo_ep_em')
    op.drop_column('anime', 'proximo_ep_numero')
    op.drop_column('anime', 'status_lancamento')

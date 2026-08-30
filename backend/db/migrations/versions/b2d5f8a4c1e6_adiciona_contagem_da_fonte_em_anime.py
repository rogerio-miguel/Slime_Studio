"""adiciona contagem da fonte em anime

Detector de episódios novos, evolução da fatia F5: o cálculo de "episódios
novos" deixa de usar o `nextAiringEpisode` da AniList e passa a comparar o
que a FONTE real do anime (site que o usuário usa) expõe com os episódios já
capturados. `anime` ganha três colunas alimentadas por
`api/servicos/sondagem.py`:

- `episodios_na_fonte`: nº de episódios regulares distintos vistos na fonte
  na última sondagem bem-sucedida.
- `fonte_verificada_em`: carimbo da última sondagem bem-sucedida — decide o
  TTL (falha de site não carimba).
- `fonte_verificada_dominio`: qual site produziu a contagem (proveniência).

Todas nullable, sem default e sem `server_default`: animes já cadastrados
ficam NULL até a primeira sondagem — não há backfill. `ADD COLUMN` nullable é
suportado nativamente pelo SQLite, sem `op.batch_alter_table`.

Revision ID: b2d5f8a4c1e6
Revises: c8f21e0a6b4d
Create Date: 2026-08-30 16:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2d5f8a4c1e6'
down_revision: Union[str, None] = 'c8f21e0a6b4d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('anime', sa.Column('episodios_na_fonte', sa.Integer(), nullable=True))
    op.add_column(
        'anime', sa.Column('fonte_verificada_em', sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        'anime', sa.Column('fonte_verificada_dominio', sa.String(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('anime', 'fonte_verificada_dominio')
    op.drop_column('anime', 'fonte_verificada_em')
    op.drop_column('anime', 'episodios_na_fonte')

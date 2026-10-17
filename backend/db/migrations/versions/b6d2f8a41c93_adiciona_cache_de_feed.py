"""adiciona cache_de_feed

Último resultado bom de cada feed de descoberta da Home (em alta, novos
lançamentos, próxima temporada, fileiras temáticas), persistido para sobreviver a
reinício da API: sem isto, a 1ª abertura da Home depois de subir o processo espera
a busca AniList + overlay de arte TMDB inteira (dezenas de segundos medidos). Tabela
nova, sem dado a migrar; descartável (é cache, não fonte de verdade).

Revision ID: b6d2f8a41c93
Revises: 8c71dfb26a37
Create Date: 2026-10-02 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b6d2f8a41c93'
down_revision: Union[str, None] = '8c71dfb26a37'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'cache_de_feed',
        sa.Column('chave', sa.String(), nullable=False),
        sa.Column('itens_json', sa.Text(), nullable=False),
        sa.Column('atualizado_em', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('chave'),
    )


def downgrade() -> None:
    op.drop_table('cache_de_feed')

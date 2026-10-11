"""adiciona abertura_de_navegador e verificacao_de_anime.dominio

`abertura_de_navegador`: cada abertura automática do navegador pelo zelador de
fontes, para o teto diário sobreviver a reinício da API. Tabela nova.
`verificacao_de_anime.dominio`: site que pediu sessão nova (`PRECISA_SESSAO`),
para o zelador saber qual renovar. `ADD COLUMN` nullable é suportado nativamente
pelo SQLite, sem `op.batch_alter_table`.

Revision ID: d7b2e5f1a903
Revises: c4e9a1b7d305
Create Date: 2026-10-11 17:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd7b2e5f1a903'
down_revision: Union[str, None] = 'c4e9a1b7d305'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'abertura_de_navegador',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('dominio', sa.String(), nullable=False),
        sa.Column('aberta_em', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_abertura_de_navegador')),
    )
    op.create_index(
        op.f('ix_abertura_de_navegador_aberta_em'), 'abertura_de_navegador', ['aberta_em']
    )
    op.add_column('verificacao_de_anime', sa.Column('dominio', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('verificacao_de_anime', 'dominio')
    op.drop_index(op.f('ix_abertura_de_navegador_aberta_em'), table_name='abertura_de_navegador')
    op.drop_table('abertura_de_navegador')

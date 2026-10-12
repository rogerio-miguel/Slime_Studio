"""adiciona verificacao_de_anime

Estado persistido das verificações periódicas de cada anime (hoje a sondagem da
fonte): próxima tentativa, último resultado e falhas consecutivas, para o backoff
sobreviver a restart e a abertura repetida da Galeria. Tabela nova, sem dado a
migrar.

Revision ID: c4e9a1b7d305
Revises: a8c3d5e7f912
Create Date: 2026-10-11 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4e9a1b7d305'
down_revision: Union[str, None] = 'a8c3d5e7f912'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'verificacao_de_anime',
        sa.Column('anime_id', sa.Integer(), nullable=False),
        sa.Column('tarefa', sa.Enum('FONTE', name='tarefadeverificacao', native_enum=False), nullable=False),
        sa.Column('proxima_em', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ultima_tentativa_em', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ultimo_sucesso_em', sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            'ultimo_resultado',
            sa.Enum(
                'OK', 'NAO_ENCONTRADO', 'PRECISA_SESSAO', 'SITE_INDISPONIVEL', 'AMBIGUO', 'ERRO',
                name='resultadodeverificacao', native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column('falhas_consecutivas', sa.Integer(), nullable=False),
        sa.Column('detalhe', sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ['anime_id'], ['anime.id'],
            name=op.f('fk_verificacao_de_anime_anime_id_anime'), ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('anime_id', 'tarefa', name=op.f('pk_verificacao_de_anime')),
    )
    op.create_index('ix_verificacao_de_anime_proxima_em', 'verificacao_de_anime', ['proxima_em'])


def downgrade() -> None:
    op.drop_index('ix_verificacao_de_anime_proxima_em', table_name='verificacao_de_anime')
    op.drop_table('verificacao_de_anime')

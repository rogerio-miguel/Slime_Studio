"""episodio ganha progresso de reproducao

Feature "continuar assistindo": `episodio.progresso_s` (posição em segundos)
e `episodio.progresso_atualizado_em` (quando foi salva) — 1:1 com `Episodio`,
sem tabela própria (app local mono-usuário). Duas colunas nullable, sem dado
existente para migrar (todo episódio começa sem progresso salvo) — `ADD
COLUMN` simples é suficiente no SQLite, sem precisar de `batch_alter_table`
(reservado para mudanças que alteram/removem coluna existente ou constraint).

Revision ID: 7a3f8c1e9d4b
Revises: 0cfc12357433
Create Date: 2026-08-18 11:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7a3f8c1e9d4b'
down_revision: Union[str, None] = '0cfc12357433'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('episodio', sa.Column('progresso_s', sa.Integer(), nullable=True))
    op.add_column(
        'episodio', sa.Column('progresso_atualizado_em', sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('episodio', 'progresso_atualizado_em')
    op.drop_column('episodio', 'progresso_s')

"""adiciona origem em fonte_anime

`origem` registra quem decidiu o mapeamento (MANUAL: escolha do usuário;
AUTOMATICA: resolução automática). As linhas existentes viram MANUAL: não há como saber
quais foram escolha do usuário, e tratar todas como manuais é o lado seguro — uma
troca automática futura nunca passa por cima delas. `server_default` é necessário
porque `ADD COLUMN ... NOT NULL` no SQLite exige um valor para as linhas atuais.

Revision ID: e2a7c9d4b618
Revises: c4e9a1b7d305
Create Date: 2026-10-11 17:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e2a7c9d4b618'
down_revision: Union[str, None] = 'c4e9a1b7d305'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'fonte_anime',
        sa.Column(
            'origem',
            sa.Enum('MANUAL', 'AUTOMATICA', name='origemdefonte', native_enum=False),
            nullable=False,
            server_default=sa.text("'MANUAL'"),
        ),
    )


def downgrade() -> None:
    op.drop_column('fonte_anime', 'origem')

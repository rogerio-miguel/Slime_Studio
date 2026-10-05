"""adiciona banner_escolhido em anime

Banner que o usuário escolhe no seletor da página do anime, por franquia (gravado
em todas as linhas do grupo). Fica numa coluna própria, fora de `banner_path`,
para que nenhum caminho que sobrescreve `banner_path` precise saber da escolha.

Nullable, sem default e sem `server_default`: `NULL` é "sem escolha, vale o banner
automático". `ADD COLUMN` nullable é suportado nativamente pelo SQLite, sem
`op.batch_alter_table`.

Revision ID: a8c3d5e7f912
Revises: b6d2f8a41c93
Create Date: 2026-10-05 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a8c3d5e7f912'
down_revision: Union[str, None] = 'b6d2f8a41c93'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('anime', sa.Column('banner_escolhido', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('anime', 'banner_escolhido')

"""adiciona sinopse em episodio

Sinopse do episódio ("EP.n - nome do ep" + sinopse abaixo, página do anime).
`titulo` já existia mas ficava sempre `NULL` na prática (nenhum extractor de
scraping expõe título/sinopse de episódio) — os dois passam a vir do overlay
TMDB (`integrations/tmdb.py`, mesmo `GET /tv/{id}/season/{n}` que já resolve
a still), persistidos na captura (`api/servicos/jobs.py::criar_job_site`).

Nullable, sem default e sem `server_default`: episódio já capturado antes
desta coluna fica `NULL` até uma recaptura — sem backfill. `ADD COLUMN`
nullable é suportado nativamente pelo SQLite, sem `op.batch_alter_table`.

Revision ID: f4a8c2d16e93
Revises: c1e5b9a34d70
Create Date: 2026-09-10 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f4a8c2d16e93'
down_revision: Union[str, None] = 'c1e5b9a34d70'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('episodio', sa.Column('sinopse', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('episodio', 'sinopse')

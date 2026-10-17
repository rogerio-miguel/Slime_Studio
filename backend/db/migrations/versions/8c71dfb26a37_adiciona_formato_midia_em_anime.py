"""adiciona formato_midia em anime

Filme/OVA/ONA/especial de uma franquia se agrupa no anime original em vez de
virar card solto no catálogo (mesmo funcionamento de temporada, ver seção 3
do CLAUDE.md). `anime` ganha:

- `formato_midia`: `format` cru da AniList ("MOVIE"/"OVA"/"ONA"/"SPECIAL")
  quando esta linha NÃO é uma temporada de TV. `NULL` é o caso normal (série
  TV) — `numero_temporada`/`serie_ancora` seguem exatamente como hoje.
  Não-nulo: `numero_temporada` nunca é preenchido (sem posição narrativa
  numerada) e `serie_ancora` é resolvido por série-mãe
  (`api/servicos/descoberta.py::_aplicar_ancora_de_midia`), não pelo walk
  `PREQUEL` normal. Usado pra excluir a linha da grade do catálogo
  (`GET /api/animes`) — só aparece no seletor de temporada da franquia.

Sem backfill: linhas já catalogadas ficam `NULL` (tratadas como série normal,
comportamento idêntico ao de hoje). Nullable, sem default — `ADD COLUMN`
nullable é suportado nativamente pelo SQLite, sem `op.batch_alter_table`.

Revision ID: 8c71dfb26a37
Revises: 26791d90cb31
Create Date: 2026-09-17 15:18:38.250605

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8c71dfb26a37'
down_revision: Union[str, None] = '26791d90cb31'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('anime', sa.Column('formato_midia', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('anime', 'formato_midia')

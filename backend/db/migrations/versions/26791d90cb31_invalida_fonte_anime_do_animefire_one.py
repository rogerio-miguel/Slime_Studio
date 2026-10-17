"""invalida fonte_anime do animefire (migração .io -> .one)

O AnimeFire trocou de domínio de novo: `animefire.io`/`api.animefire.io` pararam
de responder, site inteiro migrou pra `animefire.one`/`api.animefire.one`
(confirmado pelo usuário em 2026-09-15). `extractors/animefire.py::dominio`
passou a devolver `"animefire.one"` — mesmo raciocínio da migração irmã
292444de7e7e: enquanto linhas com o `site_dominio` antigo continuarem em
`fonte_anime`, `extractors/resolucao.py` prefere o mapeamento já salvo em vez
de resolver de novo, e a extração falha contra um domínio que não responde
mais.

`fonte_anime` é cache de resolução (site + identificador), não dado do
usuário: apagar as linhas de `site_dominio='animefire.io'` só força a
resolução a rodar de novo, ao vivo, na próxima tentativa — nada aqui é
irrecuperável, por isso o `downgrade` é no-op.

Revision ID: 26791d90cb31
Revises: f4a8c2d16e93
Create Date: 2026-09-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '26791d90cb31'
down_revision: Union[str, None] = 'f4a8c2d16e93'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DELETE FROM fonte_anime WHERE site_dominio = 'animefire.io'")


def downgrade() -> None:
    pass  # no-op: cache de resolução recalculável ao vivo, não dado do usuário — nada a restaurar

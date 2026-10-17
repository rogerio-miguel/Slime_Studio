"""invalida fonte_anime do animefire

O AnimeFire migrou de scraping de HTML pra uma API JSON pública, trocando o
esquema de identificação de episódios: slugs do site antigo (ex. `"one-piece"`)
não têm nenhuma tradução pro id opaco do esquema novo (ex. `"OZLtRqzPHBm"`).
Enquanto essas linhas antigas continuarem em `fonte_anime`, `extractors/resolucao.py`
vai preferir o mapeamento já salvo em vez de resolver de novo, e toda tentativa
de listar episódios desses animes vai falhar contra a API nova.

`fonte_anime` é cache de resolução (site + identificador), não dado do usuário:
apagar as linhas de `site_dominio='animefire.io'` só força a resolução a rodar
de novo, ao vivo, na próxima tentativa — nada aqui é irrecuperável, por isso o
`downgrade` é no-op.

Revision ID: 292444de7e7e
Revises: e7c4b1a9d2f0
Create Date: 2026-09-04 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '292444de7e7e'
down_revision: Union[str, None] = 'e7c4b1a9d2f0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DELETE FROM fonte_anime WHERE site_dominio = 'animefire.io'")


def downgrade() -> None:
    pass  # no-op: cache de resolução recalculável ao vivo, não dado do usuário — nada a restaurar

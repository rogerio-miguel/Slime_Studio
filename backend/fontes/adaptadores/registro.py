"""Registro dos extratores disponíveis (ESPECIFICACAO.md §3A) — ordem da tupla é
ordem de prioridade de fallback (`fontes/resolucao.py`).

Ordem: AnimeFire (padrão) → MeusAnimes → AnimesDrive. A base histórica é
ESPECIFICACAO.md §3A item 2 ("AnimeFire primeiro, AnimesDrive em seguida"); o
MeusAnimes entra no meio porque não tem challenge de Cloudflare (cliente leve
alcança busca/listagem/mídia, ao contrário do AnimesDrive) e resolve mídia 100%
por HTTP — mas com teto de 720p, então é fonte intermediária, não substituta do
AnimeFire.
"""

from core.erros import ErroSlimeStudio
from fontes.adaptadores.animefire import AnimeFireProvider
from fontes.adaptadores.animesdrive import AnimesDriveProvider
from fontes.adaptadores.base import ExtratorDeSite
from fontes.adaptadores.meusanimes import MeusAnimesProvider

EXTRATORES: tuple[ExtratorDeSite, ...] = (
    AnimeFireProvider(),
    MeusAnimesProvider(),
    AnimesDriveProvider(),
)

_POR_DOMINIO: dict[str, ExtratorDeSite] = {extrator.dominio: extrator for extrator in EXTRATORES}


def obter_extrator(dominio: str) -> ExtratorDeSite:
    extrator = _POR_DOMINIO.get(dominio)
    if extrator is None:
        raise ErroSlimeStudio(f"nenhum extrator registrado para o domínio {dominio!r}")
    return extrator

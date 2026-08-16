"""Registro dos extratores disponíveis (ESPECIFICACAO.md §3A) — ordem da tupla é
ordem de prioridade de fallback (`extractors/resolucao.py`).

2A: só AnimeFire (sem navegador). AnimesDrive entra na 2B.
"""

from core.erros import ErroSlimeStudio
from extractors.animefire import AnimeFireProvider
from extractors.base import ExtratorDeSite

EXTRATORES: tuple[ExtratorDeSite, ...] = (AnimeFireProvider(),)

_POR_DOMINIO: dict[str, ExtratorDeSite] = {extrator.dominio: extrator for extrator in EXTRATORES}


def obter_extrator(dominio: str) -> ExtratorDeSite:
    extrator = _POR_DOMINIO.get(dominio)
    if extrator is None:
        raise ErroSlimeStudio(f"nenhum extrator registrado para o domínio {dominio!r}")
    return extrator

"""Filtro de conteúdo adulto de todo o sistema: título cujo gênero seja
"Hentai" nunca aparece em feed, busca, relacionados nem catálogo.

Domínio puro — usado por `api/` e `integrations/` sem acoplar uma à outra.
O gênero vem cru da AniList (`genres`), em inglês, sem tradução no backend.
"""

from collections.abc import Iterable

_GENEROS_BLOQUEADOS = frozenset({"hentai"})


def eh_conteudo_adulto(generos: Iterable[str] | None) -> bool:
    return any(g.strip().casefold() in _GENEROS_BLOQUEADOS for g in generos or ())

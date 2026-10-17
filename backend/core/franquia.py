"""Chave de agrupamento de franquia — domínio puro (Escada de Minimalismo).

`Anime.serie_ancora` (walk de `relations` da AniList) é o sinal primário de "que
temporadas são da mesma franquia", mas erra quando há OVA/ONA/split-cour no meio
da cadeia (Fase 6, adiada): uma temporada fica com uma âncora e a irmã fica com
`NULL` ou com outra âncora. O slug do título SEM o marcador de temporada é o
segundo sinal que reconecta as duas — `separar_temporada` já isola o título base.

Espelhado em `frontend/src/inicio/franquia.js` (mesmo par de sinais no
agrupamento client-side do catálogo).
"""

from core.temporada import separar_temporada
from core.texto import sem_simbolo_final, slugificar


def slug_de_franquia(titulo: str) -> str:
    """Slug do título base (sem marcador de temporada nem símbolo final, como o
    "××" de "Kakegurui ××"). `""` quando o título slugifica para vazio — o
    chamador trata como "sem sinal de slug"."""
    return slugificar(separar_temporada(sem_simbolo_final(titulo))[0])

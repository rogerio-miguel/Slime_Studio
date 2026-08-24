"""Classificação de rótulo de qualidade de vídeo (ESPECIFICACAO.md §3A) —
domínio puro, sem I/O, compartilhado entre os adapters que expõem escolha de
qualidade (`extractors/animesdrive.py`, `extractors/animefire.py`).

Mesmo caráter de `extractors/versao.py`: só lê o texto que já atravessou a
fronteira do site, não faz scraping novo. Vocabulário de extractor, não
domínio persistido — fica fora de `core/enums.py` de propósito.
"""

import re
import unicodedata
from enum import IntEnum


class NivelDeQualidade(IntEnum):
    ABAIXO_DO_PISO = 0  # SD/480/mobile — reconhecido como ruim, DESCARTE SEMPRE
    DESCONHECIDA = 1  # "Dublado", "Servidor 2" — não é reivindicação de qualidade
    HD = 2  # piso aceitável
    FHD = 3


# `4k`/`2160` no mesmo padrão do FHD: sem isso uma fonte 4k seria classificada
# como `DESCONHECIDA` por não casar tier nenhum — o caso patológico de
# descartar a melhor fonte por não haver tier acima de FHD.
_REGEX_FHD = re.compile(r"\b(?:f(?:ull)?\s*hd|1080p?|2160p?|4k)\b")
_REGEX_HD = re.compile(r"\b(?:hd|720p?)\b")
_REGEX_BAIXA = re.compile(r"\b(?:sd|480p?|360p?|240p?|mobile|movel|celular|baixa)\b")


def qualidade_do_rotulo(rotulo: str) -> NivelDeQualidade:
    """Classifica `rotulo` (ex. "FullHD / HLS", "SD", "Dublado") pelo maior tier
    de qualidade citado nele — regra objetiva, não lista de sinônimos.

    Normaliza (`NFKD` + descarte de combining marks + `casefold`) e testa os
    padrões do mais alto pro mais baixo, parando no primeiro que casar — é o
    que garante que `"FHD / HD"` e `"SD/HD"` resolvam pro tier mais alto citado
    (FHD e HD, respectivamente), não pro primeiro token do rótulo.

    Ausência de qualquer vocabulário de qualidade não é SD — é `DESCONHECIDA`:
    `"Dublado"`, `"Servidor 2"` e `""` não são reivindicação de qualidade
    nenhuma, e tratá-los como ruins puniria servidor sem rótulo por engano.
    """
    normalizado = unicodedata.normalize("NFKD", rotulo)
    normalizado = "".join(c for c in normalizado if not unicodedata.combining(c))
    normalizado = re.sub(r"[^0-9a-z]+", " ", normalizado.casefold())

    if _REGEX_FHD.search(normalizado):
        return NivelDeQualidade.FHD
    if _REGEX_HD.search(normalizado):
        return NivelDeQualidade.HD
    if _REGEX_BAIXA.search(normalizado):
        return NivelDeQualidade.ABAIXO_DO_PISO
    return NivelDeQualidade.DESCONHECIDA

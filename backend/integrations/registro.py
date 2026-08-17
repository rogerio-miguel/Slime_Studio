"""Registro dos provedores de metadados disponíveis — ordem da tupla é ordem
de fallback (ESPECIFICACAO.md: AniList principal, Kitsu fallback — decisão de
produto já fechada), mesmo papel de `extractors/registro.py`.
"""

from integrations.anilist import AniListProvider
from integrations.base import ProvedorDeMetadados
from integrations.kitsu import KitsuProvider

PROVEDORES: tuple[ProvedorDeMetadados, ...] = (AniListProvider(), KitsuProvider())

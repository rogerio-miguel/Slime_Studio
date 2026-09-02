"""Registro dos provedores de metadados disponíveis — ordem da tupla é ordem
de fallback (ESPECIFICACAO.md: AniList principal, Kitsu fallback — decisão de
produto já fechada), mesmo papel de `extractors/registro.py`.
"""

from integrations.anilist import AniListProvider
from integrations.base import ProvedorDeMetadados
from integrations.kitsu import KitsuProvider

_anilist = AniListProvider()

# Cadeia de fallback para busca de metadados POR TÍTULO/ID (capa, sinopse,
# lançamento) e para o enriquecimento do catálogo — Kitsu cobre o que a AniList
# não achou.
PROVEDORES: tuple[ProvedorDeMetadados, ...] = (_anilist, KitsuProvider())

# Subconjunto para os feeds sazonais da Home ("em alta" / "próxima temporada"):
# só provedores cujo feed reflete a TEMPORADA CORRENTE. Kitsu fica de fora — seu
# `/trending/anime` é popularidade de todos os tempos (One Piece, Death Note,
# Attack on Titan…), não a temporada; como fallback ele encheria o carrossel, o
# Top 10 e as Próximas estreias de anime velho. Com a AniList fora do ar, é
# melhor a Home devolver o erro honesto ("feed indisponível", HTTP 502 →
# `FalhaDeMetadados`) do que conteúdo enganoso. Kitsu segue em `PROVEDORES`
# acima para busca por título/id.
PROVEDORES_DE_FEED: tuple[ProvedorDeMetadados, ...] = (_anilist,)

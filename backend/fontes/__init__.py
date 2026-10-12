"""Fonte = site de streaming de vídeo (AnimeFire, AnimesDrive, MeusAnimes).

Tudo que consulta esses sites vive aqui: adapters, rede/resiliência, busca por
título, resolução do mapeamento `FonteAnime` e listagem de episódios. Metadados
(AniList, Kitsu, TMDB) NÃO são fonte — são `integrations/` — e esta pasta nunca
importa de lá. O download de vídeo fica em `captura/` e depende daqui, nunca o
contrário.
"""

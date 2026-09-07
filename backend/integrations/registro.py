"""Registro dos provedores de metadados disponíveis — ordem da tupla é ordem
de fallback (ESPECIFICACAO.md: AniList principal, Kitsu fallback — decisão de
produto já fechada), mesmo papel de `extractors/registro.py`.
"""

import logging

from integrations.anilist import AniListProvider
from integrations.base import FileiraTematica, ProvedorDeArte, ProvedorDeMetadados
from integrations.kitsu import KitsuProvider
from integrations.tmdb import TmdbProvider

logger = logging.getLogger(__name__)

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

# Subconjunto para a resolução do título canônico da busca em fontes
# (`api/servicos/busca.py::_resolver_titulos_canonicos`, base de
# `_referencias_de_anime`/`_termos_de_busca`): essa resolução precisa ser rápida
# e determinística — é enriquecimento best-effort sob teto curto
# (`_TETO_METADADOS_S`), NÃO pré-condição da busca. O `buscar_titulos` do Kitsu
# é mais pobre que o da AniList (menos sinônimos, sem título nativo) e, com o
# Kitsu instável (read timeout em toda chamada), o fallback só adiciona latência
# de timeout antes de a busca degradar para o título digitado de qualquer jeito.
# Kitsu segue em `PROVEDORES` acima para busca de metadados por título/id
# (capa/sinopse/lançamento) e enriquecimento do catálogo — só a busca de
# TÍTULOS para o scraping é que é AniList-only.
PROVEDORES_DE_TITULO: tuple[ProvedorDeMetadados, ...] = (_anilist,)

# Fileiras temáticas da Home — curadoria por popularidade real por tag na
# AniList, filtrada por distintividade (cortadas tags genéricas que já se
# sobrepõem com Gêneros). Repetição de anime entre fileiras é permitida
# (mesmo comportamento de Netflix/Disney+). Sem filtro de país de origem: o
# volume por tag já é alto o bastante, filtrar derrubaria coproduções
# legítimas. Fileira de "adaptado de manhwa" foi cogitada e descartada —
# `MediaSource` da AniList não tem valor `MANHWA`, só dava pra resolver via
# query separada pelo lado do mangá + relações `ADAPTATION`, custo não
# justificado pra esta rodada. Ordem é decisão de produto fechada, não alterar.
FILEIRAS_TEMATICAS: list[FileiraTematica] = [
    FileiraTematica(chave="isekai", tag="Isekai"),
    FileiraTematica(chave="familia_encontrada", tag="Found Family"),
    FileiraTematica(chave="amor_nao_correspondido", tag="Unrequited Love"),
    FileiraTematica(chave="batalha_real", tag="Battle Royale"),
    FileiraTematica(chave="diferenca_de_idade", tag="Age Gap"),
    FileiraTematica(chave="reencarnacao", tag="Reincarnation"),
    FileiraTematica(chave="jogos_mortais", tag="Death Game"),
    FileiraTematica(chave="morando_juntos", tag="Cohabitation"),
    FileiraTematica(chave="casais_secretos", tag="Fake Relationship"),
    FileiraTematica(chave="vila_nao_tao_vila", tag="Villainess"),
]

# Provedores de ARTE (capa/banner) — tupla PRÓPRIA, não a `PROVEDORES` acima:
# `ProvedorDeArte` é uma capability autônoma (D1 do PLANO_ARTE_TMDB.md), não um
# `ProvedorDeMetadados` filtrável por `isinstance` a partir daquela tupla.
# Instalada em runtime por `instalar_provedores_de_arte`, nunca no import deste
# módulo (D2): ler o token aqui faria `uv run pytest` instanciar um
# `TmdbProvider` com token real e bater em rede de verdade em toda a suíte.
_provedores_de_arte: tuple[ProvedorDeArte, ...] = ()


def instalar_provedores_de_arte(token: str | None) -> None:
    """Chamada uma vez no lifespan da API (`api/main.py`) e no início do
    backfill (`scripts/backfill_metadados_visuais.py`) — nunca no import deste
    módulo (D2). Sem token, a tupla fica vazia e a cadeia de arte degrada pra
    AniList sem quebrar nada; loga um `warning` para a ausência não passar
    despercebida."""
    global _provedores_de_arte
    if not token:
        logger.warning("TMDB_READ_ACCESS_TOKEN ausente: capas/banners vêm só da AniList")
        _provedores_de_arte = ()
        return
    _provedores_de_arte = (TmdbProvider(token),)


def provedores_de_arte() -> tuple[ProvedorDeArte, ...]:
    return _provedores_de_arte

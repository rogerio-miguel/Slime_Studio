"""Adapter AniList (GraphQL) — provedor primário de metadados de anime.

Síncrono via `requests` (já dependência de produção do projeto —
`pyproject.toml`); o `asyncio.to_thread`/timeout que o torna não-bloqueante
mora só em `integrations/servico.py` (mesma separação de
`extractors/resiliencia.py` para os extratores de site).

Este módulo é a única fronteira onde exceção de `requests` pode existir para
este provedor: HTTP >=400 (exceto 404, tratado como "não encontrado") vira
`requests.HTTPError` via `raise_for_status()` — `integrations/servico.py`
decide o que fazer com isso (cai para o próximo provedor).
"""

import dataclasses
import html
import logging
import re
import time
from datetime import UTC, date, datetime

import requests

from core.enums import StatusLancamento
from integrations.base import (
    AnimeEmAlta,
    FileiraTematica,
    LancamentoDeAnime,
    MetadadosDeAnime,
    NoDeSerie,
    ProvedorComFileirasTematicas,
    ProvedorComLancamento,
    ProvedorComRecomendacoes,
    ProvedorComRelacoes,
    ProvedorDeMetadados,
    RelacoesDeAnime,
    TitulosDeAnime,
)
from integrations.classificacao import FORMATOS_DE_TEMPORADA, eh_serie

logger = logging.getLogger(__name__)

# Cache curto da resposta de `_QUERY_RELACOES` por `anilist_id`. Uma criação/reparo
# lê as relações do MESMO anime 2-3 vezes em segundos (classificação série×extra,
# 1º passo do walk, `buscar_serie_pai`) e a AniList limita em ~30 chamadas/min
# (medido em 2026-10-04). TTL curto: relação nova (sequência anunciada) não deve
# ficar escondida. Estado de módulo acessado de `to_thread`: `get`/`set` de dict
# são atômicos no CPython e o pior caso de corrida é uma chamada repetida.
_TTL_RELACOES_S = 120
_LIMITE_CACHE_RELACOES = 256
_cache_de_relacoes: dict[int, tuple[float, dict]] = {}

_URL = "https://graphql.anilist.co"
# Estritamente menor que o `wait_for` externo de
# `integrations/servico.py::_TIMEOUT_POR_PROVEDOR_S` (8s) — se um provedor
# está só lento (não erra), o próprio `requests` precisa estourar primeiro
# para a thread do `to_thread` terminar normalmente dentro da janela do
# `wait_for` em vez de ficar rodando órfã no thread pool até seu próprio teto.
_TIMEOUT_S = 6
# O WAF do Cloudflare da AniList passou a responder 403 a requests sem
# `Referer` (confirmado em 2026-09-06). Só esse header basta para liberar.
_HEADERS = {"Referer": "https://anilist.co/"}

_QUERY_BUSCA = """
query ($busca: String) {
  Media(search: $busca, type: ANIME) {
    id
    title { romaji english }
    coverImage { extraLarge color }
    bannerImage
    genres
    description(asHtml: false)
    status
    episodes
    seasonYear
    startDate { year month day }
    nextAiringEpisode { episode airingAt }
  }
}
"""

_QUERY_TITULOS = """
query ($busca: String) {
  Media(search: $busca, type: ANIME) {
    title { romaji english native }
    synonyms
  }
}
"""

# Busca livre do usuário na Home — lista de candidatos, não o top-1 de
# `_QUERY_BUSCA`. Mesmo bloco de campos de `_QUERY_EM_ALTA` (parser
# compartilhado `_pagina_para_animes_em_alta`); `sort: SEARCH_MATCH` devolve na
# ordem de relevância da própria AniList.
_QUERY_BUSCA_LISTA = """
query ($busca: String) {
  Page(page: 1, perPage: 24) {
    media(search: $busca, type: ANIME, sort: SEARCH_MATCH, isAdult: false) {
      id
      title { romaji english }
      coverImage { extraLarge color }
      bannerImage
      genres
      seasonYear
      startDate { year }
      status
      episodes
      duration
      format
      nextAiringEpisode { episode airingAt }
    }
  }
}
"""

_QUERY_EM_ALTA = """
query {
  Page(page: 1, perPage: 50) {
    media(status: RELEASING, type: ANIME, sort: TRENDING_DESC, isAdult: false) {
      id
      title { romaji english }
      coverImage { extraLarge color }
      bannerImage
      genres
      description(asHtml: false)
      seasonYear
      startDate { year }
      status
      episodes
      nextAiringEpisode { episode airingAt }
    }
  }
}
"""

# Feed "Novos lançamentos" da Home — agenda de exibição da AniList
# (`Page.airingSchedules`), não `Page.media`: cada nó é um EPISÓDIO que já foi
# ao ar (`airingAt_lesser: $agora`), não um anime. `sort: TIME_DESC` traz o
# mais recente primeiro; o dedup por anime (mantendo só a 1ª ocorrência = a
# mais recente) é feito em `_agenda_para_animes_em_alta`, não aqui. Mesmo bloco
# de campos de `media` que `_item_para_anime_em_alta` já sabe converter.
_QUERY_NOVOS_LANCAMENTOS = """
query ($agora: Int) {
  Page(page: 1, perPage: 50) {
    airingSchedules(airingAt_lesser: $agora, sort: TIME_DESC) {
      episode
      media {
        id
        title { romaji english }
        coverImage { extraLarge color }
        bannerImage
        genres
        seasonYear
        startDate { year }
        status
        episodes
        format
        nextAiringEpisode { episode airingAt }
      }
    }
  }
}
"""

_QUERY_POR_TAG = """
query ($tag: String) {
  Page(page: 1, perPage: 50) {
    media(
      tag: $tag
      minimumTagRank: 60
      isAdult: false
      type: ANIME
      sort: POPULARITY_DESC
    ) {
      id
      title { romaji english }
      coverImage { extraLarge color }
      bannerImage
      genres
      seasonYear
      startDate { year }
      status
      episodes
      nextAiringEpisode { episode airingAt }
    }
  }
}
"""

# Variante de `_QUERY_POR_TAG` para fileiras de GÊNERO amplo (ex. "Action") —
# gênero não tem `minimumTagRank` (esse filtro é só de tag).
_QUERY_POR_GENERO = """
query ($genero: String) {
  Page(page: 1, perPage: 50) {
    media(
      genre: $genero
      isAdult: false
      type: ANIME
      sort: POPULARITY_DESC
    ) {
      id
      title { romaji english }
      coverImage { extraLarge color }
      bannerImage
      genres
      seasonYear
      startDate { year }
      status
      episodes
      nextAiringEpisode { episode airingAt }
    }
  }
}
"""

_QUERY_PROXIMA_TEMPORADA = """
query ($estacao: MediaSeason, $ano: Int, $status: MediaStatus) {
  Page(page: 1, perPage: 50) {
    media(
      season: $estacao, seasonYear: $ano, status: $status, type: ANIME,
      sort: POPULARITY_DESC, isAdult: false
    ) {
      id
      title { romaji english }
      coverImage { extraLarge color }
      bannerImage
      genres
      seasonYear
      startDate { year }
      status
      episodes
      nextAiringEpisode { episode airingAt }
    }
  }
}
"""

_QUERY_LANCAMENTO = """
query ($id: Int) {
  Media(id: $id, type: ANIME) {
    status
    episodes
    seasonYear
    startDate { year month day }
    nextAiringEpisode { episode airingAt }
  }
}
"""

_QUERY_RELACOES = """
query ($id: Int) {
  Media(id: $id, type: ANIME) {
    id
    title { romaji }
    startDate { year month }
    format
    episodes
    duration
    relations {
      edges {
        relationType(version: 2)
        node {
          id
          type
          format
          title { romaji }
          startDate { year month }
        }
      }
    }
  }
}
"""

# Query única da seção "Relacionados" da página do anime (`integrations/base.py::
# ProvedorComRecomendacoes`): `relations` (mesmo shape de nó de `_QUERY_RELACOES`,
# sem `startDate.day`/`relationType` extra — não precisa desempatar data aqui,
# só filtrar sequência de TV já coberta pelo seletor de temporada) + `recommendations`
# (sugestão da comunidade, ordenada por `rating`). Os dois blocos de `Media` usam
# o MESMO formato de campo de `_item_para_anime_em_alta` (coverImage/bannerImage/
# genres/seasonYear/startDate/status/episodes/nextAiringEpisode/format) — parser
# reaproveitado sem adaptação.
_QUERY_RELACIONADOS = """
query ($id: Int) {
  Media(id: $id, type: ANIME) {
    relations {
      edges {
        relationType(version: 2)
        node {
          id
          type
          format
          title { romaji english }
          coverImage { extraLarge color }
          bannerImage
          genres
          seasonYear
          startDate { year }
          status
          episodes
          duration
          nextAiringEpisode { episode airingAt }
        }
      }
    }
    recommendations(sort: RATING_DESC, perPage: 25) {
      nodes {
        mediaRecommendation {
          id
          format
          title { romaji english }
          coverImage { extraLarge color }
          bannerImage
          genres
          seasonYear
          startDate { year }
          status
          episodes
          duration
          nextAiringEpisode { episode airingAt }
        }
      }
    }
  }
}
"""

_QUERY_METADADOS_POR_ID = """
query ($id: Int) {
  Media(id: $id, type: ANIME) {
    id
    title { romaji english }
    description(asHtml: false)
    coverImage { extraLarge color }
    bannerImage
    genres
    seasonYear
    startDate { year month day }
    status
    episodes
    nextAiringEpisode { episode airingAt }
  }
}
"""

_STATUS_ANILIST: dict[str, StatusLancamento] = {
    "RELEASING": StatusLancamento.EM_LANCAMENTO,
    "FINISHED": StatusLancamento.FINALIZADO,
    "NOT_YET_RELEASED": StatusLancamento.NAO_LANCADO,
    "CANCELLED": StatusLancamento.CANCELADO,
    "HIATUS": StatusLancamento.HIATO,
}

_REGEX_TAG_BR = re.compile(r"<br\s*/?>", re.IGNORECASE)
_REGEX_TAG_HTML = re.compile(r"<[^>]+>")


# `relationType`s de sequência de TV — já cobertos pelo seletor de temporada
# (`api/rotas/animes.py::_temporadas_e_proxima`, via o walk de `PREQUEL` de
# `buscar_relacoes`), então `buscar_relacionados` os descarta pra não duplicar
# a mesma temporada nas duas UIs. Só quando `node.format` também é de série —
# um `SEQUEL` fora de `FORMATOS_DE_TEMPORADA` (ex. um filme recap) não é temporada
# numerada e fica.
_RELACOES_DE_SEQUENCIA_TV = frozenset({"PREQUEL", "SEQUEL"})

# Teto de itens de `buscar_relacionados` — soma de `relations` (tipicamente
# poucos) + `recommendations` (até 25 pedidos à AniList); corta ali pra não
# estourar a fileira da página do anime com dezenas de cards.
_LIMITE_RELACIONADOS = 24

# Teto da fileira "Novos lançamentos" (Home) — pedido explícito do usuário
# (2026-09-20). Corta DEPOIS do dedup em `_agenda_para_animes_em_alta`: os 50
# episódios crus da query viram no máximo este tanto de animes únicos.
_LIMITE_NOVOS_LANCAMENTOS = 20


class AniListProvider(
    ProvedorDeMetadados,
    ProvedorComLancamento,
    ProvedorComFileirasTematicas,
    ProvedorComRelacoes,
    ProvedorComRecomendacoes,
):
    @property
    def nome(self) -> str:
        return "anilist"

    def buscar_por_titulo(self, titulo: str) -> MetadadosDeAnime | None:
        dados = self._executar(_QUERY_BUSCA, {"busca": titulo})
        media = dados.get("Media") if isinstance(dados, dict) else None
        if not isinstance(media, dict):
            return None

        titulo_bruto = media.get("title") or {}
        cover = media.get("coverImage") or {}
        return MetadadosDeAnime(
            capa_url=cover.get("extraLarge"),
            sinopse=_sanitizar_sinopse(media.get("description")),
            anilist_id=media.get("id"),
            kitsu_id=None,
            banner_url=media.get("bannerImage"),
            capa_cor=cover.get("color"),
            generos=media.get("genres") or None,
            ano=_extrair_ano(media),
            lancamento=_extrair_lancamento(media),
            titulo_romaji=_texto_ou_none(titulo_bruto.get("romaji")),
            titulo_ingles=_texto_ou_none(titulo_bruto.get("english")),
        )

    def buscar_lancamento_por_anilist_id(self, anilist_id: int) -> LancamentoDeAnime | None:
        dados = self._executar(_QUERY_LANCAMENTO, {"id": anilist_id})
        media = dados.get("Media") if isinstance(dados, dict) else None
        if not isinstance(media, dict):
            return None
        return _extrair_lancamento(media)

    def buscar_metadados_por_anilist_id(self, anilist_id: int) -> MetadadosDeAnime | None:
        dados = self._executar(_QUERY_METADADOS_POR_ID, {"id": anilist_id})
        media = dados.get("Media") if isinstance(dados, dict) else None
        if not isinstance(media, dict):
            return None

        titulo_bruto = media.get("title") or {}
        cover = media.get("coverImage") or {}
        return MetadadosDeAnime(
            capa_url=cover.get("extraLarge"),
            sinopse=_sanitizar_sinopse(media.get("description")),
            anilist_id=anilist_id,
            kitsu_id=None,
            banner_url=media.get("bannerImage"),
            capa_cor=cover.get("color"),
            generos=media.get("genres") or None,
            ano=_extrair_ano(media),
            lancamento=_extrair_lancamento(media),
            titulo_romaji=_texto_ou_none(titulo_bruto.get("romaji")),
            titulo_ingles=_texto_ou_none(titulo_bruto.get("english")),
        )

    def buscar_titulos(self, titulo: str) -> TitulosDeAnime | None:
        dados = self._executar(_QUERY_TITULOS, {"busca": titulo})
        media = dados.get("Media") if isinstance(dados, dict) else None
        if not isinstance(media, dict):
            return None

        titulo_bruto = media.get("title") or {}
        titulo_romaji = _texto_ou_none(titulo_bruto.get("romaji"))
        titulo_ingles = _texto_ou_none(titulo_bruto.get("english"))
        if titulo_romaji is None and titulo_ingles is None:
            return None
        return TitulosDeAnime(
            titulo_romaji=titulo_romaji,
            titulo_ingles=titulo_ingles,
            titulo_nativo=_texto_ou_none(titulo_bruto.get("native")),
            sinonimos=_sinonimos(media.get("synonyms")),
        )

    def listar_por_busca(self, titulo: str) -> list[AnimeEmAlta]:
        dados = self._executar(_QUERY_BUSCA_LISTA, {"busca": titulo})
        return _pagina_para_animes_em_alta(dados, "busca por título")

    def listar_em_alta(self) -> list[AnimeEmAlta]:
        return _pagina_para_animes_em_alta(self._executar(_QUERY_EM_ALTA, {}), "em alta")

    def listar_proxima_temporada(self) -> list[AnimeEmAlta]:
        agora = datetime.now(UTC)
        estacao_atual, ano_atual = _temporada_atual(agora)
        estacao, ano = _proxima_temporada(agora)
        # A temporada em curso também tem estreias futuras (o cour começa
        # escalonado ao longo do 1º mês+); sem elas a fileira pularia direto
        # pra próxima estação.
        ainda_nao_lancados = self._executar(
            _QUERY_PROXIMA_TEMPORADA,
            {"estacao": estacao_atual, "ano": ano_atual, "status": "NOT_YET_RELEASED"},
        )
        proxima = self._executar(_QUERY_PROXIMA_TEMPORADA, {"estacao": estacao, "ano": ano})
        itens = [
            *_pagina_para_animes_em_alta(ainda_nao_lancados, "estreias da temporada atual"),
            *_pagina_para_animes_em_alta(proxima, "próxima temporada"),
        ]
        return list({item.anilist_id: item for item in itens}.values())

    def listar_novos_lancamentos(self) -> list[AnimeEmAlta]:
        agora = int(datetime.now(UTC).timestamp())
        dados = self._executar(_QUERY_NOVOS_LANCAMENTOS, {"agora": agora})
        return _agenda_para_animes_em_alta(dados)

    def listar_fileira_tematica(self, fileira: FileiraTematica) -> list[AnimeEmAlta]:
        if fileira.tipo == "genero":
            dados = self._executar(_QUERY_POR_GENERO, {"genero": fileira.valor})
        else:
            dados = self._executar(_QUERY_POR_TAG, {"tag": fileira.valor})
        return _pagina_para_animes_em_alta(dados, f"fileira temática {fileira.chave!r}")

    def _media_de_relacoes(self, anilist_id: int) -> dict | None:
        """`Media` de `_QUERY_RELACOES` (cache por `_TTL_RELACOES_S`); `None` quando
        a AniList não conhece o id. Só resposta válida é cacheada."""
        agora = time.monotonic()
        memo = _cache_de_relacoes.get(anilist_id)
        if memo is not None and agora < memo[0]:
            return memo[1]
        dados = self._executar(_QUERY_RELACOES, {"id": anilist_id})
        media = dados.get("Media") if isinstance(dados, dict) else None
        if not isinstance(media, dict):
            return None
        if len(_cache_de_relacoes) >= _LIMITE_CACHE_RELACOES:
            _cache_de_relacoes.clear()
        _cache_de_relacoes[anilist_id] = (agora + _TTL_RELACOES_S, media)
        return media

    def buscar_relacoes(self, anilist_id: int) -> RelacoesDeAnime | None:
        media = self._media_de_relacoes(anilist_id)
        if media is None:
            return None

        no = _no_de_serie(media)
        if no is None:
            return None

        relacoes = media.get("relations") or {}
        arestas = relacoes.get("edges") if isinstance(relacoes, dict) else None
        prequels = _relacoes_de_serie_por_tipo(arestas or [], "PREQUEL", anilist_id)
        sequels = _relacoes_de_serie_por_tipo(arestas or [], "SEQUEL", anilist_id)

        return RelacoesDeAnime(
            no=no,
            prequels=tuple(prequels),
            sequels=tuple(sequels),
            formato=_texto_ou_none(media.get("format")),
            episodios=_inteiro_ou_none(media.get("episodes")),
            duracao_min=_inteiro_ou_none(media.get("duration")),
            tem_pai=_tem_aresta_de_pai(arestas or []),
        )

    def buscar_serie_pai(self, anilist_id: int) -> NoDeSerie | None:
        media = self._media_de_relacoes(anilist_id)
        if media is None:
            return None

        relacoes = media.get("relations") or {}
        arestas = relacoes.get("edges") if isinstance(relacoes, dict) else None
        candidatos = [
            (aresta.get("relationType"), aresta["node"])
            for aresta in arestas or []
            if isinstance(aresta, dict)
            and isinstance(aresta.get("node"), dict)
            and aresta["node"].get("type") == "ANIME"
            and aresta["node"].get("format") in FORMATOS_DE_TEMPORADA
        ]
        # `PARENT` primeiro: é a única aresta que a amostra de 400 itens mostrou
        # confiável como "extra de"; as demais só servem de fallback.
        candidatos.sort(key=lambda candidato: candidato[0] != "PARENT")
        for _tipo, node in candidatos:
            no_candidato = _no_de_serie(node)
            if no_candidato is not None:
                return no_candidato
        return None

    def buscar_relacionados(self, anilist_id: int) -> list[AnimeEmAlta]:
        dados = self._executar(_QUERY_RELACIONADOS, {"id": anilist_id})
        media = dados.get("Media") if isinstance(dados, dict) else None
        if not isinstance(media, dict):
            return []

        vistos: set[int] = {anilist_id}
        resultado: list[AnimeEmAlta] = []

        relacoes = media.get("relations") or {}
        arestas = relacoes.get("edges") if isinstance(relacoes, dict) else None
        for aresta in arestas or []:
            if not isinstance(aresta, dict):
                continue
            node = aresta.get("node")
            if not isinstance(node, dict) or node.get("type") != "ANIME":
                continue
            ident = node.get("id")
            if not isinstance(ident, int) or ident in vistos:
                continue
            # Marca como visto ANTES do filtro de sequência de TV abaixo —
            # mesmo excluída daqui, a temporada irmã não pode reentrar pela
            # passada de `recommendations` logo adiante (a AniList também
            # costuma "recomendar" a temporada anterior/seguinte como
            # parecida). Sem isto, o `continue` do filtro pulava o `node`
            # sem nunca registrar o id, e a mesma temporada que o seletor da
            # página já lista voltava a aparecer em "Relacionados" via
            # recomendação.
            vistos.add(ident)
            if (
                aresta.get("relationType") in _RELACOES_DE_SEQUENCIA_TV
                and node.get("format") in FORMATOS_DE_TEMPORADA
            ):
                continue
            resultado.append(_item_para_anime_em_alta(node))

        recomendacoes = media.get("recommendations") or {}
        nos = recomendacoes.get("nodes") if isinstance(recomendacoes, dict) else None
        for item in nos or []:
            if not isinstance(item, dict):
                continue
            recomendado = item.get("mediaRecommendation")
            if not isinstance(recomendado, dict):
                continue
            ident = recomendado.get("id")
            if not isinstance(ident, int) or ident in vistos:
                continue
            vistos.add(ident)
            resultado.append(_item_para_anime_em_alta(recomendado))

        return resultado[:_LIMITE_RELACIONADOS]

    def _executar(self, query: str, variaveis: dict) -> dict:
        resposta = requests.post(
            _URL,
            json={"query": query, "variables": variaveis},
            headers=_HEADERS,
            timeout=_TIMEOUT_S,
        )
        if resposta.status_code == 404:
            return {}
        resposta.raise_for_status()

        corpo = resposta.json()
        if not isinstance(corpo, dict) or "data" not in corpo:
            raise RuntimeError("AniList: resposta sem campo 'data'")
        return corpo.get("data") or {}


_ESTACOES_ANILIST = ("WINTER", "SPRING", "SUMMER", "FALL")


def _temporada_atual(agora: datetime) -> tuple[str, int]:
    return _ESTACOES_ANILIST[(agora.month - 1) // 3], agora.year


def _proxima_temporada(agora: datetime) -> tuple[str, int]:
    """`(estação, ano)` da temporada seguinte à de `agora` — `WINTER` (meses
    1-3), `SPRING` (4-6), `SUMMER` (7-9), `FALL` (10-12). A AniList não tem um
    enum `NEXT_SEASON`, então o cálculo é aqui. Na virada `FALL -> WINTER` o ano
    também avança."""
    indice_prox = ((agora.month - 1) // 3 + 1) % 4
    ano = agora.year + (1 if indice_prox == 0 else 0)
    return _ESTACOES_ANILIST[indice_prox], ano


def _pagina_para_animes_em_alta(dados: dict, contexto: str) -> list[AnimeEmAlta]:
    """Parser único de `Page.media` reusado por `listar_em_alta`,
    `listar_proxima_temporada` e `listar_fileira_tematica`. Os campos são quase
    idênticos nas queries; `description` (sinopse) só vem em `_QUERY_EM_ALTA` —
    nas demais `item.get("description")` é `None` e o parser deixa
    `AnimeEmAlta.sinopse` no default. `contexto` só entra na mensagem de erro
    para diferenciar qual feed veio malformado."""
    pagina = dados.get("Page") if isinstance(dados, dict) else None
    itens = pagina.get("media") if isinstance(pagina, dict) else None
    if not isinstance(itens, list):
        raise RuntimeError(f"AniList: resposta de {contexto!r} com formato inesperado")

    return [
        _item_para_anime_em_alta(item)
        for item in itens
        if isinstance(item, dict) and item.get("id") is not None
    ]


def _agenda_para_animes_em_alta(dados: dict) -> list[AnimeEmAlta]:
    """Parser de `Page.airingSchedules` para `listar_novos_lancamentos` — cada
    nó é um episódio (`{media: {...}}`), não um anime direto como em
    `_pagina_para_animes_em_alta`. Dedup por `media.id`: a query já vem
    ordenada `TIME_DESC` (mais recente primeiro), então a 1ª ocorrência de cada
    anime é sempre a do episódio mais novo — as seguintes (episódios mais
    antigos do mesmo anime) são descartadas. Corta em `_LIMITE_NOVOS_
    LANCAMENTOS` assim que atinge o teto (`break`, não `resultado[:limite]`
    no final) — sem sentido continuar deduplicando episódios mais antigos que
    nunca vão entrar no resultado."""
    pagina = dados.get("Page") if isinstance(dados, dict) else None
    agendas = pagina.get("airingSchedules") if isinstance(pagina, dict) else None
    if not isinstance(agendas, list):
        raise RuntimeError("AniList: resposta de 'novos lançamentos' com formato inesperado")

    vistos: set[int] = set()
    resultado: list[AnimeEmAlta] = []
    for agenda in agendas:
        if len(resultado) >= _LIMITE_NOVOS_LANCAMENTOS:
            break
        media = agenda.get("media") if isinstance(agenda, dict) else None
        if not isinstance(media, dict) or media.get("id") is None:
            continue
        ident = media["id"]
        if ident in vistos:
            continue
        vistos.add(ident)
        episodio = agenda.get("episode")
        item = _item_para_anime_em_alta(media)
        if isinstance(episodio, int):
            item = dataclasses.replace(item, episodio_lancado=episodio)
        resultado.append(item)
    return resultado


def _item_para_anime_em_alta(item: dict) -> AnimeEmAlta:
    """Converte um item de `Page.media` num `AnimeEmAlta` — lógica por-item
    extraída de `_pagina_para_animes_em_alta` para reuso isolado (mesmo
    formato de resposta em `listar_em_alta`, `listar_proxima_temporada`,
    `listar_fileira_tematica` e `buscar_relacionados`).

    `formato`: `None` para qualquer `Media` que `classificacao.eh_serie` trata
    como série — o contrato de `AnimeEmAltaSaida.formato`/
    `CriarAnimeRequest.formato` é "`None` = temporada normal, "MOVIE"/"OVA"/
    "ONA"/"SPECIAL" = agrupa sob a série-mãe" (`Anime.formato_midia`,
    `db.catalogo.obter_ou_criar_anime_id`). Repassar o "TV" cru da AniList
    aqui gravava `formato_midia="TV"` num anime que é uma temporada de
    verdade — some do catálogo (`listar_animes` filtra `formato_midia IS
    NULL`) sem se agrupar em nenhuma franquia (bug real, anime id=82 no
    catálogo local: "Ladies versus Butlers!" virou órfão assim ao ser
    materializado por "Relacionados"). O item do feed não traz relações, então
    `tem_pai` é sempre `False` aqui: ONA com `PARENT` nasce série e é rebaixado
    a extra no enriquecimento (`api/servicos/descoberta.py`)."""
    formato_bruto = item.get("format")
    serie = eh_serie(
        _texto_ou_none(formato_bruto),
        _inteiro_ou_none(item.get("episodes")),
        _inteiro_ou_none(item.get("duration")),
        tem_pai=False,
    )
    return AnimeEmAlta(
        titulo_romaji=(item.get("title") or {}).get("romaji") or "",
        titulo_ingles=(item.get("title") or {}).get("english"),
        capa_url=(item.get("coverImage") or {}).get("extraLarge"),
        capa_cor=(item.get("coverImage") or {}).get("color"),
        banner_url=item.get("bannerImage"),
        anilist_id=item.get("id"),
        ano_estreia=_extrair_ano(item),
        generos=tuple(
            g for g in (item.get("genres") or []) if isinstance(g, str) and g.strip()
        ),
        lancamento=_extrair_lancamento(item),
        sinopse=_sanitizar_sinopse(item.get("description")),
        formato=None if serie else _texto_ou_none(formato_bruto),
    )


def _relacoes_de_serie_por_tipo(
    arestas: list[dict], relation_type: str, anilist_id: int
) -> list[NoDeSerie]:
    """Nós de `arestas` (`relations.edges` cru da AniList) com `relationType`
    igual a `relation_type` ("PREQUEL" ou "SEQUEL") e `Media` ANIME em formato
    de temporada (`FORMATOS_DE_TEMPORADA`) — mesmo filtro para os dois sentidos do
    walk de série (`buscar_relacoes`, usado tanto por `resolver_serie` quanto
    por `resolver_franquia`)."""
    resultado: list[NoDeSerie] = []
    for aresta in arestas:
        if not isinstance(aresta, dict) or aresta.get("relationType") != relation_type:
            continue
        node = aresta.get("node")
        if not isinstance(node, dict) or node.get("type") != "ANIME":
            continue
        candidato = _no_de_serie(node)
        if candidato is None:
            continue
        if node.get("format") not in FORMATOS_DE_TEMPORADA:
            logger.info(
                "walk de série: %s %r (id=%s, format=%s) de id=%s descartado "
                "— não é temporada de TV",
                relation_type.lower(),
                candidato.titulo,
                candidato.anilist_id,
                node.get("format"),
                anilist_id,
            )
            continue
        resultado.append(candidato)
    return resultado


def _no_de_serie(media: dict) -> NoDeSerie | None:
    """`NoDeSerie` de um bloco `Media`/`node` do grafo de `relations` — `None`
    quando falta o `id` (sem ele o nó não entra no walk). `startDate` pode vir
    ausente, `None` ou parcial; mesmo estilo defensivo de `_extrair_ano`."""
    ident = media.get("id")
    if not isinstance(ident, int):
        return None
    inicio = media.get("startDate")
    if not isinstance(inicio, dict):
        inicio = {}
    ano, mes = inicio.get("year"), inicio.get("month")
    return NoDeSerie(
        anilist_id=ident,
        titulo=(media.get("title") or {}).get("romaji") or "",
        ano=ano if isinstance(ano, int) else None,
        mes=mes if isinstance(mes, int) else None,
    )


def _extrair_lancamento(media: dict) -> LancamentoDeAnime | None:
    """Parser único de estado de lançamento reusado pelos três caminhos que
    trazem esses campos (`buscar_por_titulo`, `listar_em_alta`,
    `buscar_lancamento_por_anilist_id`). Devolve `None` quando nada é
    aproveitável — nunca uma dataclass toda-nula."""
    status = _STATUS_ANILIST.get(media.get("status"))

    episodes = media.get("episodes")
    total_episodios = episodes if isinstance(episodes, int) else None

    nae = media.get("nextAiringEpisode")
    if not isinstance(nae, dict):
        nae = {}
    episode = nae.get("episode")
    proximo_ep_numero = episode if isinstance(episode, int) else None
    airing_at = nae.get("airingAt")
    proximo_ep_em = (
        datetime.fromtimestamp(airing_at, tz=UTC) if isinstance(airing_at, int) else None
    )

    ano_estreia = _extrair_ano(media)
    estreia_em = _extrair_estreia(media)

    if (
        status is None
        and total_episodios is None
        and proximo_ep_numero is None
        and proximo_ep_em is None
        and estreia_em is None
        and ano_estreia is None
    ):
        return None
    return LancamentoDeAnime(
        status=status,
        total_episodios=total_episodios,
        proximo_ep_numero=proximo_ep_numero,
        proximo_ep_em=proximo_ep_em,
        estreia_em=estreia_em,
        ano_estreia=ano_estreia,
    )


def _extrair_ano(media: dict) -> int | None:
    """Ano de estreia: `seasonYear` quando o AniList o expõe, senão
    `startDate.year`. Mesmo estilo defensivo (`isinstance(..., int)`) de
    `_extrair_lancamento` — `startDate` pode vir ausente ou `None`."""
    ano = media.get("seasonYear")
    if isinstance(ano, int):
        return ano
    inicio = media.get("startDate")
    if isinstance(inicio, dict) and isinstance(inicio.get("year"), int):
        return inicio["year"]
    return None


def _extrair_estreia(media: dict) -> date | None:
    """Data de estreia COMPLETA de `startDate` — só quando `year`, `month` e
    `day` vieram os três como int (a AniList devolve `startDate` parcial para
    títulos ainda sem grade fechada). Mesmo estilo defensivo de `_extrair_ano`;
    `date(...)` inválida (mês/dia impossível) também vira `None`."""
    inicio = media.get("startDate")
    if not isinstance(inicio, dict):
        return None
    ano, mes, dia = inicio.get("year"), inicio.get("month"), inicio.get("day")
    if not (isinstance(ano, int) and isinstance(mes, int) and isinstance(dia, int)):
        return None
    try:
        return date(ano, mes, dia)
    except ValueError:
        return None


def _texto_ou_none(texto: str | None) -> str | None:
    """Duplicado de propósito de `kitsu.py::_texto_ou_none` — helper trivial,
    não vale acoplar os dois módulos por ele (CLAUDE.md §2)."""
    if not texto:
        return None
    limpo = texto.strip()
    return limpo or None


def _inteiro_ou_none(valor: object) -> int | None:
    """`episodes`/`duration` da AniList vêm `null` em anime recém-anunciado."""
    return valor if isinstance(valor, int) and not isinstance(valor, bool) else None


def _tem_aresta_de_pai(arestas: list[dict]) -> bool:
    """Aresta `PARENT` para um `Media` ANIME — a AniList marca assim o extra
    (OVA/especial/ONA-extra) ligado à série de que ele deriva."""
    return any(
        isinstance(aresta, dict)
        and aresta.get("relationType") == "PARENT"
        and isinstance(aresta.get("node"), dict)
        and aresta["node"].get("type") == "ANIME"
        for aresta in arestas
    )


def _sinonimos(brutos: object) -> tuple[str, ...]:
    """`synonyms` da AniList pode vir `null` (não lista) ou com entradas
    vazias/só espaço — mesma filtragem defensiva de `genres` em
    `_item_para_anime_em_alta`, preservando a ordem que a AniList devolve."""
    if not isinstance(brutos, list):
        return ()
    return tuple(s for s in brutos if isinstance(s, str) and s.strip())


def _sanitizar_sinopse(bruta: str | None) -> str | None:
    """`description(asHtml: false)` do AniList ainda vem com `<br>` literal e
    entidades HTML (`&amp;`, `&quot;`, ...) — nunca deixar isso subir cru pro
    banco/frontend."""
    if not bruta:
        return None
    sem_br = _REGEX_TAG_BR.sub("\n", bruta)
    sem_tags = _REGEX_TAG_HTML.sub("", sem_br)
    limpa = html.unescape(sem_tags).strip()
    return limpa or None

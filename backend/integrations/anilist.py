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

import html
import re
from datetime import UTC, datetime

import requests

from core.enums import StatusLancamento
from integrations.base import (
    AnimeEmAlta,
    LancamentoDeAnime,
    MetadadosDeAnime,
    ProvedorComLancamento,
    ProvedorDeMetadados,
    TitulosDeAnime,
)

_URL = "https://graphql.anilist.co"
# Estritamente menor que o `wait_for` externo de
# `integrations/servico.py::_TIMEOUT_POR_PROVEDOR_S` (8s) — se um provedor
# está só lento (não erra), o próprio `requests` precisa estourar primeiro
# para a thread do `to_thread` terminar normalmente dentro da janela do
# `wait_for` em vez de ficar rodando órfã no thread pool até seu próprio teto.
_TIMEOUT_S = 6

_QUERY_BUSCA = """
query ($busca: String) {
  Media(search: $busca, type: ANIME) {
    id
    title { romaji english }
    coverImage { extraLarge }
    bannerImage
    description(asHtml: false)
    status
    episodes
    nextAiringEpisode { episode airingAt }
  }
}
"""

_QUERY_TITULOS = """
query ($busca: String) {
  Media(search: $busca, type: ANIME) {
    title { romaji english }
  }
}
"""

_QUERY_EM_ALTA = """
query {
  Page(page: 1, perPage: 50) {
    media(status: RELEASING, type: ANIME, sort: TRENDING_DESC) {
      id
      title { romaji english }
      coverImage { extraLarge }
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
query ($estacao: MediaSeason, $ano: Int) {
  Page(page: 1, perPage: 50) {
    media(season: $estacao, seasonYear: $ano, type: ANIME, sort: POPULARITY_DESC) {
      id
      title { romaji english }
      coverImage { extraLarge }
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


class AniListProvider(ProvedorDeMetadados, ProvedorComLancamento):
    @property
    def nome(self) -> str:
        return "anilist"

    def buscar_por_titulo(self, titulo: str) -> MetadadosDeAnime | None:
        dados = self._executar(_QUERY_BUSCA, {"busca": titulo})
        media = dados.get("Media") if isinstance(dados, dict) else None
        if not isinstance(media, dict):
            return None

        titulo_bruto = media.get("title") or {}
        return MetadadosDeAnime(
            capa_url=(media.get("coverImage") or {}).get("extraLarge"),
            sinopse=_sanitizar_sinopse(media.get("description")),
            anilist_id=media.get("id"),
            kitsu_id=None,
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
        return TitulosDeAnime(titulo_romaji=titulo_romaji, titulo_ingles=titulo_ingles)

    def listar_em_alta(self) -> list[AnimeEmAlta]:
        return _pagina_para_animes_em_alta(self._executar(_QUERY_EM_ALTA, {}), "em alta")

    def listar_proxima_temporada(self) -> list[AnimeEmAlta]:
        estacao, ano = _proxima_temporada(datetime.now(UTC))
        dados = self._executar(_QUERY_PROXIMA_TEMPORADA, {"estacao": estacao, "ano": ano})
        return _pagina_para_animes_em_alta(dados, "próxima temporada")

    def _executar(self, query: str, variaveis: dict) -> dict:
        resposta = requests.post(
            _URL, json={"query": query, "variables": variaveis}, timeout=_TIMEOUT_S
        )
        if resposta.status_code == 404:
            return {}
        resposta.raise_for_status()

        corpo = resposta.json()
        if not isinstance(corpo, dict) or "data" not in corpo:
            raise RuntimeError("AniList: resposta sem campo 'data'")
        return corpo.get("data") or {}


_ESTACOES_ANILIST = ("WINTER", "SPRING", "SUMMER", "FALL")


def _proxima_temporada(agora: datetime) -> tuple[str, int]:
    """`(estação, ano)` da temporada seguinte à de `agora` — `WINTER` (meses
    1-3), `SPRING` (4-6), `SUMMER` (7-9), `FALL` (10-12). A AniList não tem um
    enum `NEXT_SEASON`, então o cálculo é aqui. Na virada `FALL -> WINTER` o ano
    também avança."""
    indice_prox = ((agora.month - 1) // 3 + 1) % 4
    ano = agora.year + (1 if indice_prox == 0 else 0)
    return _ESTACOES_ANILIST[indice_prox], ano


def _pagina_para_animes_em_alta(dados: dict, contexto: str) -> list[AnimeEmAlta]:
    """Parser único de `Page.media` reusado por `listar_em_alta` e
    `listar_proxima_temporada` (mesmos campos nas duas queries). `contexto` só
    entra na mensagem de erro para diferenciar qual feed veio malformado."""
    pagina = dados.get("Page") if isinstance(dados, dict) else None
    itens = pagina.get("media") if isinstance(pagina, dict) else None
    if not isinstance(itens, list):
        raise RuntimeError(f"AniList: resposta de {contexto!r} com formato inesperado")

    return [
        AnimeEmAlta(
            titulo_romaji=(item.get("title") or {}).get("romaji") or "",
            titulo_ingles=(item.get("title") or {}).get("english"),
            capa_url=(item.get("coverImage") or {}).get("extraLarge"),
            banner_url=item.get("bannerImage"),
            anilist_id=item.get("id"),
            ano_estreia=_extrair_ano(item),
            generos=tuple(
                g for g in (item.get("genres") or []) if isinstance(g, str) and g.strip()
            ),
            lancamento=_extrair_lancamento(item),
        )
        for item in itens
        if isinstance(item, dict) and item.get("id") is not None
    ]


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

    if (
        status is None
        and total_episodios is None
        and proximo_ep_numero is None
        and proximo_ep_em is None
    ):
        return None
    return LancamentoDeAnime(
        status=status,
        total_episodios=total_episodios,
        proximo_ep_numero=proximo_ep_numero,
        proximo_ep_em=proximo_ep_em,
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


def _texto_ou_none(texto: str | None) -> str | None:
    """Duplicado de propósito de `kitsu.py::_texto_ou_none` — helper trivial,
    não vale acoplar os dois módulos por ele (CLAUDE.md §2)."""
    if not texto:
        return None
    limpo = texto.strip()
    return limpo or None


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

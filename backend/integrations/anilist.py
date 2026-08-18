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

import requests

from integrations.base import AnimeEmAlta, MetadadosDeAnime, ProvedorDeMetadados, TitulosDeAnime

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
    coverImage { extraLarge }
    bannerImage
    description(asHtml: false)
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
    }
  }
}
"""

_REGEX_TAG_BR = re.compile(r"<br\s*/?>", re.IGNORECASE)
_REGEX_TAG_HTML = re.compile(r"<[^>]+>")


class AniListProvider(ProvedorDeMetadados):
    @property
    def nome(self) -> str:
        return "anilist"

    def buscar_por_titulo(self, titulo: str) -> MetadadosDeAnime | None:
        dados = self._executar(_QUERY_BUSCA, {"busca": titulo})
        media = dados.get("Media") if isinstance(dados, dict) else None
        if not isinstance(media, dict):
            return None

        return MetadadosDeAnime(
            capa_url=(media.get("coverImage") or {}).get("extraLarge"),
            sinopse=_sanitizar_sinopse(media.get("description")),
            anilist_id=media.get("id"),
            kitsu_id=None,
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
        return TitulosDeAnime(titulo_romaji=titulo_romaji, titulo_ingles=titulo_ingles)

    def listar_em_alta(self) -> list[AnimeEmAlta]:
        dados = self._executar(_QUERY_EM_ALTA, {})
        pagina = dados.get("Page") if isinstance(dados, dict) else None
        itens = pagina.get("media") if isinstance(pagina, dict) else None
        if not isinstance(itens, list):
            raise RuntimeError("AniList: resposta de 'em alta' com formato inesperado")

        return [
            AnimeEmAlta(
                titulo_romaji=(item.get("title") or {}).get("romaji") or "",
                titulo_ingles=(item.get("title") or {}).get("english"),
                capa_url=(item.get("coverImage") or {}).get("extraLarge"),
                banner_url=item.get("bannerImage"),
                anilist_id=item.get("id"),
            )
            for item in itens
            if isinstance(item, dict) and item.get("id") is not None
        ]

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

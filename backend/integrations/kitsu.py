"""Adapter Kitsu (REST) — provedor de fallback de metadados de anime, mesmo
contrato de `integrations/anilist.py` (`ProvedorDeMetadados`).

Síncrono via `requests`; ver `integrations/anilist.py` para a nota sobre onde
mora a fronteira de exceção HTTP.
"""

import requests

from core.enums import StatusLancamento
from integrations.base import (
    AnimeEmAlta,
    LancamentoDeAnime,
    MetadadosDeAnime,
    ProvedorDeMetadados,
    TitulosDeAnime,
)

_BASE_URL = "https://kitsu.io/api/edge"
# Ver `integrations/anilist.py::_TIMEOUT_S` — mesmo raciocínio: estritamente
# menor que o `wait_for` externo de `integrations/servico.py`.
_TIMEOUT_S = 6

_STATUS_KITSU: dict[str, StatusLancamento] = {
    "current": StatusLancamento.EM_LANCAMENTO,
    "finished": StatusLancamento.FINALIZADO,
    "tba": StatusLancamento.NAO_LANCADO,
    "unreleased": StatusLancamento.NAO_LANCADO,
    "upcoming": StatusLancamento.NAO_LANCADO,
}


class KitsuProvider(ProvedorDeMetadados):
    @property
    def nome(self) -> str:
        return "kitsu"

    def buscar_por_titulo(self, titulo: str) -> MetadadosDeAnime | None:
        item = self._primeiro_anime(titulo)
        if item is None:
            return None

        atributos = item.get("attributes") or {}
        titulo_romaji, titulo_ingles = _extrair_titulos(atributos)
        return MetadadosDeAnime(
            capa_url=_maior_imagem(atributos.get("posterImage")),
            sinopse=_texto_ou_none(atributos.get("synopsis")),
            anilist_id=None,
            kitsu_id=_id_numerico(item.get("id")),
            lancamento=_extrair_lancamento(atributos),
            titulo_romaji=titulo_romaji,
            titulo_ingles=titulo_ingles,
        )

    def buscar_titulos(self, titulo: str) -> TitulosDeAnime | None:
        item = self._primeiro_anime(titulo)
        if item is None:
            return None

        titulo_romaji, titulo_ingles = _extrair_titulos(item.get("attributes") or {})
        if titulo_romaji is None and titulo_ingles is None:
            return None
        return TitulosDeAnime(titulo_romaji=titulo_romaji, titulo_ingles=titulo_ingles)

    def _primeiro_anime(self, titulo: str) -> dict | None:
        resposta = requests.get(
            f"{_BASE_URL}/anime",
            params={"filter[text]": titulo, "page[limit]": 1},
            timeout=_TIMEOUT_S,
        )
        resposta.raise_for_status()

        itens = resposta.json().get("data")
        if not isinstance(itens, list) or not itens:
            return None
        return itens[0]

    def listar_em_alta(self) -> list[AnimeEmAlta]:
        # Sem `page[limit]`, o endpoint volta só o padrão da API (~10-12
        # itens) — 20 é o teto real de `/trending/anime` no Kitsu (ao
        # contrário de `/anime`, que aceita páginas maiores); pedir mais que
        # isso não traz mais itens.
        itens = self._buscar_lista("trending/anime", {"page[limit]": 20}, "em alta")
        return _itens_para_animes_em_alta(itens)

    def listar_proxima_temporada(self) -> list[AnimeEmAlta]:
        # Fallback degradado: o Kitsu não tem enum de "próxima temporada". Em vez
        # de recalcular estação/ano (o cálculo mora em `anilist._proxima_temporada`),
        # aproxima com `filter[status]=upcoming` ordenado por popularidade —
        # itens ainda não lançados, o suficiente para o feed quando a AniList cai.
        itens = self._buscar_lista(
            "anime",
            {"filter[status]": "upcoming", "sort": "-userCount", "page[limit]": 20},
            "próxima temporada",
        )
        return _itens_para_animes_em_alta(itens)

    def _buscar_lista(self, caminho: str, params: dict, contexto: str) -> list:
        resposta = requests.get(f"{_BASE_URL}/{caminho}", params=params, timeout=_TIMEOUT_S)
        resposta.raise_for_status()

        itens = resposta.json().get("data")
        if not isinstance(itens, list):
            raise RuntimeError(f"Kitsu: resposta de {contexto!r} com formato inesperado")
        return itens


def _itens_para_animes_em_alta(itens: list) -> list[AnimeEmAlta]:
    """Parser único de `data` reusado por `listar_em_alta` e
    `listar_proxima_temporada` — nenhum dos dois endpoints (`/trending/anime`,
    `/anime`) expõe gêneros nem ano de estreia, que ficam nos defaults do
    dataclass (caminho degradado)."""
    resultado = []
    for item in itens:
        atributos = item.get("attributes") or {}
        titulos = atributos.get("titles") or {}
        resultado.append(
            AnimeEmAlta(
                # `en_jp`, não `ja_jp`: no Kitsu `ja_jp` é o título em kanji
                # (mesmo cuidado de `buscar_titulos`).
                titulo_romaji=titulos.get("en_jp") or atributos.get("canonicalTitle") or "",
                titulo_ingles=titulos.get("en"),
                capa_url=_maior_imagem(atributos.get("posterImage")),
                banner_url=_maior_imagem(atributos.get("coverImage")),
                anilist_id=None,
                ano_estreia=None,
                generos=(),
                lancamento=_extrair_lancamento(atributos),
            )
        )
    return resultado


def _extrair_lancamento(atributos: dict) -> LancamentoDeAnime | None:
    """Estado de lançamento no Kitsu: só `status` e `episodeCount` são
    aproveitáveis — a API não expõe next-airing, então `proximo_ep_*` fica
    sempre `None`. Devolve `None` quando nada é aproveitável, nunca uma
    dataclass toda-nula."""
    status = _STATUS_KITSU.get(atributos.get("status"))
    contagem = atributos.get("episodeCount")
    total_episodios = contagem if isinstance(contagem, int) else None
    if status is None and total_episodios is None:
        return None
    return LancamentoDeAnime(
        status=status,
        total_episodios=total_episodios,
        proximo_ep_numero=None,
        proximo_ep_em=None,
    )


def _extrair_titulos(atributos: dict) -> tuple[str | None, str | None]:
    """`(romaji, inglês)` a partir de `attributes` do Kitsu — extração comum a
    `buscar_por_titulo` e `buscar_titulos`.

    `en_jp`, não `ja_jp`: no Kitsu `ja_jp` é o título em kanji, inútil pros
    sites de extração brasileiros (todos indexam romaji/inglês); sem `en_jp`,
    cai pro `canonicalTitle`, nunca pro kanji.
    """
    titulos = atributos.get("titles") or {}
    romaji = _texto_ou_none(titulos.get("en_jp")) or _texto_ou_none(atributos.get("canonicalTitle"))
    ingles = _texto_ou_none(titulos.get("en"))
    return romaji, ingles


def _maior_imagem(imagem: dict | None) -> str | None:
    if not isinstance(imagem, dict):
        return None
    return imagem.get("original") or imagem.get("large") or imagem.get("small")


def _texto_ou_none(texto: str | None) -> str | None:
    if not texto:
        return None
    limpo = texto.strip()
    return limpo or None


def _id_numerico(id_bruto: str | None) -> int | None:
    if id_bruto is None:
        return None
    try:
        return int(id_bruto)
    except ValueError:
        return None

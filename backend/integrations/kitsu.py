"""Adapter Kitsu (REST) — provedor de fallback de metadados de anime, mesmo
contrato de `integrations/anilist.py` (`ProvedorDeMetadados`).

Síncrono via `requests`; ver `integrations/anilist.py` para a nota sobre onde
mora a fronteira de exceção HTTP.
"""

import requests

from integrations.base import AnimeEmAlta, MetadadosDeAnime, ProvedorDeMetadados, TitulosDeAnime

_BASE_URL = "https://kitsu.io/api/edge"
# Ver `integrations/anilist.py::_TIMEOUT_S` — mesmo raciocínio: estritamente
# menor que o `wait_for` externo de `integrations/servico.py`.
_TIMEOUT_S = 6


class KitsuProvider(ProvedorDeMetadados):
    @property
    def nome(self) -> str:
        return "kitsu"

    def buscar_por_titulo(self, titulo: str) -> MetadadosDeAnime | None:
        item = self._primeiro_anime(titulo)
        if item is None:
            return None

        atributos = item.get("attributes") or {}
        return MetadadosDeAnime(
            capa_url=_maior_imagem(atributos.get("posterImage")),
            sinopse=_texto_ou_none(atributos.get("synopsis")),
            anilist_id=None,
            kitsu_id=_id_numerico(item.get("id")),
        )

    def buscar_titulos(self, titulo: str) -> TitulosDeAnime | None:
        item = self._primeiro_anime(titulo)
        if item is None:
            return None

        atributos = item.get("attributes") or {}
        titulos = atributos.get("titles") or {}
        # `en_jp`, não `ja_jp`: no Kitsu `ja_jp` é o título em kanji, inútil
        # pros sites de extração brasileiros (todos indexam romaji/inglês).
        titulo_romaji = _texto_ou_none(titulos.get("en_jp")) or _texto_ou_none(
            atributos.get("canonicalTitle")
        )
        titulo_ingles = _texto_ou_none(titulos.get("en"))
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
        resposta = requests.get(
            f"{_BASE_URL}/trending/anime", params={"page[limit]": 20}, timeout=_TIMEOUT_S
        )
        resposta.raise_for_status()

        itens = resposta.json().get("data")
        if not isinstance(itens, list):
            raise RuntimeError("Kitsu: resposta de 'em alta' com formato inesperado")

        resultado = []
        for item in itens:
            atributos = item.get("attributes") or {}
            titulos = atributos.get("titles") or {}
            resultado.append(
                AnimeEmAlta(
                    # `en_jp`, não `ja_jp`: no Kitsu `ja_jp` é o título em
                    # kanji (mesmo cuidado de `buscar_titulos`, acima).
                    titulo_romaji=titulos.get("en_jp") or atributos.get("canonicalTitle") or "",
                    titulo_ingles=titulos.get("en"),
                    capa_url=_maior_imagem(atributos.get("posterImage")),
                    banner_url=_maior_imagem(atributos.get("coverImage")),
                    anilist_id=None,
                )
            )
        return resultado


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

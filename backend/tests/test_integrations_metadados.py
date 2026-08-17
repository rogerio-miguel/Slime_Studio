"""Testes de `integrations/`: parsing dos adapters (AniList/Kitsu) e cadeia de
fallback com timeout/cache de `integrations/servico.py`. Sem tocar rede: os
adapters são testados monkeypatchando `requests.post`/`requests.get` nos
nomes importados em cada módulo (mesmo padrão de mock usado em
`tests/test_api_animes.py` para `api.servicos.fontes`); a cadeia de fallback
é testada com provedores fake que implementam `ProvedorDeMetadados`, sem
precisar simular HTTP.
"""

import asyncio
import time

import pytest
import requests

from core.erros import FalhaDeMetadados
from integrations import servico
from integrations.anilist import AniListProvider
from integrations.base import AnimeEmAlta, MetadadosDeAnime, ProvedorDeMetadados
from integrations.kitsu import KitsuProvider


class _RespostaFalsa:
    def __init__(self, *, status_code: int = 200, corpo=None):
        self.status_code = status_code
        self._corpo = corpo if corpo is not None else {}

    def json(self):
        return self._corpo

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


# --- AniListProvider ---


def test_anilist_buscar_por_titulo_sanitiza_sinopse(monkeypatch: pytest.MonkeyPatch):
    corpo = {
        "data": {
            "Media": {
                "id": 123,
                "coverImage": {"extraLarge": "https://img/cover.jpg"},
                "bannerImage": "https://img/banner.jpg",
                "description": "Linha um<br>Linha dois &amp; mais",
            }
        }
    }
    monkeypatch.setattr(
        "integrations.anilist.requests.post", lambda *a, **k: _RespostaFalsa(corpo=corpo)
    )

    resultado = AniListProvider().buscar_por_titulo("Slime")

    assert resultado == MetadadosDeAnime(
        capa_url="https://img/cover.jpg",
        sinopse="Linha um\nLinha dois & mais",
        anilist_id=123,
        kitsu_id=None,
    )


def test_anilist_buscar_por_titulo_nao_encontrado_404(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "integrations.anilist.requests.post",
        lambda *a, **k: _RespostaFalsa(status_code=404),
    )

    assert AniListProvider().buscar_por_titulo("titulo inexistente") is None


def test_anilist_rate_limit_propaga_httperror(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "integrations.anilist.requests.post",
        lambda *a, **k: _RespostaFalsa(status_code=429),
    )

    with pytest.raises(requests.HTTPError):
        AniListProvider().buscar_por_titulo("Slime")


def test_anilist_listar_em_alta(monkeypatch: pytest.MonkeyPatch):
    corpo = {
        "data": {
            "Page": {
                "media": [
                    {
                        "id": 1,
                        "title": {"romaji": "Tensei", "english": "Reincarnated"},
                        "coverImage": {"extraLarge": "https://img/1.jpg"},
                        "bannerImage": "https://img/1-banner.jpg",
                    }
                ]
            }
        }
    }
    monkeypatch.setattr(
        "integrations.anilist.requests.post", lambda *a, **k: _RespostaFalsa(corpo=corpo)
    )

    resultado = AniListProvider().listar_em_alta()

    assert resultado == [
        AnimeEmAlta(
            titulo_romaji="Tensei",
            titulo_ingles="Reincarnated",
            capa_url="https://img/1.jpg",
            banner_url="https://img/1-banner.jpg",
            anilist_id=1,
        )
    ]


# --- KitsuProvider ---


def test_kitsu_buscar_por_titulo(monkeypatch: pytest.MonkeyPatch):
    corpo = {
        "data": [
            {
                "id": "42",
                "attributes": {
                    "synopsis": "  Uma sinopse.  ",
                    "posterImage": {"original": "https://img/poster.jpg"},
                },
            }
        ]
    }
    monkeypatch.setattr(
        "integrations.kitsu.requests.get", lambda *a, **k: _RespostaFalsa(corpo=corpo)
    )

    resultado = KitsuProvider().buscar_por_titulo("Slime")

    assert resultado == MetadadosDeAnime(
        capa_url="https://img/poster.jpg",
        sinopse="Uma sinopse.",
        anilist_id=None,
        kitsu_id=42,
    )


def test_kitsu_buscar_por_titulo_nao_encontrado(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "integrations.kitsu.requests.get", lambda *a, **k: _RespostaFalsa(corpo={"data": []})
    )

    assert KitsuProvider().buscar_por_titulo("titulo inexistente") is None


def test_kitsu_listar_em_alta(monkeypatch: pytest.MonkeyPatch):
    corpo = {
        "data": [
            {
                "attributes": {
                    "canonicalTitle": "Slime",
                    "titles": {
                        "en": "That Time I Got Reincarnated as a Slime",
                        "ja_jp": "Tensei",
                    },
                    "posterImage": {"original": "https://img/poster.jpg"},
                    "coverImage": {"original": "https://img/cover.jpg"},
                }
            }
        ]
    }
    monkeypatch.setattr(
        "integrations.kitsu.requests.get", lambda *a, **k: _RespostaFalsa(corpo=corpo)
    )

    resultado = KitsuProvider().listar_em_alta()

    assert resultado == [
        AnimeEmAlta(
            titulo_romaji="Tensei",
            titulo_ingles="That Time I Got Reincarnated as a Slime",
            capa_url="https://img/poster.jpg",
            banner_url="https://img/cover.jpg",
            anilist_id=None,
        )
    ]


# --- cadeia de fallback (integrations/servico.py) ---


class _ProvedorFake(ProvedorDeMetadados):
    def __init__(self, nome: str, *, metadados=None, em_alta=None, erro: Exception | None = None):
        self._nome = nome
        self._metadados = metadados
        self._em_alta = em_alta or []
        self._erro = erro

    @property
    def nome(self) -> str:
        return self._nome

    def buscar_por_titulo(self, titulo: str):
        if self._erro is not None:
            raise self._erro
        return self._metadados

    def listar_em_alta(self):
        if self._erro is not None:
            raise self._erro
        return self._em_alta


@pytest.fixture(autouse=True)
def _limpa_cache_em_alta(monkeypatch: pytest.MonkeyPatch):
    """`integrations.servico._cache_em_alta` é estado de módulo — isola cada
    teste para não vazar cache de um teste para o outro."""
    monkeypatch.setattr(servico, "_cache_em_alta", None)


async def test_servico_cai_para_kitsu_quando_anilist_falha(monkeypatch: pytest.MonkeyPatch):
    esperado = MetadadosDeAnime(capa_url=None, sinopse=None, anilist_id=None, kitsu_id=7)
    anilist = _ProvedorFake("anilist", erro=requests.ConnectionError("falhou"))
    kitsu = _ProvedorFake("kitsu", metadados=esperado)
    monkeypatch.setattr(servico, "PROVEDORES", (anilist, kitsu))

    resultado = await servico.buscar_por_titulo("Slime")

    assert resultado is esperado


async def test_servico_rate_limit_nao_e_fatal_se_outro_provedor_responde(
    monkeypatch: pytest.MonkeyPatch,
):
    esperado = MetadadosDeAnime(capa_url=None, sinopse=None, anilist_id=1, kitsu_id=None)
    anilist = _ProvedorFake("anilist", erro=requests.HTTPError("HTTP 429"))
    kitsu = _ProvedorFake("kitsu", metadados=esperado)
    monkeypatch.setattr(servico, "PROVEDORES", (anilist, kitsu))

    resultado = await servico.buscar_por_titulo("Slime")

    assert resultado is esperado


async def test_servico_levanta_falha_de_metadados_quando_todos_falham(
    monkeypatch: pytest.MonkeyPatch,
):
    anilist = _ProvedorFake("anilist", erro=requests.ConnectionError("falhou"))
    kitsu = _ProvedorFake("kitsu", erro=requests.ConnectionError("falhou"))
    monkeypatch.setattr(servico, "PROVEDORES", (anilist, kitsu))

    with pytest.raises(FalhaDeMetadados):
        await servico.buscar_por_titulo("Slime")


async def test_servico_nao_encontrado_em_nenhum_provedor_devolve_none(
    monkeypatch: pytest.MonkeyPatch,
):
    anilist = _ProvedorFake("anilist", metadados=None)
    kitsu = _ProvedorFake("kitsu", metadados=None)
    monkeypatch.setattr(servico, "PROVEDORES", (anilist, kitsu))

    assert await servico.buscar_por_titulo("Slime") is None


async def test_servico_timeout_de_provedor_cai_para_o_proximo(monkeypatch: pytest.MonkeyPatch):
    class _ProvedorLento(ProvedorDeMetadados):
        @property
        def nome(self) -> str:
            return "lento"

        def buscar_por_titulo(self, titulo: str):
            time.sleep(0.2)
            return None

        def listar_em_alta(self):
            return []

    esperado = MetadadosDeAnime(capa_url=None, sinopse=None, anilist_id=1, kitsu_id=None)
    rapido = _ProvedorFake("rapido", metadados=esperado)
    monkeypatch.setattr(servico, "PROVEDORES", (_ProvedorLento(), rapido))
    monkeypatch.setattr(servico, "_TIMEOUT_POR_PROVEDOR_S", 0.05)

    resultado = await servico.buscar_por_titulo("Slime")

    assert resultado is esperado


async def test_servico_em_alta_propaga_falha_de_metadados_se_todos_falham(
    monkeypatch: pytest.MonkeyPatch,
):
    anilist = _ProvedorFake("anilist", erro=requests.ConnectionError("falhou"))
    kitsu = _ProvedorFake("kitsu", erro=requests.ConnectionError("falhou"))
    monkeypatch.setattr(servico, "PROVEDORES", (anilist, kitsu))

    with pytest.raises(FalhaDeMetadados):
        await servico.listar_em_alta()


async def test_servico_em_alta_usa_cache_dentro_do_ttl(monkeypatch: pytest.MonkeyPatch):
    chamadas = []
    item = AnimeEmAlta(
        titulo_romaji="X", titulo_ingles=None, capa_url=None, banner_url=None, anilist_id=1
    )

    def _listar():
        chamadas.append(1)
        return [item]

    anilist = _ProvedorFake("anilist")
    anilist.listar_em_alta = _listar
    monkeypatch.setattr(servico, "PROVEDORES", (anilist,))

    primeira = await servico.listar_em_alta()
    segunda = await servico.listar_em_alta()

    assert len(chamadas) == 1
    assert primeira == segunda == [item]


async def test_servico_em_alta_concorrencia_compartilha_uma_unica_busca(
    monkeypatch: pytest.MonkeyPatch,
):
    """Rajada concorrente durante cache-miss não deve disparar N buscas reais
    aos provedores (thundering herd) — `_lock_em_alta` faz as chamadas
    concorrentes compartilharem uma única busca em andamento."""
    chamadas = []
    item = AnimeEmAlta(
        titulo_romaji="X", titulo_ingles=None, capa_url=None, banner_url=None, anilist_id=1
    )

    class _ProvedorLento(ProvedorDeMetadados):
        @property
        def nome(self) -> str:
            return "lento"

        def buscar_por_titulo(self, titulo: str):
            return None

        def listar_em_alta(self):
            chamadas.append(1)
            time.sleep(0.05)
            return [item]

    monkeypatch.setattr(servico, "PROVEDORES", (_ProvedorLento(),))

    primeira, segunda = await asyncio.gather(servico.listar_em_alta(), servico.listar_em_alta())

    assert len(chamadas) == 1
    assert primeira == segunda == [item]

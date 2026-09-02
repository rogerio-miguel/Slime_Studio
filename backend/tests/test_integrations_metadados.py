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
from datetime import UTC, date, datetime

import pytest
import requests

from core.enums import StatusLancamento
from core.erros import FalhaDeMetadados
from integrations import servico
from integrations.anilist import AniListProvider, _proxima_temporada
from integrations.base import (
    AnimeEmAlta,
    LancamentoDeAnime,
    MetadadosDeAnime,
    ProvedorComLancamento,
    ProvedorDeMetadados,
    TitulosDeAnime,
)
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
                        "genres": ["Action", "Fantasy"],
                        "seasonYear": 2021,
                        "startDate": {"year": 2021},
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
            ano_estreia=2021,
            generos=("Action", "Fantasy"),
            # `seasonYear` presente sem status/next-airing: `_extrair_lancamento`
            # ainda devolve bloco com só o `ano_estreia` preenchido.
            lancamento=LancamentoDeAnime(
                status=None,
                total_episodios=None,
                proximo_ep_numero=None,
                proximo_ep_em=None,
                ano_estreia=2021,
            ),
        )
    ]


def test_anilist_listar_em_alta_ano_cai_para_start_date(monkeypatch: pytest.MonkeyPatch):
    """`seasonYear` nulo → usa `startDate.year`; `genres` nulo → `generos` vazio."""
    corpo = {
        "data": {
            "Page": {
                "media": [
                    {
                        "id": 1,
                        "title": {"romaji": "Tensei", "english": None},
                        "coverImage": {"extraLarge": None},
                        "bannerImage": None,
                        "genres": None,
                        "seasonYear": None,
                        "startDate": {"year": 2024},
                    }
                ]
            }
        }
    }
    monkeypatch.setattr(
        "integrations.anilist.requests.post", lambda *a, **k: _RespostaFalsa(corpo=corpo)
    )

    (item,) = AniListProvider().listar_em_alta()

    assert item.ano_estreia == 2024
    assert item.generos == ()


def test_anilist_listar_em_alta_sem_ano_nem_generos(monkeypatch: pytest.MonkeyPatch):
    """`seasonYear` e `startDate` ausentes (`startDate` pode vir `None` inteiro,
    não só `.year` nulo) → `ano_estreia` None; sem `genres` → `generos` vazio."""
    corpo = {
        "data": {
            "Page": {
                "media": [
                    {
                        "id": 1,
                        "title": {"romaji": "Tensei", "english": None},
                        "coverImage": {"extraLarge": None},
                        "bannerImage": None,
                        "startDate": None,
                    }
                ]
            }
        }
    }
    monkeypatch.setattr(
        "integrations.anilist.requests.post", lambda *a, **k: _RespostaFalsa(corpo=corpo)
    )

    (item,) = AniListProvider().listar_em_alta()

    assert item.ano_estreia is None
    assert item.generos == ()


@pytest.mark.parametrize(
    ("agora", "esperado"),
    [
        (datetime(2026, 2, 15, tzinfo=UTC), ("SPRING", 2026)),
        (datetime(2026, 5, 15, tzinfo=UTC), ("SUMMER", 2026)),
        (datetime(2026, 8, 15, tzinfo=UTC), ("FALL", 2026)),
        (datetime(2026, 11, 1, tzinfo=UTC), ("WINTER", 2027)),
        (datetime(2026, 12, 31, tzinfo=UTC), ("WINTER", 2027)),
    ],
    ids=["winter->spring", "spring->summer", "summer->fall", "fall->winter", "ano-vira"],
)
def test_anilist_proxima_temporada_estacao_e_ano(agora: datetime, esperado: tuple[str, int]):
    assert _proxima_temporada(agora) == esperado


def test_anilist_listar_proxima_temporada(monkeypatch: pytest.MonkeyPatch):
    """Parsing idêntico ao de `listar_em_alta`; as variáveis da query vêm de
    `_proxima_temporada` (aqui congelada)."""
    corpo = {
        "data": {
            "Page": {
                "media": [
                    {
                        "id": 5,
                        "title": {"romaji": "Estreia", "english": "Premiere"},
                        "coverImage": {"extraLarge": "https://img/5.jpg"},
                        "bannerImage": "https://img/5-banner.jpg",
                        "genres": ["Drama"],
                        "seasonYear": 2027,
                        "startDate": {"year": 2027},
                        "status": "NOT_YET_RELEASED",
                        "episodes": None,
                        "nextAiringEpisode": None,
                    }
                ]
            }
        }
    }
    capturado = {}

    def _post(*a, **k):
        capturado.update(k["json"])
        return _RespostaFalsa(corpo=corpo)

    monkeypatch.setattr("integrations.anilist.requests.post", _post)
    monkeypatch.setattr("integrations.anilist._proxima_temporada", lambda _agora: ("SPRING", 2099))

    resultado = AniListProvider().listar_proxima_temporada()

    assert capturado["variables"] == {"estacao": "SPRING", "ano": 2099}
    assert resultado == [
        AnimeEmAlta(
            titulo_romaji="Estreia",
            titulo_ingles="Premiere",
            capa_url="https://img/5.jpg",
            banner_url="https://img/5-banner.jpg",
            anilist_id=5,
            ano_estreia=2027,
            generos=("Drama",),
            lancamento=LancamentoDeAnime(
                status=StatusLancamento.NAO_LANCADO,
                total_episodios=None,
                proximo_ep_numero=None,
                proximo_ep_em=None,
                # `startDate` só com `year` -> `estreia_em` None; `ano_estreia`
                # cai no `seasonYear`.
                ano_estreia=2027,
            ),
        )
    ]


def test_anilist_listar_proxima_temporada_formato_inesperado(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "integrations.anilist.requests.post",
        lambda *a, **k: _RespostaFalsa(corpo={"data": {"Page": {}}}),
    )

    with pytest.raises(RuntimeError):
        AniListProvider().listar_proxima_temporada()


def test_anilist_buscar_titulos(monkeypatch: pytest.MonkeyPatch):
    corpo = {"data": {"Media": {"title": {"romaji": "Tensei", "english": "Reincarnated"}}}}
    monkeypatch.setattr(
        "integrations.anilist.requests.post", lambda *a, **k: _RespostaFalsa(corpo=corpo)
    )

    resultado = AniListProvider().buscar_titulos("Slime")

    assert resultado == TitulosDeAnime(titulo_romaji="Tensei", titulo_ingles="Reincarnated")


def test_anilist_buscar_titulos_so_romaji_presente(monkeypatch: pytest.MonkeyPatch):
    corpo = {"data": {"Media": {"title": {"romaji": "Tensei", "english": None}}}}
    monkeypatch.setattr(
        "integrations.anilist.requests.post", lambda *a, **k: _RespostaFalsa(corpo=corpo)
    )

    resultado = AniListProvider().buscar_titulos("Slime")

    assert resultado == TitulosDeAnime(titulo_romaji="Tensei", titulo_ingles=None)


def test_anilist_buscar_titulos_media_null_devolve_none(monkeypatch: pytest.MonkeyPatch):
    corpo = {"data": {"Media": None}}
    monkeypatch.setattr(
        "integrations.anilist.requests.post", lambda *a, **k: _RespostaFalsa(corpo=corpo)
    )

    assert AniListProvider().buscar_titulos("titulo inexistente") is None


def test_anilist_buscar_por_titulo_traz_titulos_do_provedor(monkeypatch: pytest.MonkeyPatch):
    """`buscar_por_titulo` também devolve `titulo_romaji`/`titulo_ingles` — material
    de corroboração de match para o aquecimento de lançamento por título (F14)."""
    corpo = {
        "data": {
            "Media": {
                "id": 456,
                "title": {
                    "romaji": "Fuufu Ijou, Koibito Miman.",
                    "english": "More than a Married Couple, but Not Lovers",
                },
                "coverImage": {"extraLarge": "https://img/c.jpg"},
                "bannerImage": None,
                "description": "sinopse",
            }
        }
    }
    monkeypatch.setattr(
        "integrations.anilist.requests.post", lambda *a, **k: _RespostaFalsa(corpo=corpo)
    )

    resultado = AniListProvider().buscar_por_titulo("Fuufu")

    assert resultado.titulo_romaji == "Fuufu Ijou, Koibito Miman."
    assert resultado.titulo_ingles == "More than a Married Couple, but Not Lovers"


def test_anilist_buscar_por_titulo_sem_bloco_title_deixa_titulos_none(
    monkeypatch: pytest.MonkeyPatch,
):
    corpo = {"data": {"Media": {"id": 1, "description": "x"}}}
    monkeypatch.setattr(
        "integrations.anilist.requests.post", lambda *a, **k: _RespostaFalsa(corpo=corpo)
    )

    resultado = AniListProvider().buscar_por_titulo("Slime")

    assert resultado.titulo_romaji is None
    assert resultado.titulo_ingles is None


# --- AniListProvider: estado de lançamento (F2 detector de eps novos) ---


def test_anilist_extrai_lancamento_completo(monkeypatch: pytest.MonkeyPatch):
    corpo = {
        "data": {
            "Media": {
                "id": 21,
                "coverImage": {"extraLarge": "https://img/c.jpg"},
                "bannerImage": None,
                "description": "sinopse",
                "status": "RELEASING",
                "episodes": 24,
                "nextAiringEpisode": {"episode": 13, "airingAt": 1_700_000_000},
            }
        }
    }
    monkeypatch.setattr(
        "integrations.anilist.requests.post", lambda *a, **k: _RespostaFalsa(corpo=corpo)
    )

    lancamento = AniListProvider().buscar_por_titulo("Slime").lancamento

    assert lancamento == LancamentoDeAnime(
        status=StatusLancamento.EM_LANCAMENTO,
        total_episodios=24,
        proximo_ep_numero=13,
        proximo_ep_em=datetime.fromtimestamp(1_700_000_000, tz=UTC),
    )
    assert lancamento.proximo_ep_em.tzinfo is UTC


def test_anilist_lancamento_sem_next_airing(monkeypatch: pytest.MonkeyPatch):
    corpo = {
        "data": {
            "Media": {
                "id": 21,
                "description": "x",
                "status": "FINISHED",
                "episodes": 12,
                "nextAiringEpisode": None,
            }
        }
    }
    monkeypatch.setattr(
        "integrations.anilist.requests.post", lambda *a, **k: _RespostaFalsa(corpo=corpo)
    )

    lancamento = AniListProvider().buscar_por_titulo("Slime").lancamento

    assert lancamento == LancamentoDeAnime(
        status=StatusLancamento.FINALIZADO,
        total_episodios=12,
        proximo_ep_numero=None,
        proximo_ep_em=None,
    )


def test_anilist_lancamento_status_fora_do_mapa(monkeypatch: pytest.MonkeyPatch):
    corpo = {
        "data": {"Media": {"id": 21, "description": "x", "status": "SOMETHING_NEW", "episodes": 5}}
    }
    monkeypatch.setattr(
        "integrations.anilist.requests.post", lambda *a, **k: _RespostaFalsa(corpo=corpo)
    )

    lancamento = AniListProvider().buscar_por_titulo("Slime").lancamento

    assert lancamento == LancamentoDeAnime(
        status=None, total_episodios=5, proximo_ep_numero=None, proximo_ep_em=None
    )


def test_anilist_sem_dados_de_lancamento_deixa_campo_none(monkeypatch: pytest.MonkeyPatch):
    corpo = {
        "data": {
            "Media": {
                "id": 21,
                "coverImage": {"extraLarge": "https://img/c.jpg"},
                "bannerImage": "https://img/b.jpg",
                "description": "sinopse",
            }
        }
    }
    monkeypatch.setattr(
        "integrations.anilist.requests.post", lambda *a, **k: _RespostaFalsa(corpo=corpo)
    )

    assert AniListProvider().buscar_por_titulo("Slime").lancamento is None


def test_anilist_lancamento_estreia_completa(monkeypatch: pytest.MonkeyPatch):
    """`startDate` com os três componentes -> `estreia_em` data completa e
    `ano_estreia` do `seasonYear`."""
    corpo = {
        "data": {
            "Media": {
                "id": 21,
                "description": "x",
                "status": "NOT_YET_RELEASED",
                "seasonYear": 2027,
                "startDate": {"year": 2027, "month": 4, "day": 9},
            }
        }
    }
    monkeypatch.setattr(
        "integrations.anilist.requests.post", lambda *a, **k: _RespostaFalsa(corpo=corpo)
    )

    lancamento = AniListProvider().buscar_por_titulo("Slime").lancamento

    assert lancamento == LancamentoDeAnime(
        status=StatusLancamento.NAO_LANCADO,
        total_episodios=None,
        proximo_ep_numero=None,
        proximo_ep_em=None,
        estreia_em=date(2027, 4, 9),
        ano_estreia=2027,
    )


def test_anilist_lancamento_estreia_parcial_so_ano(monkeypatch: pytest.MonkeyPatch):
    """`startDate` só com `year` (sem `month`/`day`) e sem `seasonYear`:
    `estreia_em` fica None, `ano_estreia` cai no `startDate.year`."""
    corpo = {
        "data": {
            "Media": {
                "id": 21,
                "description": "x",
                "status": "NOT_YET_RELEASED",
                "startDate": {"year": 2028, "month": None, "day": None},
            }
        }
    }
    monkeypatch.setattr(
        "integrations.anilist.requests.post", lambda *a, **k: _RespostaFalsa(corpo=corpo)
    )

    lancamento = AniListProvider().buscar_por_titulo("Slime").lancamento

    assert lancamento.estreia_em is None
    assert lancamento.ano_estreia == 2028


def test_anilist_lancamento_estreia_ausente(monkeypatch: pytest.MonkeyPatch):
    """Sem `startDate` nem `seasonYear`, mas com `status`: bloco existe, os dois
    campos de estreia ficam None."""
    corpo = {
        "data": {
            "Media": {"id": 21, "description": "x", "status": "RELEASING", "startDate": None}
        }
    }
    monkeypatch.setattr(
        "integrations.anilist.requests.post", lambda *a, **k: _RespostaFalsa(corpo=corpo)
    )

    lancamento = AniListProvider().buscar_por_titulo("Slime").lancamento

    assert lancamento.estreia_em is None
    assert lancamento.ano_estreia is None


def test_anilist_lancamento_estreia_data_impossivel_vira_none(monkeypatch: pytest.MonkeyPatch):
    """`startDate` com mês/dia impossíveis (30 de fevereiro): `date(...)` levanta
    `ValueError` e `estreia_em` cai para None — `ano_estreia` sobrevive."""
    corpo = {
        "data": {
            "Media": {
                "id": 21,
                "description": "x",
                "status": "NOT_YET_RELEASED",
                "startDate": {"year": 2027, "month": 2, "day": 30},
            }
        }
    }
    monkeypatch.setattr(
        "integrations.anilist.requests.post", lambda *a, **k: _RespostaFalsa(corpo=corpo)
    )

    lancamento = AniListProvider().buscar_por_titulo("Slime").lancamento

    assert lancamento.estreia_em is None
    assert lancamento.ano_estreia == 2027


def test_anilist_lancamento_so_estreia_ainda_devolve_bloco(monkeypatch: pytest.MonkeyPatch):
    """Guard: mesmo sem status/episodes/next-airing, um `startDate` completo
    basta para `_extrair_lancamento` devolver bloco em vez de None."""
    corpo = {
        "data": {
            "Media": {
                "id": 21,
                "description": "x",
                "startDate": {"year": 2027, "month": 4, "day": 9},
            }
        }
    }
    monkeypatch.setattr(
        "integrations.anilist.requests.post", lambda *a, **k: _RespostaFalsa(corpo=corpo)
    )

    lancamento = AniListProvider().buscar_por_titulo("Slime").lancamento

    assert lancamento is not None
    assert lancamento.status is None
    assert lancamento.estreia_em == date(2027, 4, 9)


def test_anilist_listar_em_alta_preenche_lancamento(monkeypatch: pytest.MonkeyPatch):
    corpo = {
        "data": {
            "Page": {
                "media": [
                    {
                        "id": 1,
                        "title": {"romaji": "Tensei", "english": None},
                        "coverImage": {"extraLarge": None},
                        "bannerImage": None,
                        "status": "RELEASING",
                        "episodes": None,
                        "nextAiringEpisode": {"episode": 7, "airingAt": 1_700_000_000},
                    }
                ]
            }
        }
    }
    monkeypatch.setattr(
        "integrations.anilist.requests.post", lambda *a, **k: _RespostaFalsa(corpo=corpo)
    )

    (item,) = AniListProvider().listar_em_alta()

    assert item.lancamento == LancamentoDeAnime(
        status=StatusLancamento.EM_LANCAMENTO,
        total_episodios=None,
        proximo_ep_numero=7,
        proximo_ep_em=datetime.fromtimestamp(1_700_000_000, tz=UTC),
    )


def test_anilist_buscar_lancamento_por_anilist_id(monkeypatch: pytest.MonkeyPatch):
    corpo = {
        "data": {
            "Media": {
                "status": "RELEASING",
                "episodes": 24,
                "nextAiringEpisode": {"episode": 13, "airingAt": 1_700_000_000},
            }
        }
    }
    monkeypatch.setattr(
        "integrations.anilist.requests.post", lambda *a, **k: _RespostaFalsa(corpo=corpo)
    )

    resultado = AniListProvider().buscar_lancamento_por_anilist_id(21)

    assert resultado == LancamentoDeAnime(
        status=StatusLancamento.EM_LANCAMENTO,
        total_episodios=24,
        proximo_ep_numero=13,
        proximo_ep_em=datetime.fromtimestamp(1_700_000_000, tz=UTC),
    )


def test_anilist_buscar_lancamento_media_null_devolve_none(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "integrations.anilist.requests.post",
        lambda *a, **k: _RespostaFalsa(corpo={"data": {"Media": None}}),
    )

    assert AniListProvider().buscar_lancamento_por_anilist_id(999) is None


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


def test_kitsu_buscar_por_titulo_traz_titulos_do_provedor(monkeypatch: pytest.MonkeyPatch):
    """Mesma extração de `buscar_titulos` (`en_jp`/`canonicalTitle` -> romaji,
    `en` -> inglês) — corroboração de match para o aquecimento por título (F14)."""
    corpo = {
        "data": [
            {
                "id": "42",
                "attributes": {
                    "synopsis": "sinopse",
                    "canonicalTitle": "Slime",
                    "titles": {
                        "en_jp": "Tensei Shitara Slime Datta Ken",
                        "ja_jp": "転生したらスライムだった件",
                        "en": "That Time I Got Reincarnated as a Slime",
                    },
                    "posterImage": {"original": "https://img/p.jpg"},
                },
            }
        ]
    }
    monkeypatch.setattr(
        "integrations.kitsu.requests.get", lambda *a, **k: _RespostaFalsa(corpo=corpo)
    )

    resultado = KitsuProvider().buscar_por_titulo("Slime")

    assert resultado.titulo_romaji == "Tensei Shitara Slime Datta Ken"
    assert resultado.titulo_ingles == "That Time I Got Reincarnated as a Slime"


def test_kitsu_listar_em_alta(monkeypatch: pytest.MonkeyPatch):
    corpo = {
        "data": [
            {
                "attributes": {
                    "canonicalTitle": "Slime",
                    "titles": {
                        "en": "That Time I Got Reincarnated as a Slime",
                        # `en_jp` é o romaji (mesmo campo usado por
                        # `buscar_titulos`) — `ja_jp` seria o título em kanji,
                        # inútil como `titulo_romaji`.
                        "en_jp": "Tensei",
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
    # Kitsu (caminho degradado) não preenche ano/gêneros — ficam nos defaults.
    assert resultado[0].ano_estreia is None
    assert resultado[0].generos == ()


def test_kitsu_listar_proxima_temporada(monkeypatch: pytest.MonkeyPatch):
    """Fallback degradado: consulta `/anime?filter[status]=upcoming` (o Kitsu não
    tem enum de temporada) e devolve o mesmo formato de `listar_em_alta`, sem
    ano/gêneros."""
    corpo = {
        "data": [
            {
                "attributes": {
                    "canonicalTitle": "Estreia",
                    "titles": {"en_jp": "Estreia JP", "en": "Premiere"},
                    "status": "upcoming",
                    "posterImage": {"original": "https://img/p.jpg"},
                    "coverImage": {"original": "https://img/c.jpg"},
                }
            }
        ]
    }
    capturado = {}

    def _get(*a, **k):
        capturado["url"] = a[0] if a else k.get("url")
        capturado["params"] = k.get("params")
        return _RespostaFalsa(corpo=corpo)

    monkeypatch.setattr("integrations.kitsu.requests.get", _get)

    resultado = KitsuProvider().listar_proxima_temporada()

    assert capturado["url"].endswith("/anime")
    assert capturado["params"]["filter[status]"] == "upcoming"
    assert resultado == [
        AnimeEmAlta(
            titulo_romaji="Estreia JP",
            titulo_ingles="Premiere",
            capa_url="https://img/p.jpg",
            banner_url="https://img/c.jpg",
            anilist_id=None,
            lancamento=LancamentoDeAnime(
                status=StatusLancamento.NAO_LANCADO,
                total_episodios=None,
                proximo_ep_numero=None,
                proximo_ep_em=None,
            ),
        )
    ]
    assert resultado[0].ano_estreia is None
    assert resultado[0].generos == ()


def test_kitsu_buscar_titulos_usa_en_jp_e_en(monkeypatch: pytest.MonkeyPatch):
    corpo = {
        "data": [
            {
                "id": "42",
                "attributes": {
                    "canonicalTitle": "Slime",
                    "titles": {
                        "en_jp": "Tensei Shitara Slime Datta Ken",
                        "ja_jp": "転生したらスライムだった件",
                        "en": "That Time I Got Reincarnated as a Slime",
                    },
                },
            }
        ]
    }
    monkeypatch.setattr(
        "integrations.kitsu.requests.get", lambda *a, **k: _RespostaFalsa(corpo=corpo)
    )

    resultado = KitsuProvider().buscar_titulos("Slime")

    assert resultado == TitulosDeAnime(
        titulo_romaji="Tensei Shitara Slime Datta Ken",
        titulo_ingles="That Time I Got Reincarnated as a Slime",
    )


def test_kitsu_listar_em_alta_sem_en_jp_cai_para_canonical_title(monkeypatch: pytest.MonkeyPatch):
    """Regressão: `ja_jp` (kanji) não pode ser usado como `titulo_romaji` —
    só `en_jp`/`canonicalTitle`. Sem `en_jp`, cai pro `canonicalTitle`, nunca
    pro kanji de `ja_jp`."""
    corpo = {
        "data": [
            {
                "attributes": {
                    "canonicalTitle": "Slime",
                    "titles": {"ja_jp": "転生したらスライムだった件"},
                    "posterImage": None,
                    "coverImage": None,
                }
            }
        ]
    }
    monkeypatch.setattr(
        "integrations.kitsu.requests.get", lambda *a, **k: _RespostaFalsa(corpo=corpo)
    )

    resultado = KitsuProvider().listar_em_alta()

    assert resultado[0].titulo_romaji == "Slime"


def test_kitsu_buscar_titulos_sem_en_jp_cai_para_canonical_title(
    monkeypatch: pytest.MonkeyPatch,
):
    corpo = {
        "data": [
            {
                "id": "42",
                "attributes": {"canonicalTitle": "Slime", "titles": {}},
            }
        ]
    }
    monkeypatch.setattr(
        "integrations.kitsu.requests.get", lambda *a, **k: _RespostaFalsa(corpo=corpo)
    )

    resultado = KitsuProvider().buscar_titulos("Slime")

    assert resultado == TitulosDeAnime(titulo_romaji="Slime", titulo_ingles=None)


def test_kitsu_preenche_lancamento_sem_next_airing(monkeypatch: pytest.MonkeyPatch):
    corpo = {
        "data": [
            {
                "id": "42",
                "attributes": {
                    "synopsis": "sinopse",
                    "status": "current",
                    "episodeCount": 12,
                    "posterImage": {"original": "https://img/p.jpg"},
                },
            }
        ]
    }
    monkeypatch.setattr(
        "integrations.kitsu.requests.get", lambda *a, **k: _RespostaFalsa(corpo=corpo)
    )

    lancamento = KitsuProvider().buscar_por_titulo("Slime").lancamento

    assert lancamento == LancamentoDeAnime(
        status=StatusLancamento.EM_LANCAMENTO,
        total_episodios=12,
        proximo_ep_numero=None,
        proximo_ep_em=None,
    )


def test_kitsu_sem_dados_de_lancamento_deixa_campo_none(monkeypatch: pytest.MonkeyPatch):
    corpo = {"data": [{"id": "42", "attributes": {"synopsis": "sinopse"}}]}
    monkeypatch.setattr(
        "integrations.kitsu.requests.get", lambda *a, **k: _RespostaFalsa(corpo=corpo)
    )

    assert KitsuProvider().buscar_por_titulo("Slime").lancamento is None


def test_kitsu_lancamento_start_date_completo(monkeypatch: pytest.MonkeyPatch):
    """`attributes.startDate` ISO `YYYY-MM-DD` completo -> `estreia_em` data
    completa e `ano_estreia` do mesmo ano."""
    corpo = {
        "data": [
            {
                "id": "42",
                "attributes": {
                    "synopsis": "sinopse",
                    "status": "upcoming",
                    "startDate": "2027-04-15",
                },
            }
        ]
    }
    monkeypatch.setattr(
        "integrations.kitsu.requests.get", lambda *a, **k: _RespostaFalsa(corpo=corpo)
    )

    lancamento = KitsuProvider().buscar_por_titulo("Slime").lancamento

    assert lancamento == LancamentoDeAnime(
        status=StatusLancamento.NAO_LANCADO,
        total_episodios=None,
        proximo_ep_numero=None,
        proximo_ep_em=None,
        estreia_em=date(2027, 4, 15),
        ano_estreia=2027,
    )


def test_kitsu_lancamento_start_date_parcial_so_ano(monkeypatch: pytest.MonkeyPatch):
    """`startDate` só com o ano (`"2028"`) -> `estreia_em` None, `ano_estreia`
    do prefixo."""
    corpo = {
        "data": [
            {
                "id": "42",
                "attributes": {"synopsis": "s", "status": "upcoming", "startDate": "2028"},
            }
        ]
    }
    monkeypatch.setattr(
        "integrations.kitsu.requests.get", lambda *a, **k: _RespostaFalsa(corpo=corpo)
    )

    lancamento = KitsuProvider().buscar_por_titulo("Slime").lancamento

    assert lancamento.estreia_em is None
    assert lancamento.ano_estreia == 2028


def test_kitsu_lancamento_start_date_impossivel_cai_para_ano(monkeypatch: pytest.MonkeyPatch):
    """Formato `YYYY-MM-DD` mas data inválida (30 de fevereiro): `estreia_em`
    None, `ano_estreia` ainda extraído do prefixo."""
    corpo = {
        "data": [
            {
                "id": "42",
                "attributes": {
                    "synopsis": "s",
                    "status": "upcoming",
                    "startDate": "2027-02-30",
                },
            }
        ]
    }
    monkeypatch.setattr(
        "integrations.kitsu.requests.get", lambda *a, **k: _RespostaFalsa(corpo=corpo)
    )

    lancamento = KitsuProvider().buscar_por_titulo("Slime").lancamento

    assert lancamento.estreia_em is None
    assert lancamento.ano_estreia == 2027


def test_kitsu_lancamento_start_date_ausente_com_status(monkeypatch: pytest.MonkeyPatch):
    """Sem `startDate`, mas com `status`: bloco existe, campos de estreia None."""
    corpo = {
        "data": [{"id": "42", "attributes": {"synopsis": "s", "status": "current"}}]
    }
    monkeypatch.setattr(
        "integrations.kitsu.requests.get", lambda *a, **k: _RespostaFalsa(corpo=corpo)
    )

    lancamento = KitsuProvider().buscar_por_titulo("Slime").lancamento

    assert lancamento.estreia_em is None
    assert lancamento.ano_estreia is None


def test_kitsu_lancamento_so_start_date_ainda_devolve_bloco(monkeypatch: pytest.MonkeyPatch):
    """Guard: `startDate` sozinho (sem `status`/`episodeCount`) já basta para
    `_extrair_lancamento` devolver bloco em vez de None."""
    corpo = {
        "data": [{"id": "42", "attributes": {"synopsis": "s", "startDate": "2027-04-15"}}]
    }
    monkeypatch.setattr(
        "integrations.kitsu.requests.get", lambda *a, **k: _RespostaFalsa(corpo=corpo)
    )

    lancamento = KitsuProvider().buscar_por_titulo("Slime").lancamento

    assert lancamento is not None
    assert lancamento.status is None
    assert lancamento.estreia_em == date(2027, 4, 15)


def test_kitsu_nao_e_provedor_com_lancamento():
    assert not isinstance(KitsuProvider(), ProvedorComLancamento)


# --- cadeia de fallback (integrations/servico.py) ---


class _ProvedorFake(ProvedorDeMetadados):
    def __init__(
        self,
        nome: str,
        *,
        metadados=None,
        em_alta=None,
        proxima_temporada=None,
        titulos=None,
        erro: Exception | None = None,
    ):
        self._nome = nome
        self._metadados = metadados
        self._em_alta = em_alta or []
        self._proxima_temporada = proxima_temporada or []
        self._titulos = titulos
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

    def listar_proxima_temporada(self):
        if self._erro is not None:
            raise self._erro
        return self._proxima_temporada

    def buscar_titulos(self, titulo: str):
        if self._erro is not None:
            raise self._erro
        return self._titulos


class _ProvedorComLancamentoFake(ProvedorDeMetadados, ProvedorComLancamento):
    """Provedor fake que implementa a capability opcional `ProvedorComLancamento`
    (o `_ProvedorFake` acima não a implementa, para exercitar o filtro
    `isinstance` de `servico.buscar_lancamento_por_anilist_id`)."""

    def __init__(self, nome: str, *, lancamento=None, erro: Exception | None = None):
        self._nome = nome
        self._lancamento = lancamento
        self._erro = erro

    @property
    def nome(self) -> str:
        return self._nome

    def buscar_por_titulo(self, titulo: str):
        return None

    def listar_em_alta(self):
        return []

    def listar_proxima_temporada(self):
        return []

    def buscar_titulos(self, titulo: str):
        return None

    def buscar_lancamento_por_anilist_id(self, anilist_id: int):
        if self._erro is not None:
            raise self._erro
        return self._lancamento


@pytest.fixture(autouse=True)
def _limpa_caches_de_feed(monkeypatch: pytest.MonkeyPatch):
    """`integrations.servico._cache_em_alta` e `._cache_proxima_temporada` são
    estado de módulo — isola cada teste para não vazar cache de um teste para o
    outro."""
    monkeypatch.setattr(servico, "_cache_em_alta", None)
    monkeypatch.setattr(servico, "_cache_proxima_temporada", None)


@pytest.fixture(autouse=True)
def _busca_de_metadados_por_titulo_sem_rede():
    """Sobrescreve o stub global do `conftest.py`: este arquivo exercita a
    própria `servico.buscar_por_titulo` (com `PROVEDORES` fake, sem rede), então
    precisa da função real, não do stub que devolve `None`."""
    yield


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


async def test_servico_buscar_titulos_cai_para_kitsu_quando_anilist_falha(
    monkeypatch: pytest.MonkeyPatch,
):
    esperado = TitulosDeAnime(titulo_romaji="Tensei", titulo_ingles="Reincarnated")
    anilist = _ProvedorFake("anilist", erro=requests.ConnectionError("falhou"))
    kitsu = _ProvedorFake("kitsu", titulos=esperado)
    monkeypatch.setattr(servico, "PROVEDORES", (anilist, kitsu))

    resultado = await servico.buscar_titulos("Slime")

    assert resultado is esperado


async def test_servico_buscar_titulos_levanta_falha_de_metadados_quando_todos_falham(
    monkeypatch: pytest.MonkeyPatch,
):
    anilist = _ProvedorFake("anilist", erro=requests.ConnectionError("falhou"))
    kitsu = _ProvedorFake("kitsu", erro=requests.ConnectionError("falhou"))
    monkeypatch.setattr(servico, "PROVEDORES", (anilist, kitsu))

    with pytest.raises(FalhaDeMetadados):
        await servico.buscar_titulos("Slime")


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

        def listar_proxima_temporada(self):
            return []

        def buscar_titulos(self, titulo: str):
            return None

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
    monkeypatch.setattr(servico, "PROVEDORES_DE_FEED", (anilist,))

    with pytest.raises(FalhaDeMetadados):
        await servico.listar_em_alta()


async def test_servico_em_alta_nao_cai_para_kitsu_quando_anilist_falha(
    monkeypatch: pytest.MonkeyPatch,
):
    """Kitsu não entra em `PROVEDORES_DE_FEED` (ver `registro.PROVEDORES_DE_FEED`)
    — o feed "em alta" propaga o erro em vez de servir o trending all-time."""
    anilist = _ProvedorFake("anilist", erro=requests.ConnectionError("falhou"))
    kitsu = _ProvedorFake(
        "kitsu",
        em_alta=[
            AnimeEmAlta(
                titulo_romaji="One Piece",
                titulo_ingles=None,
                capa_url=None,
                banner_url=None,
                anilist_id=21,
            )
        ],
    )
    monkeypatch.setattr(servico, "PROVEDORES_DE_FEED", (anilist,))
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
    monkeypatch.setattr(servico, "PROVEDORES_DE_FEED", (anilist,))

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

        def listar_proxima_temporada(self):
            return []

        def buscar_titulos(self, titulo: str):
            return None

    monkeypatch.setattr(servico, "PROVEDORES_DE_FEED", (_ProvedorLento(),))

    primeira, segunda = await asyncio.gather(servico.listar_em_alta(), servico.listar_em_alta())

    assert len(chamadas) == 1
    assert primeira == segunda == [item]


# --- servico.listar_proxima_temporada (espelha listar_em_alta) ---


def _item_prox(anilist_id: int = 1) -> AnimeEmAlta:
    return AnimeEmAlta(
        titulo_romaji="Prox",
        titulo_ingles=None,
        capa_url=None,
        banner_url=None,
        anilist_id=anilist_id,
    )


async def test_servico_proxima_temporada_nao_cai_para_kitsu_quando_anilist_falha(
    monkeypatch: pytest.MonkeyPatch,
):
    """Kitsu não entra em `PROVEDORES_DE_FEED`: seu feed é popularidade de todos
    os tempos, não a temporada. Com a AniList fora, o feed propaga o erro em vez
    de servir conteúdo enganoso (ver `registro.PROVEDORES_DE_FEED`)."""
    anilist = _ProvedorFake("anilist", erro=requests.ConnectionError("falhou"))
    kitsu = _ProvedorFake("kitsu", proxima_temporada=[_item_prox(7)])
    monkeypatch.setattr(servico, "PROVEDORES_DE_FEED", (anilist,))
    monkeypatch.setattr(servico, "PROVEDORES", (anilist, kitsu))

    with pytest.raises(FalhaDeMetadados):
        await servico.listar_proxima_temporada()


async def test_servico_proxima_temporada_propaga_falha_de_metadados_se_todos_falham(
    monkeypatch: pytest.MonkeyPatch,
):
    anilist = _ProvedorFake("anilist", erro=requests.ConnectionError("falhou"))
    monkeypatch.setattr(servico, "PROVEDORES_DE_FEED", (anilist,))

    with pytest.raises(FalhaDeMetadados):
        await servico.listar_proxima_temporada()


async def test_servico_proxima_temporada_usa_cache_dentro_do_ttl(monkeypatch: pytest.MonkeyPatch):
    chamadas = []
    item = _item_prox()

    def _listar():
        chamadas.append(1)
        return [item]

    anilist = _ProvedorFake("anilist")
    anilist.listar_proxima_temporada = _listar
    monkeypatch.setattr(servico, "PROVEDORES_DE_FEED", (anilist,))

    primeira = await servico.listar_proxima_temporada()
    segunda = await servico.listar_proxima_temporada()

    assert len(chamadas) == 1
    assert primeira == segunda == [item]


async def test_servico_proxima_temporada_cache_independente_do_em_alta(
    monkeypatch: pytest.MonkeyPatch,
):
    """Os dois feeds têm cache/lock próprios — um cache-hit de "em alta" não
    serve o de "próxima temporada" nem vice-versa."""
    em_alta = [_item_prox(10)]
    prox = [_item_prox(20)]
    provedor = _ProvedorFake("anilist", em_alta=em_alta, proxima_temporada=prox)
    monkeypatch.setattr(servico, "PROVEDORES_DE_FEED", (provedor,))

    assert await servico.listar_em_alta() == em_alta
    assert await servico.listar_proxima_temporada() == prox


# --- servico.buscar_lancamento_por_anilist_id (F2 detector de eps novos) ---


async def test_servico_buscar_lancamento_so_consulta_provedor_capaz(
    monkeypatch: pytest.MonkeyPatch,
):
    esperado = LancamentoDeAnime(
        status=StatusLancamento.EM_LANCAMENTO,
        total_episodios=24,
        proximo_ep_numero=13,
        proximo_ep_em=datetime.fromtimestamp(1_700_000_000, tz=UTC),
    )
    anilist = _ProvedorComLancamentoFake("anilist", lancamento=esperado)
    # `erro` nunca dispara: o filtro `isinstance` pula o Kitsu antes de chamá-lo.
    kitsu = _ProvedorFake("kitsu", erro=requests.ConnectionError("não deveria ser chamado"))
    monkeypatch.setattr(servico, "PROVEDORES", (anilist, kitsu))

    resultado = await servico.buscar_lancamento_por_anilist_id(21)

    assert resultado is esperado
    assert not isinstance(kitsu, ProvedorComLancamento)


async def test_servico_buscar_lancamento_sem_provedor_capaz_devolve_none(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(servico, "PROVEDORES", (_ProvedorFake("kitsu"),))

    assert await servico.buscar_lancamento_por_anilist_id(21) is None


async def test_servico_buscar_lancamento_cai_para_proximo_capaz_em_erro(
    monkeypatch: pytest.MonkeyPatch,
):
    esperado = LancamentoDeAnime(
        status=StatusLancamento.FINALIZADO,
        total_episodios=12,
        proximo_ep_numero=None,
        proximo_ep_em=None,
    )
    falho = _ProvedorComLancamentoFake("a", erro=requests.ConnectionError("falhou"))
    ok = _ProvedorComLancamentoFake("b", lancamento=esperado)
    monkeypatch.setattr(servico, "PROVEDORES", (falho, ok))

    assert await servico.buscar_lancamento_por_anilist_id(21) is esperado


async def test_servico_buscar_lancamento_levanta_se_todos_capazes_falham(
    monkeypatch: pytest.MonkeyPatch,
):
    falho1 = _ProvedorComLancamentoFake("a", erro=requests.ConnectionError("falhou"))
    falho2 = _ProvedorComLancamentoFake("b", erro=requests.HTTPError("HTTP 502"))
    monkeypatch.setattr(servico, "PROVEDORES", (falho1, falho2))

    with pytest.raises(FalhaDeMetadados):
        await servico.buscar_lancamento_por_anilist_id(21)

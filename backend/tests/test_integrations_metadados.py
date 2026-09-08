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
from integrations import registro, servico
from integrations.anilist import AniListProvider, _proxima_temporada
from integrations.base import (
    AnimeEmAlta,
    ArteDeAnime,
    FileiraTematica,
    LancamentoDeAnime,
    MetadadosDeAnime,
    ProvedorComFileirasTematicas,
    ProvedorComLancamento,
    ProvedorDeArte,
    ProvedorDeMetadados,
    TitulosDeAnime,
)
from integrations.kitsu import KitsuProvider
from integrations.registro import FILEIRAS_TEMATICAS
from integrations.tmdb import TmdbNaoAutorizado, TmdbProvider


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
        banner_url="https://img/banner.jpg",
    )


def test_anilist_buscar_por_titulo_preenche_banner_e_capa_cor(monkeypatch: pytest.MonkeyPatch):
    corpo = {
        "data": {
            "Media": {
                "id": 7,
                "title": {"romaji": "Tensei", "english": None},
                "coverImage": {"extraLarge": "https://img/cover.jpg", "color": "#e4a15d"},
                "bannerImage": "https://img/banner.jpg",
                "description": "sinopse",
            }
        }
    }
    monkeypatch.setattr(
        "integrations.anilist.requests.post", lambda *a, **k: _RespostaFalsa(corpo=corpo)
    )

    resultado = AniListProvider().buscar_por_titulo("Slime")

    assert resultado.banner_url == "https://img/banner.jpg"
    assert resultado.capa_cor == "#e4a15d"


def test_anilist_buscar_por_titulo_sem_banner_nem_cor_deixa_campos_none(
    monkeypatch: pytest.MonkeyPatch,
):
    """`bannerImage` nulo e `coverImage` sem `color` (a AniList omite os dois em
    títulos antigos): `banner_url`/`capa_cor` caem para `None`."""
    corpo = {
        "data": {
            "Media": {
                "id": 7,
                "coverImage": {"extraLarge": "https://img/c.jpg"},
                "bannerImage": None,
                "description": "x",
            }
        }
    }
    monkeypatch.setattr(
        "integrations.anilist.requests.post", lambda *a, **k: _RespostaFalsa(corpo=corpo)
    )

    resultado = AniListProvider().buscar_por_titulo("Slime")

    assert resultado.banner_url is None
    assert resultado.capa_cor is None


def test_anilist_buscar_por_titulo_preenche_generos_e_ano(monkeypatch: pytest.MonkeyPatch):
    corpo = {
        "data": {
            "Media": {
                "id": 7,
                "coverImage": {"extraLarge": "https://img/c.jpg"},
                "bannerImage": None,
                "genres": ["Action", "Comedy"],
                "description": "x",
                "seasonYear": 2018,
            }
        }
    }
    monkeypatch.setattr(
        "integrations.anilist.requests.post", lambda *a, **k: _RespostaFalsa(corpo=corpo)
    )

    resultado = AniListProvider().buscar_por_titulo("Slime")

    assert resultado.generos == ["Action", "Comedy"]
    assert resultado.ano == 2018


def test_anilist_buscar_por_titulo_sem_generos_nem_ano_deixa_defaults(
    monkeypatch: pytest.MonkeyPatch,
):
    """`genres` vazio e sem `seasonYear`/`startDate` (títulos antigos): `generos`
    cai para `None` e `ano` para `None` — não `[]` nem `0`."""
    corpo = {
        "data": {
            "Media": {
                "id": 7,
                "coverImage": {"extraLarge": "https://img/c.jpg"},
                "bannerImage": None,
                "genres": [],
                "description": "x",
            }
        }
    }
    monkeypatch.setattr(
        "integrations.anilist.requests.post", lambda *a, **k: _RespostaFalsa(corpo=corpo)
    )

    resultado = AniListProvider().buscar_por_titulo("Slime")

    assert resultado.generos is None
    assert resultado.ano is None


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
                        "coverImage": {"extraLarge": "https://img/1.jpg", "color": "#e4a15d"},
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
            capa_cor="#e4a15d",
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
    """`seasonYear` nulo → usa `startDate.year`; `genres` nulo → `generos` vazio;
    `coverImage` sem `color` → `capa_cor` None."""
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
    assert item.capa_cor is None


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


def test_anilist_listar_fileira_tematica(monkeypatch: pytest.MonkeyPatch):
    """Parsing idêntico ao de `listar_em_alta` (`_item_para_anime_em_alta`
    reusado); aqui o foco é a query enviada — `tag` como variável e
    `minimumTagRank: 60`/`isAdult: false` fixos no filtro."""
    corpo = {
        "data": {
            "Page": {
                "media": [
                    {
                        "id": 1,
                        "title": {"romaji": "Tensei", "english": "Reincarnated"},
                        "coverImage": {"extraLarge": "https://img/1.jpg", "color": "#e4a15d"},
                        "bannerImage": "https://img/1-banner.jpg",
                        "genres": ["Action", "Fantasy"],
                        "seasonYear": 2021,
                        "startDate": {"year": 2021},
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

    fileira = FileiraTematica(chave="isekai", tag="Isekai")
    resultado = AniListProvider().listar_fileira_tematica(fileira)

    assert capturado["variables"] == {"tag": "Isekai"}
    assert "minimumTagRank: 60" in capturado["query"]
    assert "isAdult: false" in capturado["query"]
    assert resultado == [
        AnimeEmAlta(
            titulo_romaji="Tensei",
            titulo_ingles="Reincarnated",
            capa_url="https://img/1.jpg",
            capa_cor="#e4a15d",
            banner_url="https://img/1-banner.jpg",
            anilist_id=1,
            ano_estreia=2021,
            generos=("Action", "Fantasy"),
            lancamento=LancamentoDeAnime(
                status=None,
                total_episodios=None,
                proximo_ep_numero=None,
                proximo_ep_em=None,
                ano_estreia=2021,
            ),
        )
    ]


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
    corpo = {
        "data": {
            "Media": {
                "title": {
                    "romaji": "Tensei",
                    "english": "Reincarnated",
                    "native": "転生したら",
                },
                "synonyms": ["TenSura", "Slime Isekai"],
            }
        }
    }
    monkeypatch.setattr(
        "integrations.anilist.requests.post", lambda *a, **k: _RespostaFalsa(corpo=corpo)
    )

    resultado = AniListProvider().buscar_titulos("Slime")

    assert resultado == TitulosDeAnime(
        titulo_romaji="Tensei",
        titulo_ingles="Reincarnated",
        titulo_nativo="転生したら",
        sinonimos=("TenSura", "Slime Isekai"),
    )


def test_anilist_buscar_titulos_so_romaji_presente(monkeypatch: pytest.MonkeyPatch):
    corpo = {"data": {"Media": {"title": {"romaji": "Tensei", "english": None}}}}
    monkeypatch.setattr(
        "integrations.anilist.requests.post", lambda *a, **k: _RespostaFalsa(corpo=corpo)
    )

    resultado = AniListProvider().buscar_titulos("Slime")

    assert resultado == TitulosDeAnime(titulo_romaji="Tensei", titulo_ingles=None)
    assert resultado.titulo_nativo is None
    assert resultado.sinonimos == ()


def test_anilist_buscar_titulos_synonyms_null_ou_com_lixo(monkeypatch: pytest.MonkeyPatch):
    """`synonyms` pode vir `null` (não lista) ou com entradas vazias/só espaço/
    não-string — tudo filtrado, ordem preservada; `native` ausente vira `None`."""
    corpo_null = {
        "data": {"Media": {"title": {"romaji": "Tensei", "english": None}, "synonyms": None}}
    }
    monkeypatch.setattr(
        "integrations.anilist.requests.post", lambda *a, **k: _RespostaFalsa(corpo=corpo_null)
    )
    assert AniListProvider().buscar_titulos("Slime").sinonimos == ()

    corpo_lixo = {
        "data": {
            "Media": {
                "title": {"romaji": "Tensei", "english": None},
                "synonyms": ["Bom", "  ", "", None, "Outro"],
            }
        }
    }
    monkeypatch.setattr(
        "integrations.anilist.requests.post", lambda *a, **k: _RespostaFalsa(corpo=corpo_lixo)
    )
    resultado = AniListProvider().buscar_titulos("Slime")
    assert resultado.sinonimos == ("Bom", "Outro")
    assert resultado.titulo_nativo is None


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


# --- AniListProvider: metadados por id AniList (feature banner na página) ---


def test_anilist_buscar_metadados_por_anilist_id(monkeypatch: pytest.MonkeyPatch):
    corpo = {
        "data": {
            "Media": {
                "id": 21,
                "title": {"romaji": "Tensei", "english": "Reincarnated"},
                "description": "Linha um<br>Linha dois &amp; mais",
                "coverImage": {"extraLarge": "https://img/cover.jpg", "color": "#e4a15d"},
                "bannerImage": "https://img/banner.jpg",
            }
        }
    }
    capturado = {}

    def _post(*a, **k):
        capturado.update(k["json"])
        return _RespostaFalsa(corpo=corpo)

    monkeypatch.setattr("integrations.anilist.requests.post", _post)

    resultado = AniListProvider().buscar_metadados_por_anilist_id(21)

    assert capturado["variables"] == {"id": 21}
    assert resultado == MetadadosDeAnime(
        capa_url="https://img/cover.jpg",
        sinopse="Linha um\nLinha dois & mais",
        anilist_id=21,
        kitsu_id=None,
        banner_url="https://img/banner.jpg",
        capa_cor="#e4a15d",
        titulo_romaji="Tensei",
        titulo_ingles="Reincarnated",
    )


def test_anilist_buscar_metadados_por_anilist_id_extrai_generos_e_ano(
    monkeypatch: pytest.MonkeyPatch,
):
    corpo = {
        "data": {
            "Media": {
                "id": 21,
                "description": "sinopse",
                "coverImage": {"extraLarge": "https://img/cover.jpg"},
                "bannerImage": "https://img/banner.jpg",
                "genres": ["Action", "Comedy"],
                "seasonYear": 2018,
            }
        }
    }
    monkeypatch.setattr(
        "integrations.anilist.requests.post", lambda *a, **k: _RespostaFalsa(corpo=corpo)
    )

    resultado = AniListProvider().buscar_metadados_por_anilist_id(21)

    assert resultado.generos == ["Action", "Comedy"]
    assert resultado.ano == 2018


def test_anilist_buscar_metadados_por_anilist_id_ano_cai_para_start_date(
    monkeypatch: pytest.MonkeyPatch,
):
    """Sem `seasonYear`, `_extrair_ano` recai sobre `startDate.year`."""
    corpo = {
        "data": {
            "Media": {
                "id": 21,
                "description": "sinopse",
                "coverImage": {"extraLarge": "https://img/cover.jpg"},
                "bannerImage": None,
                "genres": [],
                "startDate": {"year": 2015},
            }
        }
    }
    monkeypatch.setattr(
        "integrations.anilist.requests.post", lambda *a, **k: _RespostaFalsa(corpo=corpo)
    )

    resultado = AniListProvider().buscar_metadados_por_anilist_id(21)

    assert resultado.generos is None
    assert resultado.ano == 2015


def test_anilist_buscar_metadados_por_anilist_id_media_null_devolve_none(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "integrations.anilist.requests.post",
        lambda *a, **k: _RespostaFalsa(corpo={"data": {"Media": None}}),
    )

    assert AniListProvider().buscar_metadados_por_anilist_id(999) is None


def test_kitsu_nao_implementa_metadados_por_anilist_id():
    """Kitsu herda a implementação padrão de `ProvedorDeMetadados` (`None`) — não
    conhece id AniList."""
    assert KitsuProvider().buscar_metadados_por_anilist_id(21) is None


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
    # Kitsu (caminho degradado) não preenche ano/gêneros/cor — ficam nos defaults.
    assert resultado[0].ano_estreia is None
    assert resultado[0].generos == ()
    assert resultado[0].capa_cor is None


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
    # Caminho degradado: Kitsu não expõe título nativo nem sinônimos.
    assert resultado.titulo_nativo is None
    assert resultado.sinonimos == ()


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


# --- TmdbProvider (arte: capa/banner, PLANO_ARTE_TMDB.md) ---


def _resultado_tv(**overrides) -> dict:
    base = {
        "name": "Tensei",
        "original_name": "Tensei",
        "poster_path": "/poster.jpg",
        "backdrop_path": "/backdrop.jpg",
        "first_air_date": "2018-10-02",
    }
    base.update(overrides)
    return base


def test_tmdb_buscar_arte_por_titulo_match_exato_prefixa_url_de_imagem(
    monkeypatch: pytest.MonkeyPatch,
):
    corpo = {"results": [_resultado_tv(name="Slime", original_name="Slime")]}
    monkeypatch.setattr(
        "integrations.tmdb.requests.get", lambda *a, **k: _RespostaFalsa(corpo=corpo)
    )

    resultado = TmdbProvider("token").buscar_arte_por_titulo("Slime", None)

    assert resultado == ArteDeAnime(banner_url="https://image.tmdb.org/t/p/w1280/backdrop.jpg")


def test_tmdb_desempate_por_ano_entre_dois_candidatos(monkeypatch: pytest.MonkeyPatch):
    """Nenhum dos dois candidatos bate por título exato com "Slime Franquia S3"
    (D3: TMDB modela a franquia inteira numa entrada só) — o pool cai pros dois
    e o de `first_air_date` mais perto de `ano` vence (aqui desambiguado pelo
    `backdrop_path`, já que capa não é mais parte do retorno)."""
    corpo = {
        "results": [
            _resultado_tv(
                name="Slime Franquia",
                original_name="Slime Franquia",
                backdrop_path="/franquia-backdrop.jpg",
                first_air_date="2010-01-01",
            ),
            _resultado_tv(
                name="Slime Franquia",
                original_name="Slime Franquia",
                backdrop_path="/temporada3-backdrop.jpg",
                first_air_date="2024-01-01",
            ),
        ]
    }
    monkeypatch.setattr(
        "integrations.tmdb.requests.get", lambda *a, **k: _RespostaFalsa(corpo=corpo)
    )

    resultado = TmdbProvider("token").buscar_arte_por_titulo("Slime Franquia S3", 2024)

    assert resultado.banner_url.endswith("/temporada3-backdrop.jpg")


def test_tmdb_popularity_vence_distancia_de_ano(monkeypatch: pytest.MonkeyPatch):
    """A série principal da franquia (mais popular, `first_air_date` antigo)
    vence o spin-off recente cujo ano fica mais perto do `ano` pedido — a
    distância de ano só desempata quando a popularidade empata. Sem isto, a 4ª
    temporada (ano recente) elegia o spin-off no lugar da série principal."""
    corpo = {
        "results": [
            _resultado_tv(
                name="Slime Diaries",
                original_name="Slime Diaries",
                backdrop_path="/spinoff.jpg",
                first_air_date="2021-01-01",
                popularity=12.9,
            ),
            _resultado_tv(
                name="Slime",
                original_name="Slime",
                backdrop_path="/serie-principal.jpg",
                first_air_date="2018-01-01",
                popularity=50.5,
            ),
        ]
    }
    monkeypatch.setattr(
        "integrations.tmdb.requests.get", lambda *a, **k: _RespostaFalsa(corpo=corpo)
    )

    resultado = TmdbProvider("token").buscar_arte_por_titulo("Slime 4th Season", 2026)

    assert resultado.banner_url.endswith("/serie-principal.jpg")


def test_tmdb_item_so_com_poster_path_sem_backdrop_devolve_none(
    monkeypatch: pytest.MonkeyPatch,
):
    """Sem `backdrop_path` (mesmo com `poster_path`), não há banner pra
    oferecer — capa não é mais parte do retorno, então o resultado é `None`."""
    corpo = {"results": [_resultado_tv(poster_path="/poster.jpg", backdrop_path=None)]}
    monkeypatch.setattr(
        "integrations.tmdb.requests.get", lambda *a, **k: _RespostaFalsa(corpo=corpo)
    )

    assert TmdbProvider("token").buscar_arte_por_titulo("Tensei", None) is None


def test_tmdb_results_vazio_devolve_none(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "integrations.tmdb.requests.get",
        lambda *a, **k: _RespostaFalsa(corpo={"results": []}),
    )

    assert TmdbProvider("token").buscar_arte_por_titulo("Slime", None) is None


def test_tmdb_401_levanta_nao_autorizado(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "integrations.tmdb.requests.get",
        lambda *a, **k: _RespostaFalsa(status_code=401),
    )

    with pytest.raises(TmdbNaoAutorizado):
        TmdbProvider("token").buscar_arte_por_titulo("Slime", None)


def test_tmdb_buscar_arte_por_titulo_nao_aceita_mais_numero_temporada():
    """A refinação de capa por temporada foi removida (reversão pra AniList
    como fonte exclusiva de capa) — `numero_temporada` não é mais um parâmetro
    válido de `buscar_arte_por_titulo`."""
    with pytest.raises(TypeError):
        TmdbProvider("token").buscar_arte_por_titulo("Slime", None, numero_temporada=4)


# --- TmdbProvider.buscar_still_de_episodio (Fatia 5, PLANO_ARTE_TMDB.md) ---


def test_tmdb_still_de_episodio_match_feliz(monkeypatch: pytest.MonkeyPatch):
    """Resolve a série, monta a tabela de temporadas (especial season_number=0
    fica fora da numeração absoluta; temporada 1 com 12 episódios, temporada 2
    começando no absoluto 13) e acha que o episódio absoluto 13 é o 1º da
    temporada 2."""

    def _fake_get(url, **kwargs):
        if url.endswith("/search/tv"):
            return _RespostaFalsa(
                corpo={"results": [_resultado_tv(id=999, name="Slime", original_name="Slime")]}
            )
        if url.endswith("/tv/999"):
            return _RespostaFalsa(
                corpo={
                    "seasons": [
                        {"season_number": 0, "episode_count": 3},
                        {"season_number": 1, "episode_count": 12},
                        {"season_number": 2, "episode_count": 12},
                    ]
                }
            )
        if url.endswith("/tv/999/season/2"):
            return _RespostaFalsa(
                corpo={
                    "episodes": [
                        {"episode_number": 1, "still_path": "/ep13.jpg"},
                        {"episode_number": 2, "still_path": "/ep14.jpg"},
                    ]
                }
            )
        raise AssertionError(f"URL não mapeada no fake: {url}")

    monkeypatch.setattr("integrations.tmdb.requests.get", _fake_get)

    resultado = TmdbProvider("token").buscar_still_de_episodio("Slime", 2018, 13)

    assert resultado == "https://image.tmdb.org/t/p/original/ep13.jpg"


def test_tmdb_still_de_episodio_temporada_fora_do_range_devolve_none(
    monkeypatch: pytest.MonkeyPatch,
):
    def _fake_get(url, **kwargs):
        if url.endswith("/search/tv"):
            return _RespostaFalsa(
                corpo={"results": [_resultado_tv(id=999, name="Slime", original_name="Slime")]}
            )
        if url.endswith("/tv/999"):
            return _RespostaFalsa(corpo={"seasons": [{"season_number": 1, "episode_count": 12}]})
        raise AssertionError(f"URL não mapeada no fake: {url}")

    monkeypatch.setattr("integrations.tmdb.requests.get", _fake_get)

    # 99 fica fora do intervalo [1, 12] coberto pela única temporada — nunca
    # deveria disparar `/tv/999/season/{n}` (o fake levantaria se disparasse).
    assert TmdbProvider("token").buscar_still_de_episodio("Slime", 2018, 99) is None


def test_tmdb_still_de_episodio_still_nulo_devolve_none(monkeypatch: pytest.MonkeyPatch):
    def _fake_get(url, **kwargs):
        if url.endswith("/search/tv"):
            return _RespostaFalsa(
                corpo={"results": [_resultado_tv(id=999, name="Slime", original_name="Slime")]}
            )
        if url.endswith("/tv/999"):
            return _RespostaFalsa(corpo={"seasons": [{"season_number": 1, "episode_count": 12}]})
        if url.endswith("/tv/999/season/1"):
            return _RespostaFalsa(corpo={"episodes": [{"episode_number": 5, "still_path": None}]})
        raise AssertionError(f"URL não mapeada no fake: {url}")

    monkeypatch.setattr("integrations.tmdb.requests.get", _fake_get)

    assert TmdbProvider("token").buscar_still_de_episodio("Slime", 2018, 5) is None


def test_tmdb_still_de_episodio_id_nao_resolvido_devolve_none(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "integrations.tmdb.requests.get",
        lambda *a, **k: _RespostaFalsa(corpo={"results": []}),
    )

    assert TmdbProvider("token").buscar_still_de_episodio("Slime", None, 1) is None


# --- cadeia de fallback (integrations/servico.py) ---


class _ProvedorFake(ProvedorDeMetadados):
    def __init__(
        self,
        nome: str,
        *,
        metadados=None,
        metadados_por_id=None,
        em_alta=None,
        proxima_temporada=None,
        titulos=None,
        erro: Exception | None = None,
    ):
        self._nome = nome
        self._metadados = metadados
        self._metadados_por_id = metadados_por_id
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

    def buscar_metadados_por_anilist_id(self, anilist_id: int):
        if self._erro is not None:
            raise self._erro
        return self._metadados_por_id

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


class _ProvedorComFileirasTematicasFake(ProvedorDeMetadados, ProvedorComFileirasTematicas):
    """Provedor fake que implementa a capability opcional
    `ProvedorComFileirasTematicas` (o `_ProvedorFake` acima não a implementa),
    para exercitar `servico.listar_fileira_tematica`/`listar_fileiras_tematicas`
    sem rede. `tags_com_erro` simula falha só para as fileiras cujas `chave`
    estão no conjunto — as demais respondem normalmente."""

    def __init__(self, nome: str, *, tags_com_erro: frozenset[str] = frozenset()):
        self._nome = nome
        self._tags_com_erro = tags_com_erro

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

    def listar_fileira_tematica(self, fileira: FileiraTematica) -> list[AnimeEmAlta]:
        if fileira.chave in self._tags_com_erro:
            raise requests.ConnectionError(f"falhou: {fileira.chave}")
        return [
            AnimeEmAlta(
                titulo_romaji=fileira.chave,
                titulo_ingles=None,
                capa_url=None,
                banner_url=None,
                anilist_id=None,
            )
        ]


class _ProvedorDeArteFake(ProvedorDeArte):
    """Provedor fake de `ProvedorDeArte` (overlay de banner TMDB,
    PLANO_ARTE_TMDB.md) — instalado via
    `monkeypatch.setattr(registro, "_provedores_de_arte", (fake,))`.
    `chamadas` registra `(titulo, ano)` de cada chamada real (não conta as que
    o latch/memo pouparam) — usado para verificar memo e latch sem espionar
    `buscar_arte_por_titulo` diretamente."""

    def __init__(
        self, nome: str, *, arte: ArteDeAnime | None = None, erro: Exception | None = None
    ):
        self._nome = nome
        self._arte = arte
        self._erro = erro
        self.chamadas: list[tuple[str, int | None]] = []

    @property
    def nome(self) -> str:
        return self._nome

    def buscar_arte_por_titulo(self, titulo: str, ano: int | None) -> ArteDeAnime | None:
        self.chamadas.append((titulo, ano))
        if self._erro is not None:
            raise self._erro
        return self._arte


@pytest.fixture(autouse=True)
def _limpa_caches_de_feed(monkeypatch: pytest.MonkeyPatch):
    """`integrations.servico._cache_em_alta`, `._cache_proxima_temporada` e
    `._cache_fileiras_tematicas` são estado de módulo — isola cada teste para
    não vazar cache de um teste para o outro. `_locks_fileiras_tematicas` não
    precisa ser recriado: são `asyncio.Lock` reusáveis, sempre liberados ao fim
    de cada `async with` (nenhum teste os deixa presos)."""
    monkeypatch.setattr(servico, "_cache_em_alta", None)
    monkeypatch.setattr(servico, "_cache_proxima_temporada", None)
    monkeypatch.setattr(servico, "_cache_fileiras_tematicas", {})


@pytest.fixture(autouse=True)
def _limpa_overlay_de_arte(monkeypatch: pytest.MonkeyPatch):
    """`integrations.servico._memo_arte`/`._memo_temporadas`/`._memo_still` e
    `._arte_desabilitada_por_auth` são estado de módulo (memo/latch dos
    overlays de arte — capa/banner e still de episódio, PLANO_ARTE_TMDB.md D4
    e Fatia 5) — isola cada teste pra não vazar memo/latch de um teste pro
    outro (mesmo cuidado que `conftest.py` já toma com
    `descoberta._refreshs_de_lancamento_em_voo`). `integrations.registro.
    _provedores_de_arte` fica vazio por padrão (D2: nunca lido no import) —
    quem quiser exercitar o overlay faz o próprio
    `monkeypatch.setattr(registro, "_provedores_de_arte", (...))`."""
    monkeypatch.setattr(servico, "_memo_arte", {})
    monkeypatch.setattr(servico, "_memo_temporadas", {})
    monkeypatch.setattr(servico, "_memo_still", {})
    monkeypatch.setattr(servico, "_memo_serie", {})
    monkeypatch.setattr(servico, "_arte_desabilitada_por_auth", False)


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


def test_onda_concorrente_de_falhas_nao_aprofunda_o_degrau_de_backoff():
    """Falhas "irmãs" da mesma onda concorrente (cooldown já ativo, aberto pela
    primeira delas) não incrementam `falhas_consecutivas` — sem esse guard, uma
    Home que dispara N chamadas quase simultâneas pularia os degraus
    15s→60s→300s direto pro cooldown cheio de 900s ao primeiro soluço de rede."""
    servico._registrar_falha_de_provedor("tmdb", requests.ConnectionError("1"))
    estado_apos_primeira = servico._cooldown_por_provedor["tmdb"]
    assert estado_apos_primeira[0] == 1

    for _ in range(5):
        servico._registrar_falha_de_provedor("tmdb", requests.ConnectionError("irmã"))

    assert servico._cooldown_por_provedor["tmdb"] == estado_apos_primeira


def test_sonda_de_meio_aberto_falhando_aprofunda_o_degrau():
    """Depois de o cooldown expirar, uma nova falha (a sonda de meio-aberto) SIM
    aprofunda o degrau — é o único caminho que escala o backoff."""
    servico._registrar_falha_de_provedor("tmdb", requests.ConnectionError("1"))
    falhas, _ = servico._cooldown_por_provedor["tmdb"]
    servico._cooldown_por_provedor["tmdb"] = (falhas, time.monotonic() - 1)

    servico._registrar_falha_de_provedor("tmdb", requests.ConnectionError("2"))

    assert servico._cooldown_por_provedor["tmdb"][0] == 2


async def test_servico_nao_encontrado_em_nenhum_provedor_devolve_none(
    monkeypatch: pytest.MonkeyPatch,
):
    anilist = _ProvedorFake("anilist", metadados=None)
    kitsu = _ProvedorFake("kitsu", metadados=None)
    monkeypatch.setattr(servico, "PROVEDORES", (anilist, kitsu))

    assert await servico.buscar_por_titulo("Slime") is None


async def test_servico_buscar_titulos_usa_so_anilist(monkeypatch: pytest.MonkeyPatch):
    """Caminho feliz do novo contrato: `buscar_titulos` percorre só
    `PROVEDORES_DE_TITULO` (AniList) e devolve o que ela resolveu."""
    esperado = TitulosDeAnime(titulo_romaji="Tensei", titulo_ingles="Reincarnated")
    anilist = _ProvedorFake("anilist", titulos=esperado)
    monkeypatch.setattr(servico, "PROVEDORES_DE_TITULO", (anilist,))

    resultado = await servico.buscar_titulos("Slime")

    assert resultado is esperado


async def test_servico_buscar_titulos_nao_cai_para_kitsu(monkeypatch: pytest.MonkeyPatch):
    """`buscar_titulos` percorre só `PROVEDORES_DE_TITULO` (AniList) — a
    resolução do título canônico da busca em fontes é AniList-only (ver o
    comentário da tupla em `registro.py`). AniList falhando NÃO cai para o
    Kitsu, mesmo que ele resolveria: propaga `FalhaDeMetadados` (todos os
    provedores da tupla de título falharam) para
    `api/servicos/busca.py::_resolver_titulos_canonicos` degradar para o título
    digitado."""
    anilist = _ProvedorFake("anilist", erro=requests.ConnectionError("falhou"))
    kitsu = _ProvedorFake(
        "kitsu", titulos=TitulosDeAnime(titulo_romaji="Tensei", titulo_ingles="Reincarnated")
    )
    monkeypatch.setattr(servico, "PROVEDORES_DE_TITULO", (anilist,))
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


# --- servico.buscar_metadados_por_anilist_id (feature banner na página) ---


async def test_servico_buscar_metadados_por_anilist_id_primeira_resposta_vence(
    monkeypatch: pytest.MonkeyPatch,
):
    esperado = MetadadosDeAnime(
        capa_url="https://img/c.jpg",
        sinopse="s",
        anilist_id=21,
        kitsu_id=None,
        banner_url="https://img/b.jpg",
        capa_cor="#e4a15d",
    )
    anilist = _ProvedorFake("anilist", metadados_por_id=esperado)
    kitsu = _ProvedorFake("kitsu")
    monkeypatch.setattr(servico, "PROVEDORES", (anilist, kitsu))

    assert await servico.buscar_metadados_por_anilist_id(21) is esperado


async def test_servico_buscar_metadados_por_anilist_id_cai_para_o_proximo_em_erro(
    monkeypatch: pytest.MonkeyPatch,
):
    esperado = MetadadosDeAnime(
        capa_url=None, sinopse=None, anilist_id=21, kitsu_id=None, banner_url="https://img/b.jpg"
    )
    falho = _ProvedorFake("anilist", erro=requests.ConnectionError("falhou"))
    ok = _ProvedorFake("outro", metadados_por_id=esperado)
    monkeypatch.setattr(servico, "PROVEDORES", (falho, ok))

    assert await servico.buscar_metadados_por_anilist_id(21) is esperado


async def test_servico_buscar_metadados_por_anilist_id_ninguem_resolve_devolve_none(
    monkeypatch: pytest.MonkeyPatch,
):
    """AniList respondeu sem achar (`None`), Kitsu devolve `None` pela
    implementação padrão — condição normal, não erro: devolve `None`."""
    anilist = _ProvedorFake("anilist", metadados_por_id=None)
    kitsu = _ProvedorFake("kitsu")
    monkeypatch.setattr(servico, "PROVEDORES", (anilist, kitsu))

    assert await servico.buscar_metadados_por_anilist_id(21) is None


async def test_servico_buscar_metadados_por_anilist_id_levanta_se_todos_falham(
    monkeypatch: pytest.MonkeyPatch,
):
    anilist = _ProvedorFake("anilist", erro=requests.ConnectionError("falhou"))
    kitsu = _ProvedorFake("kitsu", erro=requests.HTTPError("HTTP 502"))
    monkeypatch.setattr(servico, "PROVEDORES", (anilist, kitsu))

    with pytest.raises(FalhaDeMetadados):
        await servico.buscar_metadados_por_anilist_id(21)


# --- servico.listar_fileira_tematica / listar_fileiras_tematicas (fileiras temáticas) ---


async def test_servico_fileira_tematica_chave_desconhecida_levanta_value_error():
    with pytest.raises(ValueError):
        await servico.listar_fileira_tematica("chave-que-nao-existe")


async def test_servico_fileira_tematica_usa_cache_dentro_do_ttl(monkeypatch: pytest.MonkeyPatch):
    chamadas = []
    item = AnimeEmAlta(
        titulo_romaji="X", titulo_ingles=None, capa_url=None, banner_url=None, anilist_id=1
    )

    def _listar(fileira):
        chamadas.append(1)
        return [item]

    provedor = _ProvedorComFileirasTematicasFake("anilist")
    provedor.listar_fileira_tematica = _listar
    monkeypatch.setattr(servico, "PROVEDORES", (provedor,))

    primeira = await servico.listar_fileira_tematica("isekai")
    segunda = await servico.listar_fileira_tematica("isekai")

    assert len(chamadas) == 1
    assert primeira == segunda == [item]


async def test_servico_fileira_que_falha_e_omitida_do_agregado(monkeypatch: pytest.MonkeyPatch):
    chave_com_erro = FILEIRAS_TEMATICAS[0].chave
    provedor = _ProvedorComFileirasTematicasFake(
        "anilist", tags_com_erro=frozenset({chave_com_erro})
    )
    monkeypatch.setattr(servico, "PROVEDORES", (provedor,))

    resultado = await servico.listar_fileiras_tematicas()

    assert chave_com_erro not in resultado
    assert set(resultado) == {f.chave for f in FILEIRAS_TEMATICAS} - {chave_com_erro}


async def test_servico_fileiras_tematicas_levanta_falha_de_metadados_quando_todas_falham(
    monkeypatch: pytest.MonkeyPatch,
):
    todas_as_chaves = frozenset(f.chave for f in FILEIRAS_TEMATICAS)
    provedor = _ProvedorComFileirasTematicasFake("anilist", tags_com_erro=todas_as_chaves)
    monkeypatch.setattr(servico, "PROVEDORES", (provedor,))

    with pytest.raises(FalhaDeMetadados):
        await servico.listar_fileiras_tematicas()


# --- overlay de banner (integrations/servico.py, PLANO_ARTE_TMDB.md) ---


async def test_servico_buscar_por_titulo_tmdb_sobrescreve_so_o_banner(
    monkeypatch: pytest.MonkeyPatch,
):
    """O overlay do TMDB sobrescreve `banner_url`; `capa_url` da AniList
    sobrevive intacta — capa não é mais responsabilidade do TMDB/overlay."""
    metadados_anilist = MetadadosDeAnime(
        capa_url="https://anilist/capa.jpg",
        sinopse="s",
        anilist_id=1,
        kitsu_id=None,
        banner_url="https://anilist/banner.jpg",
        titulo_romaji="Slime",
    )
    anilist = _ProvedorFake("anilist", metadados=metadados_anilist)
    monkeypatch.setattr(servico, "PROVEDORES", (anilist,))

    tmdb = _ProvedorDeArteFake("tmdb", arte=ArteDeAnime(banner_url="https://tmdb/banner.jpg"))
    monkeypatch.setattr(registro, "_provedores_de_arte", (tmdb,))

    resultado = await servico.buscar_por_titulo("Slime")

    assert resultado.capa_url == "https://anilist/capa.jpg"
    assert resultado.banner_url == "https://tmdb/banner.jpg"


async def test_servico_tmdb_sem_backdrop_preserva_banner_da_anilist(
    monkeypatch: pytest.MonkeyPatch,
):
    """Um resultado do TMDB sem backdrop (`banner_url=None`) não pode zerar o
    `bannerImage` que a AniList já tinha resolvido."""
    metadados_anilist = MetadadosDeAnime(
        capa_url="https://anilist/capa.jpg",
        sinopse="s",
        anilist_id=1,
        kitsu_id=None,
        banner_url="https://anilist/banner.jpg",
        titulo_romaji="Slime",
    )
    anilist = _ProvedorFake("anilist", metadados=metadados_anilist)
    monkeypatch.setattr(servico, "PROVEDORES", (anilist,))

    tmdb = _ProvedorDeArteFake("tmdb", arte=ArteDeAnime(banner_url=None))
    monkeypatch.setattr(registro, "_provedores_de_arte", (tmdb,))

    resultado = await servico.buscar_por_titulo("Slime")

    assert resultado.capa_url == "https://anilist/capa.jpg"
    assert resultado.banner_url == "https://anilist/banner.jpg"


async def test_servico_provedor_de_arte_que_levanta_nao_derruba_o_feed(
    monkeypatch: pytest.MonkeyPatch,
):
    item = AnimeEmAlta(
        titulo_romaji="Slime",
        titulo_ingles=None,
        capa_url="https://anilist/capa.jpg",
        banner_url="https://anilist/banner.jpg",
        anilist_id=1,
    )
    anilist = _ProvedorFake("anilist", em_alta=[item])
    monkeypatch.setattr(servico, "PROVEDORES_DE_FEED", (anilist,))

    tmdb = _ProvedorDeArteFake("tmdb", erro=requests.ConnectionError("falhou"))
    monkeypatch.setattr(registro, "_provedores_de_arte", (tmdb,))

    resultado = await servico.listar_em_alta()

    assert resultado == [item]


async def test_servico_memo_de_arte_evita_segunda_chamada_pro_mesmo_titulo_e_ano(
    monkeypatch: pytest.MonkeyPatch,
):
    metadados_anilist = MetadadosDeAnime(
        capa_url=None,
        sinopse=None,
        anilist_id=1,
        kitsu_id=None,
        titulo_romaji="Slime",
        ano=2018,
    )
    anilist = _ProvedorFake("anilist", metadados=metadados_anilist)
    monkeypatch.setattr(servico, "PROVEDORES", (anilist,))

    tmdb = _ProvedorDeArteFake("tmdb", arte=ArteDeAnime(banner_url="https://tmdb/banner.jpg"))
    monkeypatch.setattr(registro, "_provedores_de_arte", (tmdb,))

    primeiro = await servico.buscar_por_titulo("Slime")
    segundo = await servico.buscar_por_titulo("Slime")

    assert primeiro.banner_url == segundo.banner_url == "https://tmdb/banner.jpg"
    assert tmdb.chamadas == [("Slime", 2018)]


async def test_servico_latch_desliga_arte_apos_401_pro_resto_do_lote(
    monkeypatch: pytest.MonkeyPatch,
):
    metadados_anilist = MetadadosDeAnime(
        capa_url="https://anilist/capa.jpg",
        sinopse=None,
        anilist_id=1,
        kitsu_id=None,
        banner_url="https://anilist/banner.jpg",
        titulo_romaji="Slime",
    )
    anilist = _ProvedorFake("anilist", metadados=metadados_anilist)
    monkeypatch.setattr(servico, "PROVEDORES", (anilist,))

    tmdb = _ProvedorDeArteFake("tmdb", erro=TmdbNaoAutorizado("token inválido"))
    monkeypatch.setattr(registro, "_provedores_de_arte", (tmdb,))

    primeiro = await servico.buscar_por_titulo("Slime")
    segundo = await servico.buscar_por_titulo("Slime")

    assert primeiro.capa_url == "https://anilist/capa.jpg"
    assert primeiro.banner_url == "https://anilist/banner.jpg"
    assert segundo.banner_url == "https://anilist/banner.jpg"
    assert len(tmdb.chamadas) == 1
    assert servico._arte_desabilitada_por_auth is True


# --- overlay de still de episódio (integrations/servico.py, Fatia 5) ---


async def test_servico_still_de_episodio_nenhum_provedor_devolve_none():
    assert await servico.buscar_still_de_episodio("Slime", 2018, 1) is None


async def test_servico_still_memo_evita_repescar_temporada_pro_proximo_episodio(
    monkeypatch: pytest.MonkeyPatch,
):
    """`_memo_temporadas` evita repetir `/search/tv`+`/tv/{id}` e `_memo_still`
    evita repescar `/tv/{id}/season/{n}` pro 2º episódio da MESMA temporada —
    a 1ª consulta popula o still da temporada inteira de uma vez; a 2ª (outro
    episódio, mesma temporada) e a 3ª (mesmo episódio da 1ª) não disparam
    nenhuma chamada nova."""
    chamadas: list[str] = []

    def _fake_get(url, **kwargs):
        chamadas.append(url)
        if url.endswith("/search/tv"):
            return _RespostaFalsa(
                corpo={"results": [_resultado_tv(id=999, name="Slime", original_name="Slime")]}
            )
        if url.endswith("/tv/999"):
            return _RespostaFalsa(corpo={"seasons": [{"season_number": 1, "episode_count": 12}]})
        if url.endswith("/tv/999/season/1"):
            return _RespostaFalsa(
                corpo={
                    "episodes": [
                        {"episode_number": 1, "still_path": "/ep1.jpg"},
                        {"episode_number": 2, "still_path": "/ep2.jpg"},
                    ]
                }
            )
        raise AssertionError(f"URL não mapeada no fake: {url}")

    monkeypatch.setattr("integrations.tmdb.requests.get", _fake_get)
    monkeypatch.setattr(registro, "_provedores_de_arte", (TmdbProvider("token"),))

    primeiro = await servico.buscar_still_de_episodio("Slime", 2018, 1)
    segundo = await servico.buscar_still_de_episodio("Slime", 2018, 2)
    terceiro = await servico.buscar_still_de_episodio("Slime", 2018, 1)

    assert primeiro == "https://image.tmdb.org/t/p/original/ep1.jpg"
    assert segundo == "https://image.tmdb.org/t/p/original/ep2.jpg"
    assert terceiro == primeiro
    # search/tv + tv/999 + tv/999/season/1 — uma vez cada, nunca mais.
    assert len(chamadas) == 3

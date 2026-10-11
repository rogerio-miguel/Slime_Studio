"""Busca de série no TMDB: se o título inteiro não acha nada, tenta versões mais curtas."""

import pytest

from integrations.tmdb import TmdbProvider, _consultas_de_busca


def test_consultas_comecam_pelo_titulo_inteiro_depois_cortam_o_subtitulo():
    assert _consultas_de_busca("Umayuru: Full Gate!") == ["Umayuru: Full Gate!", "Umayuru"]


def test_consultas_tiram_marcadores_soltos_ate_o_minimo_de_palavras():
    consultas = _consultas_de_busca("Diamond no Ace act II -Second Season-")

    assert consultas == [
        "Diamond no Ace act II -Second Season-",
        "Diamond no Ace act II",
        "Diamond no Ace act",
        "Diamond no Ace",
    ]


def test_consultas_nao_cortam_titulo_com_dois_pontos_colado():
    assert _consultas_de_busca("Re:Zero") == ["Re:Zero"]


class _Resposta:
    status_code = 200

    def __init__(self, corpo):
        self._corpo = corpo

    def json(self):
        return self._corpo

    def raise_for_status(self):
        pass


def test_resolver_serie_para_na_primeira_consulta_com_resultado(monkeypatch: pytest.MonkeyPatch):
    consultas: list[str] = []
    serie = {"id": 9, "name": "Umayuru", "poster_path": "/p.jpg", "popularity": 1.0}

    def _get(url, params=None, **kwargs):
        consultas.append(params["query"])
        achou = params["query"] == "Umayuru"
        return _Resposta({"results": [serie] if achou else []})

    monkeypatch.setattr("integrations.tmdb.requests.get", _get)

    resultado = TmdbProvider("token")._resolver_serie("Umayuru: Full Gate!", 2026)

    assert resultado == serie
    assert consultas == ["Umayuru: Full Gate!", "Umayuru"]


def test_resolver_serie_devolve_none_quando_nenhuma_consulta_acha(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "integrations.tmdb.requests.get", lambda *a, **k: _Resposta({"results": []})
    )

    assert TmdbProvider("token")._resolver_serie("Titulo Que Ninguem Tem Mesmo", 2026) is None

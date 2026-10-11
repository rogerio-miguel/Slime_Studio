"""Backdrop do TMDB com o título desenhado, usado na miniatura de "Acabou de sair"."""

import pytest
import requests

from integrations.tmdb import TmdbProvider


class _Resposta:
    status_code = 200

    def __init__(self, corpo):
        self._corpo = corpo

    def json(self):
        return self._corpo

    def raise_for_status(self):
        pass


def _backdrop(nome: str, *, idioma, nota=0.0, largura=3840) -> dict:
    return {"file_path": f"/{nome}", "iso_639_1": idioma, "vote_average": nota, "width": largura}


def _tmdb_com(monkeypatch: pytest.MonkeyPatch, backdrops: list[dict], chamadas: list[str]):
    def _get(url, **kwargs):
        chamadas.append(url)
        if url.endswith("/search/tv"):
            serie = {
                "id": 7,
                "name": "Slime",
                "original_name": "Slime",
                "first_air_date": "2018-10-02",
                "poster_path": "/poster.jpg",
            }
            return _Resposta({"results": [serie]})
        if url.endswith("/tv/7/images"):
            return _Resposta({"backdrops": backdrops})
        if url.startswith("https://image.tmdb.org"):
            # Medição do backdrop limpo: falha de rede é tratada pelo provider.
            raise requests.ConnectionError("sem rede no teste")
        raise AssertionError(f"URL não mapeada: {url}")

    monkeypatch.setattr("integrations.tmdb.requests.get", _get)
    return TmdbProvider("token")


def test_prefere_pt_depois_en_e_ignora_arte_limpa(monkeypatch: pytest.MonkeyPatch):
    backdrops = [
        _backdrop("en-top", idioma="en", nota=9.0),
        _backdrop("pt", idioma="pt", nota=1.0),
        _backdrop("limpo", idioma=None, nota=10.0),
    ]
    tmdb = _tmdb_com(monkeypatch, backdrops, [])

    arte = tmdb.buscar_arte_por_titulo("Slime", 2018)

    assert arte is not None
    assert arte.banner_com_titulo_url == "https://image.tmdb.org/t/p/w780/pt"
    assert arte.banner_url == "https://image.tmdb.org/t/p/original/limpo"


def test_sem_arte_com_titulo_fica_vazio_e_images_e_chamado_uma_vez(
    monkeypatch: pytest.MonkeyPatch,
):
    chamadas: list[str] = []
    tmdb = _tmdb_com(monkeypatch, [_backdrop("limpo", idioma=None)], chamadas)

    arte = tmdb.buscar_arte_por_titulo("Slime", 2018)

    assert arte is not None
    assert arte.banner_com_titulo_url is None
    assert sum(url.endswith("/tv/7/images") for url in chamadas) == 1


def test_aceita_qualquer_idioma_quando_nao_ha_pt_nem_en(monkeypatch: pytest.MonkeyPatch):
    backdrops = [
        _backdrop("ko", idioma="ko", nota=9.0),
        _backdrop("ja-fraco", idioma="ja", nota=1.0),
        _backdrop("limpo", idioma=None, nota=10.0),
    ]
    tmdb = _tmdb_com(monkeypatch, backdrops, [])

    arte = tmdb.buscar_arte_por_titulo("Slime", 2018)

    assert arte is not None
    assert arte.banner_com_titulo_url == "https://image.tmdb.org/t/p/w780/ja-fraco"


def test_idioma_fora_da_prioridade_vence_so_sozinho(monkeypatch: pytest.MonkeyPatch):
    tmdb = _tmdb_com(monkeypatch, [_backdrop("ko", idioma="ko")], [])

    arte = tmdb.buscar_arte_por_titulo("Slime", 2018)

    assert arte is not None
    assert arte.banner_com_titulo_url == "https://image.tmdb.org/t/p/w780/ko"

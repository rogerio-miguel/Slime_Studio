"""Smoke test por scraper (ESPECIFICACAO.md §7) — verifica periodicamente se cada
extrator ainda consegue localizar o link de um episódio real, sem esperar até um
job falhar em produção pra descobrir que o site mudou.

`@pytest.mark.rede`: toca rede real de propósito — desselecionado por padrão
(`addopts = ["-m", "not rede"]`, `pyproject.toml`). É diagnóstico manual, não gate
de CI.

Título de referência do AnimeFire: "One Piece" (`one-piece`) — série longa em
exibição, baixo risco de sumir do catálogo e virar fixture instável.
"""

import pytest

from extractors.animefire import AnimeFireProvider
from extractors.cliente import ClienteLeve

pytestmark = pytest.mark.rede

_IDENTIFICADOR_REFERENCIA = "one-piece"


def test_animefire_localiza_link_de_um_episodio_real():
    provider = AnimeFireProvider()
    cliente = ClienteLeve()

    resultados = provider.buscar(cliente, "One Piece")
    assert any(r.identificador == _IDENTIFICADOR_REFERENCIA for r in resultados)

    episodios = provider.listar_episodios(cliente, _IDENTIFICADOR_REFERENCIA)
    assert len(episodios) > 1000
    assert episodios[0].numero == 1  # mais antigo primeiro

    midia = provider.resolver_midia(cliente, episodios[0].url)
    assert midia.url
    assert "Referer" in midia.cabecalhos

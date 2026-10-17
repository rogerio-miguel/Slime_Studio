"""Testes de `fontes/adaptadores/versao.py` — domínio puro, sem rede/fixture."""

from core.enums import VersaoEpisodio
from fontes.adaptadores.versao import inferir_versao


def test_marcador_dublado_no_slug_devolve_dublado():
    versao = inferir_versao(
        "Tensei Shitara Slime Datta Ken", "tensei-shitara-slime-datta-ken-dublado"
    )

    assert versao == VersaoEpisodio.DUBLADO


def test_marcador_dublado_no_titulo_devolve_dublado():
    versao = inferir_versao("Tensei Shitara Slime Datta Ken Dublado", "tensei-shitara-slime")

    assert versao == VersaoEpisodio.DUBLADO


def test_marcador_legendado_explicito_devolve_legendado():
    versao = inferir_versao("One Piece Legendado", "one-piece-legendado-todos-os-episodios")

    assert versao == VersaoEpisodio.LEGENDADO


def test_sem_marcador_devolve_none():
    versao = inferir_versao("Tensei Shitara Slime Datta Ken", "tensei-shitara-slime-datta-ken")

    assert versao is None


def test_falso_positivo_de_substring_evitado():
    """`Legend` contém `leg` como substring, mas não é o marcador `leg` isolado
    por fronteira de token — não pode casar com legendado."""
    versao = inferir_versao("Legend of the Galactic Heroes", "legend-of-the-galactic-heroes")

    assert versao is None

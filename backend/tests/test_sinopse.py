"""Regra de escolha de sinopse (`core/sinopse.py`) — pura, sem I/O."""

import pytest

from core.sinopse import eh_generica, eh_primeira_temporada, escolher_sinopse

_ESPECIFICA = "Rimuru has officially become a Demon Lord after defeating Clayman. " * 3


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        (None, True),
        ("The third season of Sousou no Frieren.", True),
        ("  Second season of Aishen Qiaokeli.  ", True),
        (
            "Masamune and Adagaki return for more romantic antics, this time on a school trip.",
            False,
        ),
    ],
)
def test_eh_generica(texto, esperado):
    assert eh_generica(texto) is esperado


@pytest.mark.parametrize(
    ("ano_serie", "ano_item", "esperado"),
    [
        (2018, 2018, True),
        (2018, 2019, True),
        (2018, 2026, False),
        (None, 2026, False),
        (2018, None, False),
    ],
)
def test_eh_primeira_temporada(ano_serie, ano_item, esperado):
    assert eh_primeira_temporada(ano_serie, ano_item) is esperado


def test_primeira_temporada_usa_a_da_serie_mesmo_com_texto_especifico():
    assert (
        escolher_sinopse(_ESPECIFICA, serie_ptbr="Premissa", primeira_temporada=True) == "Premissa"
    )


def test_continuacao_especifica_mantem_o_original():
    assert (
        escolher_sinopse(_ESPECIFICA, serie_ptbr="Premissa", primeira_temporada=False)
        == _ESPECIFICA
    )


def test_continuacao_generica_recebe_a_da_serie():
    assert (
        escolher_sinopse("The second season of X.", serie_ptbr="Premissa", primeira_temporada=False)
        == "Premissa"
    )


def test_continuacao_prefere_a_da_temporada_a_qualquer_outra():
    assert (
        escolher_sinopse(
            _ESPECIFICA,
            serie_ptbr="Premissa",
            temporada_ptbr="Da temporada",
            primeira_temporada=False,
        )
        == "Da temporada"
    )


def test_sem_traducao_do_tmdb_mantem_o_original():
    assert escolher_sinopse(
        "The second season of X.", serie_ptbr=None, primeira_temporada=False
    ) == ("The second season of X.")
    assert escolher_sinopse(_ESPECIFICA, serie_ptbr=None, primeira_temporada=True) == _ESPECIFICA


def test_nunca_cria_sinopse_onde_nao_havia():
    assert escolher_sinopse(None, serie_ptbr="Premissa", primeira_temporada=True) is None

"""`core/franquia.py::slug_de_franquia` — chave que une as temporadas de uma franquia."""

import pytest

from core.franquia import slug_de_franquia


@pytest.mark.parametrize(
    ("titulo", "slug"),
    [
        ("Overlord IV", "overlord"),
        ("Sousou no Frieren 2nd Season", "sousou-no-frieren"),
        ("Kakegurui ××", "kakegurui"),
        ("Go-toubun no Hanayome ∬", "go-toubun-no-hanayome"),
        ("Magical★Explorer", "magical-explorer"),
        ("★★", ""),
    ],
)
def test_slug_de_franquia_ignora_marcador_de_temporada_e_simbolo_final(titulo, slug):
    assert slug_de_franquia(titulo) == slug


def test_temporadas_de_kakegurui_caem_na_mesma_franquia_sem_depender_da_ancora():
    assert slug_de_franquia("Kakegurui") == slug_de_franquia("Kakegurui ××")

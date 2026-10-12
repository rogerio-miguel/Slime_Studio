"""`core/texto.py::slugificar` — o normalizador único de títulos: slug gravado no
banco, termo de busca do AnimeFire e base da chave de comparação de cards."""

import pytest

from core.texto import sem_simbolo_final, slugificar, termo_de_consulta


@pytest.mark.parametrize(
    ("titulo", "esperado"),
    [
        ("Tensei Shitara Slime Datta Ken 2", "tensei-shitara-slime-datta-ken-2"),
        ("Re:Zero", "re-zero"),
        ("Fate/stay night", "fate-stay-night"),
        ("K-ON!!", "k-on"),
        ("Dr. STONE", "dr-stone"),
        ("Mob Psycho 100", "mob-psycho-100"),
        ("Komi Can't Communicate", "komi-can-t-communicate"),
    ],
)
def test_titulo_ascii_mantem_o_slug_de_sempre(titulo, esperado):
    """O slug é gravado em `Anime.slug`: mudar o de um título ASCII orfanaria a linha."""
    assert slugificar(titulo) == esperado


@pytest.mark.parametrize(
    ("titulo", "esperado"),
    [
        ("Sūgū", "sugu"),
        ("Ōkami", "okami"),
        ("Shōwa Genroku Rakugo Shinjū", "showa-genroku-rakugo-shinju"),
        ("Otome Kaijuu Caraméliser", "otome-kaijuu-carameliser"),
    ],
)
def test_letra_acentuada_perde_so_o_acento(titulo, esperado):
    assert slugificar(titulo) == esperado


@pytest.mark.parametrize(
    ("titulo", "esperado"),
    [
        ("Bjørn", "bjorn"),
        ("ÆON", "aeon"),
        ("Straße", "strasse"),
        ("Łódź", "lodz"),
    ],
)
def test_letra_sem_decomposicao_unicode_e_transliterada(titulo, esperado):
    """NFKD não decompõe `ø`/`æ`/`ß`/`ł`; sem a tabela elas sumiam ("bjrn", "on")."""
    assert slugificar(titulo) == esperado


@pytest.mark.parametrize(
    ("titulo", "esperado"),
    [
        ("Hunter × Hunter", "hunter-x-hunter"),
        ("Kakegurui ××", "kakegurui-xx"),
    ],
)
def test_sinal_de_multiplicacao_vira_x(titulo, esperado):
    """O site grafa "Hunter x Hunter"; `×` descartado dava "hunter-hunter"."""
    assert slugificar(titulo) == esperado


@pytest.mark.parametrize(
    ("titulo", "esperado"),
    [
        ("Magical★Explorer", "magical-explorer"),
        ("Gintama°", "gintama"),
        ("Yofukashi no Uta ♪", "yofukashi-no-uta"),
        ("Go-toubun no Hanayome ∬", "go-toubun-no-hanayome"),
        ("Planetes ½", "planetes-1-2"),
    ],
)
def test_simbolo_separa_palavras_em_vez_de_cola_las(titulo, esperado):
    assert slugificar(titulo) == esperado


@pytest.mark.parametrize("apostrofo", ["’", "‘", "ʼ", "′"])
def test_apostrofo_tipografico_equivale_ao_ascii(apostrofo):
    """A AniList entrega "Can’t"; o título digitado ou o site usa "Can't"."""
    assert slugificar(f"Komi Can{apostrofo}t Communicate") == slugificar(
        "Komi Can't Communicate"
    )


def test_numeral_romano_unicode_vira_letras_ascii():
    assert slugificar("Overlord Ⅳ") == "overlord-iv"


@pytest.mark.parametrize("titulo", ["進撃の巨人", "★☆", "", "   "])
def test_titulo_sem_nenhum_caractere_aproveitavel_vira_vazio(titulo):
    """Vazio é o sinal que o chamador usa pra "sem chave de comparação"."""
    assert slugificar(titulo) == ""


def test_kanji_junto_de_romaji_preserva_o_romaji():
    assert slugificar("Shingeki no Kyojin 進撃の巨人") == "shingeki-no-kyojin"


@pytest.mark.parametrize(
    ("termo", "esperado"),
    [
        ("Tensei Shitara Slime", "Tensei Shitara Slime"),
        ("dogul-wang", "dogul wang"),
        ("Magical★Explorer", "Magical Explorer"),
        ("Hunter × Hunter", "Hunter x Hunter"),
        ("Komi Can’t Communicate", "Komi Can't Communicate"),
        ("Kakegurui ××", "Kakegurui xx"),
        ("Sūgū Chouso: 「Torikae」", "Sūgū Chouso: Torikae"),
        ("Re:Zero", "Re:Zero"),
    ],
)
def test_termo_de_consulta_limpa_simbolo_e_preserva_letras(termo, esperado):
    assert termo_de_consulta(termo) == esperado


@pytest.mark.parametrize(
    ("titulo", "base"),
    [
        ("Kakegurui ××", "Kakegurui"),
        ("Go-toubun no Hanayome ∬", "Go-toubun no Hanayome"),
        ("Gintama°", "Gintama°"),
        ("Magical★Explorer", "Magical★Explorer"),
        ("Hunter × Hunter", "Hunter × Hunter"),
        ("Anime +", "Anime +"),
        ("★★", "★★"),
    ],
)
def test_sem_simbolo_final_so_tira_palavra_solta_de_simbolo(titulo, base):
    assert sem_simbolo_final(titulo) == base

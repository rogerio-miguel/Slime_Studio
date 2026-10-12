"""Helpers puros de `api/servicos/titulos_canonicos.py` (referências de validação e
escada de termos de busca a partir dos nomes canônicos do anime). Cobertura direta
além da indireta por `buscar_em_todas_as_fontes_com_titulos_alternativos`: o caso de
borda de cada um (kanji vazio, dedupe por slug, `titulos is None`) fica mais legível
isolado."""

from api.servicos import titulos_canonicos
from fontes.busca.termos import variantes_de_busca
from integrations.base import TitulosDeAnime


def test_referencias_de_anime_ordem_digitado_primeiro_depois_campos_do_provedor():
    titulos = TitulosDeAnime(
        titulo_romaji="Tensei Shitara Slime Datta Ken",
        titulo_ingles="That Time I Got Reincarnated as a Slime",
        titulo_nativo="転生したらスライムだった件",
        sinonimos=("TenSura", "Regarding Reincarnated to Slime"),
    )

    referencias = titulos_canonicos.referencias_de_anime(titulos, "Slime")

    # `titulo` na frente; romaji, inglês e cada sinônimo na ordem; o nativo em
    # kanji slugifica pra vazio e sai.
    assert referencias == [
        "Slime",
        "Tensei Shitara Slime Datta Ken",
        "That Time I Got Reincarnated as a Slime",
        "TenSura",
        "Regarding Reincarnated to Slime",
    ]


def test_referencias_de_anime_dedupe_por_slug_ignora_caixa_e_pontuacao():
    titulos = TitulosDeAnime(
        titulo_romaji="Re:Zero kara Hajimeru Isekai Seikatsu",
        titulo_ingles="Re Zero kara Hajimeru Isekai Seikatsu",
        sinonimos=("Tomb Raider King",),
    )

    referencias = titulos_canonicos.referencias_de_anime(
        titulos, "re:zero kara hajimeru isekai seikatsu"
    )

    # digitado (caixa baixa), romaji (com ":") e inglês (com espaço) slugificam
    # todos pra "re-zero-kara-hajimeru-isekai-seikatsu" — colapsam; só o
    # sinônimo distinto sobra.
    assert referencias == [
        "re:zero kara hajimeru isekai seikatsu",
        "Tomb Raider King",
    ]


def test_referencias_de_anime_descarta_none_e_string_em_branco():
    titulos = TitulosDeAnime(
        titulo_romaji=None,
        titulo_ingles="   ",
        titulo_nativo=None,
        sinonimos=("", "Blue Lock"),
    )

    referencias = titulos_canonicos.referencias_de_anime(titulos, "Aoki")

    assert referencias == ["Aoki", "Blue Lock"]


def test_referencias_de_anime_titulos_none_devolve_so_o_digitado():
    assert titulos_canonicos.referencias_de_anime(None, "Naruto") == ["Naruto"]


def test_referencias_de_anime_mantem_digitado_mesmo_quando_slugifica_pra_vazio():
    titulos = TitulosDeAnime(titulo_romaji="Sono Bisque Doll", titulo_ingles=None)

    referencias = titulos_canonicos.referencias_de_anime(titulos, "着せ替え人形")

    # kanji digitado slugifica pra vazio, mas é a âncora — fica na posição 0
    # (`corresponde_a_alguma_referencia` degrada pra aceitar referência sem
    # chave); o romaji entra normalmente.
    assert referencias == ["着せ替え人形", "Sono Bisque Doll"]


def test_termos_de_busca_titulos_none_cai_em_variantes_de_busca():
    assert titulos_canonicos.termos_de_busca(None, "Kimetsu no Yaiba") == variantes_de_busca(
        "Kimetsu no Yaiba"
    )


def test_termos_de_busca_ordem_romaji_antes_de_ingles_antes_do_digitado():
    titulos = TitulosDeAnime(
        titulo_romaji="Shingeki no Kyojin",
        titulo_ingles="Attack on Titan",
    )

    termos = titulos_canonicos.termos_de_busca(titulos, "AoT")

    assert termos[0] == "Shingeki no Kyojin"
    assert (
        termos.index("Shingeki no Kyojin")
        < termos.index("Attack on Titan")
        < termos.index("AoT")
    )


def test_termos_de_busca_dedupe_entre_escadas_por_slug():
    titulos = TitulosDeAnime(titulo_romaji="Naruto", titulo_ingles="Naruto")

    termos = titulos_canonicos.termos_de_busca(titulos, "Naruto")

    # romaji, inglês e digitado slugificam igual — a escada do romaji sobra só.
    assert termos == ["Naruto"]


def test_termos_de_busca_ignora_nativo_e_sinonimos():
    titulos = TitulosDeAnime(
        titulo_romaji="Bocchi the Rock",
        titulo_ingles=None,
        titulo_nativo="ぼっち・ざ・ろっく",
        sinonimos=("BtR", "Kessoku Band"),
    )

    termos = titulos_canonicos.termos_de_busca(titulos, "Bocchi the Rock")

    # inglês None e digitado == romaji (colapsa): sobra exatamente a escada do
    # romaji — nativo e sinônimos não contribuem termo nenhum.
    assert termos == variantes_de_busca("Bocchi the Rock")


def test_termos_de_busca_nunca_vazia_quando_so_o_digitado_e_util():
    titulos = TitulosDeAnime(titulo_romaji=None, titulo_ingles=None)

    termos = titulos_canonicos.termos_de_busca(titulos, "One Piece")

    assert termos == variantes_de_busca("One Piece")

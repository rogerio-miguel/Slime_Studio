"""Testes de `extractors/nomes.py::variantes_de_busca` — domínio puro, sem
rede. `PLANO_PADRONIZACAO_FONTES.md` D-A1/D-A2/D-A3/D-A6."""

import pytest

from extractors.nomes import variantes_de_busca


def test_titulo_simples_sem_tratamento_nenhum_devolve_so_o_titulo():
    assert variantes_de_busca("Naruto") == ["Naruto"]


def test_dois_pontos_colado_ao_texto_nao_e_tratado_como_subtitulo():
    """":" sem espaço nenhum ao redor é parte do título (ex: "Re:Zero"), não
    separador de subtítulo — tratar como separador truncaria pra um prefixo
    curto demais ("Re") e arriscaria casar o card de outro anime por
    prefix-match em sites com busca por prefixo."""
    assert variantes_de_busca("Re:Zero") == ["Re:Zero"]


def test_hifen_interno_de_palavra_composta_nao_e_cortado():
    """Hífen sem espaço em nenhum dos lados é parte da palavra (ex.
    "Keishou-sen"), não separador de subtítulo."""
    assert variantes_de_busca("Keishou-sen") == ["Keishou-sen"]


@pytest.mark.parametrize(
    ("titulo", "esperado"),
    [
        ("One Piece: A Grande Era Pirata", "One Piece"),
        ("Anime - Subtítulo", "Anime"),
    ],
)
def test_corte_de_subtitulo_inclui_o_titulo_principal(titulo, esperado):
    assert esperado in variantes_de_busca(titulo)


@pytest.mark.parametrize(
    ("titulo", "esperado"),
    [
        ("Anime 2nd Season", "Anime"),
        ("Anime Season 2", "Anime"),
        ("Anime Part 2", "Anime"),
        ("Anime (TV)", "Anime"),
        ("Anime (2024)", "Anime"),
    ],
)
def test_reducao_de_temporada_ou_parte_inclui_o_titulo_base(titulo, esperado):
    assert esperado in variantes_de_busca(titulo)


def test_marcadores_de_temporada_e_parte_empilhados_removem_os_dois():
    """Padrão comum de shonen longo fatiado em cours ("Season 3 Part 2") tem
    dois marcadores no fim — o regex é ancorado em fim de string, então um
    único `.sub()` só alcançaria o mais à direita ("Part 2"), deixando
    "Season 3" sobrando. `_remover_marcadores_temporada_parte` tem que
    descascar os dois, não só o último."""
    assert "Shingeki no Kyojin" in variantes_de_busca("Shingeki no Kyojin Season 3 Part 2")


def test_fronteira_de_token_nao_corta_ii_de_dentro_de_outra_palavra():
    """"Torii" termina em "ii" mas não é marcador de temporada — o corte de
    "II"/"III" exige espaço antes do marcador (fronteira de token), não
    substring solta de dentro de outra palavra."""
    assert variantes_de_busca("Anime Torii") == ["Anime Torii"]


def test_dedup_nao_gera_candidato_redundante_quando_marcador_ja_saiu_com_subtitulo():
    """"Part 2" some inteiro junto do subtítulo descartado no corte por
    hífen — a redução de temporada/parte só é aplicada sobre o título já
    cortado (que não tem mais marcador nenhum), nunca também sobre o
    original, senão haveria um candidato redundante (`"Nome -"`, mesmo slug
    de `"Nome"`) a mais na lista."""
    assert variantes_de_busca("Nome - Part 2") == ["Nome - Part 2", "Nome"]


def test_titulo_que_slugifica_para_vazio_nunca_devolve_lista_vazia():
    assert variantes_de_busca("本") == ["本"]


def test_ordem_e_sempre_titulo_original_primeiro_travando_a_lista_inteira():
    """Encadeia os dois tratamentos (corte de subtítulo, depois redução de
    temporada/parte sobre o resultado já cortado) — asserta a lista inteira,
    não só `in`, pra travar a ordem."""
    assert variantes_de_busca("Nome 2nd Season: Extra") == [
        "Nome 2nd Season: Extra",
        "Nome 2nd Season",
        "Nome",
    ]

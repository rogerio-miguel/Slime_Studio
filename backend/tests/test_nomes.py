"""Testes de `extractors/nomes.py` — domínio puro, sem rede.
`PLANO_PADRONIZACAO_FONTES.md` D-A1/D-A2/D-A3/D-A6 (`variantes_de_busca`) e
Fatia 1 do plano de correspondência de card (`corresponde_ao_titulo`)."""

import pytest

from extractors.nomes import corresponde_ao_titulo, variantes_de_busca


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


def test_prefixo_decrescente_cobre_palavra_divergente_no_meio_do_titulo():
    """Bug real (2026-08-25, job 35): título salvo usa romaji Hepburn
    separado ("de wa"), mas o slug do AnimeFire contrai pra "dewa" — busca
    pelo título completo falha, mas o prefixo antes da palavra divergente
    casa. Corte de subtítulo/temporada não resolve porque a divergência não
    está no fim do título — por isso o prefixo decrescente entra depois dos
    dois, sobre o candidato já mais cortado."""
    titulo = "Futsutsuka na Akujo de wa Gozaimasu ga"
    variantes = variantes_de_busca(titulo)
    assert variantes[0] == titulo
    assert "Futsutsuka na Akujo" in variantes
    # mais específico (mais palavras) tentado antes do mais curto
    assert variantes.index("Futsutsuka na Akujo de") < variantes.index("Futsutsuka na Akujo")


def test_prefixo_decrescente_para_no_minimo_de_duas_palavras():
    """Abaixo de 2 palavras o termo vira comum demais (risco de prefix-match
    com outro anime) — não desce até 1 palavra."""
    variantes = variantes_de_busca("Um Dois Tres Quatro")
    assert "Um Dois" in variantes
    assert "Um" not in variantes


def test_prefixo_decrescente_nao_ativa_pra_titulo_curto():
    """Título de 1-2 palavras não gera prefixo nenhum — `_MINIMO_PALAVRAS_PREFIXO`
    já é o próprio título, não haveria o que cortar de novo."""
    assert variantes_de_busca("Naruto") == ["Naruto"]
    assert variantes_de_busca("Anime Torii") == ["Anime Torii"]


def test_prefixo_decrescente_respeita_teto_de_variantes_em_titulo_longo():
    """Cada variante é 1 request real por site (`extractors/servico.py`), sem
    teto de tempo de lote como a Fase 2 de `api/servicos/busca.py` tem — um
    título muito longo não pode multiplicar o número de requests sem limite."""
    titulo = "Um Dois Tres Quatro Cinco Seis Sete Oito Nove Dez"  # 10 palavras
    variantes = variantes_de_busca(titulo)
    # título original + até `_MAXIMO_PREFIXOS` prefixos, nunca mais
    assert len(variantes) <= 1 + 5
    assert "Um Dois" not in variantes  # ficaria fora do teto antes de chegar no piso


_REFERENCIA_COM_SUBTITULO = (
    "Futsutsuka na Akujo de wa Gozaimasu ga: Suuguu Chouso Torikae Den"
)


@pytest.mark.parametrize(
    ("referencia", "candidato"),
    [
        (_REFERENCIA_COM_SUBTITULO, "Futsutsuka na Akujo dewa Gozaimasu ga"),
        (
            _REFERENCIA_COM_SUBTITULO,
            "Futsutsuka na Akujo dewa Gozaimasu ga: Sūgū Chōso Torikae Den",
        ),
        ("One Piece", "One Piece (Dublado)"),
    ],
)
def test_corresponde_ao_titulo_aceita_card_truncado_ou_com_marcador_de_versao(
    referencia, candidato
):
    """Card de site de busca costuma vir truncado antes do subtítulo, com
    contração romaji diferente da grafia Hepburn separada ("dewa" vs "de
    wa"), com macron em vez de vogal dobrada ("Sūgū" vs "Suuguu"), ou com
    marcador de versão colado ("(Dublado)") — nenhum desses casos pode
    reprovar um card que é genuinamente o mesmo anime."""
    assert corresponde_ao_titulo(referencia, candidato) is True


def test_corresponde_ao_titulo_vale_nos_dois_sentidos_de_prefixo():
    """A relação é `ref.startswith(cand) or cand.startswith(ref)` — vale
    tanto quando o candidato é o prefixo da referência (card truncado)
    quanto quando a referência é o prefixo do candidato (referência salva
    truncada, card do site com o título completo)."""
    referencia = "One Piece"
    candidato = "One Piece (Dublado)"
    assert corresponde_ao_titulo(referencia, candidato) is True
    assert corresponde_ao_titulo(candidato, referencia) is True


def test_corresponde_ao_titulo_rejeita_card_que_so_compartilha_prefixo_curto():
    """"Futsutsuka na" sozinho é um prefixo comum demais — um card de anime
    genuinamente diferente que só compartilha esse começo não pode passar
    como se fosse o mesmo título (falso-positivo de busca por prefixo, ver
    `_prefixos_decrescentes`)."""
    candidato_de_outro_anime = "Futsutsuka na Akademi de Mahou wo Narau Ken"
    assert corresponde_ao_titulo(_REFERENCIA_COM_SUBTITULO, candidato_de_outro_anime) is False


def test_corresponde_ao_titulo_sem_base_de_comparacao_na_referencia_degrada_pra_aceitar():
    """Título só com caracteres que `slugificar` não preserva (ex. kanji sem
    romanização) não dá chave nenhuma pra comparar — sem base pra rejeitar,
    degrada pra aceitar."""
    assert corresponde_ao_titulo("本", "Qualquer Card Candidato") is True


def test_corresponde_ao_titulo_candidato_sem_base_mas_referencia_valida_rejeita():
    """Referência tem chave normal, mas o candidato não tem nenhuma — não há
    como validar a correspondência, e aqui a falta de base é do lado que
    está sendo checado, não do lado de referência: rejeita."""
    assert corresponde_ao_titulo("One Piece", "本") is False


def test_corresponde_ao_titulo_strings_vazias_ou_so_espaco_degradam_pra_aceitar():
    """Sem chave dos dois lados — a checagem de `referencia` vem primeiro e
    já não tem base pra rejeitar."""
    assert corresponde_ao_titulo("", "") is True
    assert corresponde_ao_titulo("   ", "   ") is True

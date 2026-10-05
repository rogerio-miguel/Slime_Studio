"""Testes de `extractors/busca/termos.py` e `extractors/busca/correspondencia.py`
— domínio puro, sem rede. `PLANO_PADRONIZACAO_FONTES.md` D-A1/D-A2/D-A3/D-A6
(`variantes_de_busca`) e plano de correspondência de card
(`corresponde_a_alguma_referencia`, validação contra vários nomes do anime)."""

import pytest

from core.texto import slugificar
from extractors.busca.correspondencia import (
    corresponde_a_alguma_referencia,
    proximidade_a_referencias,
)
from extractors.busca.termos import variantes_de_busca


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
    substring solta de dentro de outra palavra. O bloco de recall gera "Anime"
    (1ª palavra), mas "Torii" nunca aparece cortado no meio."""
    assert variantes_de_busca("Anime Torii") == ["Anime Torii", "Anime"]


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


def test_prefixo_crescente_cobre_palavra_divergente_no_meio_do_titulo():
    """Bug real (2026-08-25, job 35): título salvo usa romaji Hepburn
    separado ("de wa"), mas o slug do AnimeFire contrai pra "dewa" — busca
    pelo título completo falha, mas um prefixo que para antes da palavra
    divergente casa. Corte de subtítulo/temporada não resolve porque a
    divergência não está no fim do título — por isso os prefixos crescentes
    entram depois dos dois, sobre o candidato já mais cortado."""
    titulo = "Futsutsuka na Akujo de wa Gozaimasu ga"
    variantes = variantes_de_busca(titulo)
    assert variantes[0] == titulo
    assert "Futsutsuka na Akujo" in variantes  # prefixo que para antes de "de wa"
    # ordem crescente: prefixo mais curto tentado antes do mais longo
    assert variantes.index("Futsutsuka na") < variantes.index("Futsutsuka na Akujo")


def test_prefixo_crescente_pula_prefixo_curto_demais():
    """Piso por caractere, não por nº de palavras: a 1ª palavra "Um" (slug
    "um", 2 chars < 3) fica fora da escada — termo curto demais casaria o card
    de outro anime por prefix-match. Prefixos com slug de 3+ chars entram."""
    variantes = variantes_de_busca("Um Dois Tres Quatro")
    assert "Um" not in variantes
    assert "Um Dois" in variantes
    assert "Um Dois Tres" in variantes


def test_prefixo_crescente_nao_ativa_pra_titulo_de_uma_palavra():
    """Título de 1 palavra não gera prefixo nenhum (`_prefixos_crescentes`
    exige 2+ palavras). Título de 2 palavras gera exatamente o prefixo da 1ª
    palavra."""
    assert variantes_de_busca("Naruto") == ["Naruto"]
    assert variantes_de_busca("Anime Torii") == ["Anime Torii", "Anime"]


def test_prefixo_crescente_respeita_teto_de_variantes_em_titulo_longo():
    """Cada variante é 1 request real por site (`extractors/busca/servico.py`), sem
    teto de tempo de lote — um
    título muito longo não pode multiplicar o número de requests sem limite."""
    titulo = "Um Dois Tres Quatro Cinco Seis Sete Oito Nove Dez"  # 10 palavras
    variantes = variantes_de_busca(titulo)
    # título original + até `_MAXIMO_PREFIXOS` (3) prefixos, nunca mais
    assert len(variantes) <= 1 + 3
    assert "Um Dois" in variantes  # escada crescente inclui os prefixos curtos
    assert "Um Dois Tres Quatro" not in variantes  # 4º prefixo passa do teto de 3


def test_lista_completa_trava_os_dois_blocos_e_o_teto_de_tres():
    """Título de 7 palavras sem subtítulo nem marcador de temporada: bloco de
    precisão é só a sonda 0, bloco de recall gera os 3 primeiros prefixos.
    Trava a ordem (não monotônica em tamanho) e o teto de 3."""
    assert variantes_de_busca("Futsutsuka na Akujo de wa Gozaimasu ga") == [
        "Futsutsuka na Akujo de wa Gozaimasu ga",
        "Futsutsuka",
        "Futsutsuka na",
        "Futsutsuka na Akujo",
    ]


def test_lista_completa_interacao_marcador_de_temporada_com_recall():
    """"Season 3 Part 2" some no bloco de precisão (dois marcadores
    empilhados) e o bloco de recall roda sobre "Shingeki no Kyojin" já
    reduzido, não sobre o título original."""
    assert variantes_de_busca("Shingeki no Kyojin Season 3 Part 2") == [
        "Shingeki no Kyojin Season 3 Part 2",
        "Shingeki no Kyojin",
        "Shingeki",
        "Shingeki no",
    ]


def test_grafia_colada_no_site_vira_busca_pela_primeira_palavra():
    """Título local com espaço ("Dogul Wang") e site que grafa colado
    ("Dogulwang"): a busca pela 1ª palavra ("Dogul", slug de 5 chars) é o que
    faz o card aparecer — `corresponde_a_alguma_referencia` valida depois por
    chave normalizada."""
    assert variantes_de_busca("Dogul Wang") == ["Dogul Wang", "Dogul"]


def test_pontuacao_de_borda_nao_vaza_para_cortes_e_prefixos():
    """Romaji longo cujo `_REGEX_SEPARADOR_SUBTITULO` corta em ".: " deixando o
    ponto final colado no fim do principal — antes, o corte e os prefixos
    herdavam o ponto e a querystring do site ia com pontuação literal
    (confirmado ao vivo: "?s=...Chikaimashita.:..." devolve 0, o card existe).
    A posição 0 continua crua (contrato); os derivados saem aparados, e um
    deles slugifica para um prefixo do slug real do card."""
    titulo = (
        "Buchigire Reijou wa Houfuku wo Chikaimashita.: "
        "Madousho no Chikara de Sokoku wo Tataki Tsubushimasu"
    )
    variantes = variantes_de_busca(titulo)

    assert variantes[0] == titulo  # posição 0 exata
    assert all("." not in v and ":" not in v for v in variantes[1:])
    assert "Buchigire Reijou wa Houfuku wo Chikaimashita" in variantes

    slug_do_card = (
        "buchigire-reijou-wa-houfuku-wo-chikaimashita-madousho-no-chikara-"
        "de-sokoku-wo-tatakitsubushimasu"
    )
    # o título cru slugificado NÃO casa (contração "tatakitsubushimasu"), mas
    # algum termo aparado é um prefixo limpo do slug do card
    assert not slug_do_card.startswith(slugificar(titulo))
    assert any(slugificar(v) and slug_do_card.startswith(slugificar(v)) for v in variantes)


def test_dois_pontos_medial_sobrevive_ao_aparo_de_pontuacao():
    """Regressão: ":" colado ("Re:Zero") é medial, não pontuação de borda —
    `_aparar_pontuacao` não o remove nem deixa "Re" solto como 1º prefixo
    (mesmo risco de prefix-match do `_REGEX_SEPARADOR_SUBTITULO`)."""
    variantes = variantes_de_busca("Re:Zero kara Hajimeru Isekai Seikatsu")

    assert variantes[0] == "Re:Zero kara Hajimeru Isekai Seikatsu"
    assert "Re:Zero" in variantes
    assert "Re" not in variantes


def test_hifen_interno_sobrevive_ao_aparo_de_pontuacao():
    """Regressão: hífen interno de palavra composta ("Keishou-sen") não está em
    `_PONTUACAO_DE_BORDA` — sobrevive ao aparo na posição 0 e no prefixo."""
    variantes = variantes_de_busca("Keishou-sen no Monshou")

    assert variantes[0] == "Keishou-sen no Monshou"
    assert "Keishou-sen" in variantes


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
def test_corresponde_a_alguma_ref_aceita_card_truncado_ou_com_marcador_de_versao(
    referencia, candidato
):
    """Card de site de busca costuma vir truncado antes do subtítulo, com
    contração romaji diferente da grafia Hepburn separada ("dewa" vs "de
    wa"), com macron em vez de vogal dobrada ("Sūgū" vs "Suuguu"), ou com
    marcador de versão colado ("(Dublado)") — nenhum desses casos pode
    reprovar um card que é genuinamente o mesmo anime."""
    assert corresponde_a_alguma_referencia([referencia], candidato) is True


def test_corresponde_a_alguma_ref_vale_nos_dois_sentidos_de_prefixo():
    """A relação é `ref.startswith(cand) or cand.startswith(ref)` — vale
    tanto quando o candidato é o prefixo da referência (card truncado)
    quanto quando a referência é o prefixo do candidato (referência salva
    truncada, card do site com o título completo)."""
    referencia = "One Piece"
    candidato = "One Piece (Dublado)"
    assert corresponde_a_alguma_referencia([referencia], candidato) is True
    assert corresponde_a_alguma_referencia([candidato], referencia) is True


def test_corresponde_a_alguma_ref_rejeita_card_que_so_compartilha_prefixo_curto():
    """"Futsutsuka na" sozinho é um prefixo comum demais — um card de anime
    genuinamente diferente que só compartilha esse começo não pode passar
    como se fosse o mesmo título (falso-positivo de busca por prefixo, ver
    `_prefixos_crescentes`)."""
    candidato_de_outro_anime = "Futsutsuka na Akademi de Mahou wo Narau Ken"
    assert (
        corresponde_a_alguma_referencia([_REFERENCIA_COM_SUBTITULO], candidato_de_outro_anime)
        is False
    )


def test_corresponde_a_alguma_ref_sem_base_de_comparacao_na_referencia_degrada_pra_aceitar():
    """Título só com caracteres que `slugificar` não preserva (ex. kanji sem
    romanização) não dá chave nenhuma pra comparar — sem base pra rejeitar,
    degrada pra aceitar."""
    assert corresponde_a_alguma_referencia(["本"], "Qualquer Card Candidato") is True


def test_corresponde_a_alguma_ref_candidato_sem_base_mas_referencia_valida_rejeita():
    """Referência tem chave normal, mas o candidato não tem nenhuma — não há
    como validar a correspondência, e aqui a falta de base é do lado que
    está sendo checado, não do lado de referência: rejeita."""
    assert corresponde_a_alguma_referencia(["One Piece"], "本") is False


def test_corresponde_a_alguma_ref_strings_vazias_ou_so_espaco_degradam_pra_aceitar():
    """Sem chave dos dois lados — a checagem de referência vem primeiro e
    já não tem base pra rejeitar."""
    assert corresponde_a_alguma_referencia([""], "") is True
    assert corresponde_a_alguma_referencia(["   "], "   ") is True


def test_corresponde_a_alguma_ref_lista_vazia_degrada_pra_aceitar():
    """Nenhuma referência pra validar contra — mesmo veredito de "referência
    sem chave": sem base pra rejeitar, aceita (CLAUDE.md §4, decisão
    explícita). Um chamador que monta a lista de nomes do provedor pode acabar
    com ela vazia (anime sem nenhum título alternativo)."""
    assert corresponde_a_alguma_referencia([], "Qualquer Card Candidato") is True


def test_corresponde_a_alguma_ref_basta_uma_referencia_da_lista_bater():
    """O card vem grafado no título inglês do provedor; a referência em
    português que o usuário digitou não bate por chave nenhuma, mas o título
    inglês (também na lista) bate — basta uma correspondência pra validar o
    card como o mesmo anime. Se nenhuma bate, segue rejeitando."""
    referencias = ["Rei das Cavernas: A Ascensao", "Tomb Raider King"]
    assert corresponde_a_alguma_referencia(referencias, "Tomb Raider King") is True
    assert corresponde_a_alguma_referencia(referencias, "Solo Leveling") is False


@pytest.mark.parametrize(
    ("referencia", "candidato"),
    [
        ("One Piece", "One"),
        ("Kaguya-sama wa Kokurasetai", "Kaguya"),
        ("Naruto Shippuden", "Naruto"),
    ],
)
def test_corresponde_a_alguma_ref_rejeita_card_de_uma_palavra_vs_ref_composta(
    referencia, candidato
):
    """A escada de prefixos crescentes (busca começando pela 1ª palavra) faz os
    sites devolverem muitos cards de uma palavra — "One" numa busca por "One
    Piece" — e a contenção de prefixo sozinha os aceitaria ("one" é prefixo de
    "onepiece"). Um card de UMA palavra é sinal fraco demais pra auto-aceitar
    contra uma referência de 2+ palavras quando o mesmo veredito decide qual
    episódio baixar. Contagem no texto original, antes da normalização."""
    assert corresponde_a_alguma_referencia([referencia], candidato) is False


def test_corresponde_a_alguma_ref_guard_de_uma_palavra_vale_por_referencia():
    """O guard de card de uma palavra vs. referência de 2+ palavras é aplicado
    por referência: se TODA referência composta reprovaria o card, ele
    continua rejeitado — nenhuma "salva" a outra. Mas uma referência de uma
    palavra na lista valida o card de uma palavra."""
    so_compostas = ["Naruto Shippuden", "Naruto: O Filme"]
    assert corresponde_a_alguma_referencia(so_compostas, "Naruto") is False
    assert corresponde_a_alguma_referencia([*so_compostas, "Naruto"], "Naruto") is True


@pytest.mark.parametrize(
    ("referencia", "candidato"),
    [
        # chaves normalizadas idênticas ("dogulwang") — escapam do guard de
        # contagem e travam a proteção de grafia colada vs. separada entre sites
        ("DogulWang", "Dogul Wang"),
        # candidato de 2 palavras: o guard de uma palavra não dispara, a
        # contenção de prefixo continua valendo para card truncado antes do
        # subtítulo
        ("Fate/stay night: Unlimited Blade Works", "Fate/stay night"),
        ("Bleach", "Bleach"),
    ],
)
def test_corresponde_a_alguma_ref_guard_de_uma_palavra_nao_endurece_casos_legitimos(
    referencia, candidato
):
    assert corresponde_a_alguma_referencia([referencia], candidato) is True


@pytest.mark.parametrize(
    ("referencia", "candidato", "esperado_primeiro_criterio"),
    [
        # chave normalizada idêntica -> 0 (grafia colada/separada colapsa na
        # mesma chave "dogulwang")
        ("Naruto", "Naruto", 0),
        ("DogulWang", "Dogul Wang", 0),
        # só compartilha prefixo -> 1, sempre depois de qualquer match idêntico
        ("Naruto", "Naruto Shippuden", 1),
        ("One Piece", "One Piece: A Grande Era Pirata", 1),
        # referência sem chave (vazia/só espaço) nunca conta como idêntica —
        # o `ref and` impede que candidatos de chave vazia empatem em 0
        ("", "", 1),
        ("   ", "Qualquer Card", 1),
    ],
)
def test_proximidade_a_referencias_pontua_identico_antes_de_prefixo(
    referencia, candidato, esperado_primeiro_criterio
):
    """1º critério da tupla: 0 quando a chave normalizada é idêntica à da
    referência (match exato), 1 quando só há contenção de prefixo. Chave
    idêntica ainda zera o 2º critério (mesma chave, diferença de comprimento 0)."""
    proximidade = proximidade_a_referencias([referencia], candidato)
    assert proximidade[0] == esperado_primeiro_criterio
    if esperado_primeiro_criterio == 0:
        assert proximidade == (0, 0)


def test_proximidade_a_referencias_ordena_do_match_exato_ao_mais_distante():
    """`sorted` com a chave: match exato primeiro (`(0, 0)`), depois os que só
    compartilham prefixo por menor diferença de comprimento — o card truncado
    mais perto da referência antes da continuação bem mais longa."""
    candidatos = ["Naruto Shippuden Ultimate Ninja Storm", "Naruto Shippuden", "Naruto"]
    assert sorted(candidatos, key=lambda t: proximidade_a_referencias(["Naruto"], t)) == [
        "Naruto",
        "Naruto Shippuden",
        "Naruto Shippuden Ultimate Ninja Storm",
    ]


def test_proximidade_a_referencias_escolhe_a_melhor_referencia():
    """Com várias referências, o candidato pontua pela mais parecida — a menor
    (mais próxima) tupla entre todas. O card bate exatamente uma referência e
    só compartilha prefixo com a outra: vale o `(0, 0)` da exata."""
    referencias = ["Naruto Shippuden", "Naruto"]
    assert proximidade_a_referencias(referencias, "Naruto") == (0, 0)
    # na ordenação, o card que casa exato uma referência vem antes do que só
    # compartilha prefixo com todas
    candidatos = ["Naruto Shippuden Ultimate Ninja Storm", "Naruto"]
    assert sorted(candidatos, key=lambda t: proximidade_a_referencias(referencias, t)) == [
        "Naruto",
        "Naruto Shippuden Ultimate Ninja Storm",
    ]


def test_proximidade_a_referencias_lista_vazia_nunca_pontua_como_match_exato():
    """Sem referência nenhuma o candidato foi aceito por
    `corresponde_a_alguma_referencia` (degrada pra aceitar), mas não pode
    fingir match exato: 1º critério sempre 1, fica atrás de qualquer match
    real na ordenação."""
    assert proximidade_a_referencias([], "Qualquer Card")[0] == 1


_REFERENCIAS_OVERLORD_II = ["Overlord II", "Over Lord 2", "オーバーロードⅡ"]


@pytest.mark.parametrize(
    ("candidato", "esperado"),
    [
        # regressão ao vivo: o "Ⅱ" do título nativo virava a chave "i" e aceitava
        # qualquer card começando com "i"
        ("In the Clear Moonlit Dusk", False),
        ("Overlord 3 – Todos os Episódios", False),
        ("Overlord 2 – Todos os Episódios", True),
        # card da franquia (nome sem o marcador), que o guard de uma palavra rejeitava
        ("Overlord", True),
    ],
)
def test_corresponde_a_alguma_ref_temporada_com_numeral_romano_e_titulo_nativo(
    candidato, esperado
):
    assert corresponde_a_alguma_referencia(_REFERENCIAS_OVERLORD_II, candidato) is esperado


def test_corresponde_a_alguma_ref_numeral_romano_nao_colide_com_a_temporada_1():
    """"II" não pode colapsar em "i" pela regra de vogal longa e virar "Overlord I"."""
    assert corresponde_a_alguma_referencia(["Overlord II"], "Overlord I") is False
    assert corresponde_a_alguma_referencia(["Overlord II"], "Overlord 2") is True
    assert corresponde_a_alguma_referencia(["Overlord IV"], "Overlord 4") is True


def test_corresponde_a_alguma_ref_chave_curta_nao_aceita_por_prefixo():
    """Referência de chave curta ("Ⅳ" nativo -> "4") não é prefixo de card sem relação."""
    assert corresponde_a_alguma_referencia(["オーバーロードⅣ"], "4-nin wa Idol") is False


def test_corresponde_a_alguma_ref_card_da_franquia_so_vale_com_marcador_na_referencia():
    """Sem marcador de temporada a referência não tem "franquia": o guard de uma
    palavra continua valendo ("One" vs "One Piece")."""
    assert corresponde_a_alguma_referencia(["One Piece"], "One") is False
    assert corresponde_a_alguma_referencia(["Naruto Shippuden"], "Naruto") is False
    assert corresponde_a_alguma_referencia(["One Piece Season 2"], "One Piece") is True


def test_proximidade_a_referencias_card_da_franquia_fica_depois_do_que_casa_por_prefixo():
    candidatos = ["Overlord", "Overlord 2 – Todos os Episódios", "Overlord II"]
    ordenados = sorted(candidatos, key=lambda t: proximidade_a_referencias(["Overlord II"], t))
    assert ordenados == ["Overlord II", "Overlord 2 – Todos os Episódios", "Overlord"]


def test_marcador_de_numeral_romano_alem_de_ii_e_iii_entra_na_reducao():
    assert "Dungeon ni Deai wo" in variantes_de_busca("Dungeon ni Deai wo IV")
    assert "Nome" in variantes_de_busca("Nome VIII")


def test_corresponde_a_alguma_ref_card_dublado_da_franquia_tambem_vale():
    """MeusAnimes cataloga "Overlord Dublado" como entrada própria da franquia."""
    assert corresponde_a_alguma_referencia(["Overlord II"], "Overlord Dublado") is True
    assert corresponde_a_alguma_referencia(["Overlord II"], "Outro Anime Dublado") is False
    # sem marcador de temporada na referência não há "franquia": mantém o guard
    assert corresponde_a_alguma_referencia(["One Piece"], "One Dublado") is False

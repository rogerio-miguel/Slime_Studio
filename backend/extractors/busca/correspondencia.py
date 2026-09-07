"""Correspondência entre os títulos de referência de um anime e o título de um
card devolvido por busca em site de streaming (`extractors/busca/`).

Domínio puro — zero I/O, zero dependência de rede/framework.
`corresponde_a_alguma_referencia` valida se um card realmente corresponde a
ALGUMA das referências de título passadas (o mesmo anime tem vários nomes —
romaji, inglês, nativo, sinônimos de provedor — e o card do site pode estar
grafado em qualquer um deles), em vez de só compartilhar um prefixo curto com
outro anime (falso-positivo real de site com busca por prefixo);
`proximidade_a_referencias` ordena os cards já aprovados, do mais próximo da
referência mais parecida ao mais distante.
"""

import re

from core.texto import slugificar

# Vogal longa aparece grafada de duas formas conforme o site: par dobrado
# ("Suuguu", romaji Hepburn "solto") ou reduzida a partir de macron pelo
# `slugificar` via NFKD+ascii-ignore ("Sūgū" -> "sugu"). Colapsar o par pra
# sua primeira letra faz as duas grafias caírem na mesma chave — sem isso
# "suuguu" (chave com par dobrado) nunca bateria com "sugu" (chave já
# reduzida do outro lado).
_REGEX_VOGAL_LONGA = re.compile(r"ou|uu|oo|aa|ii|ee")


def corresponde_a_alguma_referencia(referencias: list[str], titulo_candidato: str) -> bool:
    """Valida se `titulo_candidato` (`titulo_exibicao` de um card devolvido por
    busca em site de streaming) corresponde a QUALQUER uma das `referencias` —
    os vários nomes do mesmo anime (título salvo/digitado, romaji, inglês,
    nativo, sinônimos de provedor). Basta bater com uma: o anime pode estar
    cadastrado em português enquanto o site indexa só o romaji, e o card
    romaji ainda é o mesmo anime.

    Cada referência é checada isoladamente por `_corresponde_a_uma_referencia`
    (contenção de prefixo sobre chave normalizada + guard de card de uma
    palavra — a docstring dela tem o PORQUÊ de cada regra); o veredito é o OR
    entre todas. Um card que não bate com NENHUMA referência é falso-positivo
    de busca por prefixo e é descartado pelo chamador
    (`extractors/busca/servico.py`).

    `referencias` vazia degrada para aceitar — mesmo veredito que uma
    referência sem chave de comparação (título só em kanji) já produz por
    dentro: sem nenhuma base pra rejeitar, não há como afirmar que o card está
    errado (CLAUDE.md §4, erro nunca silencioso — a decisão de aceitar é
    explícita, não um `if` que caiu no `else` por acaso). Quem monta a lista é
    quem sabe se vir vazia é esperado (anime sem nenhum título alternativo) ou
    sintoma de bug a montante.
    """
    if not referencias:
        return True
    return any(
        _corresponde_a_uma_referencia(referencia, titulo_candidato)
        for referencia in referencias
    )


def _corresponde_a_uma_referencia(referencia: str, titulo_candidato: str) -> bool:
    """Regra de correspondência de UMA referência — primitiva de
    `corresponde_a_alguma_referencia`. Valida se `titulo_candidato`
    (`titulo_exibicao` de um card devolvido por busca em site de streaming)
    realmente corresponde a `referencia`, em vez de só compartilhar um prefixo
    curto com outro anime — falso-positivo real de sites com busca por prefixo
    (ver `extractors/busca/termos.py::_prefixos_crescentes`): um prefixo de
    2-3 palavras casa por texto com o card de um anime completamente diferente
    que começa igual.

    Comparação por contenção de prefixo sobre uma chave normalizada (slug
    sem hífen, vogal longa colapsada) em vez de distância de edição ou
    token-set: token-set quebra em contrações romaji ("de wa" vs "dewa" viram
    conjuntos de token diferentes) e Levenshtein não separa bem um card
    verdadeiro truncado (ex. site corta antes do subtítulo) de um
    falso-positivo que só compartilha o começo.

    Trade-off aceito: um card de UMA palavra nunca valida uma `referencia` de
    duas ou mais palavras (contagem no texto original, antes da normalização).
    A escada de prefixos crescentes faz os sites devolverem muitos cards de
    uma palavra ("One" numa busca por "One Piece") e a contenção de prefixo
    sozinha os aceitaria. Se algum site genuinamente cadastrar um anime de
    título composto com uma única palavra, esse card passa a ser rejeitado —
    sinal fraco demais pra auto-aceitar quando o mesmo veredito decide qual
    episódio baixar. Chaves normalizadas idênticas escapam do guard (grafia
    colada vs. separada entre sites: "DogulWang" vs "Dogul Wang").
    """
    ref = _chave_de_comparacao(referencia)
    if not ref:
        return True  # sem base pra validar (ex. título só em kanji): degrada pra aceitar
    cand = _chave_de_comparacao(titulo_candidato)
    if not cand:
        return False
    # Igualdade de chave vem antes do check de contagem: casa grafia colada/separada (DogulWang).
    if ref == cand:
        return True
    if len(titulo_candidato.split()) == 1 and len(referencia.split()) > 1:
        return False
    return ref.startswith(cand) or cand.startswith(ref)


def _chave_de_comparacao(texto: str) -> str:
    """Chave de comparação de `texto`: slug (via `slugificar`) sem hífen, com
    vogal longa colapsada.

    Slugificar primeiro dá a fronteira de token que a remoção de hífen
    depois precisa — sem passar por slug antes, um marcador de versão como
    "(Dublado)" coladinho ao texto viraria ruído misturado à palavra
    anterior em vez de virar um separador (que a remoção de hífen então
    apaga de propósito, pra "de-wa" e "dewa" caírem na mesma chave "dewa").
    Vogal longa colapsa por último, depois que separadores já sumiram, senão
    um par vogal-vogal formado só pela junção de duas palavras vizinhas (que
    o hífen removido deixou coladas) escaparia da normalização.
    """
    slug = slugificar(texto)
    sem_hifen = slug.replace("-", "")
    return _REGEX_VOGAL_LONGA.sub(lambda correspondencia: correspondencia.group(0)[0], sem_hifen)


def proximidade_a_referencias(
    referencias: list[str], titulo_candidato: str
) -> tuple[int, int]:
    """Chave de ordenação para candidatos JÁ aprovados por
    `corresponde_a_alguma_referencia`, do mais próximo à referência mais
    parecida ao mais distante — consumida por
    `extractors/busca/servico.py::buscar_em_com_variantes` via `list.sort`.

    Existe por causa da sonda larga: o bloco de recall de
    `extractors/busca/termos.py::variantes_de_busca` busca pela 1ª palavra,
    então uma única variante volta com vários cards legítimos ("Naruto" e
    "Naruto Shippuden" numa busca por "Naruto") e o primeiro da lista é o que
    a UI mostra e o que a captura tende a baixar. Sem ordenar, esse primeiro é
    só quem o site listou antes.

    Com várias referências (os vários nomes do anime), o candidato pontua pela
    SUA MELHOR referência — a menor (mais próxima) tupla de
    `_proximidade_a_uma_referencia` entre todas. Um card que bate exatamente o
    título inglês não pode ser rebaixado só porque diverge do romaji: a
    referência que mais o aproxima é a que conta.

    Cada tupla de `_proximidade_a_uma_referencia` tem dois critérios, nesta
    ordem:

    1. Chave normalizada idêntica à da referência (`_chave_de_comparacao`, a
       mesma de `_corresponde_a_uma_referencia`) pontua 0; match que só passou
       por contenção de prefixo pontua 1. O card cujo título bate exatamente
       vem antes do que apenas começa igual. Referência sem chave (só kanji,
       string vazia) nunca pontua 0 — o `ref and` impede que dois candidatos
       de chave vazia empatem em 0 e "ganhem" de um match real.
    2. Desempate: menor diferença de comprimento entre a chave do candidato e
       a da referência. Aproxima o card truncado antes do subtítulo ("Nome"
       por "Nome: Subtítulo") e afasta uma continuação bem mais longa.

    `referencias` vazia usa a tupla de uma referência sem chave (`""`) — mesmo
    caso de borda que `corresponde_a_alguma_referencia` já aceitou; o card
    aprovado sem base de comparação fica no fim da ordenação, nunca à frente
    de um match real.

    Sem terceiro critério de propósito: o `list.sort` do chamador é estável,
    então candidatos de tupla igual mantêm a ordem em que o site os devolveu —
    sinal fraco, mas preferível a uma reordenação arbitrária.
    """
    if not referencias:
        return _proximidade_a_uma_referencia("", titulo_candidato)
    return min(
        _proximidade_a_uma_referencia(referencia, titulo_candidato)
        for referencia in referencias
    )


def _proximidade_a_uma_referencia(referencia: str, titulo_candidato: str) -> tuple[int, int]:
    """Tupla `(criterio_exato, diferenca_de_comprimento)` de uma referência —
    primitiva de `proximidade_a_referencias`, que documenta o significado de
    cada critério e como a ordenação a consome."""
    ref = _chave_de_comparacao(referencia)
    cand = _chave_de_comparacao(titulo_candidato)
    return (0 if ref and ref == cand else 1, abs(len(cand) - len(ref)))

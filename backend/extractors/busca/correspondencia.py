"""Correspondência entre o título buscado e o título de um card devolvido por
busca em site de streaming (`extractors/busca/`).

Domínio puro — zero I/O, zero dependência de rede/framework.
`corresponde_ao_titulo` valida se um card realmente corresponde ao título de
referência (em vez de só compartilhar um prefixo curto com outro anime —
falso-positivo real de site com busca por prefixo); `proximidade_do_titulo`
ordena os cards já aprovados, do mais próximo da referência ao mais distante.
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


def corresponde_ao_titulo(referencia: str, titulo_candidato: str) -> bool:
    """Valida se `titulo_candidato` (`titulo_exibicao` de um card devolvido
    por busca em site de streaming) realmente corresponde a `referencia` (o
    título salvo/buscado), em vez de só compartilhar um prefixo curto com
    outro anime — falso-positivo real de sites com busca por prefixo (ver
    `extractors/busca/termos.py::_prefixos_crescentes`): um prefixo de 2-3
    palavras casa por texto com o card de um anime completamente diferente
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


def proximidade_do_titulo(referencia: str, titulo_candidato: str) -> tuple[int, int]:
    """Chave de ordenação para candidatos JÁ aprovados por `corresponde_ao_titulo`,
    do mais próximo de `referencia` ao mais distante — consumida por
    `extractors/busca/servico.py::buscar_em_com_variantes` via `list.sort`.

    Existe por causa da sonda larga: o bloco de recall de
    `extractors/busca/termos.py::variantes_de_busca` busca pela 1ª palavra,
    então uma única variante volta com vários cards legítimos ("Naruto" e
    "Naruto Shippuden" numa busca por "Naruto") e o primeiro da lista é o que
    a UI mostra e o que a captura tende a baixar. Sem ordenar, esse primeiro é
    só quem o site listou antes.

    Dois critérios, nesta ordem:

    1. Chave normalizada idêntica à da `referencia` (`_chave_de_comparacao`, a
       mesma de `corresponde_ao_titulo` — slug sem hífen, vogal longa
       colapsada) pontua 0; match que só passou por contenção de prefixo pontua
       1. O card cujo título bate exatamente vem antes do que apenas começa
       igual. `referencia` sem chave (só kanji, string vazia) nunca pontua 0 —
       o `ref and` impede que dois candidatos de chave vazia empatem em 0 e
       "ganhem" de um match real.
    2. Desempate: menor diferença de comprimento entre a chave do candidato e a
       da `referencia`. Aproxima o card truncado antes do subtítulo ("Nome" por
       "Nome: Subtítulo") e afasta uma continuação bem mais longa.

    Sem terceiro critério de propósito: o `list.sort` do chamador é estável,
    então candidatos de tupla igual mantêm a ordem em que o site os devolveu —
    sinal fraco, mas preferível a uma reordenação arbitrária.
    """
    ref = _chave_de_comparacao(referencia)
    cand = _chave_de_comparacao(titulo_candidato)
    return (0 if ref and ref == cand else 1, abs(len(cand) - len(ref)))

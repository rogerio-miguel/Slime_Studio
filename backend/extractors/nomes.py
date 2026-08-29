"""Motor de tratamento de nome para busca em sites de streaming (`extractors/`).

Domínio puro — zero I/O, zero dependência de rede/framework. Produz variantes
de busca progressivamente mais agressivas a partir de um título de anime, do
mais provável (o título como veio) ao mais truncado, para sites cuja busca
casa por prefixo/texto exato em vez de full-text (ex. AnimeFire). Iterar essas
variantes até achar resultado é responsabilidade de quem chama — este módulo
só calcula a lista.
"""

import re

from core.texto import slugificar

# `/pesquisar/<termo>` do AnimeFire (e sites com busca por prefixo em geral)
# casam pelo título principal, não por texto completo — qualquer palavra de
# um subtítulo depois de ":"/"~"/" - " já zera o resultado (confirmado ao
# vivo: título com subtítulo devolve 0 resultados mesmo sem o ":" literal,
# mas o título truncado antes do separador encontra o card normalmente).
# Espaço obrigatório em pelo menos um lado do separador — evita cortar hífen
# interno de palavra composta (ex. "Keishou-sen") E evita tratar ":"/"~"
# colado ao texto (ex. "Re:Zero") como separador de subtítulo — esse segundo
# caso truncaria pra um prefixo curto demais ("Re") e arriscaria casar o card
# de outro anime por prefix-match, trocando silenciosamente "não encontrei"
# por "encontrei o errado".
_REGEX_SEPARADOR_SUBTITULO = re.compile(r"\s*[:~]\s+|\s+[:~]\s*|\s+[-–—]\s+")

# Marcadores de temporada/parte no fim do título: "2nd Season", "Season 2",
# "Part 2", "Cour 2", "(TV)", "(2024)" (ano entre parênteses) e "II"/"III".
# Fronteira de token obrigatória via `\s+` antes do marcador — nunca corta
# substring solta de dentro de outra palavra (ex. não pode cortar "ii" do
# fim de "Torii", que não tem espaço antes do "ii").
_REGEX_MARCADOR_TEMPORADA_PARTE = re.compile(
    r"""
    \s+
    (?:
        \d+(?:st|nd|rd|th)\s+Season   # "2nd Season"
      | Season\s+\d+                  # "Season 2"
      | Part\s+\d+                    # "Part 2"
      | Cour\s+\d+                    # "Cour 2"
      | \(TV\)                        # "(TV)"
      | \(\d{4}\)                     # "(2024)"
      | (?:II|III)                    # "II" / "III" ao final
    )
    \s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)


def variantes_de_busca(titulo: str) -> list[str]:
    """Termos de busca derivados de `titulo`, do mais provável ao mais
    agressivo, já deduplicados por `core/texto.py::slugificar` e sempre com
    `titulo` na posição 0. Nunca vazio.
    """
    titulo = titulo.strip()
    candidatos = [titulo]

    principal = _REGEX_SEPARADOR_SUBTITULO.split(titulo, maxsplit=1)[0].strip()
    cortou_subtitulo = bool(principal) and principal != titulo
    if cortou_subtitulo:
        candidatos.append(principal)

    # Reduz temporada/parte sobre o título já cortado do passo anterior (ou
    # sobre o original quando não houve corte de subtítulo) — nunca os dois
    # de forma independente, senão um marcador já descartado junto do
    # subtítulo (ex. "Nome - Part 2") voltaria a produzir um candidato
    # redundante (ex. "Nome -") a partir do título original.
    base_temporada = principal if cortou_subtitulo else titulo
    sem_marcador = _remover_marcadores_temporada_parte(base_temporada)
    if sem_marcador and sem_marcador != base_temporada:
        candidatos.append(sem_marcador)

    candidatos.extend(_prefixos_decrescentes(candidatos[-1]))

    return _deduplicar_por_slug(candidatos)


# Palavras mínimas num prefixo — abaixo disso o termo vira comum demais e
# arrisca casar o card de outro anime por prefix-match (mesmo risco já
# documentado pro corte de subtítulo, ver `_REGEX_SEPARADOR_SUBTITULO`).
_MINIMO_PALAVRAS_PREFIXO = 2

# Teto de variantes extras geradas aqui — cada uma vira 1 request real por
# site em `extractors/servico.py::buscar_em_com_variantes` (Fase 1 de
# `api/servicos/busca.py`, sem `wait_for` de lote como a Fase 2 tem). Sem
# teto, um título muito longo multiplicaria o número de requests contra
# sites com anti-bot proporcional ao tamanho do título. 5 já cobre o caso
# real que motivou isso (7 palavras, precisa cair até 3 — 5 variantes).
_MAXIMO_PREFIXOS = 5


def _prefixos_decrescentes(texto: str) -> list[str]:
    """Prefixos de `texto` cortando uma palavra por vez a partir do fim, do
    mais específico ao mais curto, até `_MINIMO_PALAVRAS_PREFIXO` ou
    `_MAXIMO_PREFIXOS` variantes — o que vier primeiro.

    Cobre busca por prefixo (AnimeFire e sites com padrão parecido) que
    quebra numa única palavra divergente no *meio* do título — ex. contração
    romaji que o site grafa diferente do título canônico que guardamos
    ("dewa" no slug do site vs "de wa" Hepburn separado que vem do provedor
    de metadado) — sem precisar mapear cada contração manualmente: o prefixo
    mais longo que ainda inclui a palavra divergente falha, mas o próximo,
    sem ela, casa. Corte de subtítulo/temporada não resolve esse caso porque
    a divergência não está no fim do título.
    """
    palavras = texto.split()
    n_inicial = len(palavras) - 1
    n_final = max(_MINIMO_PALAVRAS_PREFIXO - 1, n_inicial - _MAXIMO_PREFIXOS)
    return [" ".join(palavras[:n]) for n in range(n_inicial, n_final, -1)]


def _remover_marcadores_temporada_parte(texto: str) -> str:
    """Aplica `_REGEX_MARCADOR_TEMPORADA_PARTE` repetidamente até estabilizar.

    O regex é ancorado em `\\s*$`, então um único `.sub()` só alcança o
    marcador mais à direita — títulos com dois marcadores empilhados (ex.
    "Shingeki no Kyojin Season 3 Part 2", padrão comum de shonen longo
    fatiado em cours) ficariam com "Part 2" cortado mas "Season 3" sobrando.
    O laço descasca um marcador por vez até não sobrar nenhum."""
    anterior = None
    atual = texto
    while atual != anterior:
        anterior = atual
        atual = _REGEX_MARCADOR_TEMPORADA_PARTE.sub("", atual).strip()
    return atual


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
    `_prefixos_decrescentes`): um prefixo de 2-3 palavras casa por texto com
    o card de um anime completamente diferente que começa igual.

    Comparação por contenção de prefixo sobre uma chave normalizada (slug
    sem hífen, vogal longa colapsada) em vez de distância de edição ou
    token-set: token-set quebra em contrações romaji ("de wa" vs "dewa" viram
    conjuntos de token diferentes) e Levenshtein não separa bem um card
    verdadeiro truncado (ex. site corta antes do subtítulo) de um
    falso-positivo que só compartilha o começo.
    """
    ref = _chave_de_comparacao(referencia)
    if not ref:
        return True  # sem base pra validar (ex. título só em kanji): degrada pra aceitar
    cand = _chave_de_comparacao(titulo_candidato)
    if not cand:
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


def _deduplicar_por_slug(candidatos: list[str]) -> list[str]:
    """Colapsa candidatos cujo slug coincide (ex. "Nome: Sub" e "Nome - Sub"),
    mantendo a primeira ocorrência — `titulo` é sempre a primeira, então
    nunca é removido daqui."""
    vistos: set[str] = set()
    resultado: list[str] = []
    for candidato in candidatos:
        chave = slugificar(candidato)
        if chave in vistos:
            continue
        vistos.add(chave)
        resultado.append(candidato)
    return resultado

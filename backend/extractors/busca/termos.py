"""Geração dos termos de busca a partir de um título de anime
(`extractors/busca/`).

Domínio puro — zero I/O, zero dependência de rede/framework. A partir de um
título de anime, `variantes_de_busca` monta a lista de termos de busca em
dois blocos:

- Precisão: o título como veio (índice 0) e cortes conservadores no fim —
  subtítulo depois de ":"/"~"/" - " e marcador de temporada/parte.
- Recall: prefixos CRESCENTES a partir da 1ª palavra. Sites cuja busca casa
  por prefixo de slug (AnimeFire) ou por palavra (WordPress do AnimesDrive)
  têm chance MAIOR de devolver o card certo com a 1ª palavra do que com o
  título inteiro — grafia de contração romaji, hífen, sufixo e subtítulo
  divergem entre o título canônico e o slug do site (confirmado ao vivo:
  "dogul" acha o card "Dogulwang", "dogul-wang" não).

Todo candidato menos a posição 0 (que é `titulo` exato) é aparado por
`_aparar_pontuacao`: esses mesmos sites não indexam pontuação na borda de um
token, então o ponto final ou o ":" de subtítulo herdado do título no fim de
um corte/prefixo só derruba o recall (confirmado ao vivo:
"?s=...Chikaimashita.:..." devolve 0, o card existe).

A lista NÃO é monotônica em tamanho: o bloco de precisão vem inteiro antes do
de recall e costuma ser mais longo que o começo dele ("Nome 2nd Season" antes
de "Nome"). É intencional — a ordem é "mais provável de casar" primeiro, não
"mais palavras" primeiro; sem esta nota alguém "conserta" reordenando. Iterar
as variantes até achar resultado é de quem chama — este módulo só calcula.
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
# "Part 2", "Cour 2", "(TV)", "(2024)" (ano entre parênteses) e numeral romano
# "II".."IX". "V" e "X" sozinhos ficam de fora: letra solta demais pra ser
# marcador sem falso corte.
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
      | (?:II|III|IV|VI{1,3}|IX)      # numeral romano ao final
    )
    \s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)


def variantes_de_busca(titulo: str) -> list[str]:
    """Termos de busca derivados de `titulo`, do mais provável de casar ao
    mais agressivo, deduplicados por `core/texto.py::slugificar` e sempre com
    `titulo` na posição 0. Nunca vazio.

    Dois blocos, nesta ordem (ver docstring do módulo):

    1. Precisão — `titulo.strip()`, depois o título sem subtítulo
       (`_REGEX_SEPARADOR_SUBTITULO`) e sem marcador de temporada/parte
       (`_REGEX_MARCADOR_TEMPORADA_PARTE`), cada corte aplicado sobre o
       resultado do anterior.
    2. Recall — `_prefixos_crescentes` sobre o candidato já mais reduzido do
       bloco 1: a 1ª palavra, as 2 primeiras, as 3 primeiras.

    A posição 0 é sempre `titulo` exato (sonda de texto completo — alguns
    sites a querem crua); todo candidato DERIVADO (os cortes do bloco 1 e os
    prefixos do bloco 2) passa por `_aparar_pontuacao`, que tira a pontuação
    de borda herdada do título (ponto final, ":" de subtítulo) — os sites de
    busca não a indexam e ela só derruba o recall.

    A lista não é monotônica em tamanho — o bloco 1 pode devolver candidatos
    mais longos que os primeiros do bloco 2. Não reordenar por tamanho: a
    ordem é por probabilidade de casar, não por comprimento.

    Limitação conhecida: a direção "título local grafado colado → site que
    usa a grafia com espaço" NÃO é coberta (separar palavra composta exigiria
    dicionário). A inversa (local com espaço → site colado) é: cai na busca
    pela 1ª palavra + validação por chave normalizada em
    `extractors/busca/correspondencia.py::corresponde_a_alguma_referencia`.
    """
    return _deduplicar_por_slug([v for degrau in _degraus(titulo) for v in degrau])


def escada_combinada(titulos: list[str]) -> list[str]:
    """Escada de busca de VÁRIOS nomes do mesmo anime (digitado, romaji,
    inglês...), ordenada por degrau e não por nome: primeiro todos os títulos
    completos, depois todos os cortes de subtítulo/temporada, por último os
    prefixos de recall. Deduplicada por slug, 1ª ocorrência vence.

    Por quê: concatenar a escada inteira de cada idioma fazia o site gastar a
    escada do romaji (cortes e prefixos, quase sempre sem resultado) antes de
    sondar o título inglês completo — medido ao vivo, o card certo do
    MeusAnimes ("Above Myriads") só aparecia na 5ª variante. Os degraus de
    precisão de TODOS os nomes vêm antes de qualquer prefixo de recall, que é o
    degrau caro (devolve dezenas de cards sem relação).

    Com um título só é idêntica a `variantes_de_busca`."""
    por_titulo = [_degraus(titulo) for titulo in titulos]
    return _deduplicar_por_slug(
        [v for indice in range(3) for degraus in por_titulo for v in degraus[indice]]
    )


def _degraus(titulo: str) -> tuple[list[str], list[str], list[str]]:
    """`(completo, cortes, prefixos)` de `titulo`: o título como veio (posição
    0 crua, contrato de `variantes_de_busca`), os cortes de precisão e os
    prefixos de recall. Derivados já aparados de pontuação de borda."""
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
    sem_marcador = remover_marcadores_temporada_parte(base_temporada)
    if sem_marcador and sem_marcador != base_temporada:
        candidatos.append(sem_marcador)

    cortes = [_aparar_pontuacao(c) for c in candidatos[1:]]
    # Bloco de recall: prefixos crescentes sobre o candidato já mais reduzido.
    # Posição 0 crua; todo derivado aparado da pontuação de borda que herdou do
    # título e que os sites de busca não indexam.
    prefixos = [_aparar_pontuacao(p) for p in _prefixos_crescentes(candidatos[-1])]
    return [candidatos[0]], cortes, prefixos


# Slug com menos caracteres que isto como prefixo (ex. "Ao", "Re", "K" — 1ª
# palavra de "Ao Haru Ride", "Re:Zero"...) é comum demais: casaria o card de
# outro anime por prefix-match (mesmo risco já documentado pro corte de
# subtítulo, ver `_REGEX_SEPARADOR_SUBTITULO`). Piso por caractere, não por
# nº de palavras — o que decide o risco é o tamanho do termo, não a contagem.
_MINIMO_CARACTERES_PREFIXO = 3

# A 1ª palavra sozinha é o prefixo mais largo da escada: medido ao vivo, "Wan"
# devolveu 20-35 cards sem relação por site, num request de ~2s. Piso maior só
# pra ela; "Dogul"/"Yasei"/"Above" (5) passam, "Wan"/"Boku"/"Kimi" caem e o
# prefixo de 2 palavras ("Wan Ren") cobre o recall.
_MINIMO_CARACTERES_PRIMEIRA_PALAVRA = 5

# Teto de prefixos gerados aqui — cada um vira 1 request real por site em
# `extractors/busca/servico.py::buscar_em_com_variantes` (chamado por
# `api/servicos/busca.py`, sem teto de tempo de lote). O
# título completo (sonda 0) + os até 2 cortes do bloco de precisão já cobrem
# o lado longo; 3 prefixos bastam pro lado curto sem multiplicar request
# contra site com anti-bot proporcional ao tamanho do título.
_MAXIMO_PREFIXOS = 3


def _prefixos_crescentes(texto: str) -> list[str]:
    """Prefixos de `texto` crescendo uma palavra por vez a partir do início —
    1ª palavra, 2 primeiras, 3 primeiras — até `_MAXIMO_PREFIXOS` ou o
    penúltimo corte possível (nunca o texto inteiro), o que vier primeiro.
    Prefixo cujo slug tem menos de `_MINIMO_CARACTERES_PREFIXO` caracteres é
    pulado (não encurta a escada, só não entra).

    Crescente, não decrescente: em site de prefix-match (slug do AnimeFire) ou
    match por palavra (WordPress do AnimesDrive) a 1ª palavra casa MAIS que o
    título inteiro — contração romaji, hífen, sufixo e subtítulo divergem
    entre o título canônico e o slug do site e todos ficam fora de um prefixo
    curto. Cobre também a palavra divergente no *meio* do título ("de wa"
    Hepburn vs "dewa" contraído no slug) sem mapear cada contração: o prefixo
    antes dela casa.

    Teto de 3: o título completo (sonda 0) e os até 2 cortes do bloco de
    precisão já cobrem o lado longo; passar de 3 prefixos só multiplica
    request contra site com anti-bot sem ganho real de recall.

    Corte por caractere e não por palavra: o que torna um prefixo perigoso é
    ser curto e comum, e isso se mede em caracteres — "Ao"/"Re"/"K" como 1ª
    palavra são request garantidamente inútil, "Dogul" (5 chars) não.
    """
    palavras = texto.split()
    if len(palavras) < 2:
        return []
    limite = min(_MAXIMO_PREFIXOS, len(palavras) - 1)
    prefixos: list[str] = []
    for n in range(1, limite + 1):
        prefixo = " ".join(palavras[:n])
        minimo = _MINIMO_CARACTERES_PRIMEIRA_PALAVRA if n == 1 else _MINIMO_CARACTERES_PREFIXO
        if len(slugificar(prefixo)) < minimo:
            continue  # "Ao", "Re", "K", "Wan" — request que só traz ruído
        prefixos.append(prefixo)
    return prefixos


def remover_marcadores_temporada_parte(texto: str) -> str:
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


# Pontuação que os sites de busca não indexam quando aparece na BORDA de um
# token: some do slug do AnimeFire e não conta como termo no WordPress do
# AnimesDrive. Aparada só do início/fim de cada palavra dos candidatos
# derivados, NUNCA do miolo — ":" em "Re:Zero", "/" em "Fate/stay" e "-" em
# "Keishou-sen" são significativos (mesmo cuidado do `_REGEX_SEPARADOR_SUBTITULO`,
# que exige espaço para tratar ":"/"-" como separador). Hífen fica de fora da
# lista de propósito: encurtar "Keishou-sen" não ajuda nenhum site.
_PONTUACAO_DE_BORDA = ".,;:!?~…\"'“”‘’«»"


def _aparar_pontuacao(texto: str) -> str:
    """Tira `_PONTUACAO_DE_BORDA` do início e do fim de cada palavra de `texto`,
    preservando a pontuação medial. Palavra que fica vazia (era só pontuação)
    sai; se não sobrar nada, devolve `texto.strip()` — a lista de
    `variantes_de_busca` nunca pode conter termo vazio."""
    palavras = [palavra.strip(_PONTUACAO_DE_BORDA) for palavra in texto.split()]
    return " ".join(palavra for palavra in palavras if palavra) or texto.strip()


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

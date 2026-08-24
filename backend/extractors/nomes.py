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

    return _deduplicar_por_slug(candidatos)


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

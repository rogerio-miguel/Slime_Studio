"""Separação de marcador de temporada em título de anime — domínio puro, sem
dependências externas (Escada de Minimalismo), usado pela resolução de arte
via TMDB (a busca do TMDB é por *série*, não por temporada — sem extrair o
número, uma capa multi-temporada sempre resolve pro pôster da temporada 1).

Fronteira deliberada com `extractors/busca/termos.py::_remover_marcadores_
temporada_parte`: os dois regex reconhecem marcadores parecidos ("Season 2",
"Part 2", romano) e usam a mesma técnica de laço (um `.sub()` só alcança o
marcador mais à direita; títulos com dois marcadores empilhados exigem
descascar um por vez até estabilizar), mas respondem perguntas diferentes.
`extractors/` decide *o que digitar na busca de um site de streaming* — errar
pra mais estrito só custa um termo de busca a menos numa lista que já tem
fallback. Este módulo decide *qual temporada, dentre várias, o TMDB está
mostrando* — errar aqui é mostrar a capa errada pro usuário. Same-shaped
regex, garantias diferentes (este módulo também extrai o número, aquele só
descarta); não deduplicar os dois construindo um sobre o outro.
"""

import re
from dataclasses import dataclass

# Mapa de numeral romano reconhecido -> número da temporada. Só II/III/IV:
# "I" sozinho colide demais com outras coisas (inicial de nome, algarismo
# solto) e não há anime no catálogo com 5+ temporadas nomeadas em romano.
_MAPA_ROMANO = {"II": 2, "III": 3, "IV": 4}

# Marcadores que ANCORAM o número da temporada (viram `numero` no retorno) e
# marcadores que só são descartados do título (Part/Cour/TV/ano) mas nunca
# definem `numero` sozinhos — um título só com "Part 2" não é "temporada 2",
# é um recorte de exibição da MESMA temporada.
#
# Fronteira de token obrigatória via `\s+` antes do marcador — nunca casa
# substring solta de dentro de outra palavra (ex. não pode cortar "ii" do
# fim de "Torii", que não tem espaço antes do "ii", nem "0" solto no fim de
# "Steins;Gate 0", que não tem nenhum marcador de palavra na frente).
_REGEX_MARCADOR_TEMPORADA = re.compile(
    r"""
    \s+
    (?:
        Season\s+(?P<num_season_n>\d+)                       # "Season 3"
      | (?P<num_n_season>\d+)(?:st|nd|rd|th)\s+Season         # "3rd Season"
      | (?P<num_temporada_a>\d+)\s*ª\s*Temporada              # "3ª Temporada"
      | Temporada\s+(?P<num_temporada_b>\d+)                  # "Temporada 3"
      | (?P<romano>II|III|IV)                                 # "II" / "III" / "IV" ao final
      | Part\s+\d+                                            # "Part 2" (descarta, sem número)
      | Cour\s+\d+                                            # "Cour 2" (descarta, sem número)
      | \(TV\)                                                # "(TV)" (descarta)
      | \(\d{4}\)                                             # "(2024)" (descarta)
    )
    \s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)


def separar_temporada(titulo: str) -> tuple[str, int | None]:
    """Separa `titulo` em `(titulo_sem_marcadores, numero_da_temporada)`.

    Descasca marcadores de temporada/parte do FIM do título em laço — um
    `.sub()` só alcançaria o marcador mais à direita, então títulos com dois
    marcadores empilhados (ex. "Shingeki no Kyojin Season 3 Part 2", padrão
    comum de shonen longo fatiado em cours) ficariam com "Part 2" cortado mas
    "Season 3" sobrando. O laço repete até nenhum marcador mais casar,
    guardando o primeiro número de temporada encontrado ao longo do processo
    (o exemplo acima devolve `("Shingeki no Kyojin", 3)`: "Part 2" é
    descartado sem gerar número, "Season 3" na iteração seguinte gera).

    Quando nenhum marcador reconhecido casa, devolve `titulo` sem NENHUMA
    modificação (identidade, nem strip) e `numero=None` — dígito solto no fim
    sem marcador de palavra na frente (`Season`/`Temporada`/romano) nunca
    vira temporada (ex. "Steins;Gate 0", "86", "91 Days" continuam intactos).
    """
    numero: int | None = None
    atual = titulo
    anterior = None
    while atual != anterior:
        anterior = atual
        match = _REGEX_MARCADOR_TEMPORADA.search(atual)
        if match is None:
            break
        if numero is None:
            numero = _numero_do_match(match)
        atual = atual[: match.start()].rstrip()
    if atual == titulo:
        return titulo, None
    return atual, numero


@dataclass(frozen=True, slots=True)
class PosicaoNaSerie:
    """Posição de uma temporada dentro da franquia — resultado de
    `conciliar_posicao`, gravado em `Anime.numero_temporada`/`Anime.serie_ancora`
    por `db/catalogo.py::aplicar_posicao_na_serie`."""

    numero_temporada: int | None
    serie_ancora: int | None


def conciliar_posicao(
    *,
    marcador: int | None,
    ordinal_do_grafo: int | None,
    ancora_do_grafo: int | None,
    anilist_id: int | None,
) -> PosicaoNaSerie:
    """Concilia o número de temporada do marcador do título (`separar_temporada`)
    com o resultado do walk de `relations`
    (`integrations/servico.py::resolver_serie`).

    Regra única: **o marcador do título sempre vence** — é o número que o
    produtor literalmente nomeou, e é a mesma convenção comercial que a fonte
    (AnimeFire) usa para numerar `seasons[]`. O grafo só preenche o vazio:

    - `numero_temporada` = `marcador` se existir, senão `ordinal_do_grafo` (pode
      seguir `None`; para o contrato do adapter de fonte, `None` = "não recorta").
    - `serie_ancora` = `ancora_do_grafo`, exceto: `None` quando o grafo não
      resolveu nada; e `None` quando o marcador indica temporada >= 2 mas a
      âncora do grafo é o próprio `anilist_id` (guarda anti-auto-âncora — o walk
      não achou prequel apesar de o título dizer T2+; ancorar em si mesmo faria
      dessa temporada um card de franquia próprio na Fase 5). Âncora igual ao
      próprio id COM ordinal 1 e sem marcador é mantida: é anime de temporada
      única legítimo, e é essa âncora que faz o recorte funcionar na T1.

    Divergência entre `marcador` e `ordinal_do_grafo` não é resolvida aqui (fica
    o marcador); cabe ao chamador logá-la — este módulo é domínio puro, sem
    logging.
    """
    numero_temporada = marcador if marcador is not None else ordinal_do_grafo

    serie_ancora = ancora_do_grafo
    if (
        serie_ancora is not None
        and marcador is not None
        and marcador >= 2
        and ancora_do_grafo == anilist_id
    ):
        serie_ancora = None

    return PosicaoNaSerie(numero_temporada=numero_temporada, serie_ancora=serie_ancora)


def _numero_do_match(match: re.Match[str]) -> int | None:
    """Extrai o número de temporada do grupo nomeado que casou em `match`,
    ou `None` quando o marcador casado é dos que só descartam (Part/Cour/
    TV/ano)."""
    grupos = match.groupdict()
    for chave in ("num_season_n", "num_n_season", "num_temporada_a", "num_temporada_b"):
        valor = grupos.get(chave)
        if valor is not None:
            return int(valor)
    romano = grupos.get("romano")
    if romano is not None:
        return _MAPA_ROMANO[romano.upper()]
    return None

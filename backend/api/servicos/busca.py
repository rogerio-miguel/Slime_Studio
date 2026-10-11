"""Orquestração de `GET /api/animes/buscar-fontes` que cruza `fontes/` ×
`integrations/` — único ponto que importa os dois lados da fronteira pra este
fluxo, mesma decisão de `api/servicos/descoberta.py`/`fontes.py` (CLAUDE.md
§1: `fontes/` NUNCA importa de `integrations/`, e vice-versa; orquestração
cross-camada mora aqui).

Uma função pública, `buscar_em_todas_as_fontes_com_titulos_alternativos`, que
serve o diálogo "Trocar fonte": resolve o anime canônico no provedor de
metadados (AniList) UPFRONT (`_resolver_titulos_canonicos`), monta a escada de
termos combinada dos vários idiomas (`_termos_de_busca`) e a lista de
referências de validação multi-idioma (`_referencias_de_anime`), e faz Fase 1
PARALELA (cada site esgotando a escada de forma independente, validação
multi-referência via `correspondencia.py`). Devolve a UNIÃO das fontes onde o
anime realmente existe.

A busca da Home NÃO passa mais por aqui — virou busca direta na AniList
(`GET /api/animes/buscar`, `integrations.servico.listar_por_busca`); a
resolução de fonte da Home ficou preguiçosa, na página do anime.

Infra:

- `variantes_de_busca` de `fontes.busca.termos` — gerador de variantes de
  regex;
- `_referencias_de_anime` (todos os nomes do anime para `referencias=` da
  validação de card) e `_termos_de_busca` (escada combinada dos idiomas);
- `_completar_nao_consultados` — todo `EXTRATORES` aparece na saída, mesmo o
  site que não chegou a ser consultado (senão a UI que checa "todas as fontes
  indisponíveis" mentiria);
- teto `_TETO_METADADOS_S` (o round-trip de `buscar_titulos`);
- caráter best-effort do metadado de provedor: falha ou timeout nunca derruba a
  busca nos sites, que segue só com o título digitado.

Candidato de busca em fonte não carrega capa: `fontes/` é só extração de
VÍDEO (`ResultadoBusca` não tem `capa_url`) e o diálogo "Trocar fonte" lista
os candidatos só por nome/site/versão. A capa do anime é resolvida na
materialização (`criar_anime` -> `enriquecer_anime_criado`), não aqui.
"""

import asyncio
import logging
import time

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.texto import slugificar
from fontes.adaptadores.registro import EXTRATORES
from fontes.busca import servico as servico_fontes
from fontes.busca.servico import ResultadoDeFonte
from fontes.busca.termos import escada_combinada, variantes_de_busca
from integrations import servico as servico_metadados
from integrations.base import TitulosDeAnime

logger = logging.getLogger(__name__)

_SessionMaker = async_sessionmaker[AsyncSession]

# Sub-teto só de `buscar_titulos`:
# `_resolver_titulos_canonicos` roda como `wait_for` separado, UPFRONT, porque a
# escada de termos da Fase 1 (`_termos_de_busca`) já depende do título canônico.
# Sem este teto, uma AniList pendurada seguraria a busca nos sites de extração
# antes de a primeira rodada de scraping sequer começar.
#
# `buscar_titulos` percorre só `PROVEDORES_DE_TITULO` (AniList — ver
# `integrations/registro.py`), então o pior caso é UM provedor lento, não dois:
# o `_chamar` interno de `integrations/servico.py` já estoura em
# `_TIMEOUT_POR_PROVEDOR_S` (8s) e a cadeia degrada para `FalhaDeMetadados` ->
# `None`. Este teto externo fica logo acima disso (9s, era 10s quando a cadeia
# ainda caía para o Kitsu aqui) só para garantir que o timeout interno por
# provedor dispare primeiro — o mesmo racional do próprio
# `_TIMEOUT_POR_PROVEDOR_S` ser > o timeout de `requests` de cada adapter.
_TETO_METADADOS_S = 9


async def _resolver_titulos_canonicos(titulo: str) -> TitulosDeAnime | None:
    """Resolve o anime canônico para `titulo` só na AniList
    (`integrations.servico.buscar_titulos` percorre apenas `PROVEDORES_DE_TITULO`
    — Kitsu não entra aqui, ver o comentário da tupla em `integrations/registro.py`)
    — a base de `_referencias_de_anime` e `_termos_de_busca`.

    Best-effort: qualquer falha (rede, timeout de `_TETO_METADADOS_S`, AniList
    fora do ar, formato inesperado) degrada para `None` e a busca segue só com
    o título digitado como referência. Captura ampla e intencional (CLAUDE.md §4
    — degrada explícito com `logger.warning`, não silencioso): resolver o
    canônico é enriquecimento, não pré-condição; o provedor fora do ar não pode
    derrubar a busca nos sites de extração."""
    try:
        return await asyncio.wait_for(
            servico_metadados.buscar_titulos(titulo), timeout=_TETO_METADADOS_S
        )
    except Exception as excecao:
        logger.warning(
            "resolução de título canônico best-effort falhou para título %r: %s",
            titulo,
            excecao,
        )
        return None


# --- Busca combinada paralela em todos os sites ---

# Cache em memória do resultado de "Trocar fonte", por título digitado: reabrir o
# diálogo ou voltar de outra temporada refazia dezenas de requests idênticos aos
# sites. Só guarda resposta COMPLETA e positiva (todo site consultado e disponível e ao menos
# um candidato) — "não achei" e "não consegui tentar" nunca ficam presos, porque o
# usuário que busca de novo espera uma tentativa de verdade. Vive só no processo da
# API (some no restart) e é limitado em tamanho.
_TTL_CACHE_DE_BUSCA_S = 120
_MAXIMO_ENTRADAS_CACHE_DE_BUSCA = 64
_relogio = time.monotonic
_cache_de_busca: dict[str, tuple[float, list[ResultadoDeFonte]]] = {}


def _chave_do_cache_de_busca(titulo: str) -> str:
    return slugificar(titulo) or titulo.strip().casefold()


async def buscar_em_todas_as_fontes_com_titulos_alternativos(
    sessionmaker: _SessionMaker, titulo: str
) -> list[ResultadoDeFonte]:
    """`_buscar_em_todas_as_fontes` com o cache de `_cache_de_busca` por cima."""
    chave = _chave_do_cache_de_busca(titulo)
    agora = _relogio()
    guardado = _cache_de_busca.get(chave)
    if guardado is not None and agora - guardado[0] < _TTL_CACHE_DE_BUSCA_S:
        return guardado[1]

    resultado = await _buscar_em_todas_as_fontes(sessionmaker, titulo)

    completo = not any(f.indisponivel or f.motivo == _MOTIVO_NAO_CONSULTADO for f in resultado)
    if completo and any(f.candidatos for f in resultado):
        _cache_de_busca[chave] = (_relogio(), resultado)
        while len(_cache_de_busca) > _MAXIMO_ENTRADAS_CACHE_DE_BUSCA:
            del _cache_de_busca[next(iter(_cache_de_busca))]  # a mais antiga (ordem de inserção)
    else:
        _cache_de_busca.pop(chave, None)
    return resultado


async def _buscar_em_todas_as_fontes(
    sessionmaker: _SessionMaker, titulo: str
) -> list[ResultadoDeFonte]:
    """Devolve a UNIÃO de todas as fontes que realmente têm o anime — busca
    paralela em todos os sites, cada um esgotando sua própria escada de
    variantes de forma independente e exaustiva
    (`fontes.busca.servico.buscar_por_site_com_variantes`): nenhum site
    interrompe ou "rouba a vez" da busca dos outros. A validação de card
    (`fontes/busca/correspondencia.py::corresponde_a_alguma_referencia`
    sobre todos os nomes do anime) vem embutida em `buscar_em_com_variantes`.
    Serve o diálogo "Trocar fonte", que mostra as alternativas lado a lado.

    1. `_resolver_titulos_canonicos` (best-effort sob `_TETO_METADADOS_S`) —
       `None` degrada para só o título digitado como referência/termo, não
       derruba a busca.
    2. `referencias` (`_referencias_de_anime` — todos os nomes do anime) e
       `termos` (`_termos_de_busca` — escada combinada de romaji + inglês +
       digitado, deduplicada por slug).
    3. `buscar_por_site_com_variantes` com a escada combinada em TODOS os sites
       em paralelo, cada um esgotando a escada.

    Havia uma Fase 2 (reexpandir os sites sem candidato com cada título canônico
    isolado) que a escada combinada já tornava redundante — não tocava a rede e
    segurava um teto de 190s à toa; foi removida. O bug que a motivou ("Dogul
    Wang", 2026-08-29: um site achar pela escada de regex impedia o segundo de
    ser consultado com o título inglês do provedor) é coberto por a escada
    combinada incluir o título inglês de cada site desde a 1ª varredura.
    """
    titulos = await _resolver_titulos_canonicos(titulo)
    referencias = _referencias_de_anime(titulos, titulo)
    termos = _termos_de_busca(titulos, titulo)

    resultado_por_dominio = await servico_fontes.buscar_por_site_com_variantes(
        sessionmaker, termos, referencias=referencias
    )
    return _completar_nao_consultados(resultado_por_dominio)


_MOTIVO_NAO_CONSULTADO = "não consultado"


def _completar_nao_consultados(
    resultados: dict[str, ResultadoDeFonte],
) -> list[ResultadoDeFonte]:
    """Saída na ordem de `EXTRATORES`. `resultados` pode não ter entrada pra todo
    site; o contrato da API precisa listar todos os domínios mesmo assim (senão a
    UI que checa "todas as fontes indisponíveis" mentiria) — o ausente sai como
    `indisponivel=False, candidatos=[], motivo="não consultado"`."""
    finais = []
    for extrator in EXTRATORES:
        if extrator.dominio in resultados:
            finais.append(resultados[extrator.dominio])
        else:
            finais.append(
                ResultadoDeFonte(
                    dominio=extrator.dominio,
                    candidatos=[],
                    indisponivel=False,
                    motivo=_MOTIVO_NAO_CONSULTADO,
                )
            )
    return finais


def _referencias_de_anime(titulos: TitulosDeAnime | None, titulo: str) -> list[str]:
    """Todos os nomes conhecidos do anime, para passar como `referencias=` à
    validação de card
    (`fontes/busca/correspondencia.py::corresponde_a_alguma_referencia`): o
    card devolvido pelo site pode estar grafado em qualquer um dos nomes do
    anime (romaji, inglês, nativo, sinônimo de provedor) e basta bater com um —
    validar só contra o título digitado rejeitaria o card certo quando o site
    indexa outro idioma.

    Ordem: `titulo` (o digitado) primeiro — é a âncora, o único nome que
    sabemos ser o que o usuário quis; depois `titulo_romaji`, `titulo_ingles`,
    `titulo_nativo` e cada `sinonimo` na ordem que o provedor devolveu.

    `titulo` fica na lista mesmo que slugifique pra vazio (título só em kanji —
    improvável no campo digitado, mas `corresponde_a_alguma_referencia` já
    degrada pra aceitar quando a referência não tem chave de comparação, então
    mantê-lo é inócuo e preserva a âncora). Todo OUTRO candidato cujo slug
    (`core/texto.py::slugificar`) seja vazio é descartado: `titulo_nativo` em
    kanji vira chave vazia e `corresponde_a_alguma_referencia` compara por
    contenção de chave normalizada — chave vazia não valida nem rejeita nada,
    só entra como ruído. Duplicata por chave `slugificar` também sai (o título
    digitado em caixa baixa e o romaji do provedor em Title Case colapsam numa
    referência só), assim como `None` e string em branco. A tolerância mais
    forte — espaço vs. grafia colada, "Dogul Wang" vs "DogulWang" — é de
    `corresponde_a_alguma_referencia` (que remove o hífen do slug), não deste
    filtro: manter as duas grafias na lista aqui é redundância inócua, não bug.

    `titulos is None` (o provedor não achou o anime) → só `[titulo]`.
    """
    if titulos is None:
        return [titulo]

    referencias = [titulo]
    slugs_vistos: set[str] = {slugificar(titulo)}
    candidatos = (
        titulos.titulo_romaji,
        titulos.titulo_ingles,
        titulos.titulo_nativo,
        *titulos.sinonimos,
    )
    for candidato in candidatos:
        if candidato is None:
            continue
        slug = slugificar(candidato)
        if not slug or slug in slugs_vistos:
            continue
        slugs_vistos.add(slug)
        referencias.append(candidato)
    return referencias


def _termos_de_busca(titulos: TitulosDeAnime | None, titulo: str) -> list[str]:
    """Escada de termos de busca combinada dos vários idiomas do anime, pra
    varrer os sites de extração — concatena a escada de `variantes_de_busca`
    (`fontes/busca/termos.py`, o mesmo gerador da Fase 1) de cada idioma.

    Ordem: por degrau (`fontes/busca/termos.py::escada_combinada` — todos os
    títulos completos, depois todos os cortes, por último os prefixos) e, dentro
    do degrau, `titulo_romaji`, `titulo_ingles`, `titulo` (o digitado) — romaji
    primeiro porque os sites de streaming indexam romaji com mais frequência
    que qualquer outra grafia. A ordem aqui é só a heurística de "qual termo
    tende a fazer o card certo aparecer primeiro"; a PRECISÃO não vem desta
    lista e sim da validação multi-referência
    (`corresponde_a_alguma_referencia` sobre `_referencias_de_anime`) e do
    desempate de `proximidade_a_referencias`, que rodam sobre os cards achados.

    `titulo_nativo` e `sinonimos` NÃO entram (ao contrário de
    `_referencias_de_anime`, onde entram): nativo em kanji slugifica pra vazio
    e não é termo de busca nenhum; sinônimo de provedor (abreviação, título
    regional) é ruidoso demais como termo — dispararia scraping à toa — e só
    presta como referência de validação depois que o card já apareceu.

    Dedup final por chave `core/texto.py::slugificar`, preservando a primeira
    ocorrência (a escada do romaji vence as repetições nas escadas seguintes).
    Nunca vazia — `titulo` sempre contribui pelo menos a si mesmo.

    `titulos is None` (o provedor não achou o anime) → `variantes_de_busca(titulo)`.
    """
    if titulos is None:
        return variantes_de_busca(titulo)

    return escada_combinada(
        [idioma for idioma in (titulos.titulo_romaji, titulos.titulo_ingles, titulo) if idioma]
    )

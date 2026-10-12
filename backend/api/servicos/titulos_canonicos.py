"""Nomes canônicos do anime (AniList) como insumo de busca e de validação nas
fontes: resolve os títulos, monta as referências de validação multi-idioma e a
escada de termos de busca. Compartilhado por `api/servicos/busca.py` ("Trocar
fonte") e `api/servicos/fontes.py` (resolução de fonte) — cruza `integrations/`
(`buscar_titulos`) com `fontes/` (`variantes_de_busca`), por isso mora aqui e não
em nenhum dos dois pacotes (CLAUDE.md §1).
"""

import asyncio
import logging

from core.texto import slugificar
from fontes.busca.termos import escada_combinada, variantes_de_busca
from integrations import servico as servico_metadados
from integrations.base import TitulosDeAnime

logger = logging.getLogger(__name__)

# Sub-teto só de `buscar_titulos`:
# `resolver_titulos_canonicos` roda como `wait_for` separado, UPFRONT, porque a
# escada de termos da Fase 1 (`termos_de_busca`) já depende do título canônico.
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


async def resolver_titulos_canonicos(titulo: str) -> TitulosDeAnime | None:
    """Resolve o anime canônico para `titulo` só na AniList
    (`integrations.servico.buscar_titulos` percorre apenas `PROVEDORES_DE_TITULO`
    — Kitsu não entra aqui, ver o comentário da tupla em `integrations/registro.py`)
    — a base de `referencias_de_anime` e `termos_de_busca`.

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


def referencias_de_anime(titulos: TitulosDeAnime | None, titulo: str) -> list[str]:
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


def termos_de_busca(titulos: TitulosDeAnime | None, titulo: str) -> list[str]:
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
    (`corresponde_a_alguma_referencia` sobre `referencias_de_anime`) e do
    desempate de `proximidade_a_referencias`, que rodam sobre os cards achados.

    `titulo_nativo` e `sinonimos` NÃO entram (ao contrário de
    `referencias_de_anime`, onde entram): nativo em kanji slugifica pra vazio
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

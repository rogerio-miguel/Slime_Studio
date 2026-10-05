"""Orquestração de `GET /api/animes/buscar-fontes` que cruza `extractors/` ×
`integrations/` — único ponto que importa os dois lados da fronteira pra este
fluxo, mesma decisão de `api/servicos/descoberta.py`/`fontes.py` (CLAUDE.md
§1: `extractors/` NUNCA importa de `integrations/`, e vice-versa; orquestração
cross-camada mora aqui).

Uma função pública, `buscar_em_todas_as_fontes_com_titulos_alternativos`, que
serve o diálogo "Trocar fonte": resolve o anime canônico no provedor de
metadados (AniList) UPFRONT (`_resolver_titulos_canonicos`), monta a escada de
termos combinada dos vários idiomas (`_termos_de_busca`) e a lista de
referências de validação multi-idioma (`_referencias_de_anime`), e faz Fase 1
PARALELA (cada site esgotando a escada de forma independente, validação
multi-referência via `correspondencia.py`), seguida de Fase 2 por termo de
provedor (romaji/inglês, best-effort) enquanto sobrar site pendente. Devolve a
UNIÃO das fontes onde o anime realmente existe.

A busca da Home NÃO passa mais por aqui — virou busca direta na AniList
(`GET /api/animes/buscar`, `integrations.servico.listar_por_busca`); a
resolução de fonte da Home ficou preguiçosa, na página do anime.

Bug real que o gate por-site da Fase 2 resolve (2026-08-29): com gate global,
"Dogul Wang" achado no site padrão pela escada de regex impedia o segundo site
de ser consultado com o título inglês do provedor ("Tomb Raider King"), onde o
anime existe — o diálogo listava uma fonte só. A escada combinada da Fase 1
hoje cobre esse caso já na Fase 1; a Fase 2 virou redundante e está rastreada
para remoção — ver `_expandir_com_termos_de_provedor_em_todas_as_fontes`.

Infra:

- `variantes_de_busca` de `extractors.busca.termos` — gerador de variantes de
  regex;
- `_referencias_de_anime` (todos os nomes do anime para `referencias=` da
  validação de card) e `_termos_de_busca` (escada combinada dos idiomas);
- `_completar_nao_consultados` — todo `EXTRATORES` aparece na saída, mesmo o
  site que não chegou a ser consultado (senão a UI que checa "todas as fontes
  indisponíveis" mentiria);
- tetos: `_TETO_METADADOS_S` (só o round-trip de `buscar_titulos`) e
  `_TETO_EXPANSAO_S` (o trabalho de rede best-effort da Fase 2);
- caráter best-effort do trabalho de provedor/Fase 2: falha, timeout ou
  qualquer outro erro nunca propaga pra fora nem derruba a Fase 1 já obtida.

Candidato de busca em fonte não carrega capa: `extractors/` é só extração de
VÍDEO (`ResultadoBusca` não tem `capa_url`) e o diálogo "Trocar fonte" lista
os candidatos só por nome/site/versão. A capa do anime é resolvida na
materialização (`criar_anime` -> `enriquecer_anime_criado`), não aqui.
"""

import asyncio
import logging
import time

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.texto import slugificar
from extractors.busca import servico as servico_extractors
from extractors.busca.servico import ResultadoDeFonte
from extractors.busca.termos import escada_combinada, variantes_de_busca
from extractors.registro import EXTRATORES
from integrations import servico as servico_metadados
from integrations.base import TitulosDeAnime

logger = logging.getLogger(__name__)

_SessionMaker = async_sessionmaker[AsyncSession]

# Teto do trabalho de rede best-effort da Fase 2 (só ela — a Fase 1 e o
# round-trip de `buscar_titulos` rodam FORA deste orçamento). `wait_for`
# externo que, ao estourar, devolve o que a Fase 1 já obteve em vez de travar a
# resposta.
#
# Perfil "Fase 2, escada por termo de provedor":
# `_expandir_com_termos_de_provedor_em_todas_as_fontes` tenta até 2 termos de
# provedor (romaji, inglês), cada um gerando a PRÓPRIA escada de variantes
# (`extractors/busca/termos.py::variantes_de_busca` — até 3 termos de precisão
# + até `_MAXIMO_PREFIXOS`=3 prefixos de recall, 6 variantes no pior caso),
# tentados termo a termo em SEQUÊNCIA (sites em PARALELO dentro de cada termo,
# não multiplicam). Cada variante custa até o timeout do GET síncrono dos
# adapters (`_TIMEOUT_S` de `extractors/animefire.py` etc., 15s). Conta: até
# 2 × (6 × 15s) = 180s, dentro dos 190. A Fase 2 hoje é redundante (a escada
# combinada da Fase 1 já a domina — ela nem chega a tocar a rede), mas o teto
# fica no valor da conta enquanto a Fase 2 existir.
#
# A variância de captura de navegador de um site com challenge (até 90s) é um
# risco estrutural separado — fora do escopo desta conta.
_TETO_EXPANSAO_S = 190

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


# --- Fase 1 combinada paralela + Fase 2 (expansão por termo de provedor) ---
# Fase 2 mora em `_expandir_com_termos_de_provedor_em_todas_as_fontes` — hoje
# redundante (a escada combinada da Fase 1 já a domina), mantida até uma fatia
# de remoção própria.
# Cache em memória do resultado de "Trocar fonte", por título digitado: reabrir o
# diálogo ou voltar de outra temporada refazia dezenas de requests idênticos aos
# sites. Só guarda resposta COMPLETA e positiva (nenhum site indisponível e ao menos
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
    (`extractors.busca.servico.buscar_por_site_com_variantes`): nenhum site
    interrompe ou "rouba a vez" da busca dos outros. A validação de card
    (`extractors/busca/correspondencia.py::corresponde_a_alguma_referencia`
    sobre todos os nomes do anime) vem embutida em `buscar_em_com_variantes`.
    Serve o diálogo "Trocar fonte", que mostra as alternativas lado a lado.

    1. `_resolver_titulos_canonicos` (best-effort sob `_TETO_METADADOS_S`) —
       `None` degrada para só o título digitado como referência/termo, não
       derruba a busca.
    2. `referencias` (`_referencias_de_anime` — todos os nomes do anime) e
       `termos` (`_termos_de_busca` — escada combinada de romaji + inglês +
       digitado, deduplicada por slug).
    3. Fase 1: `buscar_por_site_com_variantes` com a escada combinada em TODOS
       os sites em paralelo, cada um esgotando a escada.
    4. Fase 2 (`_expandir_com_termos_de_provedor_em_todas_as_fontes`,
       best-effort sob `_TETO_EXPANSAO_S`): enquanto sobrar site PENDENTE (não
       `indisponivel` e sem candidato), reexpande só os pendentes com cada
       título canônico isolado. REDUNDANTE desde que a Fase 1 passou a varrer
       a escada combinada — mantida por segurança, rastreada para remoção.

    O gate da Fase 2 é POR-SITE, não global — bug real 2026-08-29 ("Dogul
    Wang"): com gate global, um site achar pela escada de regex pulava a Fase
    2 inteira e o segundo site nunca era consultado com o título inglês do
    provedor ("Tomb Raider King"), onde o anime existe — o diálogo listava uma
    fonte só. A escada combinada da Fase 1 hoje cobre esse caso já na Fase 1.
    """
    titulos = await _resolver_titulos_canonicos(titulo)
    referencias = _referencias_de_anime(titulos, titulo)
    termos = _termos_de_busca(titulos, titulo)

    resultado_por_dominio = await servico_extractors.buscar_por_site_com_variantes(
        sessionmaker, termos, referencias=referencias
    )
    resultado = _completar_nao_consultados(resultado_por_dominio)

    # Mesmo critério do `pendentes` de `_expandir_com_termos_de_provedor_em_
    # todas_as_fontes`: site sem candidato e ainda disponível é trabalho em
    # aberto pro contrato de UNIÃO, mesmo com outro site já tendo achado. Gate
    # mais frouxo que esse filtro desperdiça rede; mais estrito pula a Fase 2 e
    # o site pendente nunca é consultado (bug real, ver docstring de módulo).
    algum_site_pendente = any(
        not fonte.indisponivel and not fonte.candidatos for fonte in resultado
    )
    if algum_site_pendente:
        slugs_fase1 = {slugificar(v) for v in termos}
        try:
            expandido = await asyncio.wait_for(
                _expandir_com_termos_de_provedor_em_todas_as_fontes(
                    sessionmaker, titulo, titulos, resultado, slugs_fase1
                ),
                timeout=_TETO_EXPANSAO_S,
            )
        except Exception as excecao:
            # Captura ampla e intencional: a expansão da Fase 2 é best-effort —
            # timeout do lote de scraping ou qualquer outro erro não pode
            # derrubar a busca da Fase 1 (o metadado já foi resolvido upfront,
            # fora daqui).
            logger.warning(
                "expansão por termo de provedor best-effort falhou para título %r: %s",
                titulo,
                excecao,
            )
            expandido = None
        if expandido is not None:
            resultado = expandido

    return resultado


async def _expandir_com_termos_de_provedor_em_todas_as_fontes(
    sessionmaker: _SessionMaker,
    titulo: str,
    titulos: TitulosDeAnime | None,
    resultado_fase1: list[ResultadoDeFonte],
    slugs_fase1: set[str],
) -> list[ResultadoDeFonte] | None:
    """Fase 2 (best-effort): reexpande os sites ainda PENDENTES com cada título
    canônico do provedor isoladamente. Contrato de saída: a UNIÃO das fontes.

    Recebe `titulos` JÁ resolvido pelo chamador (`_resolver_titulos_canonicos`,
    upfront, uma vez só — compartilhado com a montagem da Fase 1); NÃO refaz o
    round-trip de metadados. `titulos is None` → `None` (o chamador mantém a
    Fase 1).

    `_termos_alternativos` uma vez (romaji, depois inglês, descartando o que
    repete o digitado); por termo: `pendentes` recalculado (não `indisponivel`
    e sem candidato de termo anterior), escada própria (`variantes_de_busca`)
    filtrada pelo dedupe de `slugs_fase1`, fan-out `buscar_por_site_com_
    variantes` só nos `pendentes` (`dominios=`, evita reconsultar quem já
    respondeu), referência isolada `[termo]`. Só passa pro próximo termo se
    ainda sobrar pendente.

    REDUNDANTE na prática: `slugs_fase1 = {slugificar(v) for v in termos}` e
    `termos` (`_termos_de_busca`) já concatena as escadas de romaji e inglês —
    então `_variantes_sem_repetir_fase1` esvazia a escada de todo termo aqui e
    esta função retorna `None` sem tocar a rede. Mantida intacta na fatia d3
    (Fase 1 combinada + dedupe correto); a remoção — desta função, de
    `_termos_alternativos` e do gate — é uma fatia própria do orquestrador.

    `None` quando o provedor não resolveu `titulos`, quando `_termos_
    alternativos` degrada para vazio (romaji/inglês repetem o digitado ou
    slugificam para vazio), ou quando nenhum termo achou candidato novo — o
    chamador mantém o resultado (intacto) da Fase 1."""
    if titulos is None:
        return None
    termos = _termos_alternativos(titulos, titulo)
    if not termos:
        return None

    por_dominio = {fonte.dominio: fonte for fonte in resultado_fase1}
    algum_termo_achou = False

    for termo in termos:
        pendentes = [
            dominio
            for dominio, fonte in por_dominio.items()
            if not fonte.indisponivel and not fonte.candidatos
        ]
        if not pendentes:
            break  # todo site já achou candidato ou ficou indisponível
        variantes_termo = _variantes_sem_repetir_fase1(variantes_de_busca(termo), slugs_fase1)
        if not variantes_termo:
            continue  # a escada combinada da Fase 1 já varreu toda a escada deste termo
        resposta_por_dominio = await servico_extractors.buscar_por_site_com_variantes(
            sessionmaker, variantes_termo, referencias=[termo], dominios=pendentes
        )
        por_dominio.update(resposta_por_dominio)
        if any(fonte.candidatos for fonte in resposta_por_dominio.values()):
            algum_termo_achou = True

    if not algum_termo_achou:
        return None
    return _completar_nao_consultados(por_dominio)


_MOTIVO_NAO_CONSULTADO = "não consultado"


def _completar_nao_consultados(
    resultados: dict[str, ResultadoDeFonte],
) -> list[ResultadoDeFonte]:
    """`resultados` pode não ter entrada pra todo `EXTRATORES` — um fan-out
    best-effort cancelado por timeout pode não ter resposta pra todo site. O
    contrato de saída da API precisa listar todos os domínios mesmo assim
    (senão a UI que checa "todas as fontes indisponíveis" mentiria) — o não
    consultado sai como `indisponivel=False, candidatos=[], motivo="não
    consultado"`."""
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


def _termos_alternativos(titulos: TitulosDeAnime, titulo_original: str) -> list[str]:
    """Ordem: romaji, depois inglês. Descarta por chave `core/texto.py::slugificar`
    o que repete o termo digitado e o que slugifica pra vazio (kanji)."""
    slug_original = slugificar(titulo_original)
    candidatos = [titulos.titulo_romaji, titulos.titulo_ingles]

    termos: list[str] = []
    slugs_vistos: set[str] = {slug_original}
    for candidato in candidatos:
        if candidato is None:
            continue
        slug = slugificar(candidato)
        if not slug or slug in slugs_vistos:
            continue
        slugs_vistos.add(slug)
        termos.append(candidato)
    return termos


def _referencias_de_anime(titulos: TitulosDeAnime | None, titulo: str) -> list[str]:
    """Todos os nomes conhecidos do anime, para passar como `referencias=` à
    validação de card
    (`extractors/busca/correspondencia.py::corresponde_a_alguma_referencia`): o
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
    (`extractors/busca/termos.py`, o mesmo gerador da Fase 1) de cada idioma.

    Ordem: por degrau (`extractors/busca/termos.py::escada_combinada` — todos os
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


def _variantes_sem_repetir_fase1(variantes: list[str], slugs_fase1: set[str]) -> list[str]:
    """Filtra a escada de variantes de um termo de provedor (`variantes_de_busca`),
    removendo qualquer entrada cujo slug (`core/texto.py::slugificar`) já foi
    tentado na Fase 1 (`variantes_puras` do título digitado) — dedupe entre
    fases: nunca reconsulta um site com exatamente o mesmo termo de busca que
    a Fase 1 já tentou e não achou."""
    return [variante for variante in variantes if slugificar(variante) not in slugs_fase1]

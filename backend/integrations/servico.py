"""Serviço de metadados externos: cadeia de fallback AniList -> Kitsu com
timeout por provedor, e cache em memória de processo do feed "em alta".

Também orquestra o overlay de arte (capa/banner) de TMDB por cima do
resultado de metadados/feed, ANTES de gravar qualquer cache — ver a seção
"overlay de arte" no fim do arquivo e `PLANO_ARTE_TMDB.md` (D4) para o
racional completo (memo próprio, latch de autenticação, mecânica de lote). A
seção "overlay de still de episódio" logo depois (Fatia 5 do mesmo plano)
expõe `buscar_still_de_episodio`, consumido por
`api/servicos/fontes.py::listar_episodios_remotos` — não um dos 5 pontos de
montagem acima, é chamado por episódio, não por registro de metadados/feed.

Único lugar de `integrations/` com `asyncio.to_thread`/`asyncio.wait_for`
(mesma separação de `extractors/resiliencia.py` para os extratores de site).

Cache do feed "em alta": sem precedente de cache em memória no projeto — os
dois candidatos óbvios (`extractors/circuit_breaker.py`,
`extractors/sessao_cache.py`) são ambos persistidos em SQLite, o que não se
aplica aqui (não há necessidade de sobreviver a restart de processo para um
cache de 1h de um feed público). Uma variável de módulo com timestamp resolve
sem introduzir Redis nem um novo padrão de infraestrutura.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import replace

import requests

from core.erros import FalhaDeMetadados
from core.texto import slugificar
from integrations.base import (
    AnimeEmAlta,
    ArteDeAnime,
    FileiraTematica,
    LancamentoDeAnime,
    MetadadosDeAnime,
    ProvedorComFileirasTematicas,
    ProvedorComLancamento,
    ProvedorDeArte,
    ProvedorDeMetadados,
    TitulosDeAnime,
)
from integrations.registro import (
    FILEIRAS_TEMATICAS,
    PROVEDORES,
    PROVEDORES_DE_FEED,
    provedores_de_arte,
)
from integrations.tmdb import (
    TabelaDeTemporadas,
    TmdbNaoAutorizado,
    TmdbProvider,
    localizar_temporada,
)

logger = logging.getLogger(__name__)

# Teto curto por provedor: estas são APIs JSON públicas sem bypass (ao
# contrário de `extractors/resiliencia.py::_TETO_ESPERA_S`, que cobre até 2
# chamadas HTTP sequenciais de um adapter com bypass) — uma falha aqui deve
# liberar o próximo provedor da cadeia rápido.
#
# Precisa ser ESTRITAMENTE MAIOR que o timeout interno do `requests` de cada
# adapter (`integrations/anilist.py::_TIMEOUT_S` / `integrations/kitsu.py::
# _TIMEOUT_S`, hoje 6s): assim, quando um provedor só está lento (não erra),
# é a própria chamada `requests` que estoura primeiro — a thread do
# `to_thread` termina normalmente dentro da janela deste `wait_for` em vez de
# ficar órfã rodando no thread pool até o timeout dela mesma (`to_thread` não
# é cancelável pelo `wait_for`).
_TIMEOUT_POR_PROVEDOR_S: float = 8
_TTL_EM_ALTA_S = 3600
# Roster de temporada muda devagar (estreias/adiamentos, não trending diário) —
# TTL mais folgado que o de "em alta".
_TTL_PROXIMA_TEMPORADA_S = 6 * 3600
# Popularidade por tag muda mais devagar ainda que o roster de temporada (não é
# lançamento/estreia, é ranking de trending histórico por tag) — TTL mais
# folgado que os dois acima.
_TTL_FILEIRA_TEMATICA_S = 12 * 3600
# Teto de requisições simultâneas à AniList ao buscar as 10 `FILEIRAS_TEMATICAS`
# de uma vez (`listar_fileiras_tematicas`): nem sequencial (lento demais para a
# Home), nem as 10 em paralelo (risco de rate limit — mesma preocupação do
# comentário de `PROVEDORES_DE_FEED` em `registro.py`).
_CONCORRENCIA_FILEIRAS_TEMATICAS = 3

# Overlay de arte (TMDB, PLANO_ARTE_TMDB.md D4) — TTL do memo >= o maior TTL de
# feed acima (`_TTL_FILEIRA_TEMATICA_S`, 12h): um feed já cacheado nunca
# re-pergunta ao TMDB dentro da própria vida.
_TTL_ARTE_S = 12 * 3600
# 3 fileiras simultâneas (`_CONCORRENCIA_FILEIRAS_TEMATICAS`) × 6 = 18 req/s de
# pico, folgado no teto do TMDB.
_CONCORRENCIA_ARTE = 6
_TETO_LOTE_ARTE_S = 20
_LIMITE_MEMO_ARTE = 4000

# Exceções esperadas de um provedor (rede, HTTP >=400 incluindo 429, timeout
# de `wait_for`, ou formato de resposta inesperado que o adapter sinaliza com
# `RuntimeError`) — qualquer outra exceção é bug do adapter, não "provedor
# fora do ar", e deve propagar em vez de ser engolida pela cadeia de fallback.
_ERROS_DE_PROVEDOR: tuple[type[Exception], ...] = (
    requests.RequestException,
    RuntimeError,
    TimeoutError,
)

# `(expira_em_monotonic, itens)` — `None` até o primeiro sucesso.
_cache_em_alta: tuple[float, list[AnimeEmAlta]] | None = None

# Guarda a seção "checar cache -> buscar se expirado -> gravar cache" de
# `listar_em_alta` contra rajada concorrente (thundering herd): sem isto, N
# requisições simultâneas durante uma janela de cache-miss disparariam N
# buscas reais aos provedores em paralelo, agravando o risco de rate-limit
# do AniList (§9 do documento de especificação).
_lock_em_alta = asyncio.Lock()

# `(expira_em_monotonic, itens)` — `None` até o primeiro sucesso. Cache/lock
# próprios (independentes dos de "em alta"): é outro feed, outro TTL.
_cache_proxima_temporada: tuple[float, list[AnimeEmAlta]] | None = None
_lock_proxima_temporada = asyncio.Lock()

# Cache/lock POR FILEIRA (não um par global como acima): cada uma das 10
# `FILEIRAS_TEMATICAS` é buscada e expira de forma independente — um lock
# global serializaria a busca de todas as fileiras entre si, e uma fileira
# lenta ou em cache-miss bloquearia as outras 9 sem necessidade. Chaves e locks
# pré-criados a partir de `FILEIRAS_TEMATICAS` (fixa, definida em
# `registro.py`) — sem criação preguiçosa de lock por chave, que exigiria sua
# própria proteção contra corrida.
_cache_fileiras_tematicas: dict[str, tuple[float, list[AnimeEmAlta]]] = {}
_locks_fileiras_tematicas: dict[str, asyncio.Lock] = {
    fileira.chave: asyncio.Lock() for fileira in FILEIRAS_TEMATICAS
}
_fileiras_por_chave: dict[str, FileiraTematica] = {
    fileira.chave: fileira for fileira in FILEIRAS_TEMATICAS
}

# Memo de processo do overlay de arte (D4): `(slug do título, ano) ->
# (expira_em_monotonic, ArteDeAnime | None)`. Com cache negativo — título que o
# TMDB não achou não é re-perguntado dentro do TTL. Ao ultrapassar
# `_LIMITE_MEMO_ARTE`, `_gravar_memo_arte` limpa o dict inteiro (política
# simples e correta, sem LRU). `tests/test_integrations_metadados.py` tem
# fixture autouse que zera isto entre testes (estado de módulo).
_memo_arte: dict[tuple[str, int | None], tuple[float, ArteDeAnime | None]] = {}

# Memo de dois níveis do overlay de still de episódio (Fatia 5,
# PLANO_ARTE_TMDB.md): `_memo_temporadas` cacheia a `TabelaDeTemporadas`
# (id da série TMDB + primeiro episódio absoluto de cada temporada) por
# (slug do título, ano) — evita repetir `_resolver_serie`+`GET /tv/{id}` por
# episódio. `_memo_still` cacheia o still final por (slug do título, ano,
# numero_absoluto); a primeira consulta de QUALQUER episódio de uma temporada
# popula o still de TODOS os episódios dela de uma vez
# (`TmdbProvider.stills_da_temporada` devolve a temporada inteira), então uma
# página com N episódios da mesma temporada paga só 1
# `GET /tv/{id}/season/{n}`. Mesmo TTL (`_TTL_ARTE_S`) e mesma política de
# limite (`_LIMITE_MEMO_ARTE`, limpa o dict inteiro ao estourar) do memo de
# arte acima. `tests/test_integrations_metadados.py` tem fixture autouse que
# zera os três memos entre testes.
_memo_temporadas: dict[tuple[str, int | None], tuple[float, TabelaDeTemporadas | None]] = {}
_memo_still: dict[tuple[str, int | None, int], tuple[float, str | None]] = {}

# Latch: liga na primeira `TmdbNaoAutorizado` (token errado/revogado) e nunca
# desliga sozinho — um token ruim não muda em runtime, só reiniciando o
# processo com um token corrigido. Evita dezenas de warnings por feed quando a
# má configuração já foi identificada uma vez (loga em ERROR só na virada).
_arte_desabilitada_por_auth = False


async def buscar_por_titulo(titulo: str) -> MetadadosDeAnime | None:
    """Tenta cada provedor de `PROVEDORES` em ordem até achar metadados para
    `titulo`; ver `_buscar_em_cadeia` para a semântica de fallback. Overlay de
    arte (TMDB) sobreposto antes de devolver — ver `_com_arte`/D4."""
    resultado = await _buscar_em_cadeia(
        lambda provedor: provedor.buscar_por_titulo, titulo, descricao="busca por título"
    )
    if resultado is None:
        return resultado
    titulo_arte = resultado.titulo_ingles or resultado.titulo_romaji or titulo
    return await _com_arte(resultado, titulo=titulo_arte, ano=resultado.ano)


async def buscar_titulos(titulo: str) -> TitulosDeAnime | None:
    """Tenta cada provedor de `PROVEDORES` em ordem até achar títulos
    alternativos (romaji/inglês) para `titulo` — usado por
    `api/servicos/busca.py` para reexpandir uma busca vazia nos sites de
    extração; ver `_buscar_em_cadeia` para a semântica de fallback."""
    return await _buscar_em_cadeia(
        lambda provedor: provedor.buscar_titulos, titulo, descricao="busca de títulos"
    )


async def buscar_lancamento_por_anilist_id(anilist_id: int) -> LancamentoDeAnime | None:
    """Estado de lançamento (status/próximo episódio) de um anime pelo seu id
    AniList. Só provedores que implementam `ProvedorComLancamento` entram na
    cadeia (hoje só o AniList — Kitsu não expõe next-airing).

    Mesma semântica de fallback de `_buscar_em_cadeia`: primeira resposta
    não-`None` vence; um provedor que levanta é logado e a cadeia segue para o
    próximo; só levanta `FalhaDeMetadados` se todos os provedores capazes
    falharem de fato. Se nenhum provedor é capaz, devolve `None` (condição
    estrutural, não "provedores fora do ar"). Sem cache — a frequência do
    refresh oportunista (F4) é controlada por quem chama.
    """
    capazes = [p for p in PROVEDORES if isinstance(p, ProvedorComLancamento)]
    if not capazes:
        return None

    algum_respondeu = False
    ultimo_erro: Exception | None = None
    for provedor in capazes:
        try:
            resultado = await _chamar(
                provedor, provedor.buscar_lancamento_por_anilist_id, anilist_id
            )
        except _ERROS_DE_PROVEDOR as excecao:
            logger.warning(
                "provedor de metadados %r falhou ao buscar lançamento de anilist_id=%s: %s",
                provedor.nome,
                anilist_id,
                excecao,
            )
            ultimo_erro = excecao
            continue

        algum_respondeu = True
        if resultado is not None:
            return resultado

    if algum_respondeu:
        return None
    raise FalhaDeMetadados(
        f"todos os provedores falharam ao buscar lançamento de anilist_id={anilist_id}"
    ) from ultimo_erro


async def buscar_metadados_por_anilist_id(anilist_id: int) -> MetadadosDeAnime | None:
    """Metadados completos (capa, banner, cor dominante da capa, sinopse) de um
    anime pelo seu id AniList — usado pelo backfill de arte visual
    (`scripts/backfill_metadados_visuais.py`).

    Mesma semântica de fallback de `buscar_lancamento_por_anilist_id`: primeira
    resposta não-`None` vence; um provedor que levanta é logado e a cadeia segue
    para o próximo; só levanta `FalhaDeMetadados` se TODOS os provedores falharem
    de fato (rede/HTTP/timeout). Provedores que não conhecem id AniList (Kitsu)
    devolvem `None` pela implementação padrão de `ProvedorDeMetadados` e a cadeia
    segue — se ninguém resolve, devolve `None` em vez de exceção. Sem cache (o
    cache TTL de `servico.py` é só para os feeds sazonais). Overlay de arte
    (TMDB) sobreposto antes de devolver — ver `_com_arte`/D4.
    """
    algum_respondeu = False
    ultimo_erro: Exception | None = None
    for provedor in PROVEDORES:
        try:
            resultado = await _chamar(
                provedor, provedor.buscar_metadados_por_anilist_id, anilist_id
            )
        except _ERROS_DE_PROVEDOR as excecao:
            logger.warning(
                "provedor de metadados %r falhou ao buscar metadados de anilist_id=%s: %s",
                provedor.nome,
                anilist_id,
                excecao,
            )
            ultimo_erro = excecao
            continue

        algum_respondeu = True
        if resultado is not None:
            titulo_arte = resultado.titulo_ingles or resultado.titulo_romaji
            return await _com_arte(resultado, titulo=titulo_arte, ano=resultado.ano)

    if algum_respondeu:
        return None
    raise FalhaDeMetadados(
        f"todos os provedores falharam ao buscar metadados de anilist_id={anilist_id}"
    ) from ultimo_erro


async def _buscar_em_cadeia[T](
    operacao: Callable[[ProvedorDeMetadados], Callable[[str], T | None]],
    titulo: str,
    *,
    descricao: str,
) -> T | None:
    """Tenta cada provedor de `PROVEDORES` em ordem, chamando `operacao(provedor)`
    com `titulo`. Um provedor que responde mas não encontra o título (`None`)
    não é falha — cai para o próximo provedor tentar, mesma filosofia de
    `extractors/resolucao.py` (busca vazia não é erro). Só levanta
    `FalhaDeMetadados` se todos os provedores falharem de fato (rede/HTTP/
    timeout); se todos responderem sem encontrar, devolve `None` (título não
    existe em nenhum provedor conhecido). `descricao` entra na mensagem de
    log/erro para diferenciar qual operação falhou.
    """
    algum_respondeu = False
    ultimo_erro: Exception | None = None

    for provedor in PROVEDORES:
        try:
            resultado = await _chamar(provedor, operacao(provedor), titulo)
        except _ERROS_DE_PROVEDOR as excecao:
            logger.warning(
                "provedor de metadados %r falhou em %s de %r: %s",
                provedor.nome,
                descricao,
                titulo,
                excecao,
            )
            ultimo_erro = excecao
            continue

        algum_respondeu = True
        if resultado is not None:
            return resultado

    if algum_respondeu:
        return None
    raise FalhaDeMetadados(
        f"todos os provedores de metadados falharam em {descricao} de {titulo!r}"
    ) from ultimo_erro


async def listar_em_alta() -> list[AnimeEmAlta]:
    """Feed "lançamentos em alta", cacheado em memória por `_TTL_EM_ALTA_S`.
    Percorre só `PROVEDORES_DE_FEED` (AniList; Kitsu de fora — ver o comentário
    da tupla em `registro.py`). Propaga `FalhaDeMetadados` se todos falharem —
    nunca devolve `[]` silenciosamente para não confundir "sem lançamentos" com
    "provedores fora do ar" (CLAUDE.md: erro nunca silencioso).

    Checagem de cache em duas etapas (double-checked locking): a primeira,
    fora do `_lock_em_alta`, evita contenção no caminho comum de cache-hit;
    a segunda, já dentro do lock, evita que uma corrotina que esperou o lock
    refaça uma busca que outra corrotina concorrente acabou de completar.
    """
    global _cache_em_alta

    if _cache_em_alta is not None:
        expira_em, itens = _cache_em_alta
        if time.monotonic() < expira_em:
            return itens

    async with _lock_em_alta:
        if _cache_em_alta is not None:
            expira_em, itens = _cache_em_alta
            if time.monotonic() < expira_em:
                return itens

        ultimo_erro: Exception | None = None
        for provedor in PROVEDORES_DE_FEED:
            try:
                itens = await _chamar(provedor, provedor.listar_em_alta)
            except _ERROS_DE_PROVEDOR as excecao:
                logger.warning(
                    "provedor de metadados %r falhou ao listar 'em alta': %s",
                    provedor.nome,
                    excecao,
                )
                ultimo_erro = excecao
                continue

            itens = await _sobrepor_arte_em_lote(itens)
            _cache_em_alta = (time.monotonic() + _TTL_EM_ALTA_S, itens)
            return itens

        raise FalhaDeMetadados(
            "todos os provedores de metadados falharam ao listar 'em alta'"
        ) from ultimo_erro


async def listar_proxima_temporada() -> list[AnimeEmAlta]:
    """Feed "próxima temporada", cacheado em memória por
    `_TTL_PROXIMA_TEMPORADA_S`. Mesma mecânica de `listar_em_alta` (cache/lock
    próprios, double-checked locking, só `PROVEDORES_DE_FEED`): propaga
    `FalhaDeMetadados` se todos falharem — nunca devolve `[]` silenciosamente
    para não confundir "temporada ainda sem anúncios" com "provedores fora do
    ar" (CLAUDE.md: erro nunca silencioso)."""
    global _cache_proxima_temporada

    if _cache_proxima_temporada is not None:
        expira_em, itens = _cache_proxima_temporada
        if time.monotonic() < expira_em:
            return itens

    async with _lock_proxima_temporada:
        if _cache_proxima_temporada is not None:
            expira_em, itens = _cache_proxima_temporada
            if time.monotonic() < expira_em:
                return itens

        ultimo_erro: Exception | None = None
        for provedor in PROVEDORES_DE_FEED:
            try:
                itens = await _chamar(provedor, provedor.listar_proxima_temporada)
            except _ERROS_DE_PROVEDOR as excecao:
                logger.warning(
                    "provedor de metadados %r falhou ao listar 'próxima temporada': %s",
                    provedor.nome,
                    excecao,
                )
                ultimo_erro = excecao
                continue

            itens = await _sobrepor_arte_em_lote(itens)
            _cache_proxima_temporada = (
                time.monotonic() + _TTL_PROXIMA_TEMPORADA_S,
                itens,
            )
            return itens

        raise FalhaDeMetadados(
            "todos os provedores de metadados falharam ao listar 'próxima temporada'"
        ) from ultimo_erro


async def listar_fileira_tematica(chave: str) -> list[AnimeEmAlta]:
    """Uma fileira temática específica (`FILEIRAS_TEMATICAS` em `registro.py`),
    cacheada em memória por `_TTL_FILEIRA_TEMATICA_S` via `_listar_com_cache`.
    Levanta `ValueError` se `chave` não corresponde a nenhuma fileira
    conhecida, e propaga `FalhaDeMetadados` se a busca falhar (ver
    `_buscar_fileira_tematica_sem_cache`) — ao contrário de
    `listar_fileiras_tematicas`, aqui não há "fileiras irmãs" para absorver a
    falha, então a exceção sobe para quem chamou."""
    fileira = _fileiras_por_chave.get(chave)
    if fileira is None:
        raise ValueError(f"fileira temática desconhecida: {chave!r}")

    return await _listar_com_cache(chave, lambda: _buscar_fileira_tematica_sem_cache(fileira))


async def listar_fileiras_tematicas() -> dict[str, list[AnimeEmAlta]]:
    """Todas as `FILEIRAS_TEMATICAS`, cada uma com seu cache/TTL próprio (ver
    `listar_fileira_tematica`), buscadas com no máximo
    `_CONCORRENCIA_FILEIRAS_TEMATICAS` requisições simultâneas à AniList.

    Uma fileira que falha (exceção, timeout, resposta malformada — tudo que
    `_buscar_fileira_tematica_sem_cache` já traduz em `FalhaDeMetadados`) é
    logada e OMITIDA do dict resultado; as demais seguem normalmente. Só
    levanta `FalhaDeMetadados` se TODAS as fileiras falharem — nunca devolve
    `{}` silenciosamente, para não confundir "todas sem resultado" com
    "provedor fora do ar" (CLAUDE.md: erro nunca silencioso).
    """
    semaforo = asyncio.Semaphore(_CONCORRENCIA_FILEIRAS_TEMATICAS)

    async def _buscar_uma(fileira: FileiraTematica) -> tuple[str, list[AnimeEmAlta] | None]:
        async with semaforo:
            try:
                return fileira.chave, await listar_fileira_tematica(fileira.chave)
            except FalhaDeMetadados as excecao:
                logger.warning(
                    "fileira temática %r omitida do agregado: %s", fileira.chave, excecao
                )
                return fileira.chave, None

    resultados = await asyncio.gather(*(_buscar_uma(fileira) for fileira in FILEIRAS_TEMATICAS))

    fileiras = {chave: itens for chave, itens in resultados if itens is not None}
    if not fileiras:
        raise FalhaDeMetadados("todas as fileiras temáticas falharam ao listar")
    return fileiras


async def _buscar_fileira_tematica_sem_cache(fileira: FileiraTematica) -> list[AnimeEmAlta]:
    """Busca `fileira` sem cache, entre os provedores que implementam
    `ProvedorComFileirasTematicas` (hoje só a AniList). Kitsu não entra aqui
    mesmo como fallback — decisão de produto fechada, taxonomia de tags
    incompatível entre provedores (ver `registro.py`) — e nem precisaria de
    filtro especial: ele simplesmente não implementa a capability. Levanta
    `FalhaDeMetadados` se todos os provedores capazes falharem."""
    capazes = [p for p in PROVEDORES if isinstance(p, ProvedorComFileirasTematicas)]

    ultimo_erro: Exception | None = None
    for provedor in capazes:
        try:
            itens = await _chamar(provedor, provedor.listar_fileira_tematica, fileira)
        except _ERROS_DE_PROVEDOR as excecao:
            logger.warning(
                "provedor de metadados %r falhou ao listar fileira temática %r: %s",
                provedor.nome,
                fileira.chave,
                excecao,
            )
            ultimo_erro = excecao
            continue

        return await _sobrepor_arte_em_lote(itens)

    raise FalhaDeMetadados(
        f"todos os provedores falharam ao listar fileira temática {fileira.chave!r}"
    ) from ultimo_erro


async def _listar_com_cache(
    chave: str, buscar: Callable[[], Awaitable[list[AnimeEmAlta]]]
) -> list[AnimeEmAlta]:
    """Cache-com-TTL genérico por chave, usado SÓ pelas fileiras temáticas
    (`_cache_fileiras_tematicas`/`_locks_fileiras_tematicas`/
    `_TTL_FILEIRA_TEMATICA_S`) — `listar_em_alta`/`listar_proxima_temporada`
    deliberadamente NÃO foram migradas para este helper: são caminho crítico
    da Home e o risco de regressão não compensa nesta fatia, mesmo que isso
    duplique um pouco a lógica de cache-com-TTL já escrita ali.

    Mesmo double-checked locking dos dois: primeira checagem fora do lock
    (evita contenção no cache-hit comum), segunda já dentro do lock — mas o
    lock aqui é POR `chave`, não um lock único do módulo, então um cache-miss
    numa fileira nunca bloqueia a busca de outra.
    """
    if chave in _cache_fileiras_tematicas:
        expira_em, itens = _cache_fileiras_tematicas[chave]
        if time.monotonic() < expira_em:
            return itens

    async with _locks_fileiras_tematicas[chave]:
        if chave in _cache_fileiras_tematicas:
            expira_em, itens = _cache_fileiras_tematicas[chave]
            if time.monotonic() < expira_em:
                return itens

        itens = await buscar()
        _cache_fileiras_tematicas[chave] = (time.monotonic() + _TTL_FILEIRA_TEMATICA_S, itens)
        return itens


# --- overlay de arte (TMDB, PLANO_ARTE_TMDB.md D4) ---


def _gravar_memo_arte(chave: tuple[str, int | None], arte: ArteDeAnime | None) -> None:
    """Grava só em caminho de sucesso (chamador decide quando), inclusive
    `None` (cache negativo). Ao ultrapassar `_LIMITE_MEMO_ARTE`, limpa o dict
    inteiro — política simples e correta, sem LRU."""
    if len(_memo_arte) >= _LIMITE_MEMO_ARTE:
        _memo_arte.clear()
    _memo_arte[chave] = (time.monotonic() + _TTL_ARTE_S, arte)


def _desabilitar_arte_por_auth(provedor: ProvedorDeArte, excecao: TmdbNaoAutorizado) -> None:
    """Liga o latch de auth e loga em `ERROR` **só na primeira vez**. Sem
    `await` entre o check e o set, é atômico sob o scheduler cooperativo do
    asyncio — mas `buscar_arte_por_titulo`/`buscar_still_de_episodio` já podem ter
    disparado várias chamadas concorrentes (`_CONCORRENCIA_ARTE`, até 3 lotes
    em paralelo) antes de a primeira falha chegar aqui; sem esse guard, cada
    uma delas loga de novo ao resolver o próprio 401 — dezenas de linhas em
    vez de uma, exatamente o ruído que o latch existe pra evitar."""
    global _arte_desabilitada_por_auth
    if _arte_desabilitada_por_auth:
        return
    _arte_desabilitada_por_auth = True
    logger.error(
        "provedor de arte %r rejeitou o token — desabilitando overlay de arte "
        "pro resto do processo: %s",
        provedor.nome,
        excecao,
    )


async def buscar_arte_por_titulo(titulo: str, ano: int | None) -> ArteDeAnime | None:
    """Busca capa/banner nos `provedores_de_arte()` instalados (hoje só TMDB),
    com memo de processo por `(slug do título, ano)` — TTL `_TTL_ARTE_S`, com
    cache negativo: sem isso, aquecer `listar_fileiras_tematicas` do zero
    custaria ~500 chamadas TMDB (10 fileiras × 50 itens, repetição alta de
    anime entre fileiras).

    Pública (não `_`-prefixada) porque, além do overlay interno via
    `_com_arte`, `scripts/backfill_metadados_visuais.py` (Fatia 4 do
    PLANO_ARTE_TMDB.md) chama direto pra re-resolver arte de anime já
    catalogado, sem passar pelo fluxo completo de metadados.

    Erro de provedor (`_ERROS_DE_PROVEDOR`) NUNCA grava no memo — congelar 12h
    de "sem arte" por causa de uma falha transitória de rede seria pior que
    tentar de novo na próxima chamada; a busca simplesmente segue para o
    próximo provedor da tupla (hoje só há um, TMDB — o loop é preparado para
    mais). `TmdbNaoAutorizado` (token errado/revogado) é tratada à parte: liga
    o latch de módulo e loga uma vez em `ERROR` — sem isso um token errado
    geraria dezenas de warnings por feed e a má configuração ficaria
    invisível; a partir daí, devolve `None` de imediato sem tentar de novo.
    """
    if _arte_desabilitada_por_auth:
        return None

    chave = (slugificar(titulo), ano)
    memo = _memo_arte.get(chave)
    if memo is not None:
        expira_em, arte = memo
        if time.monotonic() < expira_em:
            return arte

    for provedor in provedores_de_arte():
        try:
            arte = await _chamar(provedor, provedor.buscar_arte_por_titulo, titulo, ano)
        except TmdbNaoAutorizado as excecao:
            _desabilitar_arte_por_auth(provedor, excecao)
            return None
        except _ERROS_DE_PROVEDOR as excecao:
            logger.warning(
                "provedor de arte %r falhou ao buscar arte de %r: %s",
                provedor.nome,
                titulo,
                excecao,
            )
            continue

        _gravar_memo_arte(chave, arte)
        if arte is not None:
            return arte

    return None


# --- overlay de still de episódio (TMDB, Fatia 5 do PLANO_ARTE_TMDB.md) ---


def _gravar_memo_temporadas(
    chave: tuple[str, int | None], tabela: TabelaDeTemporadas | None
) -> None:
    """Mesma política de `_gravar_memo_arte`: grava inclusive `None` (cache
    negativo), limpa o dict inteiro ao estourar `_LIMITE_MEMO_ARTE`."""
    if len(_memo_temporadas) >= _LIMITE_MEMO_ARTE:
        _memo_temporadas.clear()
    _memo_temporadas[chave] = (time.monotonic() + _TTL_ARTE_S, tabela)


def _gravar_memo_still(chave: tuple[str, int | None, int], still: str | None) -> None:
    """Mesma política de `_gravar_memo_arte`: grava inclusive `None` (cache
    negativo), limpa o dict inteiro ao estourar `_LIMITE_MEMO_ARTE`."""
    if len(_memo_still) >= _LIMITE_MEMO_ARTE:
        _memo_still.clear()
    _memo_still[chave] = (time.monotonic() + _TTL_ARTE_S, still)


async def buscar_still_de_episodio(
    titulo: str, ano: int | None, numero_absoluto: int
) -> str | None:
    """Thumb TMDB do episódio `numero_absoluto` (numeração absoluta local) de
    `titulo`/`ano` — overlay best-effort consumido por
    `api/servicos/fontes.py::listar_episodios_remotos` sobre
    `EpisodioRemoto.thumb_url` (Fatia 5 do plano de arte TMDB). `None` sempre
    que não achar ou o provedor falhar — quem chama decide o fallback (o
    `thumb_url` original do extractor). Compartilha o latch de autenticação
    (`_arte_desabilitada_por_auth`) com `buscar_arte_por_titulo`: um token rejeitado
    desabilita os dois overlays de uma vez, não só o de capa/banner.
    """
    if _arte_desabilitada_por_auth:
        return None

    chave_still = (slugificar(titulo), ano, numero_absoluto)
    memo = _memo_still.get(chave_still)
    if memo is not None:
        expira_em, still = memo
        if time.monotonic() < expira_em:
            return still

    for provedor in provedores_de_arte():
        try:
            still = await _buscar_still_de_um_provedor(provedor, titulo, ano, numero_absoluto)
        except TmdbNaoAutorizado as excecao:
            _desabilitar_arte_por_auth(provedor, excecao)
            return None
        except _ERROS_DE_PROVEDOR as excecao:
            logger.warning(
                "provedor de arte %r falhou ao buscar still do episódio %s de %r: %s",
                provedor.nome,
                numero_absoluto,
                titulo,
                excecao,
            )
            continue

        if still is not None:
            return still

    return None


async def _buscar_still_de_um_provedor(
    provedor: ProvedorDeArte, titulo: str, ano: int | None, numero_absoluto: int
) -> str | None:
    """`TmdbProvider` (hoje o único `ProvedorDeArte`) ganha o caminho com
    cache em dois níveis: resolve/reusa a `TabelaDeTemporadas` via
    `_memo_temporadas` pra achar a temporada de `numero_absoluto` sem nova
    consulta HTTP quando já resolvida antes; então busca (ou reusa do memo) os
    stills de TODA a temporada de uma vez
    (`TmdbProvider.stills_da_temporada`), populando `_memo_still` pros outros
    episódios dela — não só o pedido. Qualquer outro `ProvedorDeArte`
    hipotético cai na chamada direta e simples do método da ABC, sem o bônus
    de cache por temporada (não há como fatiar uma temporada que ele não
    expõe)."""
    if not isinstance(provedor, TmdbProvider):
        still = await _chamar(
            provedor, provedor.buscar_still_de_episodio, titulo, ano, numero_absoluto
        )
        _gravar_memo_still((slugificar(titulo), ano, numero_absoluto), still)
        return still

    chave_temporada = (slugificar(titulo), ano)
    memo_tabela = _memo_temporadas.get(chave_temporada)
    if memo_tabela is not None and time.monotonic() < memo_tabela[0]:
        tabela = memo_tabela[1]
    else:
        tabela = await _chamar(provedor, provedor.tabela_de_temporadas, titulo, ano)
        _gravar_memo_temporadas(chave_temporada, tabela)

    if tabela is None:
        return None

    localizacao = localizar_temporada(tabela.temporadas, numero_absoluto)
    if localizacao is None:
        return None
    numero_da_temporada, numero_na_temporada = localizacao

    stills = await _chamar(
        provedor, provedor.stills_da_temporada, tabela.id_da_serie, numero_da_temporada
    )
    if stills is None:
        # Negativo só do episódio pedido (não dá pra "fatiar" uma temporada
        # que não veio) — evita repescar esta mesma temporada só por causa
        # deste episódio específico dentro do TTL.
        _gravar_memo_still((slugificar(titulo), ano, numero_absoluto), None)
        return None

    # Popula o still de TODOS os episódios da temporada de uma vez — não só o
    # pedido — evitando repescar `/tv/{id}/season/{n}` pros próximos episódios
    # da mesma temporada (motivo de existir `_memo_temporadas`/`_memo_still`).
    primeiro_absoluto = next(
        primeiro
        for numero, primeiro, _contagem in tabela.temporadas
        if numero == numero_da_temporada
    )
    for numero_local, still_url in stills.items():
        chave = (slugificar(titulo), ano, primeiro_absoluto + numero_local - 1)
        _gravar_memo_still(chave, still_url)

    return stills.get(numero_na_temporada)


async def _com_arte[T](registro: T, *, titulo: str | None, ano: int | None) -> T:
    """Sobrepõe capa/banner de TMDB num `MetadadosDeAnime` ou `AnimeEmAlta` —
    genérico porque os dois compartilham exatamente os campos `capa_url`/
    `banner_url`. `titulo=None` devolve `registro` intacto (nada para
    buscar). Campo do TMDB nulo PRESERVA o valor anterior — um match com
    pôster e sem backdrop não pode zerar o `bannerImage` da AniList. Qualquer
    falha do overlay (`_ERROS_DE_PROVEDOR`) vira warning e devolve `registro`
    intacto: arte é sempre best-effort, nunca derruba o registro base.
    """
    if titulo is None:
        return registro

    try:
        arte = await buscar_arte_por_titulo(titulo, ano)
    except _ERROS_DE_PROVEDOR as excecao:
        logger.warning("overlay de arte falhou para %r: %s", titulo, excecao)
        return registro

    if arte is None:
        return registro

    return replace(
        registro,
        capa_url=arte.capa_url if arte.capa_url is not None else registro.capa_url,
        banner_url=arte.banner_url if arte.banner_url is not None else registro.banner_url,
    )


async def _sobrepor_arte_em_lote(itens: list[AnimeEmAlta]) -> list[AnimeEmAlta]:
    """Sobrepõe arte de TMDB em cada item de um feed, ANTES de gravar no
    cache do feed (D4) — o custo de N chamadas TMDB só é pago 1x por janela
    de TTL do feed, não por request de Home. Mesma mecânica de
    concorrência/deadline de `api/servicos/capas.py::_consultar_capas`: item
    que não resolveu a tempo mantém a arte da AniList (a *task* pendente é
    cancelada — não a chamada HTTP síncrona em voo, mesma limitação
    documentada lá).

    Guarda `not itens` explícita: `asyncio.wait` levanta `ValueError` para uma
    lista vazia de tarefas — diferente de `api/servicos/capas.py::_consultar_capas`,
    aqui o guard mora dentro da função (5 pontos de chamada, nenhum precisa
    lembrar de checar antes)."""
    if not itens:
        return itens

    semaforo = asyncio.Semaphore(_CONCORRENCIA_ARTE)

    async def _sobrepor_um(indice: int, item: AnimeEmAlta) -> tuple[int, AnimeEmAlta]:
        async with semaforo:
            titulo = item.titulo_ingles or item.titulo_romaji
            item_com_arte = await _com_arte(item, titulo=titulo, ano=item.ano_estreia)
            return indice, item_com_arte

    tasks = [asyncio.ensure_future(_sobrepor_um(i, item)) for i, item in enumerate(itens)]
    concluidas, pendentes = await asyncio.wait(tasks, timeout=_TETO_LOTE_ARTE_S)
    if pendentes:
        for tarefa in pendentes:
            tarefa.cancel()
        # Aguarda a cancelação assentar antes de devolver — mesma razão de
        # `api/servicos/capas.py::_consultar_capas` (a *task* asyncio não pode
        # ficar solta, mesmo que a thread do OS por trás dela rode até o fim).
        await asyncio.gather(*pendentes, return_exceptions=True)

    resultado = list(itens)
    for tarefa in concluidas:
        indice, item_com_arte = tarefa.result()
        resultado[indice] = item_com_arte
    return resultado


async def _chamar[T](
    provedor: ProvedorDeMetadados | ProvedorDeArte, operacao: Callable[..., T], *args: object
) -> T:
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(operacao, *args), timeout=_TIMEOUT_POR_PROVEDOR_S
        )
    except TimeoutError as excecao:
        raise TimeoutError(
            f"{provedor.nome} excedeu o teto de {_TIMEOUT_POR_PROVEDOR_S}s"
        ) from excecao

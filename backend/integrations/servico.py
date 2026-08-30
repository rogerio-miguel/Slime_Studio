"""Serviço de metadados externos: cadeia de fallback AniList -> Kitsu com
timeout por provedor, e cache em memória de processo do feed "em alta".

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
from collections.abc import Callable

import requests

from core.erros import FalhaDeMetadados
from integrations.base import (
    AnimeEmAlta,
    LancamentoDeAnime,
    MetadadosDeAnime,
    ProvedorComLancamento,
    ProvedorDeMetadados,
    TitulosDeAnime,
)
from integrations.registro import PROVEDORES

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


async def buscar_por_titulo(titulo: str) -> MetadadosDeAnime | None:
    """Tenta cada provedor de `PROVEDORES` em ordem até achar metadados para
    `titulo`; ver `_buscar_em_cadeia` para a semântica de fallback."""
    return await _buscar_em_cadeia(
        lambda provedor: provedor.buscar_por_titulo, titulo, descricao="busca por título"
    )


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
    Propaga `FalhaDeMetadados` se todos os provedores falharem — nunca
    devolve `[]` silenciosamente para não confundir "sem lançamentos" com
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
        for provedor in PROVEDORES:
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

            _cache_em_alta = (time.monotonic() + _TTL_EM_ALTA_S, itens)
            return itens

        raise FalhaDeMetadados(
            "todos os provedores de metadados falharam ao listar 'em alta'"
        ) from ultimo_erro


async def _chamar[T](
    provedor: ProvedorDeMetadados, operacao: Callable[..., T], *args: object
) -> T:
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(operacao, *args), timeout=_TIMEOUT_POR_PROVEDOR_S
        )
    except TimeoutError as excecao:
        raise TimeoutError(
            f"{provedor.nome} excedeu o teto de {_TIMEOUT_POR_PROVEDOR_S}s"
        ) from excecao

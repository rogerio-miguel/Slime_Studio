"""Composer de resiliência dos extratores (ESPECIFICACAO.md §3A) — único lugar do
projeto que usa `asyncio.to_thread` para os adapters síncronos (D1 do plano).

`asyncio.to_thread` não é cancelável, por isso a chamada é envolvida em
`asyncio.wait_for` com um teto acima do timeout que o adapter já passa para o
cliente HTTP — o teto aqui é uma rede de segurança, não a primeira linha de
defesa contra travamento.
"""

import asyncio
import logging
from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.erros import FalhaDeExtracao, SessaoRejeitada, SiteEmCooldown
from extractors import circuit_breaker, sessao_cache
from extractors.base import ExtratorDeSite
from extractors.cliente import ClienteDeSite, ClienteLeve, ClienteNavegador

logger = logging.getLogger(__name__)

_SessionMaker = async_sessionmaker[AsyncSession]

# Teto de `wait_for`: cobre o pior caso agregado de um adapter com duas chamadas
# HTTP sequenciais (ex. `extractors/animefire.py::resolver_midia` faz
# `obter_html` + `obter_json`), cada uma com o timeout de 15s que os adapters
# passam a cada chamada de `ClienteDeSite` (`extractors/animefire.py::_TIMEOUT_S`)
# — 2 × 15s = 30s de pior caso plausível + 15s de margem real acima disso, para
# nunca ser o primeiro a estourar em condições normais.
_TETO_ESPERA_S = 45

# TTL da sessão cacheada após sucesso via cliente leve. Estimativa conservadora
# até termos dados reais de expiração do `cf_clearance` (só o cliente de
# navegador — adiado até um site real exigir — resolve desafio de verdade;
# hoje é sessão sem cookie de desafio).
_TTL_SESSAO_S = 6 * 3600


async def chamar[T](
    sessionmaker: _SessionMaker,
    extrator: ExtratorDeSite,
    operacao: Callable[[ClienteDeSite], T],
    *,
    permitir_navegador: bool = True,
) -> T:
    """Executa `operacao(cliente)` com cooldown, cache de sessão e fallback pra
    navegador quando a sessão cacheada é rejeitada.

    Contabilização no circuit breaker: uma falha de sessão isolada (cache
    expirado/rejeitado) não conta contra o site — só conta se a tentativa
    seguinte com sessão nova (o navegador) também falhar, ou se não houver
    fallback disponível (`permitir_navegador=False`). Isso evita abrir cooldown
    por um cookie vencido, que é esperado e não indica bloqueio (ESPECIFICACAO.md
    §9, risco "sessão de bypass expirada").
    """
    dominio = extrator.dominio

    if await circuit_breaker.esta_em_cooldown(sessionmaker, dominio):
        raise SiteEmCooldown(f"{dominio} em cooldown", dominio=dominio)

    contexto = await sessao_cache.carregar(sessionmaker, dominio)
    cliente: ClienteDeSite = ClienteLeve(
        cookies=contexto.cookies if contexto else None,
        user_agent=contexto.user_agent if contexto else None,
    )

    try:
        resultado = await _executar(cliente, operacao, timeout_s=_TETO_ESPERA_S)
    except SessaoRejeitada as excecao:
        await sessao_cache.invalidar(sessionmaker, dominio)
        if not permitir_navegador:
            await circuit_breaker.registrar_falha(sessionmaker, dominio, excecao)
            raise
        cliente = ClienteNavegador()
        try:
            resultado = await _executar(cliente, operacao, timeout_s=_TETO_ESPERA_S)
        except FalhaDeExtracao as excecao_navegador:
            if excecao_navegador.permite_retentativa:
                await circuit_breaker.registrar_falha(sessionmaker, dominio, excecao_navegador)
            raise
    except FalhaDeExtracao as excecao:
        if excecao.permite_retentativa:
            await circuit_breaker.registrar_falha(sessionmaker, dominio, excecao)
        raise

    await circuit_breaker.registrar_sucesso(sessionmaker, dominio)
    await sessao_cache.salvar(
        sessionmaker, dominio, cliente.cookies(), cliente.user_agent(), ttl_s=_TTL_SESSAO_S
    )
    return resultado


async def _executar[T](
    cliente: ClienteDeSite, operacao: Callable[[ClienteDeSite], T], *, timeout_s: int
) -> T:
    try:
        return await asyncio.wait_for(asyncio.to_thread(operacao, cliente), timeout=timeout_s)
    except TimeoutError as excecao:
        raise FalhaDeExtracao(
            f"operação excedeu o teto de {timeout_s}s", permite_retentativa=True
        ) from excecao

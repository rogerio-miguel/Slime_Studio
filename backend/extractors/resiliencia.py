"""Composer de resiliência dos extratores (ESPECIFICACAO.md §3A) — único lugar do
projeto que usa `asyncio.to_thread` para os adapters síncronos (D1 do plano).

`asyncio.to_thread` não é cancelável, por isso a chamada é envolvida em
`asyncio.wait_for` com um teto acima do timeout que o adapter já passa para o
cliente HTTP — o teto aqui é uma rede de segurança, não a primeira linha de
defesa contra travamento.

Também é o único lugar que escolhe **qual** cliente o adapter recebe
(`extractors/cliente.py`): leve por padrão, navegador quando o site/operação
exige ou quando a sessão cacheada é rejeitada.
"""

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial

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

# Teto próprio do caminho com navegador: 45s não cabe aqui. Uma resolução de
# mídia via navegador soma cold start do Chromium, carga da página de episódio
# com JS, e a janela de captura de `ClienteNavegador.capturar_midia`
# (`extractors/animesdrive.py::_TIMEOUT_CAPTURA_S`, 90s). Medido ao vivo em
# 2026-08-17: 3s a 17s do início da navegação até a URL de mídia aparecer — o
# teto largo cobre o caso patológico (overlay de anúncio engolindo cliques),
# não o caso normal. Continua sendo rede de segurança: quem estoura primeiro em
# condição normal é o timeout interno da captura.
_TETO_ESPERA_NAVEGADOR_S = 150

# TTL da sessão cacheada após sucesso via cliente leve. Estimativa conservadora
# até termos dados reais de expiração do `cf_clearance` (só o cliente de
# navegador resolve desafio de verdade; a sessão do cliente leve é sessão sem
# cookie de desafio).
_TTL_SESSAO_S = 6 * 3600


@dataclass(frozen=True, slots=True)
class _Execucao[T]:
    """Resultado da operação **mais** o material de sessão, colhido antes de o
    cliente ser fechado."""

    resultado: T
    cookies: dict[str, str]
    user_agent: str


async def chamar[T](
    sessionmaker: _SessionMaker,
    extrator: ExtratorDeSite,
    operacao: Callable[[ClienteDeSite], T],
    *,
    permitir_navegador: bool = True,
    exigir_navegador: bool = False,
) -> T:
    """Executa `operacao(cliente)` com cooldown, cache de sessão e fallback pra
    navegador quando a sessão cacheada é rejeitada.

    `exigir_navegador` é a versão por **operação** (quem passa é
    `extractors/servico.py::baixar_episodio`, a partir de
    `ExtratorDeSite.exige_navegador_para_midia`); `extrator.exige_navegador` é a
    versão por **site**. Qualquer uma das duas já começa no navegador, sem passar
    pelo cliente leve — diferente do fallback abaixo, que é reação a
    `SessaoRejeitada`.

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

    usar_navegador = exigir_navegador or extrator.exige_navegador
    if usar_navegador:
        fabrica = ClienteNavegador
    else:
        contexto = await sessao_cache.carregar(sessionmaker, dominio)
        fabrica = partial(
            ClienteLeve,
            cookies=contexto.cookies if contexto else None,
            user_agent=contexto.user_agent if contexto else None,
        )

    try:
        execucao = await _executar(fabrica, operacao, timeout_s=_teto_de(usar_navegador))
    except SessaoRejeitada as excecao:
        await sessao_cache.invalidar(sessionmaker, dominio)
        # Sem fallback quando já era o navegador: escalar pra ele de novo só
        # repetiria a mesma tentativa com o mesmo resultado.
        if not permitir_navegador or usar_navegador:
            await circuit_breaker.registrar_falha(sessionmaker, dominio, excecao)
            raise
        logger.info("sessão de %s rejeitada — escalando para o cliente de navegador", dominio)
        try:
            execucao = await _executar(
                ClienteNavegador, operacao, timeout_s=_TETO_ESPERA_NAVEGADOR_S
            )
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
        sessionmaker, dominio, execucao.cookies, execucao.user_agent, ttl_s=_TTL_SESSAO_S
    )
    return execucao.resultado


def _teto_de(usar_navegador: bool) -> int:
    return _TETO_ESPERA_NAVEGADOR_S if usar_navegador else _TETO_ESPERA_S


async def _executar[T](
    fabrica: Callable[[], ClienteDeSite],
    operacao: Callable[[ClienteDeSite], T],
    *,
    timeout_s: int,
) -> _Execucao[T]:
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_executar_sincrono, fabrica, operacao), timeout=timeout_s
        )
    except TimeoutError as excecao:
        raise FalhaDeExtracao(
            f"operação excedeu o teto de {timeout_s}s", permite_retentativa=True
        ) from excecao


def _executar_sincrono[T](
    fabrica: Callable[[], ClienteDeSite], operacao: Callable[[ClienteDeSite], T]
) -> _Execucao[T]:
    """Cria, usa, colhe a sessão e fecha o cliente — tudo na **mesma** thread.

    O cliente de navegador é um processo Chromium com conexão CDP viva: criá-lo
    aqui dentro (e não no event loop) mantém criação/uso/fechamento numa thread
    só, e o `finally` garante que o processo morre mesmo quando o `wait_for` do
    chamador já desistiu — `asyncio.to_thread` não é cancelável, a thread segue
    até o fim e é ela quem faz a limpeza.
    """
    cliente = fabrica()
    try:
        return _Execucao(operacao(cliente), cliente.cookies(), cliente.user_agent())
    finally:
        cliente.fechar()

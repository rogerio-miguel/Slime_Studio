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
import time
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
# com JS, e o conjunto de tentativas de servidor de
# `extractors/animesdrive.py::resolver_midia` (modo com seletor de qualidade:
# até `_MAX_CAPTURAS_POR_EPISODIO` capturas, cobertas por um único orçamento
# `_ORCAMENTO_CAPTURAS_S`). Medido ao vivo em 2026-08-17: 3s a 17s do início da
# navegação até a URL de mídia aparecer, no caminho de 1 candidato só — o teto
# largo cobre o caso patológico (overlay de anúncio engolindo cliques, ou
# vários candidatos falhando em sequência), não o caso normal.
#
# Conta: ~20s (cold start do Chromium + `obter_html`) + `_ORCAMENTO_CAPTURAS_S`
# de 120s (teto de relógio de parede pro conjunto de tentativas de servidor) +
# ~40s de overshoot (cada `capturar_midia` confere o limite no topo do loop e
# ainda pode gastar uma rodada de 2,5s mais uma conferência HTTP de 10s depois
# disso, × até 3 tentativas) ≈ 180s, mais margem pra nunca ser o primeiro a
# estourar em condição normal. O caminho de um candidato só (ou o modo legado,
# sem seletor de qualidade) continua fechando em ~123s, bem abaixo do teto —
# sem regressão pro comportamento anterior a este orçamento.
#
# Continua sendo rede de segurança: quem estoura primeiro em condição normal é
# o timeout interno da captura/orçamento, não este `wait_for`.
_TETO_ESPERA_NAVEGADOR_S = 195

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
    nome_operacao: str = "operacao",
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

    Instrumentação (Fase E1, PLANO_PADRONIZACAO_FONTES.md): `nome_operacao` é só
    um rótulo pra log, o chamador escolhe a string (ex. "buscar",
    "listar_episodios", "resolver_midia") — nunca URL, que pode carregar token
    de sessão. Log só sai no fim de cada tentativa — sucesso em `info`, falha
    (qualquer ramo de exceção) em `warning` — com a duração total já somando a
    escalada quando ela acontece.
    """
    dominio = extrator.dominio
    inicio = time.monotonic()

    if await circuit_breaker.esta_em_cooldown(sessionmaker, dominio):
        raise SiteEmCooldown(f"{dominio} em cooldown", dominio=dominio)

    usar_navegador = exigir_navegador or extrator.exige_navegador
    escalou = False
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
            _logar_falha(dominio, nome_operacao, escalou=escalou, inicio=inicio)
            raise
        logger.info(
            "sessão de %s rejeitada após %.3fs no cliente leve — escalando para o navegador",
            dominio,
            time.monotonic() - inicio,
        )
        escalou = True
        try:
            execucao = await _executar(
                ClienteNavegador, operacao, timeout_s=_TETO_ESPERA_NAVEGADOR_S
            )
        except FalhaDeExtracao as excecao_navegador:
            if excecao_navegador.permite_retentativa:
                await circuit_breaker.registrar_falha(sessionmaker, dominio, excecao_navegador)
            _logar_falha(dominio, nome_operacao, escalou=escalou, inicio=inicio)
            raise
    except FalhaDeExtracao as excecao:
        if excecao.permite_retentativa:
            await circuit_breaker.registrar_falha(sessionmaker, dominio, excecao)
        _logar_falha(dominio, nome_operacao, escalou=escalou, inicio=inicio)
        raise

    await circuit_breaker.registrar_sucesso(sessionmaker, dominio)
    await sessao_cache.salvar(
        sessionmaker, dominio, execucao.cookies, execucao.user_agent, ttl_s=_TTL_SESSAO_S
    )
    logger.info(
        "chamada concluída: dominio=%s operacao=%s cliente=%s escalou=%s duracao_s=%.3f",
        dominio,
        nome_operacao,
        "navegador" if (usar_navegador or escalou) else "leve",
        escalou,
        time.monotonic() - inicio,
    )
    return execucao.resultado


def _logar_falha(dominio: str, nome_operacao: str, *, escalou: bool, inicio: float) -> None:
    """Mesma disciplina do log de sucesso em `chamar` (sem URL) — nível
    `warning`, chamado de cada ramo de exceção antes de propagar."""
    logger.warning(
        "chamada falhou: dominio=%s operacao=%s escalou=%s duracao_s=%.3f",
        dominio,
        nome_operacao,
        escalou,
        time.monotonic() - inicio,
    )


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

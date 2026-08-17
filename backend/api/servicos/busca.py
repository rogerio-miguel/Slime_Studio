"""Enriquecimento de capa dos resultados de `GET /api/animes/buscar-fontes`
(`extractors/`) via metadado de provedor externo (`integrations/`) — único
ponto que importa os dois lados da fronteira pra este fluxo, mesma decisão de
`api/servicos/descoberta.py`/`fontes.py` (CLAUDE.md §1: `extractors/` NUNCA
importa de `integrations/`, e vice-versa; orquestração cross-camada mora aqui).

Hoje só o AnimeFire precisa disto — a página de busca dele genuinamente não
expõe imagem nenhuma (confirmado ao vivo e no código de referência
Slime_Shell_Web, não é bug de parsing). O AnimesDrive já vem com capa própria
da busca (`extractors/animesdrive.py::buscar`).
"""

import asyncio
import logging
from dataclasses import replace

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.texto import slugificar
from extractors.base import ResultadoBusca
from extractors.servico import ResultadoDeFonte
from integrations import servico as servico_metadados

logger = logging.getLogger(__name__)

_SessionMaker = async_sessionmaker[AsyncSession]

# Teto pequeno de propósito: `buscar-fontes` já dispara uma rajada em paralelo
# por site (`extractors/servico.py::buscar_em_todas_as_fontes`); este
# enriquecimento roda LOGO DEPOIS, sobre um provedor diferente (AniList/Kitsu,
# sem circuit breaker próprio como `extractors/`) — 5 é um teto conservador
# pra nunca virar uma segunda rajada descontrolada, mesmo espírito de
# `integrations/servico.py::_lock_em_alta` (thundering herd), sem depender de
# medição real de rate limit ainda inexistente pra este caminho.
_CONCORRENCIA_MAXIMA = 5

# Teto do LOTE inteiro (asyncio.wait, não wait_for por chamada individual):
# `integrations/servico.py::buscar_por_titulo` tenta AniList e, se falhar,
# Kitsu, cada um com até `_TIMEOUT_POR_PROVEDOR_S` (8s) — pior caso de UMA
# chamada é 16s. Mesmo raciocínio de
# `api/servicos/descoberta.py::_TETO_ENRIQUECIMENTO_S` (16s + margem = 18s)
# pra essa mesma função; aqui o teto cobre várias chamadas em paralelo
# (limitadas pelo semáforo acima) — quem não terminar a tempo é cancelado
# explicitamente, nunca some rodando em segundo plano após a resposta.
_TETO_LOTE_S = 18


async def enriquecer_capas(
    sessionmaker: _SessionMaker, resultados: list[ResultadoDeFonte]
) -> list[ResultadoDeFonte]:
    """Preenche `capa_url` dos candidatos que vieram sem (`ResultadoBusca.
    capa_url is None`) consultando `integrations.servico.buscar_por_titulo`.
    Best-effort: falha de uma consulta (`FalhaDeMetadados`, timeout ou
    qualquer outra exceção do provedor) nunca propaga daqui pra fora nem
    derruba os demais candidatos — aquele título simplesmente fica sem capa.

    `sessionmaker` não é usado no corpo hoje (`buscar_por_titulo` não toca o
    banco) — mantido na assinatura por consistência com as demais funções de
    `api/servicos/` (todas recebem sessionmaker como 1º parâmetro) e pra não
    obrigar mudar a assinatura no dia em que este enriquecimento passar a
    persistir alguma coisa (ex. cache de capa por título).
    """
    titulos_pendentes = _titulos_sem_capa(resultados)
    if not titulos_pendentes:
        return resultados

    capa_por_titulo = await _consultar_capas(titulos_pendentes)
    if not capa_por_titulo:
        return resultados

    return [
        replace(
            fonte,
            candidatos=[_com_capa(candidato, capa_por_titulo) for candidato in fonte.candidatos],
        )
        for fonte in resultados
    ]


def _titulos_sem_capa(resultados: list[ResultadoDeFonte]) -> list[str]:
    """Dedupe por título normalizado (`core/texto.py::slugificar`) — dois
    candidatos com o mesmo título, do mesmo site ou de sites diferentes, geram
    só uma consulta a `buscar_por_titulo`."""
    vistos: set[str] = set()
    titulos: list[str] = []
    for fonte in resultados:
        for candidato in fonte.candidatos:
            if candidato.capa_url is not None:
                continue
            chave = slugificar(candidato.titulo_exibicao)
            if chave in vistos:
                continue
            vistos.add(chave)
            titulos.append(candidato.titulo_exibicao)
    return titulos


def _com_capa(candidato: ResultadoBusca, capa_por_titulo: dict[str, str]) -> ResultadoBusca:
    if candidato.capa_url is not None:
        return candidato
    capa = capa_por_titulo.get(slugificar(candidato.titulo_exibicao))
    return candidato if capa is None else replace(candidato, capa_url=capa)


async def _consultar_capas(titulos: list[str]) -> dict[str, str]:
    """Dispara `buscar_por_titulo` para cada título em paralelo, limitado por
    `_CONCORRENCIA_MAXIMA` e pelo teto de tempo `_TETO_LOTE_S` do lote
    inteiro. `asyncio.wait` (não `wait_for`) pra aproveitar o que já terminou
    dentro do prazo em vez de cancelar tudo de uma vez; as tasks que ainda
    estiverem pendentes quando o prazo bater são canceladas explicitamente, e
    a cancelação é aguardada antes de devolver — a *task* não some rodando
    solta. Isso não cobre a chamada HTTP síncrona já em voo dentro do
    `asyncio.to_thread` de `integrations/servico.py`: cancelamento não
    interrompe uma thread do OS em andamento (mesma limitação documentada em
    `extractors/resiliencia.py`), então na pior das hipóteses ela roda até
    terminar sozinha — só o resultado é descartado, nunca aplicado."""
    semaforo = asyncio.Semaphore(_CONCORRENCIA_MAXIMA)

    async def _consultar_um(titulo: str) -> tuple[str, str | None]:
        chave = slugificar(titulo)
        async with semaforo:
            try:
                metadados = await servico_metadados.buscar_por_titulo(titulo)
            except Exception as excecao:
                # Captura ampla e intencional: enriquecimento de capa é
                # best-effort (docstring do módulo) — `FalhaDeMetadados`
                # (todos os provedores falharam), timeout ou qualquer outro
                # erro do adapter não pode derrubar os demais títulos do lote.
                logger.warning(
                    "enriquecimento de capa best-effort falhou para título %r: %s",
                    titulo,
                    excecao,
                )
                return chave, None
        return chave, metadados.capa_url if metadados is not None else None

    tasks = [asyncio.ensure_future(_consultar_um(titulo)) for titulo in titulos]
    concluidas, pendentes = await asyncio.wait(tasks, timeout=_TETO_LOTE_S)
    if pendentes:
        for tarefa in pendentes:
            tarefa.cancel()
        # Aguarda a cancelação de fato assentar antes de devolver — sem isto a
        # *task* asyncio fica solta (não a thread do OS por trás dela, ver
        # docstring acima). `return_exceptions=True` porque toda pendente aqui
        # levanta `CancelledError` por construção.
        await asyncio.gather(*pendentes, return_exceptions=True)

    capa_por_titulo: dict[str, str] = {}
    for tarefa in concluidas:
        chave, capa = tarefa.result()
        if capa:  # filtra None e "" (provedor externo não garante não-vazio)
            capa_por_titulo[chave] = capa
    return capa_por_titulo

"""Orquestração de `GET /api/animes/buscar-fontes` que cruza `extractors/` ×
`integrations/` — único ponto que importa os dois lados da fronteira pra este
fluxo, mesma decisão de `api/servicos/descoberta.py`/`fontes.py` (CLAUDE.md
§1: `extractors/` NUNCA importa de `integrations/`, e vice-versa; orquestração
cross-camada mora aqui). Duas responsabilidades:

- `buscar_com_titulos_alternativos`: se a busca com o termo digitado vier
  vazia (mas alguma fonte respondeu), tenta de novo com título(s) alternativo(s)
  do mesmo anime (romaji/inglês, via `integrations/servico.py::buscar_titulos`)
  — tolerância a idioma (usuário digitou em inglês, sites indexam romaji, ou
  vice-versa).
- `enriquecer_capas`: preenche `capa_url` dos candidatos que vieram sem, via
  metadado de provedor externo (`integrations/`). Hoje só o AnimeFire precisa
  disto — a página de busca dele genuinamente não expõe imagem nenhuma
  (confirmado ao vivo e no código de referência Slime_Shell_Web, não é bug de
  parsing). O AnimesDrive já vem com capa própria da busca
  (`extractors/animesdrive.py::buscar`).
"""

import asyncio
import logging
from dataclasses import dataclass, replace

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.texto import slugificar
from extractors import servico as servico_extractors
from extractors.base import ResultadoBusca
from extractors.servico import ResultadoDeFonte
from integrations import servico as servico_metadados
from integrations.base import TitulosDeAnime

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

# Teto da fase inteira de expansão por título alternativo (metadado + até 2
# rodadas de scraping, uma por termo alternativo — D4 do plano): tempo
# suficiente para `buscar_titulos` (até `_TETO_METADADOS_S`) mais duas
# chamadas a `buscar_em_todas_as_fontes`, sem deixar o usuário esperando
# indefinidamente por uma tentativa best-effort. Quem não terminar a tempo é
# cancelado — devolve a rodada original em vez de travar a resposta.
_TETO_EXPANSAO_S = 20

# Sub-teto só de `buscar_titulos` dentro da fase acima: sem isto, AniList +
# Kitsu no pior caso (cada um até `integrations/servico.py::
# _TIMEOUT_POR_PROVEDOR_S`, 8s) consomem os 20s inteiros de `_TETO_EXPANSAO_S`
# sozinhos, sem sobrar tempo pra nenhuma rodada de scraping alternativa.
_TETO_METADADOS_S = 10


@dataclass(frozen=True, slots=True)
class BuscaEmFontes:
    """Resultado da busca em fontes + de qual termo ele veio.
    `termo_alternativo is None` significa "veio do termo digitado"."""

    fontes: list[ResultadoDeFonte]
    termo_alternativo: str | None


async def buscar_com_titulos_alternativos(
    sessionmaker: _SessionMaker, titulo: str
) -> BuscaEmFontes:
    """Busca em todas as fontes com `titulo`; se vier vazia mas alguma fonte
    respondeu (`_merece_expansao`), tenta de novo com título(s) alternativo(s)
    do mesmo anime (romaji/inglês, via `integrations.servico.buscar_titulos`)
    — tolerância a idioma (usuário digitou em inglês, sites indexam romaji, ou
    vice-versa).

    Best-effort, mesmo padrão já documentado em `_consultar_capas` deste
    módulo: falha ou timeout na expansão (`_TETO_EXPANSAO_S`) nunca propaga
    daqui pra fora nem derruba a busca base — devolve a rodada original.

    Limitação conhecida (mesma já documentada em `_consultar_capas`): o
    `wait_for` externo cancela a *task* asyncio, não a thread do SO já em voo
    dentro do `to_thread` de `extractors/resiliencia.py` — na pior das
    hipóteses ela roda até terminar sozinha, e a rodada cancelada não registra
    sucesso/falha no circuit breaker.
    """
    fontes = await servico_extractors.buscar_em_todas_as_fontes(sessionmaker, titulo)
    if not _merece_expansao(fontes):
        return BuscaEmFontes(fontes=fontes, termo_alternativo=None)

    try:
        expandido = await asyncio.wait_for(
            _tentar_titulos_alternativos(sessionmaker, titulo), timeout=_TETO_EXPANSAO_S
        )
    except Exception as excecao:
        # Captura ampla e intencional: expansão por título alternativo é
        # best-effort (docstring acima) — falha de metadado, timeout do lote
        # ou qualquer outro erro não pode derrubar a busca base já obtida.
        logger.warning(
            "expansão por título alternativo best-effort falhou para título %r: %s",
            titulo,
            excecao,
        )
        return BuscaEmFontes(fontes=fontes, termo_alternativo=None)

    if expandido is not None:
        return expandido
    return BuscaEmFontes(fontes=fontes, termo_alternativo=None)


def _merece_expansao(fontes: list[ResultadoDeFonte]) -> bool:
    return any(not f.indisponivel for f in fontes) and all(not f.candidatos for f in fontes)


async def _tentar_titulos_alternativos(
    sessionmaker: _SessionMaker, titulo: str
) -> BuscaEmFontes | None:
    titulos = await asyncio.wait_for(
        servico_metadados.buscar_titulos(titulo), timeout=_TETO_METADADOS_S
    )
    if titulos is None:
        return None

    for termo in _termos_alternativos(titulos, titulo):
        fontes = await servico_extractors.buscar_em_todas_as_fontes(sessionmaker, termo)
        if any(fonte.candidatos for fonte in fontes):
            logger.info(
                "busca por título %r vazia, achou candidatos com o termo alternativo %r",
                titulo,
                termo,
            )
            return BuscaEmFontes(fontes=fontes, termo_alternativo=termo)
        logger.info(
            "termo alternativo %r também não achou candidatos para título %r",
            termo,
            titulo,
        )
    return None


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

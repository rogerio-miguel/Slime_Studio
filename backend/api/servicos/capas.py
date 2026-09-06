"""Enriquecimento best-effort de capa para os candidatos de
`GET /api/animes/buscar-fontes`: `extractors/` não resolve mais imagem alguma
(Fatia 3 de `PLANO_ARTE_TMDB.md` — `extractors/` volta a ser só extração de
VÍDEO), então **todo** candidato de busca é enriquecido aqui, consultando
metadado de provedor externo (`integrations/servico.py::buscar_por_titulo`,
capa já resolvida pela cadeia TMDB→AniList, D4 do plano). Falha de uma
consulta nunca propaga daqui pra fora nem derruba os demais candidatos —
aquele título só fica sem capa.

Módulo próprio, separado de `api/servicos/busca.py`: ao contrário daquela
orquestração, este fluxo NÃO cruza a fronteira `extractors/` ×
`integrations/` (CLAUDE.md §1) — consome só `integrations/servico.py` e dois
tipos de dado (`extractors.base.ResultadoBusca` e
`extractors.busca.servico.ResultadoDeFonte`), nunca chama um extrator. Vivia
em `busca.py` por acidente histórico (mesmo consumidor de rota), não por
pertencer àquela fronteira.

Não confundir com `api/servicos/descoberta.py`, que enriquece metadado
(capa/sinopse/ids) de anime já CATALOGADO e o persiste no banco — aqui o alvo
é um candidato de busca ainda NÃO catalogado e nada é persistido (só o
`dict` de saída é usado em memória pela rota).

Quem aplica isto é a rota `api/rotas/animes.py` (`buscar_animes_em_fontes`),
DEPOIS da busca em fontes (`api/servicos/busca.py`) e antes de montar
`BuscaEmFontesSaida` — nunca os extratores nem `busca.py`.
"""

import asyncio
import logging

from core.texto import slugificar
from extractors.busca.servico import ResultadoDeFonte
from integrations import servico as servico_metadados

logger = logging.getLogger(__name__)

# Teto pequeno de propósito: `buscar-fontes` já roda a busca sequencial por
# site de `api/servicos/busca.py::buscar_com_titulos_alternativos`; este
# enriquecimento roda LOGO DEPOIS, sobre um provedor diferente (AniList/TMDB,
# sem circuit breaker próprio como `extractors/`) — 5 é um teto conservador pra
# nunca virar uma segunda rajada descontrolada, mesmo espírito de
# `integrations/servico.py::_lock_em_alta` (thundering herd), sem depender de
# medição real de rate limit ainda inexistente pra este caminho.
_CONCORRENCIA_MAXIMA = 5

# Teto do LOTE inteiro (asyncio.wait, não wait_for por chamada individual):
# `integrations/servico.py::buscar_por_titulo` tenta a cadeia de provedores de
# metadado, cada um com até `_TIMEOUT_POR_PROVEDOR_S` (8s) — pior caso de UMA
# chamada é 16s. Mesmo raciocínio de
# `api/servicos/descoberta.py::_TETO_ENRIQUECIMENTO_S` (16s + margem = 18s)
# pra essa mesma função; aqui o teto cobre várias chamadas em paralelo
# (limitadas pelo semáforo acima) — quem não terminar a tempo é cancelado
# explicitamente, nunca some rodando em segundo plano após a resposta.
_TETO_LOTE_S = 18


async def capas_por_titulo(resultados: list[ResultadoDeFonte]) -> dict[str, str]:
    """Consulta `integrations.servico.buscar_por_titulo` para cada título
    distinto entre os candidatos de `resultados` e devolve
    `dict[slug do título -> capa_url]` (chave via `core/texto.py::slugificar`).
    Best-effort: falha de uma consulta (`FalhaDeMetadados`, timeout ou
    qualquer outra exceção do provedor) nunca propaga daqui pra fora nem
    derruba os demais candidatos — aquele título simplesmente fica ausente do
    dict devolvido. Título sem capa encontrada também fica ausente (nunca
    entra com valor `None`)."""
    titulos = _titulos_distintos(resultados)
    if not titulos:
        return {}
    return await _consultar_capas(titulos)


def _titulos_distintos(resultados: list[ResultadoDeFonte]) -> list[str]:
    """Dedupe por título normalizado (`core/texto.py::slugificar`) — dois
    candidatos com o mesmo título, do mesmo site ou de sites diferentes, geram
    só uma consulta a `buscar_por_titulo`."""
    vistos: set[str] = set()
    titulos: list[str] = []
    for fonte in resultados:
        for candidato in fonte.candidatos:
            chave = slugificar(candidato.titulo_exibicao)
            if chave in vistos:
                continue
            vistos.add(chave)
            titulos.append(candidato.titulo_exibicao)
    return titulos


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

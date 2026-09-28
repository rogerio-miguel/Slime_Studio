"""Hub de assinantes WS + poll da fila (D3 do plano da Fase 3) — sem tabela de
eventos, sem IPC: um único `MonitorDeFila` faz um `SELECT` a cada 2s dentro do
próprio processo da API e publica só o que mudou desde o poll anterior.

`Assinantes` é o hub em memória (canal `"admin"` ou `f"job:{id}"` -> fila por
conexão); `MonitorDeFila` é dono da task de poll, que só existe enquanto houver
ao menos um assinante em qualquer canal.
"""

import asyncio
import contextlib
import logging
from datetime import UTC, datetime, timedelta

from fastapi import WebSocket
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from models.anime import Anime
from models.episodio import Episodio
from models.job import Job

logger = logging.getLogger(__name__)

_SessionMaker = async_sessionmaker[AsyncSession]

_INTERVALO_MONITOR_S = 2
_JANELA_JOBS_FINALIZADOS_MIN = 10
_TAMANHO_FILA_POR_CONEXAO = 64

_COLUNAS_JOB = (
    Job.id,
    Job.episodio_id,
    Job.status,
    Job.etapa_atual,
    Job.progresso_pct,
    Job.erro_msg,
    Job.tentativas,
    Job.criado_em,
    Job.finalizado_em,
    Job.heartbeat_em,
    Anime.id.label("anime_id"),
    Anime.titulo.label("anime_titulo"),
    Episodio.numero.label("episodio_numero"),
)


class Assinantes:
    """Hub de broadcast em memória. Uma conexão assina no máximo uma vez por
    canal — `assinar` é chamada de novo para cada canal que a rota WS precisar."""

    def __init__(self) -> None:
        self._filas: dict[str, dict[WebSocket, asyncio.Queue]] = {}

    async def assinar(self, canal: str, ws: WebSocket) -> asyncio.Queue:
        fila: asyncio.Queue = asyncio.Queue(maxsize=_TAMANHO_FILA_POR_CONEXAO)
        self._filas.setdefault(canal, {})[ws] = fila
        return fila

    def cancelar(self, canal: str, ws: WebSocket) -> None:
        conexoes = self._filas.get(canal)
        if conexoes is None:
            return
        conexoes.pop(ws, None)
        if not conexoes:
            del self._filas[canal]

    async def publicar(self, canal: str, mensagem: dict) -> None:
        """Fila cheia (assinante não está drenando rápido o suficiente) fecha
        aquela conexão com o código 1013 ("try again later") em vez de descartar
        a mensagem silenciosamente ou bloquear o publicador."""
        conexoes_cheias = [
            ws
            for ws, fila in self._filas.get(canal, {}).items()
            if not _tentar_publicar(fila, mensagem)
        ]
        for ws in conexoes_cheias:
            logger.warning("fila cheia no canal %s — fechando conexão (1013)", canal)
            self.cancelar(canal, ws)
            with contextlib.suppress(RuntimeError):
                await ws.close(code=1013)

    def total_assinantes(self) -> int:
        return sum(len(conexoes) for conexoes in self._filas.values())


def _tentar_publicar(fila: asyncio.Queue, mensagem: dict) -> bool:
    try:
        fila.put_nowait(mensagem)
        return True
    except asyncio.QueueFull:
        return False


class MonitorDeFila:
    """Poll + diff (D3): sobe uma única task de poll na 1ª assinatura de
    qualquer canal, derruba quando o último assinante sai. O primeiro poll de
    cada vez que a task sobe é baseline — não emite nada (senão todo job
    existente no boot da API dispararia um evento)."""

    def __init__(self, sessionmaker: _SessionMaker, assinantes: Assinantes) -> None:
        self._sessionmaker = sessionmaker
        self._assinantes = assinantes
        self._task: asyncio.Task | None = None
        self._contador = 0
        self._lock = asyncio.Lock()
        self._snapshot: dict[int, tuple] = {}
        self._tem_baseline = False

    async def ao_assinar(self) -> None:
        async with self._lock:
            self._contador += 1
            if self._task is None:
                self._tem_baseline = False
                self._task = asyncio.create_task(self._loop())

    async def ao_sair(self) -> None:
        tarefa = None
        async with self._lock:
            self._contador = max(0, self._contador - 1)
            if self._contador == 0 and self._task is not None:
                tarefa, self._task = self._task, None
        if tarefa is not None:
            tarefa.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await tarefa

    async def parar(self) -> None:
        """Chamado no shutdown do lifespan (`api/main.py`) — cancela a task de
        poll se ela estiver viva, independente de contagem de assinantes."""
        tarefa = None
        async with self._lock:
            tarefa, self._task = self._task, None
            self._contador = 0
        if tarefa is not None:
            tarefa.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await tarefa

    async def _loop(self) -> None:
        with contextlib.suppress(asyncio.CancelledError):
            while True:
                await self._pollar()
                await asyncio.sleep(_INTERVALO_MONITOR_S)

    async def _pollar(self) -> None:
        linhas = await buscar_jobs_ativos(self._sessionmaker)
        atual = {linha["id"]: _chave_diff(linha) for linha in linhas}

        if not self._tem_baseline:
            self._snapshot = atual
            self._tem_baseline = True
            return

        por_id = {linha["id"]: linha for linha in linhas}
        for job_id, chave in atual.items():
            if self._snapshot.get(job_id) != chave:
                mensagem = {"tipo": "job_atualizado", "job": por_id[job_id]}
                await self._assinantes.publicar("admin", mensagem)
                await self._assinantes.publicar(f"job:{job_id}", mensagem)

        self._snapshot = atual


def _chave_diff(linha: dict) -> tuple:
    return (linha["status"], linha["etapa_atual"], linha["progresso_pct"], linha["erro_msg"])


async def buscar_jobs_ativos(sessionmaker: _SessionMaker) -> list[dict]:
    """Jobs não finalizados, ou finalizados há menos de `_JANELA_JOBS_FINALIZADOS_MIN`
    minutos — job que sai da janela simplesmente para de gerar eventos, não é um
    evento em si."""
    limite = datetime.now(UTC) - timedelta(minutes=_JANELA_JOBS_FINALIZADOS_MIN)
    async with sessionmaker() as sessao:
        resultado = await sessao.execute(
            select(*_COLUNAS_JOB)
            .join(Episodio, Job.episodio_id == Episodio.id)
            .join(Anime, Episodio.anime_id == Anime.id)
            .where((Job.finalizado_em.is_(None)) | (Job.finalizado_em >= limite))
        )
        return [dict(linha._mapping) for linha in resultado]


async def buscar_job(sessionmaker: _SessionMaker, job_id: int) -> dict | None:
    """Snapshot de um único job, sem filtro de janela — usado no `accept` de
    `/ws/jobs/{id}` (o job pode já estar fora da janela de eventos ativos, mas o
    cliente que abriu a página dele ainda quer ver o estado atual)."""
    async with sessionmaker() as sessao:
        resultado = await sessao.execute(
            select(*_COLUNAS_JOB)
            .join(Episodio, Job.episodio_id == Episodio.id)
            .join(Anime, Episodio.anime_id == Anime.id)
            .where(Job.id == job_id)
        )
        linha = resultado.first()
        return dict(linha._mapping) if linha is not None else None

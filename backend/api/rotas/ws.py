"""Rotas WebSocket (`/ws/admin`, `/ws/jobs/{id}`).

Por conexão: duas tasks — uma em `websocket.receive()` (detecta desconexão) e
outra drenando a fila de mensagens do assinante. A primeira a terminar cancela a
outra; `finally` sempre cancela a assinatura e avisa o monitor que a conexão
saiu, mesmo em desconexão abrupta.
"""

import asyncio
import logging

from fastapi import APIRouter, WebSocket
from fastapi.encoders import jsonable_encoder
from starlette.websockets import WebSocketDisconnect

from api.eventos import Assinantes, MonitorDeFila, buscar_job, buscar_jobs_ativos

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/admin")
async def ws_admin(websocket: WebSocket) -> None:
    jobs = await buscar_jobs_ativos(websocket.app.state.sessionmaker)
    await _atender(websocket, canal="admin", snapshot={"tipo": "snapshot", "jobs": jobs})


@router.websocket("/ws/jobs/{job_id}")
async def ws_job(websocket: WebSocket, job_id: int) -> None:
    job = await buscar_job(websocket.app.state.sessionmaker, job_id)
    snapshot = {"tipo": "snapshot", "jobs": [job] if job is not None else []}
    await _atender(websocket, canal=f"job:{job_id}", snapshot=snapshot)


async def _atender(websocket: WebSocket, *, canal: str, snapshot: dict) -> None:
    assinantes: Assinantes = websocket.app.state.assinantes
    monitor: MonitorDeFila = websocket.app.state.monitor

    await websocket.accept()
    await websocket.send_json(jsonable_encoder(snapshot))

    fila = await assinantes.assinar(canal, websocket)
    await monitor.ao_assinar()

    task_receber = asyncio.create_task(_detectar_desconexao(websocket))
    task_enviar = asyncio.create_task(_drenar_fila(websocket, fila))

    try:
        await asyncio.wait({task_receber, task_enviar}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in (task_receber, task_enviar):
            if not task.done():
                task.cancel()
        await asyncio.gather(task_receber, task_enviar, return_exceptions=True)
        assinantes.cancelar(canal, websocket)
        await monitor.ao_sair()


async def _detectar_desconexao(websocket: WebSocket) -> None:
    """Consumir `receive()` é o que faz a desconexão do cliente ser detectada —
    sem isto a tarefa de envio ficaria presa indefinidamente numa conexão morta,
    vazando a assinatura e a task do monitor."""
    try:
        while True:
            await websocket.receive()
    except WebSocketDisconnect:
        pass


async def _drenar_fila(websocket: WebSocket, fila: asyncio.Queue) -> None:
    while True:
        mensagem = await fila.get()
        await websocket.send_json(jsonable_encoder(mensagem))

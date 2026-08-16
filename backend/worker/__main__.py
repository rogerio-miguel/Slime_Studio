"""Entry point do processo worker (ESPECIFICACAO.md §2.1/§3B).

Fluxo: config → lock de instância única → engine/sessionmaker → recicla jobs
órfãos uma vez → loop de reivindicação com heartbeat em paralelo. Shutdown
cooperativo em `SIGINT`/`SIGTERM`: para de reivindicar novos jobs, cancela o
job em voo (o que mata o subprocesso ffmpeg/ffprobe atual, ver
`pipeline/ferramentas.py`) e devolve-o para a fila — não é tratado como falha.
"""

import asyncio
import logging
import os
import signal
import socket

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config import Config, carregar_config
from db.engine import criar_engine, criar_sessionmaker
from worker.bloqueio import BloqueioDeInstancia
from worker.executor import processar
from worker.fila import (
    devolver_para_fila,
    reciclar_jobs_orfaos,
    registrar_heartbeat,
    reivindicar_proximo,
)

logger = logging.getLogger(__name__)

_SessionMaker = async_sessionmaker[AsyncSession]

_INTERVALO_POLLING_S = 5
_INTERVALO_HEARTBEAT_S = 15


async def principal(config: Config) -> int:
    with BloqueioDeInstancia(config.caminho_lock):
        worker_id = f"{socket.gethostname()}:{os.getpid()}"
        engine = criar_engine(config)
        sessionmaker = criar_sessionmaker(engine)

        try:
            reciclados = await reciclar_jobs_orfaos(sessionmaker)
            if reciclados:
                logger.info("reciclados %d job(s) órfão(s) para na_fila", reciclados)

            parar = asyncio.Event()
            loop = asyncio.get_running_loop()
            for sinal in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sinal, parar.set)

            while not parar.is_set():
                job_id = await reivindicar_proximo(sessionmaker, worker_id=worker_id)
                if job_id is None:
                    await _dormir_ou_parar(parar, _INTERVALO_POLLING_S)
                    continue

                await _processar_com_shutdown_cooperativo(job_id, sessionmaker, config, parar)
        finally:
            await engine.dispose()

        return 0


async def _dormir_ou_parar(parar: asyncio.Event, segundos: int) -> None:
    try:
        await asyncio.wait_for(parar.wait(), timeout=segundos)
    except TimeoutError:
        pass


async def _processar_com_shutdown_cooperativo(
    job_id: int, sessionmaker: _SessionMaker, config: Config, parar: asyncio.Event
) -> None:
    task_job = asyncio.create_task(processar(job_id, sessionmaker, config))
    task_heartbeat = asyncio.create_task(_bater_heartbeat(job_id, sessionmaker))
    task_shutdown = asyncio.create_task(parar.wait())

    try:
        concluidas, _pendentes = await asyncio.wait(
            {task_job, task_shutdown}, return_when=asyncio.FIRST_COMPLETED
        )

        if task_shutdown in concluidas and not task_job.done():
            logger.info(
                "shutdown solicitado — cancelando job %s e devolvendo para a fila", job_id
            )
            task_job.cancel()
            try:
                await task_job
            except asyncio.CancelledError:
                pass
            await devolver_para_fila(sessionmaker, job_id)
        elif task_job.done() and task_job.exception() is not None:
            # processar() só deixa escapar exceção em bug real — ela mesma
            # trata FonteInvalida/FalhaDeFerramenta/Exception internamente.
            logger.exception(
                "job %s: exceção não tratada escapou de processar()",
                job_id,
                exc_info=task_job.exception(),
            )
    finally:
        for task in (task_job, task_heartbeat, task_shutdown):
            if not task.done():
                task.cancel()
        await asyncio.gather(task_job, task_heartbeat, task_shutdown, return_exceptions=True)


async def _bater_heartbeat(job_id: int, sessionmaker: _SessionMaker) -> None:
    try:
        while True:
            await asyncio.sleep(_INTERVALO_HEARTBEAT_S)
            await registrar_heartbeat(sessionmaker, job_id)
    except asyncio.CancelledError:
        pass


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    codigo_saida = asyncio.run(principal(carregar_config()))
    raise SystemExit(codigo_saida)


if __name__ == "__main__":
    main()

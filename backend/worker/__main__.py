"""Entry point do processo worker (ESPECIFICACAO.md §2.1/§3B).

Fluxo: config → lock de instância única → engine/sessionmaker → recicla jobs
órfãos uma vez → loop de reivindicação com heartbeat em paralelo. Dois gatilhos
cooperativos de parada de um job em voo, ambos via o mesmo mecanismo (cancela
`task_job`, o que mata o subprocesso ffmpeg/ffprobe atual — `pipeline/ferramentas.py`
— e limpa o `.tmp` via `pipeline/hls.py`):
- Shutdown por `SIGINT`/`SIGTERM`: devolve o job para a fila (`na_fila`), não é
  falha nem cancelamento — só interrompido por causa do processo, será
  reivindicado de novo.
- Cancelamento pedido pela API (`Job.cancelamento_solicitado`, checado a cada
  ciclo de heartbeat — até `_INTERVALO_HEARTBEAT_S` de latência): finaliza como
  `cancelado`, definitivo (precisa de retry explícito para voltar à fila).
"""

import asyncio
import logging
import os
import signal
import socket

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config import Config, carregar_config
from core.enums import StatusJob
from db.engine import criar_engine, criar_sessionmaker
from db.fila import (
    atualizar_status,
    cancelamento_foi_solicitado,
    devolver_para_fila,
    marcar_cancelado,
    reciclar_jobs_orfaos,
    registrar_heartbeat,
    reivindicar_proximo,
)
from worker.bloqueio import BloqueioDeInstancia
from worker.executor import processar

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
    task_cancelamento = asyncio.create_task(_observar_cancelamento(job_id, sessionmaker))

    try:
        concluidas, _pendentes = await asyncio.wait(
            {task_job, task_shutdown, task_cancelamento}, return_when=asyncio.FIRST_COMPLETED
        )

        if task_shutdown in concluidas and not task_job.done():
            logger.info(
                "shutdown solicitado — cancelando job %s e devolvendo para a fila", job_id
            )
            await _cancelar_task_job(task_job)
            await devolver_para_fila(sessionmaker, job_id)
        elif task_cancelamento in concluidas and not task_job.done():
            logger.info("cancelamento solicitado via API — cancelando job %s", job_id)
            await atualizar_status(sessionmaker, job_id, StatusJob.CANCELANDO, etapa="cancelando")
            await _cancelar_task_job(task_job)
            # `await atualizar_status` acima é um ponto de suspensão real: `task_job`
            # pode ter concluído com sucesso durante essa janela, o que faz
            # `.cancel()` virar no-op. Só marcar `cancelado` se o cancelamento de
            # fato pegou — senão sobrescreveria um job que já terminou `pronto`.
            if task_job.cancelled():
                await marcar_cancelado(sessionmaker, job_id)
            else:
                logger.info(
                    "job %s concluiu antes do cancelamento surtir efeito — "
                    "mantendo o resultado (não marcando como cancelado)",
                    job_id,
                )
        elif task_job.done() and task_job.exception() is not None:
            # processar() só deixa escapar exceção em bug real — ela mesma
            # trata FonteInvalida/FalhaDeFerramenta/Exception internamente.
            logger.exception(
                "job %s: exceção não tratada escapou de processar()",
                job_id,
                exc_info=task_job.exception(),
            )
    finally:
        for task in (task_job, task_heartbeat, task_shutdown, task_cancelamento):
            if not task.done():
                task.cancel()
        await asyncio.gather(
            task_job, task_heartbeat, task_shutdown, task_cancelamento, return_exceptions=True
        )


async def _cancelar_task_job(task_job: asyncio.Task) -> None:
    """Cancela `task_job` e aguarda a `CancelledError` se propagar por completo —
    é isso que mata o subprocesso ffmpeg/ffprobe em voo (`pipeline/ferramentas.py`)
    e limpa o `.tmp` de empacotamento (`pipeline/hls.py::empacotar`, que captura
    `BaseException` — inclui `CancelledError` — para remover `destino_tmp`)."""
    task_job.cancel()
    try:
        await task_job
    except asyncio.CancelledError:
        pass


async def _bater_heartbeat(job_id: int, sessionmaker: _SessionMaker) -> None:
    try:
        while True:
            await asyncio.sleep(_INTERVALO_HEARTBEAT_S)
            await registrar_heartbeat(sessionmaker, job_id)
    except asyncio.CancelledError:
        pass


async def _observar_cancelamento(job_id: int, sessionmaker: _SessionMaker) -> None:
    """Consulta `Job.cancelamento_solicitado` no mesmo intervalo do heartbeat
    (`_INTERVALO_HEARTBEAT_S` — até esse tanto de latência entre `POST
    .../cancelar` pegar um job já em execução e o worker reagir). Termina assim
    que o sinalizador estiver `True`, o que conta como conclusão desta task para
    o `asyncio.wait` de `_processar_com_shutdown_cooperativo`."""
    while True:
        await asyncio.sleep(_INTERVALO_HEARTBEAT_S)
        if await cancelamento_foi_solicitado(sessionmaker, job_id):
            return


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    # Mídia e parciais criados pelo worker (e pelo ffmpeg/yt-dlp filhos) só do dono.
    os.umask(0o077)
    codigo_saida = asyncio.run(principal(carregar_config()))
    raise SystemExit(codigo_saida)


if __name__ == "__main__":
    main()

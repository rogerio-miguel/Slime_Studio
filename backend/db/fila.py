"""Acesso à tabela `Job` — todo acesso ao estado da fila passa por aqui
(ESPECIFICACAO.md §3B).

Sessões curtas: uma por operação, nunca segurando transação aberta durante o
`ffmpeg`. O claim atômico em `reivindicar_proximo` é seguro porque o UPDATE
reafirma o mesmo predicado de elegibilidade do SELECT no próprio WHERE e o
`rowcount` é conferido — nunca um SELECT seguido de UPDATE sem esse predicado.
"""

from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import ColumnElement, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.enums import ESTADOS_EM_EXECUCAO, StatusJob
from models.job import Job

_SessionMaker = async_sessionmaker[AsyncSession]


def _predicado_elegivel_para_claim(agora: datetime) -> ColumnElement[bool]:
    """Elegível para claim: `na_fila`, ou `falhou_extracao` com `proxima_tentativa_em`
    já vencida. Usado idêntico no SELECT e no UPDATE de `reivindicar_proximo` — as
    duas cópias precisam ser a mesma expressão, ou o claim atômico deixa de ser
    seguro (uma janela em que o SELECT vê um job que o UPDATE não reconhece)."""
    return or_(
        Job.status == StatusJob.NA_FILA,
        (Job.status == StatusJob.FALHOU_EXTRACAO) & (Job.proxima_tentativa_em <= agora),
    )


async def reciclar_jobs_orfaos(sessionmaker: _SessionMaker, *, limiar_s: int = 120) -> int:
    """Devolve para `na_fila` jobs travados num estado "em execução" com
    heartbeat velho (ou nunca setado) — cobre crash do worker e reboot da
    máquina. Roda uma vez no boot do worker."""
    limite = datetime.now(UTC) - timedelta(seconds=limiar_s)
    async with sessionmaker() as sessao:
        resultado = await sessao.execute(
            update(Job)
            .where(
                Job.status.in_(ESTADOS_EM_EXECUCAO),
                (Job.heartbeat_em.is_(None)) | (Job.heartbeat_em < limite),
            )
            .values(
                status=StatusJob.NA_FILA,
                worker_id=None,
                heartbeat_em=None,
                tentativas=Job.tentativas + 1,
                # Sem isto, um `cancelamento_solicitado=True` que a API setou num
                # job em execução sobrevive ao reclaim e cancela por engano a
                # PRÓXIMA tentativa (que nunca pediu cancelamento nenhum).
                cancelamento_solicitado=False,
            )
        )
        await sessao.commit()
        return resultado.rowcount


async def reivindicar_proximo(sessionmaker: _SessionMaker, *, worker_id: str) -> int | None:
    """Reivindica o próximo job elegível (`na_fila`, ou `falhou_extracao` com
    `proxima_tentativa_em` vencida), em ordem FIFO (`criado_em`).

    Claim atômico: o UPDATE reafirma o mesmo predicado do SELECT no WHERE e
    confere `rowcount`; se outra instância venceu a corrida para aquele id, tenta
    o próximo candidato da lista.
    """
    agora = datetime.now(UTC)
    predicado = _predicado_elegivel_para_claim(agora)
    async with sessionmaker() as sessao:
        candidatos = await sessao.execute(
            select(Job.id).where(predicado).order_by(Job.criado_em)
        )
        for (job_id,) in candidatos:
            resultado = await sessao.execute(
                update(Job)
                .where(Job.id == job_id, predicado)
                .values(
                    status=StatusJob.BAIXANDO,
                    worker_id=worker_id,
                    iniciado_em=datetime.now(UTC),
                )
            )
            if resultado.rowcount == 1:
                await sessao.commit()
                return job_id
        return None


async def registrar_heartbeat(sessionmaker: _SessionMaker, job_id: int) -> None:
    async with sessionmaker() as sessao:
        await sessao.execute(
            update(Job).where(Job.id == job_id).values(heartbeat_em=datetime.now(UTC))
        )
        await sessao.commit()


async def atualizar_status(
    sessionmaker: _SessionMaker,
    job_id: int,
    status: StatusJob,
    *,
    etapa: str | None = None,
    progresso_pct: int | None = None,
) -> None:
    valores: dict[str, object] = {"status": status}
    if etapa is not None:
        valores["etapa_atual"] = etapa
    if progresso_pct is not None:
        valores["progresso_pct"] = progresso_pct

    async with sessionmaker() as sessao:
        await sessao.execute(update(Job).where(Job.id == job_id).values(**valores))
        await sessao.commit()


async def concluir(sessionmaker: _SessionMaker, job_id: int) -> None:
    async with sessionmaker() as sessao:
        await sessao.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(status=StatusJob.PRONTO, progresso_pct=100, finalizado_em=datetime.now(UTC))
        )
        await sessao.commit()


async def falhar(sessionmaker: _SessionMaker, job_id: int, *, etapa: str, erro: str) -> None:
    async with sessionmaker() as sessao:
        await sessao.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(
                status=StatusJob.FALHOU,
                etapa_atual=etapa,
                erro_msg=erro,
                finalizado_em=datetime.now(UTC),
            )
        )
        await sessao.commit()


async def falhar_extracao(
    sessionmaker: _SessionMaker,
    job_id: int,
    *,
    etapa: str,
    erro: str,
    proxima_tentativa_em: datetime,
) -> None:
    """Falha retentável de extração (ESPECIFICACAO.md §3A): incrementa `tentativas`
    e agenda `proxima_tentativa_em` (backoff), mas **não** preenche `finalizado_em`
    — o job ainda vai ser reivindicado de novo por `reivindicar_proximo`."""
    async with sessionmaker() as sessao:
        await sessao.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(
                status=StatusJob.FALHOU_EXTRACAO,
                etapa_atual=etapa,
                erro_msg=erro,
                tentativas=Job.tentativas + 1,
                proxima_tentativa_em=proxima_tentativa_em,
            )
        )
        await sessao.commit()


async def marcar_aguardando_intervencao(
    sessionmaker: _SessionMaker, job_id: int, *, etapa: str, erro: str
) -> None:
    """Falha de extração esgotada (sem mais retentativas) ou não-retentável por
    natureza (`EstruturaDoSiteMudou`) — precisa de atenção humana, não é mais
    reivindicado automaticamente."""
    async with sessionmaker() as sessao:
        await sessao.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(
                status=StatusJob.AGUARDANDO_INTERVENCAO,
                etapa_atual=etapa,
                erro_msg=erro,
                finalizado_em=datetime.now(UTC),
            )
        )
        await sessao.commit()


async def devolver_para_fila(sessionmaker: _SessionMaker, job_id: int) -> None:
    """Usado no shutdown cooperativo por sinal — não é falha, não incrementa `tentativas`.

    Também limpa `cancelamento_solicitado`: sem isso, um cancelamento pedido
    pela API que ainda não tinha sido observado sobrevive ao reagendamento e
    cancela por engano a próxima tentativa (que nunca pediu cancelamento)."""
    async with sessionmaker() as sessao:
        await sessao.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(
                status=StatusJob.NA_FILA,
                worker_id=None,
                heartbeat_em=None,
                cancelamento_solicitado=False,
            )
        )
        await sessao.commit()


async def criar_job(
    sessionmaker: _SessionMaker, episodio_id: int, duracao_esperada_s: int | None = None
) -> int:
    """Cria um `Job` para um `Episodio` já existente, em `na_fila`. Usado por
    `db/catalogo.py::criar_episodio_e_job` (episódio e job em duas transações
    curtas, não uma — mesma filosofia de sessão-por-operação deste módulo)."""
    async with sessionmaker() as sessao:
        job = Job(
            episodio_id=episodio_id,
            status=StatusJob.NA_FILA,
            duracao_esperada_s=duracao_esperada_s,
        )
        sessao.add(job)
        await sessao.commit()
        return job.id


async def solicitar_cancelamento(
    sessionmaker: _SessionMaker, job_id: int
) -> Literal["cancelado", "cancelando", "invalido"]:
    """Cancela um job (ESPECIFICACAO.md §5, `POST /api/admin/jobs/{id}/cancelar`).

    A API nunca escreve `status` de um job já reivindicado pelo worker — esta
    coluna é do worker a partir daí. Job ainda não reivindicado (`na_fila`) ou
    parado numa retentativa (`falhou_extracao`) é cancelado direto aqui
    (`"cancelado"`). Job em execução só recebe o sinalizador
    `cancelamento_solicitado`; é o worker (`worker/__main__.py::_bater_heartbeat`)
    quem observa o sinalizador e faz a transição real para `cancelado`
    (`"cancelando"`, latência de até um ciclo de heartbeat). Qualquer outro
    estado (já finalizado, por exemplo) não pode ser cancelado (`"invalido"`).
    """
    async with sessionmaker() as sessao:
        resultado = await sessao.execute(
            update(Job)
            .where(
                Job.id == job_id,
                Job.status.in_((StatusJob.NA_FILA, StatusJob.FALHOU_EXTRACAO)),
            )
            .values(status=StatusJob.CANCELADO, finalizado_em=datetime.now(UTC))
        )
        if resultado.rowcount == 1:
            await sessao.commit()
            return "cancelado"

        resultado = await sessao.execute(
            update(Job)
            .where(Job.id == job_id, Job.status.in_(ESTADOS_EM_EXECUCAO))
            .values(cancelamento_solicitado=True)
        )
        if resultado.rowcount == 1:
            await sessao.commit()
            return "cancelando"

        await sessao.rollback()
        return "invalido"


# Estados dos quais um job pode ser retentado do zero (retry desta fase = requeue
# completo, sem retomar de chunk comitado — pós-gatilho de hardware, §12).
_ESTADOS_RETENTAVEIS: tuple[StatusJob, ...] = (
    StatusJob.FALHOU,
    StatusJob.FALHOU_EXTRACAO,
    StatusJob.AGUARDANDO_INTERVENCAO,
    StatusJob.CANCELADO,
)


async def marcar_cancelado(sessionmaker: _SessionMaker, job_id: int) -> None:
    """Finaliza um job como `cancelado` depois que o worker parou
    cooperativamente a task em execução, observando `cancelamento_solicitado`
    (`worker/__main__.py::_observar_cancelamento`). Diferente de
    `devolver_para_fila` (shutdown por sinal, que reagenda em vez de finalizar)."""
    async with sessionmaker() as sessao:
        await sessao.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(status=StatusJob.CANCELADO, worker_id=None, finalizado_em=datetime.now(UTC))
        )
        await sessao.commit()


async def cancelamento_foi_solicitado(sessionmaker: _SessionMaker, job_id: int) -> bool:
    async with sessionmaker() as sessao:
        resultado = await sessao.execute(
            select(Job.cancelamento_solicitado).where(Job.id == job_id)
        )
        return bool(resultado.scalar_one_or_none())


async def reagendar_para_retry(sessionmaker: _SessionMaker, job_id: int) -> bool:
    """Devolve `job_id` para `na_fila`, limpando todo estado da tentativa anterior.
    Devolve `False` se o job não estiver num estado retentável (`_ESTADOS_RETENTAVEIS`)."""
    async with sessionmaker() as sessao:
        resultado = await sessao.execute(
            update(Job)
            .where(Job.id == job_id, Job.status.in_(_ESTADOS_RETENTAVEIS))
            .values(
                status=StatusJob.NA_FILA,
                erro_msg=None,
                worker_id=None,
                heartbeat_em=None,
                finalizado_em=None,
                proxima_tentativa_em=None,
                cancelamento_solicitado=False,
                progresso_pct=0,
            )
        )
        await sessao.commit()
        return resultado.rowcount == 1

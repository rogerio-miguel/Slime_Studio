"""Acesso à tabela `Job` — todo acesso ao estado da fila passa por aqui
(ESPECIFICACAO.md §3B).

Sessões curtas: uma por operação, nunca segurando transação aberta durante o
`ffmpeg`. O claim atômico em `reivindicar_proximo` é seguro porque o UPDATE
reafirma o mesmo predicado de elegibilidade do SELECT no próprio WHERE e o
`rowcount` é conferido — nunca um SELECT seguido de UPDATE sem esse predicado.
"""

from datetime import UTC, datetime, timedelta

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
    """Usado no shutdown cooperativo por sinal — não é falha, não incrementa `tentativas`."""
    async with sessionmaker() as sessao:
        await sessao.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(status=StatusJob.NA_FILA, worker_id=None, heartbeat_em=None)
        )
        await sessao.commit()

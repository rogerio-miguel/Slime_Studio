"""Rotas de job: criação (dois modos), listagem/detalhe, cancelamento, retry e
notificações (ESPECIFICACAO.md §5, Passo 4 do plano da Fase 3)."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.dependencias import obter_sessao, obter_sessionmaker
from api.esquemas import (
    CancelarJobSaida,
    CriarJobLocalRequest,
    CriarJobRequest,
    JobCriadoSaida,
    JobSaida,
    RetryJobSaida,
)
from api.servicos import jobs as servico_jobs
from core.enums import StatusJob
from db.fila import reagendar_para_retry, solicitar_cancelamento
from models.anime import Anime
from models.job import Job

_SessionMaker = async_sessionmaker[AsyncSession]

router = APIRouter(prefix="/api/admin", tags=["admin-jobs"])


@router.post("/jobs", response_model=JobCriadoSaida, status_code=status.HTTP_201_CREATED)
async def criar_job(
    corpo: CriarJobRequest,
    sessionmaker: _SessionMaker = Depends(obter_sessionmaker),
    sessao: AsyncSession = Depends(obter_sessao),
) -> JobCriadoSaida:
    if isinstance(corpo, CriarJobLocalRequest):
        job_id = await servico_jobs.criar_job_local(
            sessionmaker,
            anime=corpo.anime,
            numero=corpo.numero,
            tipo=corpo.tipo,
            versao=corpo.versao,
            caminho_local=corpo.caminho_local,
            titulo_episodio=corpo.titulo_episodio,
            ano=corpo.ano,
            duracao_esperada_s=corpo.duracao_esperada_s,
        )
    else:
        anime = await sessao.get(Anime, corpo.anime_id)
        if anime is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="anime não encontrado"
            )
        job_id = await servico_jobs.criar_job_site(
            sessionmaker,
            anime=anime,
            numero=corpo.numero,
            tipo=corpo.tipo,
            versao=corpo.versao,
            duracao_esperada_s=corpo.duracao_esperada_s,
        )
    return JobCriadoSaida(job_id=job_id)


@router.get("/jobs", response_model=list[JobSaida])
async def listar_jobs(
    status_filtro: StatusJob | None = Query(default=None, alias="status"),
    sessao: AsyncSession = Depends(obter_sessao),
) -> list[Job]:
    consulta = select(Job).order_by(Job.criado_em.desc())
    if status_filtro is not None:
        consulta = consulta.where(Job.status == status_filtro)
    resultado = await sessao.execute(consulta)
    return list(resultado.scalars())


@router.get("/jobs/{job_id}", response_model=JobSaida)
async def obter_job(job_id: int, sessao: AsyncSession = Depends(obter_sessao)) -> Job:
    job = await sessao.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job não encontrado")
    return job


@router.post(
    "/jobs/{job_id}/cancelar", response_model=CancelarJobSaida, status_code=status.HTTP_202_ACCEPTED
)
async def cancelar_job(
    job_id: int,
    sessao: AsyncSession = Depends(obter_sessao),
    sessionmaker: _SessionMaker = Depends(obter_sessionmaker),
) -> CancelarJobSaida:
    job = await sessao.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job não encontrado")

    resultado = await solicitar_cancelamento(sessionmaker, job_id)
    if resultado == "invalido":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="job não pode ser cancelado no estado atual",
        )
    return CancelarJobSaida(status=resultado)


@router.post("/jobs/{job_id}/retry", response_model=RetryJobSaida)
async def retry_job(
    job_id: int,
    sessao: AsyncSession = Depends(obter_sessao),
    sessionmaker: _SessionMaker = Depends(obter_sessionmaker),
) -> RetryJobSaida:
    job = await sessao.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job não encontrado")

    reagendado = await reagendar_para_retry(sessionmaker, job_id)
    if not reagendado:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="job não pode ser retentado no estado atual",
        )
    return RetryJobSaida(job_id=job_id)


@router.get("/notificacoes", response_model=list[JobSaida])
async def notificacoes(sessao: AsyncSession = Depends(obter_sessao)) -> list[Job]:
    """Jobs que precisam de atenção humana (`aguardando_intervencao`) — o painel
    admin lista aqui o que o WS classificaria como "precisa de atenção" (esse
    rótulo é derivado do `status` pelo cliente, ver plano §3; esta rota é a
    mesma ideia como leitura simples, sob demanda)."""
    resultado = await sessao.execute(
        select(Job)
        .where(Job.status == StatusJob.AGUARDANDO_INTERVENCAO)
        .order_by(Job.finalizado_em.desc())
    )
    return list(resultado.scalars())

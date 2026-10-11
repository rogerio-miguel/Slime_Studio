"""Rotas de operação do circuit breaker por site (`/api/admin/sites*`),
ESPECIFICACAO.md §5, Passo 5 do plano da Fase 3."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.dependencias import obter_sessao, obter_sessionmaker
from api.esquemas import SiteSaida
from fontes.rede import circuit_breaker
from models.estado_site import EstadoSite

_SessionMaker = async_sessionmaker[AsyncSession]

router = APIRouter(prefix="/api/admin/sites", tags=["admin-sites"])


@router.get("", response_model=list[SiteSaida])
async def listar_sites(sessao: AsyncSession = Depends(obter_sessao)) -> list[SiteSaida]:
    resultado = await sessao.execute(select(EstadoSite))
    agora = datetime.now(UTC)
    return [
        SiteSaida(
            dominio=estado.site_dominio,
            falhas_consecutivas=estado.falhas_consecutivas,
            degradado=estado.cooldown_ate > agora,
            cooldown_ate=estado.cooldown_ate,
            ultima_falha_em=estado.ultima_falha_em,
            ultimo_erro=estado.ultimo_erro,
        )
        for estado in resultado.scalars()
    ]


@router.post("/{dominio}/reset", status_code=status.HTTP_204_NO_CONTENT)
async def resetar_site(
    dominio: str,
    sessao: AsyncSession = Depends(obter_sessao),
    sessionmaker: _SessionMaker = Depends(obter_sessionmaker),
) -> None:
    estado = await sessao.get(EstadoSite, dominio)
    if estado is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="site não encontrado")
    await circuit_breaker.registrar_sucesso(sessionmaker, dominio)

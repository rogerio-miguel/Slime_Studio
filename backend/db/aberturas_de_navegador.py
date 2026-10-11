"""Persistência das aberturas automáticas do navegador (`AberturaDeNavegador`)
— base do teto diário do zelador de fontes."""

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from models.abertura_de_navegador import AberturaDeNavegador

_SessionMaker = async_sessionmaker[AsyncSession]


async def aberturas_desde(sessao: AsyncSession, desde: datetime) -> int:
    resultado = await sessao.execute(
        select(func.count()).where(AberturaDeNavegador.aberta_em >= desde)
    )
    return resultado.scalar_one()


async def registrar_abertura(
    sessionmaker: _SessionMaker, dominio: str, agora: datetime | None = None
) -> None:
    async with sessionmaker() as sessao:
        sessao.add(AberturaDeNavegador(dominio=dominio, aberta_em=agora or datetime.now(UTC)))
        await sessao.commit()

"""Observabilidade da sondagem de fontes (`/api/admin/verificacoes`): o estado
persistido de cada verificação, para responder "quando foi verificado, quando
será de novo e por que não agora"."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencias import obter_sessao
from api.esquemas import VerificacaoSaida
from models.verificacao_de_anime import VerificacaoDeAnime

router = APIRouter(prefix="/api/admin/verificacoes", tags=["admin-verificacoes"])


@router.get("", response_model=list[VerificacaoSaida])
async def listar_verificacoes(
    anime_id: int | None = None, sessao: AsyncSession = Depends(obter_sessao)
) -> list[VerificacaoDeAnime]:
    consulta = select(VerificacaoDeAnime).order_by(VerificacaoDeAnime.proxima_em)
    if anime_id is not None:
        consulta = consulta.where(VerificacaoDeAnime.anime_id == anime_id)
    return list((await sessao.execute(consulta)).scalars())

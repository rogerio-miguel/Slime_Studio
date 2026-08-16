"""Rotas de anime: `/api/admin/animes*` (cadastro manual, confirmação de fonte,
remoção) e `/api/animes*` (catálogo público, leitura pelo player).

Fora do escopo desta fase (plano §4): `GET /api/admin/animes/buscar`
(AniList/Kitsu) — `integrations/` ainda não existe.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.dependencias import obter_config, obter_sessao, obter_sessionmaker
from api.esquemas import AnimeSaida, ConfirmarFonteRequest, CriarAnimeRequest, EpisodioSaida
from api.servicos import catalogo as servico_catalogo
from core.config import Config
from db.catalogo import obter_ou_criar_anime_id
from extractors.base import ResultadoBusca
from extractors.resolucao import confirmar_fonte
from models.anime import Anime
from models.episodio import Episodio

_SessionMaker = async_sessionmaker[AsyncSession]

router = APIRouter(prefix="/api/admin/animes", tags=["admin-animes"])
router_publico = APIRouter(prefix="/api/animes", tags=["animes"])


@router.post("", response_model=AnimeSaida)
async def criar_anime(
    corpo: CriarAnimeRequest,
    sessionmaker: _SessionMaker = Depends(obter_sessionmaker),
    sessao: AsyncSession = Depends(obter_sessao),
) -> Anime:
    """Get-or-create por slug — cadastro manual sem passar por busca de site."""
    anime_id = await obter_ou_criar_anime_id(sessionmaker, corpo.titulo, corpo.ano)
    return await sessao.get(Anime, anime_id)


@router.post("/{anime_id}/fontes/confirmar", status_code=status.HTTP_200_OK)
async def confirmar_fonte_do_anime(
    anime_id: int,
    corpo: ConfirmarFonteRequest,
    sessionmaker: _SessionMaker = Depends(obter_sessionmaker),
    sessao: AsyncSession = Depends(obter_sessao),
) -> dict[str, str]:
    """Stateless (D5 do plano): só grava `FonteAnime` e devolve 200. O cliente
    re-`POST`a `/api/admin/jobs` (modo `site`), que agora acha a fonte mapeada e
    segue sem pedir confirmação de novo."""
    anime = await sessao.get(Anime, anime_id)
    if anime is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="anime não encontrado")

    candidato = ResultadoBusca(
        titulo_exibicao=corpo.titulo_exibicao, identificador=corpo.identificador, url=corpo.url
    )
    await confirmar_fonte(sessionmaker, anime, corpo.dominio, candidato)
    return {"status": "ok"}


@router.delete("/{anime_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remover_anime(
    anime_id: int,
    config: Config = Depends(obter_config),
    sessionmaker: _SessionMaker = Depends(obter_sessionmaker),
) -> None:
    removido = await servico_catalogo.remover_anime(sessionmaker, config, anime_id)
    if not removido:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="anime não encontrado")


@router_publico.get("", response_model=list[AnimeSaida])
async def listar_animes(sessao: AsyncSession = Depends(obter_sessao)) -> list[Anime]:
    resultado = await sessao.execute(select(Anime).order_by(Anime.titulo))
    return list(resultado.scalars())


@router_publico.get("/{anime_id}/episodios", response_model=list[EpisodioSaida])
async def listar_episodios_do_anime(
    anime_id: int, sessao: AsyncSession = Depends(obter_sessao)
) -> list[Episodio]:
    resultado = await sessao.execute(
        select(Episodio).where(Episodio.anime_id == anime_id).order_by(Episodio.numero)
    )
    return list(resultado.scalars())

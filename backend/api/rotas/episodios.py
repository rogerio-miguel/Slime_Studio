"""Rotas de episódio: mídia HLS (sem `StaticFiles` — D1 do plano; servida via
`FileResponse`) e CRUD parcial de catálogo (`PATCH`/`DELETE`) + marcação de
assistido.

**Ordem de declaração importa**: `playlist.m3u8` precisa vir antes do catch-all
`{recurso:path}` — um catch-all declarado primeiro engolia o próprio manifesto.

Fora do escopo desta fase (plano §4): `POST /episodios/{id}/reduzir` (upscaling
em lote, pós-gatilho de hardware — ESPECIFICACAO.md §12).
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.dependencias import obter_config, obter_sessao, obter_sessionmaker
from api.esquemas import AtualizarEpisodioRequest, EpisodioSaida
from api.servicos import catalogo as servico_catalogo
from api.servicos.midia import RecursoDeMidiaInvalido, resolver_caminho
from core.config import Config
from models.episodio import Episodio

_SessionMaker = async_sessionmaker[AsyncSession]

router = APIRouter(prefix="/api/episodios", tags=["episodios"])
router_admin = APIRouter(prefix="/api/admin/episodios", tags=["admin-episodios"])

_TIPO_M3U8 = "application/vnd.apple.mpegurl"
_TIPO_TS = "video/mp2t"
_CACHE_MANIFESTO = "private, max-age=60"
_CACHE_SEGMENTO = "private, max-age=31536000, immutable"


@router.get("/{episodio_id}/playlist.m3u8")
async def obter_master(
    episodio_id: int,
    config: Config = Depends(obter_config),
    sessao: AsyncSession = Depends(obter_sessao),
) -> FileResponse:
    """Master manifest — `Episodio.hls_path` é dado do servidor (não input do
    usuário), então não passa pela guarda de traversal de `resolver_caminho`."""
    episodio = await sessao.get(Episodio, episodio_id)
    if episodio is None or episodio.hls_path is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="episódio sem HLS empacotado"
        )

    caminho = (config.media_root / episodio.hls_path).resolve()
    if not caminho.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="manifesto não encontrado em disco"
        )

    return FileResponse(caminho, media_type=_TIPO_M3U8, headers={"Cache-Control": _CACHE_MANIFESTO})


@router.get("/{episodio_id}/{recurso:path}")
async def obter_recurso(
    episodio_id: int,
    recurso: str,
    config: Config = Depends(obter_config),
    sessao: AsyncSession = Depends(obter_sessao),
) -> FileResponse:
    """Variante (`index.m3u8`) e segmentos (`seg_*.ts`) — o master os referencia
    relativamente, então servir o master em `.../playlist.m3u8` faz o `hls.js`
    resolver tudo daqui para baixo sem reescrever manifesto."""
    episodio = await sessao.get(Episodio, episodio_id)
    if episodio is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="episódio não encontrado"
        )

    try:
        caminho = resolver_caminho(config, episodio, recurso)
    except RecursoDeMidiaInvalido as excecao:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(excecao)) from excecao

    tipo = _TIPO_M3U8 if caminho.suffix == ".m3u8" else _TIPO_TS
    cache = _CACHE_MANIFESTO if caminho.suffix == ".m3u8" else _CACHE_SEGMENTO
    return FileResponse(caminho, media_type=tipo, headers={"Cache-Control": cache})


@router.post("/{episodio_id}/assistido", status_code=status.HTTP_204_NO_CONTENT)
async def marcar_assistido(
    episodio_id: int, sessao: AsyncSession = Depends(obter_sessao)
) -> None:
    resultado = await sessao.execute(
        update(Episodio).where(Episodio.id == episodio_id).values(assistido_em=datetime.now(UTC))
    )
    if resultado.rowcount == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="episódio não encontrado"
        )
    await sessao.commit()


@router_admin.patch("/{episodio_id}", response_model=EpisodioSaida)
async def atualizar_episodio(
    episodio_id: int,
    corpo: AtualizarEpisodioRequest,
    sessao: AsyncSession = Depends(obter_sessao),
) -> Episodio:
    episodio = await sessao.get(Episodio, episodio_id)
    if episodio is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="episódio não encontrado"
        )

    for campo, valor in corpo.model_dump(exclude_unset=True).items():
        setattr(episodio, campo, valor)

    try:
        await sessao.commit()
    except IntegrityError as excecao:
        await sessao.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="já existe um episódio com essa identidade (anime+numero+tipo+versao)",
        ) from excecao

    await sessao.refresh(episodio)
    return episodio


@router_admin.delete("/{episodio_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remover_episodio(
    episodio_id: int,
    config: Config = Depends(obter_config),
    sessionmaker: _SessionMaker = Depends(obter_sessionmaker),
) -> None:
    removido = await servico_catalogo.remover_episodio(sessionmaker, config, episodio_id)
    if not removido:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="episódio não encontrado"
        )

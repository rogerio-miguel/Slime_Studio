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
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.dependencias import obter_config, obter_sessao, obter_sessionmaker
from api.esquemas import (
    AtualizarEpisodioRequest,
    ContinuarAssistindoSaida,
    EpisodioSaida,
    SalvarProgressoRequest,
)
from api.servicos import catalogo as servico_catalogo
from api.servicos import progresso as servico_progresso
from api.servicos.midia import RecursoDeMidiaInvalido, resolver_caminho
from core.config import Config
from models.episodio import Episodio

_SessionMaker = async_sessionmaker[AsyncSession]

router = APIRouter(prefix="/api/episodios", tags=["episodios"])
router_admin = APIRouter(prefix="/api/admin/episodios", tags=["admin-episodios"])

_TIPO_M3U8 = "application/vnd.apple.mpegurl"
_TIPO_TS = "video/mp2t"
_CACHE_MANIFESTO = "private, max-age=60"
# Nunca `immutable`/max-age longo aqui: a URL do segmento (`seg_%05d.ts`) é
# determinística por anime/episódio (`diretorio_do_episodio`), não por
# conteúdo — uma recaptura (remover do catálogo + baixar de novo) gera bytes
# novos no mesmo caminho. `immutable` fazia o navegador nunca mais perguntar
# pro servidor depois da primeira carga, servindo o segmento antigo pra
# sempre mesmo após reprocessamento (bug reproduzido: bumper promocional do
# site de origem, capturado só na primeira tentativa, sobrevivendo em cache
# do Chrome a uma recaptura limpa). `FileResponse` do Starlette já calcula
# ETag/Last-Modified do arquivo em disco (`stat_result`), então isso aqui só
# evita a promessa falsa de imutabilidade — sem fetch, sem short-circuit 304
# nesta versão do Starlette, a próxima carga já pega o arquivo atual.
_CACHE_SEGMENTO = "private, max-age=0, must-revalidate"
# Limiar de conclusão espelhando `progresso.py::_LIMIAR_CONCLUSAO` — acima
# disso, o progresso salvo seria indistinguível de "já assistido", que é o
# gatilho de `liberar_episodio` (PaginaDoPlayer.jsx), não de salvar posição.
_LIMIAR_CONCLUSAO_PROGRESSO = 0.9


# Path fixo antes de qualquer rota com `{episodio_id}` no mesmo prefixo (mesma
# armadilha documentada em `api/rotas/animes.py` para `/em-alta`/`/buscar-fontes`
# vs. `/{anime_id}`) — sem isso um `{episodio_id}` declarado antes engoliria
# "continuar-assistindo" como valor de id (`int` typing barra a conversão, mas
# a ordem aqui segue o mesmo padrão defensivo do resto do arquivo).
@router.get("/continuar-assistindo", response_model=list[ContinuarAssistindoSaida])
async def continuar_assistindo(
    sessionmaker: _SessionMaker = Depends(obter_sessionmaker),
) -> list[ContinuarAssistindoSaida]:
    linhas = await servico_progresso.listar_continuar_assistindo(sessionmaker)
    return [
        ContinuarAssistindoSaida(
            episodio_id=linha.episodio_id,
            anime_id=linha.anime_id,
            anime_titulo=linha.anime_titulo,
            capa_path=linha.capa_path,
            numero=linha.numero,
            titulo=linha.titulo,
            progresso_s=linha.progresso_s,
            duracao_s=linha.duracao_s,
        )
        for linha in linhas
    ]


@router.get("/{episodio_id}", response_model=EpisodioSaida)
async def obter_episodio(
    episodio_id: int, sessao: AsyncSession = Depends(obter_sessao)
) -> Episodio:
    """Resolve o fallback de refresh de `PaginaDoPlayer.jsx` (título/anime/
    progresso quando `location.state` não veio, ex. acesso direto à URL)."""
    episodio = await sessao.get(Episodio, episodio_id)
    if episodio is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="episódio não encontrado"
        )
    return episodio


@router.post("/{episodio_id}/progresso", status_code=status.HTTP_204_NO_CONTENT)
async def salvar_progresso(
    episodio_id: int,
    corpo: SalvarProgressoRequest,
    sessao: AsyncSession = Depends(obter_sessao),
) -> None:
    linha = (
        await sessao.execute(select(Episodio.duracao_s).where(Episodio.id == episodio_id))
    ).first()
    if linha is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="episódio não encontrado"
        )
    (duracao_s,) = linha
    if duracao_s is not None and corpo.segundos > _LIMIAR_CONCLUSAO_PROGRESSO * duracao_s:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="segundos além do limiar de conclusão do episódio — use /assistido",
        )

    resultado = await sessao.execute(
        update(Episodio)
        .where(Episodio.id == episodio_id)
        .values(progresso_s=corpo.segundos, progresso_atualizado_em=datetime.now(UTC))
    )
    if resultado.rowcount == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="episódio não encontrado"
        )
    await sessao.commit()


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


@router.post("/{episodio_id}/liberar", status_code=status.HTTP_204_NO_CONTENT)
async def liberar_episodio(
    episodio_id: int,
    config: Config = Depends(obter_config),
    sessionmaker: _SessionMaker = Depends(obter_sessionmaker),
) -> None:
    """Rota pública (não `admin`) — ação do fluxo do player, disparada ao sair
    de um episódio já assistido (Feature "liberar arquivo ao terminar"), não
    gestão de catálogo."""
    liberado = await servico_catalogo.liberar_episodio(sessionmaker, config, episodio_id)
    if not liberado:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="episódio não encontrado"
        )


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

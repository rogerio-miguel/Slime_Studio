"""Rotas de anime: `/api/admin/animes*` (cadastro manual, confirmação de fonte,
remoção) e `/api/animes*` (catálogo público, leitura pelo player, feed "em
alta" de metadados externos via `integrations/`).
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.dependencias import obter_config, obter_sessao, obter_sessionmaker
from api.esquemas import (
    AnimeDetalheSaida,
    AnimeEmAltaSaida,
    AnimeSaida,
    BuscaEmFontesSaida,
    ConfirmarFonteRequest,
    CriarAnimeRequest,
    EpisodioRemotoSaida,
    EpisodioSaida,
    FonteConsultadaSaida,
    ResultadoBuscaFonteSaida,
)
from api.servicos import busca as servico_busca
from api.servicos import catalogo as servico_catalogo
from api.servicos import descoberta as servico_descoberta
from api.servicos import fontes as servico_fontes
from core.config import Config
from db.catalogo import obter_ou_criar_anime_id
from extractors import servico as servico_extractors
from extractors.base import EpisodioRemoto, ResultadoBusca
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
    """Get-or-create por slug — cadastro manual sem passar por busca de site.
    Metadados (capa/sinopse/ids de provedor) persistem direto se vierem no
    payload; se ausentes, `api/servicos/descoberta.py` tenta enriquecer por
    título em best-effort (nunca bloqueia esta criação)."""
    anime_id = await obter_ou_criar_anime_id(sessionmaker, corpo.titulo, corpo.ano)
    await servico_descoberta.enriquecer_anime_criado(
        sessionmaker,
        anime_id,
        corpo.titulo,
        anilist_id=corpo.anilist_id,
        kitsu_id=corpo.kitsu_id,
        capa_url=corpo.capa_url,
        sinopse=corpo.sinopse,
    )
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


@router.get("/{anime_id}/episodios-remotos", response_model=list[EpisodioRemotoSaida])
async def listar_episodios_remotos_do_anime(
    anime_id: int,
    sessao: AsyncSession = Depends(obter_sessao),
    sessionmaker: _SessionMaker = Depends(obter_sessionmaker),
) -> list[EpisodioRemoto]:
    """Posições de episódio na fonte remota (site) do anime — o frontend cruza
    isto com `GET /api/animes/{id}/episodios` (já capturados) para montar a
    grade prontos/não capturados na página do anime."""
    anime = await sessao.get(Anime, anime_id)
    if anime is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="anime não encontrado")
    return await servico_fontes.listar_episodios_remotos(sessionmaker, anime)


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


# `/em-alta` precisa vir ANTES de `/{anime_id}` — um `{anime_id}` declarado
# primeiro casaria com `anime_id="em-alta"` (mesma armadilha documentada em
# `api/rotas/episodios.py` para `playlist.m3u8` vs. o catch-all `{recurso:path}`).
@router_publico.get("/em-alta", response_model=list[AnimeEmAltaSaida])
async def listar_animes_em_alta(
    sessionmaker: _SessionMaker = Depends(obter_sessionmaker),
) -> list[AnimeEmAltaSaida]:
    pares = await servico_descoberta.listar_em_alta_com_catalogo(sessionmaker)
    return [
        AnimeEmAltaSaida(
            titulo_romaji=item.titulo_romaji,
            titulo_ingles=item.titulo_ingles,
            capa_url=item.capa_url,
            banner_url=item.banner_url,
            anilist_id=item.anilist_id,
            anime_id=anime_id,
        )
        for item, anime_id in pares
    ]


# `/buscar-fontes` precisa vir ANTES de `/{anime_id}` — mesma armadilha de
# `/em-alta` acima: um `{anime_id}` declarado primeiro casaria com
# `anime_id="buscar-fontes"`.
@router_publico.get("/buscar-fontes", response_model=BuscaEmFontesSaida)
async def buscar_animes_em_fontes(
    titulo: str = Query(..., max_length=200),
    sessionmaker: _SessionMaker = Depends(obter_sessionmaker),
) -> BuscaEmFontesSaida:
    """Busca ao vivo em todos os sites de extração (ainda não catalogado
    localmente) — alimenta a subseção "Resultados em outras fontes" da Home.
    `fontes` traz o status de cada site consultado (disponível ou não, com
    motivo) — a UI usa isso pra distinguir "não achei nada" de "não consegui
    nem tentar" (CLAUDE.md §4, erro nunca silencioso)."""
    if not titulo.strip():
        return BuscaEmFontesSaida(resultados=[], fontes=[])

    fontes = await servico_extractors.buscar_em_todas_as_fontes(sessionmaker, titulo)
    fontes = await servico_busca.enriquecer_capas(sessionmaker, fontes)
    return BuscaEmFontesSaida(
        resultados=[
            ResultadoBuscaFonteSaida(
                titulo_exibicao=candidato.titulo_exibicao,
                identificador=candidato.identificador,
                url=candidato.url,
                dominio=fonte.dominio,
                capa_url=candidato.capa_url,
            )
            for fonte in fontes
            for candidato in fonte.candidatos
        ],
        fontes=[
            FonteConsultadaSaida(
                dominio=fonte.dominio, indisponivel=fonte.indisponivel, motivo=fonte.motivo
            )
            for fonte in fontes
        ],
    )


@router_publico.get("/{anime_id}", response_model=AnimeDetalheSaida)
async def obter_anime(anime_id: int, sessao: AsyncSession = Depends(obter_sessao)) -> Anime:
    anime = await sessao.get(Anime, anime_id)
    if anime is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="anime não encontrado")
    return anime


@router_publico.get("/{anime_id}/episodios", response_model=list[EpisodioSaida])
async def listar_episodios_do_anime(
    anime_id: int, sessao: AsyncSession = Depends(obter_sessao)
) -> list[Episodio]:
    resultado = await sessao.execute(
        select(Episodio).where(Episodio.anime_id == anime_id).order_by(Episodio.numero)
    )
    return list(resultado.scalars())

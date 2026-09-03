"""Rotas de anime: `/api/admin/animes*` (cadastro manual, confirmação de fonte,
remoção) e `/api/animes*` (catálogo público, leitura pelo player, feed "em
alta" de metadados externos via `integrations/`).
"""

import logging

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
    EpisodiosRemotosSaida,
    EscopoBusca,
    FonteConsultadaSaida,
    ResultadoBuscaFonteSaida,
)
from api.servicos import busca as servico_busca
from api.servicos import capas as servico_capas
from api.servicos import catalogo as servico_catalogo
from api.servicos import descoberta as servico_descoberta
from api.servicos import fontes as servico_fontes
from api.servicos import jobs as servico_jobs
from api.servicos import lancamentos as servico_lancamentos
from api.servicos import sondagem as servico_sondagem
from core.config import Config
from core.enums import VersaoDeFonte, VersaoEpisodio
from db.catalogo import obter_ou_criar_anime_id
from extractors.base import ResultadoBusca
from extractors.registro import EXTRATORES
from extractors.resolucao import confirmar_fonte
from extractors.versao import inferir_versao
from integrations.base import AnimeEmAlta
from models.anime import Anime
from models.episodio import Episodio
from models.fonte_anime import FonteAnime

_SessionMaker = async_sessionmaker[AsyncSession]

logger = logging.getLogger(__name__)

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
    segue sem pedir confirmação de novo.

    `corpo.versao` é o round-trip do que o frontend recebeu em
    `ResultadoBuscaFonteSaida.versao` pro candidato escolhido — nunca a fonte de
    verdade: o servidor rederiva via `inferir_versao` (mesma lógica de
    `extractors/resolucao.py::confirmar_fonte`) e só loga se divergir."""
    anime = await sessao.get(Anime, anime_id)
    if anime is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="anime não encontrado")

    extrator = next((e for e in EXTRATORES if e.dominio == corpo.dominio), None)
    versao_servidor: VersaoEpisodio | None = None
    if extrator is not None and extrator.diferencia_versao:
        versao_servidor = (
            inferir_versao(corpo.titulo_exibicao, corpo.identificador) or VersaoEpisodio.LEGENDADO
        )
        if corpo.versao is not None and corpo.versao != versao_servidor:
            logger.warning(
                "versão divergente ao confirmar fonte em %r: cliente=%r, servidor=%r —"
                " usando servidor",
                corpo.dominio,
                corpo.versao,
                versao_servidor,
            )

    candidato = ResultadoBusca(
        titulo_exibicao=corpo.titulo_exibicao,
        identificador=corpo.identificador,
        url=corpo.url,
        versao=versao_servidor,
    )
    await confirmar_fonte(sessionmaker, anime, corpo.dominio, candidato)
    return {"status": "ok"}


@router.get("/{anime_id}/episodios-remotos", response_model=EpisodiosRemotosSaida)
async def listar_episodios_remotos_do_anime(
    anime_id: int,
    versao: VersaoEpisodio = Query(VersaoEpisodio.LEGENDADO),
    sessao: AsyncSession = Depends(obter_sessao),
    sessionmaker: _SessionMaker = Depends(obter_sessionmaker),
) -> EpisodiosRemotosSaida:
    """Posições de episódio na fonte remota (site) do anime — o frontend cruza
    isto com `GET /api/animes/{id}/episodios` (já capturados) para montar a
    grade prontos/não capturados na página do anime. `dominio` identifica qual
    site resolveu a lista abaixo (hipótese mais provável de divergência de
    contagem de episódios: fonte errada sendo exibida sem indicação de qual
    site foi usado). `versao` tem default `LEGENDADO` pra preservar o
    comportamento anterior à Fase 3 até o frontend passar a enviá-la."""
    anime = await sessao.get(Anime, anime_id)
    if anime is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="anime não encontrado")
    resultado = await servico_fontes.listar_episodios_remotos(sessionmaker, anime, versao)
    return EpisodiosRemotosSaida(
        dominio=resultado.dominio,
        episodios=[
            EpisodioRemotoSaida(rotulo=episodio.rotulo, numero=episodio.numero)
            for episodio in resultado.episodios
        ],
    )


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
async def listar_animes(
    sessao: AsyncSession = Depends(obter_sessao),
    sessionmaker: _SessionMaker = Depends(obter_sessionmaker),
) -> list[AnimeSaida]:
    resultado = await sessao.execute(select(Anime).order_by(Anime.titulo))
    animes = list(resultado.scalars())
    ids = [anime.id for anime in animes]
    maior_capturado = await servico_lancamentos.maior_numero_capturado_por_anime(sessao, ids)
    com_episodios = await servico_catalogo.ids_com_episodios(sessao, ids)
    # Carona fire-and-forget: sonda a fonte real dos animes em lançamento cuja
    # contagem está velha/ausente. O resultado entra no banco para a PRÓXIMA
    # leitura do catálogo, não para esta (`api/servicos/sondagem.py`). Zero
    # `await` de rede aqui — só a query agregada abaixo e o agendamento síncrono.
    versoes = await servico_sondagem.versoes_de_sondagem_por_anime(sessao, ids)
    servico_sondagem.agendar_sondagens(sessionmaker, animes, versoes)
    # Aquece o `status_lancamento` (filtro do badge) dos animes que nunca foram
    # abertos individualmente — sem isso ficam `NULL` e o badge nunca aparece.
    servico_descoberta.agendar_refreshs_do_catalogo(sessionmaker, animes)
    # `status_lancamento` e `proximo_ep_em` vêm do `model_validate` (campos
    # mapeados 1:1 com colunas de `Anime`); `episodios_novos` e `tem_episodios`
    # são derivados e precisam ser injetados à parte.
    return [
        AnimeSaida.model_validate(anime).model_copy(
            update={
                "episodios_novos": servico_lancamentos.episodios_novos(
                    anime, maior_capturado.get(anime.id, 0)
                ),
                "tem_episodios": anime.id in com_episodios,
            }
        )
        for anime in animes
    ]


# `/em-alta` precisa vir ANTES de `/{anime_id}` — um `{anime_id}` declarado
# primeiro casaria com `anime_id="em-alta"` (mesma armadilha documentada em
# `api/rotas/episodios.py` para `playlist.m3u8` vs. o catch-all `{recurso:path}`).
@router_publico.get("/em-alta", response_model=list[AnimeEmAltaSaida])
async def listar_animes_em_alta(
    sessionmaker: _SessionMaker = Depends(obter_sessionmaker),
) -> list[AnimeEmAltaSaida]:
    pares = await servico_descoberta.listar_em_alta_com_catalogo(sessionmaker)
    return [_para_saida_em_alta(item, anime_id) for item, anime_id in pares]


# `/proxima-temporada` — mesma armadilha de ordem de `/em-alta`: precisa vir
# ANTES de `/{anime_id}`, senão casaria com `anime_id="proxima-temporada"`.
@router_publico.get("/proxima-temporada", response_model=list[AnimeEmAltaSaida])
async def listar_animes_proxima_temporada(
    sessionmaker: _SessionMaker = Depends(obter_sessionmaker),
) -> list[AnimeEmAltaSaida]:
    pares = await servico_descoberta.listar_proxima_temporada_com_catalogo(sessionmaker)
    return [_para_saida_em_alta(item, anime_id) for item, anime_id in pares]


def _para_saida_em_alta(item: AnimeEmAlta, anime_id: int | None) -> AnimeEmAltaSaida:
    """Traduz um item do feed (`integrations.base.AnimeEmAlta`) já cruzado com o
    catálogo para o schema HTTP. `item.lancamento` pode ser `None` (nem todo item
    do feed traz bloco) — os três escalares de lançamento caem para `None`."""
    lanc = item.lancamento
    return AnimeEmAltaSaida(
        titulo_romaji=item.titulo_romaji,
        titulo_ingles=item.titulo_ingles,
        capa_url=item.capa_url,
        banner_url=item.banner_url,
        anilist_id=item.anilist_id,
        anime_id=anime_id,
        ano_estreia=item.ano_estreia,
        generos=list(item.generos),
        capa_cor=item.capa_cor,
        status_lancamento=lanc.status if lanc else None,
        proximo_ep_numero=lanc.proximo_ep_numero if lanc else None,
        proximo_ep_em=lanc.proximo_ep_em if lanc else None,
    )


# `/buscar-fontes` precisa vir ANTES de `/{anime_id}` — mesma armadilha de
# `/em-alta` acima: um `{anime_id}` declarado primeiro casaria com
# `anime_id="buscar-fontes"`.
@router_publico.get("/buscar-fontes", response_model=BuscaEmFontesSaida)
async def buscar_animes_em_fontes(
    titulo: str = Query(..., max_length=200),
    escopo: EscopoBusca = Query("padrao"),
    sessionmaker: _SessionMaker = Depends(obter_sessionmaker),
) -> BuscaEmFontesSaida:
    """Busca ao vivo em sites de extração (ainda não catalogado localmente).
    `escopo=padrao` (default): motor sequencial por site da Fase A, alimenta
    a subseção "Resultados em outras fontes" da Home. `escopo=todas`: cada
    site busca em paralelo, esgotando de forma independente e exaustiva sua
    própria escada de variantes, sem que um "roube a vez" do outro (INV-1',
    `extractors.busca.servico.buscar_por_site_com_variantes`) — alimenta o diálogo
    "Trocar fonte" (D-B1, PLANO_PADRONIZACAO_FONTES.md — mesmo response
    assembly abaixo nos dois escopos, só a estratégia de iteração de site
    difere). `fontes` traz o status de cada site consultado (disponível ou
    não, com motivo) — a UI usa isso pra distinguir "não achei nada" de "não
    consegui nem tentar" (CLAUDE.md §4, erro nunca silencioso)."""
    if not titulo.strip():
        return BuscaEmFontesSaida(resultados=[], fontes=[])

    if escopo == "todas":
        busca = await servico_busca.buscar_em_todas_as_fontes_com_titulos_alternativos(
            sessionmaker, titulo
        )
    else:
        busca = await servico_busca.buscar_com_titulos_alternativos(sessionmaker, titulo)
    fontes = await servico_capas.enriquecer_capas(sessionmaker, busca.fontes)
    return BuscaEmFontesSaida(
        resultados=[
            ResultadoBuscaFonteSaida(
                titulo_exibicao=candidato.titulo_exibicao,
                identificador=candidato.identificador,
                url=candidato.url,
                dominio=fonte.dominio,
                capa_url=candidato.capa_url,
                versao=candidato.versao,
                site_diferencia_versao=_diferencia_versao(fonte.dominio),
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
        termo_alternativo=busca.termo_alternativo,
        dominio_alternativo=busca.dominio_alternativo,
    )


@router_publico.get("/{anime_id}", response_model=AnimeDetalheSaida)
async def obter_anime(
    anime_id: int,
    sessao: AsyncSession = Depends(obter_sessao),
    sessionmaker: _SessionMaker = Depends(obter_sessionmaker),
) -> AnimeDetalheSaida:
    anime = await sessao.get(Anime, anime_id)
    if anime is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="anime não encontrado")
    # F4b: refresh lazy fire-and-forget do estado de lançamento — não aguarda,
    # só agenda para a próxima leitura (ver `descoberta.agendar_refresh_de_lancamento`).
    servico_descoberta.agendar_refresh_de_lancamento(sessionmaker, anime)
    resultado = await sessao.execute(
        select(FonteAnime.versao, FonteAnime.resolvido_em).where(FonteAnime.anime_id == anime_id)
    )
    fontes_mapeadas = resultado.all()
    versoes_de_fonte = {linha.versao for linha in fontes_mapeadas}
    mais_recente = max(fontes_mapeadas, key=lambda linha: linha.resolvido_em, default=None)
    versao_confirmada_mais_recente = (
        servico_jobs.versao_episodio_da_fonte(mais_recente.versao)
        if mais_recente is not None
        else None
    )
    # Sondagem oportunista da fonte real — mesma carona fire-and-forget do
    # `agendar_refresh_de_lancamento` de F4b acima, mas alimentando
    # `Anime.episodios_na_fonte`. Reusa a linha de `FonteAnime` já lida (sem
    # `versao_confirmada`/`DESCONHECIDA` da tradução de F4: aqui é
    # `versao_de_sondagem`, `NAO_DIFERENCIADA -> LEGENDADO`).
    versoes_de_sondagem = (
        {anime.id: servico_sondagem.versao_de_sondagem(mais_recente.versao)}
        if mais_recente is not None
        else {}
    )
    servico_sondagem.agendar_sondagens(sessionmaker, [anime], versoes_de_sondagem)
    return AnimeDetalheSaida(
        id=anime.id,
        titulo=anime.titulo,
        slug=anime.slug,
        ano=anime.ano,
        capa_path=anime.capa_path,
        sinopse=anime.sinopse,
        criado_em=anime.criado_em,
        versoes_disponiveis=_versoes_disponiveis(versoes_de_fonte),
        versao_confirmada_mais_recente=versao_confirmada_mais_recente,
        status_lancamento=anime.status_lancamento,
    )


def _diferencia_versao(dominio: str) -> bool:
    """`ExtratorDeSite.diferencia_versao` do extractor registrado para `dominio`
    (`False` se o domínio não estiver registrado)."""
    extrator = next((e for e in EXTRATORES if e.dominio == dominio), None)
    return extrator.diferencia_versao if extrator is not None else False


def _versoes_disponiveis(versoes_de_fonte: set[VersaoDeFonte]) -> list[VersaoEpisodio]:
    """Deriva as versões "disponíveis" de um anime a partir das linhas de
    `FonteAnime` já mapeadas — não é live-probe (ver docstring de `obter_anime`).

    Sem nenhuma linha (fonte nunca resolvida) ou com qualquer linha
    `NAO_DIFERENCIADA` (fonte serve qualquer versão pedida), ambas contam como
    disponíveis; senão, só as versões com linha confirmada."""
    if not versoes_de_fonte or VersaoDeFonte.NAO_DIFERENCIADA in versoes_de_fonte:
        return [VersaoEpisodio.LEGENDADO, VersaoEpisodio.DUBLADO]
    disponiveis = []
    if VersaoDeFonte.LEGENDADO in versoes_de_fonte:
        disponiveis.append(VersaoEpisodio.LEGENDADO)
    if VersaoDeFonte.DUBLADO in versoes_de_fonte:
        disponiveis.append(VersaoEpisodio.DUBLADO)
    return disponiveis


@router_publico.get("/{anime_id}/episodios", response_model=list[EpisodioSaida])
async def listar_episodios_do_anime(
    anime_id: int, sessao: AsyncSession = Depends(obter_sessao)
) -> list[Episodio]:
    resultado = await sessao.execute(
        select(Episodio).where(Episodio.anime_id == anime_id).order_by(Episodio.numero)
    )
    return list(resultado.scalars())

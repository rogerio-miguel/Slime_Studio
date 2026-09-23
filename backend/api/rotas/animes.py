"""Rotas de anime: `/api/admin/animes*` (cadastro manual, confirmação de fonte,
remoção) e `/api/animes*` (catálogo público, leitura pelo player, feed "em
alta" de metadados externos via `integrations/`).
"""

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.dependencias import obter_config, obter_sessao, obter_sessionmaker
from api.esquemas import (
    AnimeDetalheSaida,
    AnimeEmAltaSaida,
    AnimeSaida,
    AquecimentoCatalogoSaida,
    BuscaEmFontesSaida,
    ConfirmarFonteRequest,
    CriarAnimeRequest,
    EpisodioRemotoSaida,
    EpisodioSaida,
    EpisodiosRemotosSaida,
    FileiraTematicaSaida,
    FonteConsultadaSaida,
    ResultadoBuscaFonteSaida,
    TemporadaIrmaSaida,
)
from api.servicos import busca as servico_busca
from api.servicos import catalogo as servico_catalogo
from api.servicos import descoberta as servico_descoberta
from api.servicos import fontes as servico_fontes
from api.servicos import jobs as servico_jobs
from api.servicos import lancamentos as servico_lancamentos
from api.servicos import sondagem as servico_sondagem
from core.config import Config
from core.enums import StatusLancamento, VersaoDeFonte, VersaoEpisodio
from core.franquia import slug_de_franquia
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
    anime_id = await obter_ou_criar_anime_id(
        sessionmaker, corpo.titulo, corpo.ano, formato_midia=corpo.formato
    )
    await servico_descoberta.enriquecer_anime_criado(
        sessionmaker,
        anime_id,
        corpo.titulo,
        anilist_id=corpo.anilist_id,
        kitsu_id=corpo.kitsu_id,
        capa_url=corpo.capa_url,
        sinopse=corpo.sinopse,
        banner_url=corpo.banner_url,
        capa_cor=corpo.capa_cor,
        generos=corpo.generos,
        titulo_ingles=corpo.titulo_ingles,
        formato=corpo.formato,
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
    `ResultadoBuscaFonteSaida.versao` pro candidato escolhido. Preferência: o
    servidor rederiva via `inferir_versao` (mesma lógica de
    `extractors/resolucao.py::confirmar_fonte`) quando encontra marcador no
    texto — sites como AnimesDrive/MeusAnimes o carregam no slug/título, e aí
    o servidor não confia cegamente no cliente. Sites como AnimeFire
    diferenciam por um campo à parte da API (`audio`, sem marcador textual —
    `extractors/animefire.py::_resultados_do_item`) e `inferir_versao` NUNCA
    encontra nada pra eles: sem esta ressalva, toda confirmação nesses sites
    era silenciosamente regravada como `LEGENDADO`, não importa o que o
    usuário escolheu (`corpo.versao`, já calculado com o sinal correto lá na
    busca, é o round-trip confiável nesse caso)."""
    anime = await sessao.get(Anime, anime_id)
    if anime is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="anime não encontrado")

    extrator = next((e for e in EXTRATORES if e.dominio == corpo.dominio), None)
    versao_servidor: VersaoEpisodio | None = None
    if extrator is not None and extrator.diferencia_versao:
        versao_inferida = inferir_versao(corpo.titulo_exibicao, corpo.identificador)
        if versao_inferida is not None:
            versao_servidor = versao_inferida
            if corpo.versao is not None and corpo.versao != versao_servidor:
                logger.warning(
                    "versão divergente ao confirmar fonte em %r: cliente=%r, servidor=%r —"
                    " usando servidor",
                    corpo.dominio,
                    corpo.versao,
                    versao_servidor,
                )
        else:
            versao_servidor = corpo.versao or VersaoEpisodio.LEGENDADO

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
            EpisodioRemotoSaida(
                rotulo=episodio.rotulo,
                numero=episodio.numero,
                thumb_url=episodio.thumb_url,
                titulo=episodio.titulo,
                sinopse=episodio.sinopse,
            )
            for episodio in resultado.episodios
        ],
    )


@router.post("/{anime_id}/marcar-todos-assistidos", status_code=status.HTTP_204_NO_CONTENT)
async def marcar_todos_assistidos(
    anime_id: int,
    versao: VersaoEpisodio = Query(VersaoEpisodio.LEGENDADO),
    sessao: AsyncSession = Depends(obter_sessao),
    sessionmaker: _SessionMaker = Depends(obter_sessionmaker),
) -> None:
    """Botão "Marcar como assistido" da página do anime — marca `assistido_em`
    (agora) em todo `Episodio` já capturado localmente que ainda não tem a
    marca, e ainda cria (`LIBERADO`, sem `Job`) um `Episodio` pra cada número
    que a fonte remota ativa lista e que o usuário nunca capturou (pedido
    explícito do usuário: o botão marca TODO episódio disponível, não só os já
    baixados). `versao` decide qual fonte resolver pro segundo passo — mesmo
    parâmetro que `PaginaDoAnime.jsx` já manda pra `episodios-remotos`/
    `criar_job_site` (`versaoPedida`). Detalhe em
    `api/servicos/jobs.py::marcar_todos_assistidos`."""
    anime = await sessao.get(Anime, anime_id)
    if anime is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="anime não encontrado")
    await servico_jobs.marcar_todos_assistidos(sessionmaker, anime=anime, versao=versao)


@router.post(
    "/{anime_id}/episodios/{numero}/marcar-assistido", status_code=status.HTTP_204_NO_CONTENT
)
async def marcar_episodio_assistido(
    anime_id: int,
    numero: int,
    versao: VersaoEpisodio = Query(VersaoEpisodio.LEGENDADO),
    sessao: AsyncSession = Depends(obter_sessao),
    sessionmaker: _SessionMaker = Depends(obter_sessionmaker),
) -> None:
    """Item "Marcar como assistido" do menu de
    `components/CartaoContinuarAssistindo.jsx` (Home) — mesma semântica de
    `marcar_todos_assistidos` acima, restrita a UM número (pedido explícito
    do usuário: "Continuar assistindo" mostra só o próximo episódio, marcar o
    anime inteiro dali surpreende). Detalhe em
    `api/servicos/jobs.py::marcar_episodio_assistido`."""
    anime = await sessao.get(Anime, anime_id)
    if anime is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="anime não encontrado")
    await servico_jobs.marcar_episodio_assistido(
        sessionmaker, anime=anime, numero=numero, versao=versao
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
    aquecer: bool = False,
    sessao: AsyncSession = Depends(obter_sessao),
    sessionmaker: _SessionMaker = Depends(obter_sessionmaker),
) -> list[AnimeSaida]:
    # `formato_midia IS NULL` exclui filme/OVA/ONA/especial: essas linhas se
    # agrupam no anime original (seletor de temporada, `_agrupar_franquias`/
    # `_temporadas_e_proxima`) em vez de aparecer como card solto na grade.
    resultado = await sessao.execute(
        select(Anime).where(Anime.formato_midia.is_(None)).order_by(Anime.titulo)
    )
    animes = list(resultado.scalars())
    ids = [anime.id for anime in animes]
    maior_capturado = await servico_lancamentos.maior_numero_capturado_por_anime(sessao, ids)
    com_episodios = await servico_catalogo.ids_com_episodios(sessao, ids)
    assistidos = await servico_lancamentos.ids_totalmente_assistidos(sessao, animes)
    # Badge "Dublado"/"Legendado" (uma query batched, não uma por card — ver
    # docstring de `versoes_confirmadas_mais_recentes_por_anime`) e aviso
    # "Nª temporada estreia em ..." (agrupamento de franquia rodado uma vez,
    # `_agrupar_franquias`, reaproveitado por card — ver docstring de
    # `_temporadas_e_proxima`).
    versoes_confirmadas = await servico_sondagem.versoes_confirmadas_mais_recentes_por_anime(
        sessao, ids
    )
    grupos_de_franquia = await _agrupar_franquias(sessao)
    # Aquecimento opt-in via `?aquecer=true`: carona fire-and-forget que sonda a
    # fonte real (scraping) dos animes em lançamento com contagem velha/ausente e
    # aquece o `status_lancamento` (filtro do badge) via AniList/Kitsu. Só a
    # Galeria (`paginas/Galeria.jsx`, rota `/animes` — catálogo completo com os
    # badges) envia a flag; a Home (`paginas/Inicio.jsx`) chama sem ela e não
    # paga esse custo a cada abertura. O resultado entra no banco para a PRÓXIMA
    # leitura do catálogo, não para esta — logo o badge de "episódios novos" na
    # Home reflete a última passada da Galeria. Zero `await` de rede aqui: a
    # query de versões só alimenta o agendamento, que é síncrono.
    if aquecer:
        versoes = await servico_sondagem.versoes_de_sondagem_por_anime(sessao, ids)
        # Reparo de fonte perdida (2026-09-15, migração
        # `26791d90cb31_invalida_fonte_anime_do_animefire_one`): anime com
        # episódio capturado mas ZERO `FonteAnime` mapeada nunca ganha entrada
        # em `versoes_de_sondagem_por_anime` (não há fonte pra consultar) e
        # `agendar_sondagens` o pulava pra sempre — só um `versao_confirmada_
        # mais_recente` nulo pro badge Dublado/Legendado sumir do card sem
        # nenhum jeito automático de voltar. Palpite de versão vem do próprio
        # episódio já capturado; `ignorar_gate_de_status` deixa isto tentar
        # mesmo pra anime `FINALIZADO` (o gate normal de status não se aplica
        # aqui — é reparo pontual, não sondagem contínua de contagem).
        # `ids_fora_de_cooldown_de_reparo` corta quem falhou a varredura cara
        # (todos os extratores, sem fonte mapeada pra atalhar) há pouco tempo —
        # sem isto, um anime não encontrado em lugar nenhum repetia a
        # varredura inteira a cada `?aquecer=true`.
        ids_sem_fonte_com_episodios = servico_sondagem.ids_fora_de_cooldown_de_reparo(
            aid for aid in ids if aid in com_episodios and aid not in versoes
        )
        versoes_de_reparo = await servico_sondagem.versoes_para_reresolver_fonte_perdida(
            sessao, ids_sem_fonte_com_episodios
        )
        versoes = {**versoes, **versoes_de_reparo}
        servico_sondagem.agendar_sondagens(
            sessionmaker,
            animes,
            versoes,
            ignorar_gate_de_status=frozenset(versoes_de_reparo),
        )
        servico_descoberta.agendar_refreshs_do_catalogo(sessionmaker, animes)
    # `status_lancamento` e `proximo_ep_em` vêm do `model_validate` (campos
    # mapeados 1:1 com colunas de `Anime`); `episodios_novos`, `tem_episodios`,
    # `assistido` e `episodios_atuais` são derivados e precisam ser injetados à
    # parte.
    resultado_saida = []
    for anime in animes:
        _, proxima_temporada = _temporadas_e_proxima(
            anime.id, anime.numero_temporada, grupos_de_franquia[anime.id]
        )
        resultado_saida.append(
            AnimeSaida.model_validate(anime).model_copy(
                update={
                    "episodios_novos": servico_lancamentos.episodios_novos(
                        anime, maior_capturado.get(anime.id, 0)
                    ),
                    "tem_episodios": anime.id in com_episodios,
                    "assistido": anime.id in assistidos,
                    "episodios_atuais": max(
                        maior_capturado.get(anime.id, 0), anime.episodios_na_fonte or 0
                    )
                    or None,
                    "versao_confirmada_mais_recente": versoes_confirmadas.get(anime.id),
                    "proxima_temporada": proxima_temporada,
                }
            )
        )
    return resultado_saida


# Mesma armadilha de ordem de `/em-alta` abaixo: precisa vir ANTES de
# `/{anime_id}`, senão casaria com `anime_id="aquecimento-em-andamento"`.
@router_publico.get("/aquecimento-em-andamento", response_model=AquecimentoCatalogoSaida)
async def aquecimento_em_andamento(
    sessao: AsyncSession = Depends(obter_sessao),
) -> AquecimentoCatalogoSaida:
    ids = (
        (await sessao.execute(select(Anime.id).where(Anime.formato_midia.is_(None))))
        .scalars()
        .all()
    )
    em_andamento = servico_sondagem.sondagem_em_andamento(
        ids
    ) or servico_descoberta.refresh_em_andamento(ids)
    return AquecimentoCatalogoSaida(em_andamento=em_andamento)


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


# `/novos-lancamentos` — mesma armadilha de ordem de `/em-alta`: precisa vir
# ANTES de `/{anime_id}`, senão casaria com `anime_id="novos-lancamentos"`.
@router_publico.get("/novos-lancamentos", response_model=list[AnimeEmAltaSaida])
async def listar_animes_novos_lancamentos(
    sessionmaker: _SessionMaker = Depends(obter_sessionmaker),
) -> list[AnimeEmAltaSaida]:
    pares = await servico_descoberta.listar_novos_lancamentos_com_catalogo(sessionmaker)
    return [_para_saida_em_alta(item, anime_id) for item, anime_id in pares]


# `/fileiras-tematicas` — mesma armadilha de ordem de `/em-alta`/`/proxima-
# temporada`: precisa vir ANTES de `/{anime_id}`, senão casaria com
# `anime_id="fileiras-tematicas"`.
@router_publico.get("/fileiras-tematicas", response_model=list[FileiraTematicaSaida])
async def listar_animes_fileiras_tematicas(
    sessionmaker: _SessionMaker = Depends(obter_sessionmaker),
) -> list[FileiraTematicaSaida]:
    fileiras = await servico_descoberta.listar_fileiras_tematicas_com_catalogo(sessionmaker)
    return [
        FileiraTematicaSaida(
            chave=chave,
            itens=[_para_saida_em_alta(item, anime_id) for item, anime_id in pares],
        )
        for chave, pares in fileiras
    ]


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
        total_episodios=lanc.total_episodios if lanc else None,
        sinopse=item.sinopse,
        formato=item.formato,
        episodio_lancado=item.episodio_lancado,
    )


# `/buscar` precisa vir ANTES de `/{anime_id}` — mesma armadilha de `/em-alta`:
# um `{anime_id}` declarado primeiro casaria com `anime_id="buscar"`.
@router_publico.get("/buscar", response_model=list[AnimeEmAltaSaida])
async def buscar_animes(
    titulo: str = Query(..., max_length=200),
    sessionmaker: _SessionMaker = Depends(obter_sessionmaker),
) -> list[AnimeEmAltaSaida]:
    """Busca livre de anime na biblioteca de metadados (AniList) — alimenta a
    busca da Home. Cada temporada é uma entrada AniList própria (o catálogo
    local agrupa por franquia numa fase futura); `anime_id` vem preenchido
    quando aquela temporada já está catalogada. Mesmo schema de saída do feed
    "em alta"."""
    if not titulo.strip():
        return []
    pares = await servico_descoberta.listar_busca_com_catalogo(sessionmaker, titulo.strip())
    return [_para_saida_em_alta(item, anime_id) for item, anime_id in pares]


# `/buscar-fontes` precisa vir ANTES de `/{anime_id}` — mesma armadilha de
# `/em-alta` acima: um `{anime_id}` declarado primeiro casaria com
# `anime_id="buscar-fontes"`.
@router_publico.get("/buscar-fontes", response_model=BuscaEmFontesSaida)
async def buscar_animes_em_fontes(
    titulo: str = Query(..., max_length=200),
    sessionmaker: _SessionMaker = Depends(obter_sessionmaker),
) -> BuscaEmFontesSaida:
    """Busca ao vivo em sites de extração — alimenta o diálogo "Trocar fonte":
    cada site busca em paralelo, esgotando de forma independente e exaustiva sua
    própria escada de variantes, sem que um "roube a vez" do outro
    (`extractors.busca.servico.buscar_por_site_com_variantes`). Devolve a UNIÃO
    das fontes onde o anime existe. `fontes` traz o status de cada site
    consultado (disponível ou não, com motivo) — a UI usa isso pra distinguir
    "não achei nada" de "não consegui nem tentar" (CLAUDE.md §4, erro nunca
    silencioso)."""
    if not titulo.strip():
        return BuscaEmFontesSaida(resultados=[], fontes=[])

    fontes = await servico_busca.buscar_em_todas_as_fontes_com_titulos_alternativos(
        sessionmaker, titulo
    )
    return BuscaEmFontesSaida(
        resultados=[
            ResultadoBuscaFonteSaida(
                titulo_exibicao=candidato.titulo_exibicao,
                identificador=candidato.identificador,
                url=candidato.url,
                dominio=fonte.dominio,
                versao=candidato.versao,
                site_diferencia_versao=_diferencia_versao(fonte.dominio),
                correspondencia_incerta=fonte.correspondencia_incerta,
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
    # Mesma carona, para sinopse/banner/cor/gêneros ainda faltando (anime
    # materializado do feed "em alta", que nunca traz sinopse) — ver
    # `descoberta.agendar_enriquecimento_de_metadados`.
    servico_descoberta.agendar_enriquecimento_de_metadados(sessionmaker, anime)
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
    grupos = await _agrupar_franquias(sessao)
    temporadas, proxima_temporada = _temporadas_e_proxima(
        anime.id, anime.numero_temporada, grupos[anime.id]
    )
    return AnimeDetalheSaida(
        id=anime.id,
        titulo=anime.titulo,
        titulo_ingles=anime.titulo_ingles,
        slug=anime.slug,
        ano=anime.ano,
        capa_path=anime.capa_path,
        banner_path=anime.banner_path,
        capa_cor=anime.capa_cor,
        generos=anime.generos or [],
        sinopse=anime.sinopse,
        criado_em=anime.criado_em,
        versoes_disponiveis=_versoes_disponiveis(versoes_de_fonte),
        versao_confirmada_mais_recente=versao_confirmada_mais_recente,
        status_lancamento=anime.status_lancamento,
        serie_ancora=anime.serie_ancora,
        numero_temporada=anime.numero_temporada,
        temporadas=temporadas,
        proxima_temporada=proxima_temporada,
    )


@router_publico.get("/{anime_id}/relacionados", response_model=list[AnimeEmAltaSaida])
async def listar_relacionados_do_anime(
    anime_id: int,
    sessao: AsyncSession = Depends(obter_sessao),
    sessionmaker: _SessionMaker = Depends(obter_sessionmaker),
) -> list[AnimeEmAltaSaida]:
    """Seção "Relacionados" da página do anime — recomendações da comunidade
    AniList + relações de franquia não sequenciais (spin-off, filme, OVA...);
    temporadas em sequência direta já aparecem no seletor de temporada
    (`AnimeDetalheSaida.temporadas`) e são filtradas daqui por `anime_id`
    (`_ids_do_seletor_de_temporada` abaixo) — não só pelo `relationType` cru
    da AniList (`integrations.anilist.py::buscar_relacionados`), que só vê a
    aresta DIRETA desta mídia e não cobre uma temporada irmã sem edge direta
    mas já unida no seletor pelo union-find de franquia (`_agrupar_franquias`,
    slug do título base OU `serie_ancora` em comum). Sem `anilist_id`
    (cadastro manual/enriquecimento ainda não rodou), devolve `[]` — mesmo
    formato de "sem sugestão" de `integrations.servico.listar_relacionados`,
    sem 404/erro."""
    anime = await sessao.get(Anime, anime_id)
    if anime is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="anime não encontrado")
    if anime.anilist_id is None:
        return []
    grupos = await _agrupar_franquias(sessao)
    ids_do_seletor = _ids_do_seletor_de_temporada(anime.id, anime.numero_temporada, grupos)
    pares = await servico_descoberta.listar_relacionados_com_catalogo(
        sessionmaker, anime.anilist_id
    )
    return [
        _para_saida_em_alta(item, aid)
        for item, aid in pares
        if aid is None or aid not in ids_do_seletor
    ]


def _ids_do_seletor_de_temporada(
    anime_id: int, numero_temporada: int | None, grupos: dict[int, list[object]]
) -> set[int]:
    """`Anime.id` de tudo que `_temporadas_e_proxima` já oferece pra `anime_id`
    — as irmãs do seletor de temporada MAIS o bookmark de `proxima_temporada`
    (uma "próxima estreia" que o usuário já salvou não deveria repetir como
    sugestão) — usado por `listar_relacionados_do_anime` pra não duplicar
    card entre as duas seções da página."""
    temporadas, proxima_temporada = _temporadas_e_proxima(
        anime_id, numero_temporada, grupos[anime_id]
    )
    ids = {temporada.id for temporada in temporadas}
    if proxima_temporada is not None:
        ids.add(proxima_temporada.id)
    return ids


async def _agrupar_franquias(sessao: AsyncSession) -> dict[int, list[object]]:
    """`{anime_id: grupo}` — agrupa o catálogo INTEIRO em componentes conexos de
    franquia (união por `serie_ancora` OU slug do título base, `core/
    franquia.py` — o segundo sinal cobre o walk de `relations` que erra com
    OVA/ONA/split-cour no meio, Fase 6), uma query só. `grupo` é a lista
    ordenada por `numero_temporada` (NULL por último) de TODAS as linhas da
    franquia — mesma lista (referência compartilhada) pra cada `anime_id`
    membro dela, então indexar o dict não duplica dado. Espelha o agrupamento
    de `frontend/src/inicio/franquia.js`.

    A parte cara de `_temporadas_e_proxima`: varrer o catálogo inteiro (dezenas
    de linhas, uso pessoal — barato o bastante pra não justificar índice) só
    UMA VEZ por request, não por anime. `obter_anime` chama isto pro grupo de 1
    anime; `listar_animes` reaproveita o mesmo dict pra cada card da grade —
    sem isso, calcular `proxima_temporada` pro catálogo inteiro escanearia o
    catálogo inteiro de novo a cada anime (O(N²))."""
    tem_episodio = exists().where(Episodio.anime_id == Anime.id)
    linhas = (
        await sessao.execute(
            select(
                Anime.id,
                Anime.numero_temporada,
                Anime.titulo,
                Anime.serie_ancora,
                Anime.status_lancamento,
                Anime.estreia_em,
                Anime.ano,
                Anime.formato_midia,
                Anime.total_episodios_anilist,
                tem_episodio.label("tem_episodios"),
            )
        )
    ).all()

    pai: dict[object, object] = {}

    def acha(no: object) -> object:
        pai.setdefault(no, no)
        while pai[no] != no:
            pai[no] = pai[pai[no]]
            no = pai[no]
        return no

    def une(a: object, b: object) -> None:
        pai[acha(a)] = acha(b)

    for linha in linhas:
        no = ("id", linha.id)
        acha(no)
        slug = slug_de_franquia(linha.titulo)
        if slug:
            une(no, ("slug", slug))
        if linha.serie_ancora is not None:
            une(no, ("anc", linha.serie_ancora))

    grupos_por_raiz: dict[object, list[object]] = {}
    for linha in linhas:
        grupos_por_raiz.setdefault(acha(("id", linha.id)), []).append(linha)
    for grupo in grupos_por_raiz.values():
        grupo.sort(
            key=lambda linha: (
                linha.numero_temporada is None,
                linha.numero_temporada or 0,
                linha.id,
            )
        )

    return {linha.id: grupos_por_raiz[acha(("id", linha.id))] for linha in linhas}


def _temporadas_e_proxima(
    anime_id: int, numero_temporada_atual: int | None, grupo: list[object]
) -> tuple[list[TemporadaIrmaSaida], TemporadaIrmaSaida | None]:
    """`(temporadas_do_seletor, proxima_temporada_prevista)` do anime `anime_id`
    dentro do `grupo` (de `_agrupar_franquias`) da sua franquia. Sem I/O — só a
    lógica pura, reaproveitada por anime tanto em `obter_anime` (grupo de 1
    anime) quanto em `listar_animes` (mesmo grupo, uma vez por franquia,
    reaproveitado pra cada membro que aparece na grade).

    - `temporadas_do_seletor`: irmãs (inclui a própria) ordenadas por
      `numero_temporada` (NULL por último), EXCETO as que ainda não existem como
      conteúdo — `nao_lancado` e sem episódio capturado, i.e. bookmark de
      "Próximas estreias" — porque navegar pra elas só levaria a página vazia. A
      própria temporada de `anime_id` fica sempre. `[]` quando sobra só ela
      (nada a oferecer no seletor). Espelha `temporadaAcessivel` de
      `inicio/franquia.js`.
    - `proxima_temporada_prevista`: a irmã `nao_lancado` de menor
      `numero_temporada` acima da atual que já tem `estreia_em` no futuro, ou —
      quando a AniList ainda não fechou a data completa — pelo menos `ano` no
      ano corrente ou adiante. Alimenta o aviso "Nª temporada estreia em ..." no
      hero da página do anime e no card do catálogo (data completa quando há,
      senão só o ano). `None` quando não há nenhuma nesse estado."""

    def _acessivel(linha: object) -> bool:
        return (
            linha.id == anime_id
            or bool(linha.tem_episodios)
            or linha.status_lancamento != StatusLancamento.NAO_LANCADO
        )

    acessiveis = [linha for linha in grupo if _acessivel(linha)]
    temporadas = (
        [
            TemporadaIrmaSaida(
                id=linha.id,
                numero_temporada=linha.numero_temporada,
                titulo=linha.titulo,
                formato_midia=linha.formato_midia,
                total_episodios=linha.total_episodios_anilist,
            )
            for linha in acessiveis
        ]
        if len(acessiveis) >= 2
        else []
    )

    hoje = datetime.now(UTC).date()
    numero_atual = numero_temporada_atual or 0

    def _prevista(linha: object) -> bool:
        """Irmã que ainda vem: `nao_lancado`, numerada acima da atual, e com
        alguma âncora temporal no futuro — data completa (`estreia_em`) de
        preferência, senão o `ano` (>= ano corrente) como fallback pro aviso
        degradar pra "estreia em 2026" em vez de sumir."""
        if linha.id == anime_id or linha.status_lancamento != StatusLancamento.NAO_LANCADO:
            return False
        if (linha.numero_temporada or 0) <= numero_atual:
            return False
        if linha.estreia_em is not None:
            return linha.estreia_em > hoje
        return linha.ano is not None and linha.ano >= hoje.year

    previstas = [linha for linha in grupo if _prevista(linha)]
    proxima = (
        TemporadaIrmaSaida(
            id=previstas[0].id,
            numero_temporada=previstas[0].numero_temporada,
            titulo=previstas[0].titulo,
            estreia_em=previstas[0].estreia_em,
            ano=previstas[0].ano,
        )
        if previstas
        else None
    )
    return temporadas, proxima


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

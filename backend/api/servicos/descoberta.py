"""Orquestração de metadados externos (`integrations/`) com o catálogo local
— mesmo papel de `api/servicos/fontes.py`, mas para `integrations/servico.py`
em vez de `extractors/`. Não importa `fastapi` nem Pydantic (regra de
dependência da Clean Architecture, CLAUDE.md §1); `api/rotas/animes.py`
traduz para schemas.
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.enums import StatusLancamento
from core.erros import FalhaDeMetadados
from core.texto import slugificar
from db.catalogo import (
    aplicar_metadados,
    atualizar_lancamento,
    atualizar_lancamentos_em_lote,
    localizar_animes_por_anilist_id,
    localizar_animes_por_slug,
)
from integrations import servico
from integrations.base import AnimeEmAlta, MetadadosDeAnime
from models.anime import Anime

logger = logging.getLogger(__name__)

_SessionMaker = async_sessionmaker[AsyncSession]

# F4 — refresh oportunista do estado de lançamento. Sem scheduler/cron (decisão
# de produto): o dado só é atualizado em dois momentos de "carona" — o cruzamento
# do feed "em alta" (F4a, de graça: o feed já traz o bloco fresco da AniList) e a
# abertura da página de um anime em lançamento com dado mais velho que isto (F4b,
# busca lazy fire-and-forget). Compartilhado pelos dois caminhos.
_TTL_LANCAMENTO_S = 6 * 3600

# Referência forte às buscas lazy de F4b em andamento: (1) deduplica aberturas
# concorrentes da mesma página e (2) impede o GC de coletar uma `Task`
# fire-and-forget antes de ela terminar. A entrada sai no `add_done_callback`.
_refreshs_de_lancamento_em_voo: dict[int, asyncio.Task] = {}

# Teto do enriquecimento best-effort no cadastro manual — a criação do anime
# é o objetivo primário; este valor é a rede de segurança que garante que o
# cadastro nunca fica preso esperando um provedor externo responder.
#
# `servico.buscar_por_titulo` pode tentar AniList e, se falhar, Kitsu, em
# sequência — cada um com até `integrations.servico._TIMEOUT_POR_PROVEDOR_S`
# (8s) de `wait_for`. Pior caso plausível: 8s + 8s = 16s, mais margem real
# acima disso (overhead de `asyncio.to_thread`/agendamento) para nunca ser o
# primeiro a estourar em condições normais — 18s.
_TETO_ENRIQUECIMENTO_S = 18


async def listar_em_alta_com_catalogo(
    sessionmaker: _SessionMaker,
) -> list[tuple[AnimeEmAlta, int | None]]:
    """Feed "em alta" (`integrations.servico.listar_em_alta`) pareado com
    `Anime.id` local, quando o anime já está catalogado. Propaga
    `FalhaDeMetadados` se os provedores falharem — a rota pública nunca deve
    devolver `[]` como se fosse "sem lançamentos" quando na verdade os
    provedores estão fora do ar.

    Prioridade de cruzamento: `anilist_id` primeiro (único, sem
    falso-negativo por subtítulo/pontuação divergente), slug do título
    romaji como *fallback* só para os itens sem match por `anilist_id` —
    necessário porque o Kitsu (provedor de fallback) não carrega
    `anilist_id`."""
    itens = await servico.listar_em_alta()

    anilist_ids = [item.anilist_id for item in itens if item.anilist_id is not None]
    por_anilist_id = await localizar_animes_por_anilist_id(sessionmaker, anilist_ids)

    slugs_pendentes = [
        slugificar(item.titulo_romaji)
        for item in itens
        if item.anilist_id is None or item.anilist_id not in por_anilist_id
    ]
    por_slug = await localizar_animes_por_slug(sessionmaker, slugs_pendentes)

    pares = []
    for item in itens:
        anime_id = por_anilist_id.get(item.anilist_id) if item.anilist_id is not None else None
        if anime_id is None:
            anime_id = por_slug.get(slugificar(item.titulo_romaji))
        pares.append((item, anime_id))

    await _refrescar_lancamentos_do_cruzamento(sessionmaker, pares)
    return pares


def _lancamento_esta_velho(atualizado_em: datetime | None, limite: datetime) -> bool:
    """`True` quando o carimbo do último refresh de lançamento é nulo ou anterior
    a `limite`. `ColunaDataHoraUTC` devolve datetime *aware*, mas um valor naive
    vindo direto do SQLite é normalizado para UTC antes de comparar."""
    if atualizado_em is None:
        return True
    if atualizado_em.tzinfo is None:
        atualizado_em = atualizado_em.replace(tzinfo=UTC)
    return atualizado_em < limite


async def _refrescar_lancamentos_do_cruzamento(
    sessionmaker: _SessionMaker, pares: list[tuple[AnimeEmAlta, int | None]]
) -> None:
    """F4a — refresh "de graça": para cada item do feed que já traz `lancamento`
    e cruzou com um anime catalogado, sobrescreve as colunas de lançamento do
    anime quando o dado local está velho (> `_TTL_LANCAMENTO_S`) ou ausente. O
    bloco vem do próprio feed "em alta" — nenhuma chamada de rede extra.

    Best-effort de ponta a ponta: falha de leitura ou de escrita vira `warning` e
    nunca derruba `GET /api/animes/em-alta` (o cruzamento já foi montado)."""
    do_feed = {
        anime_id: item.lancamento
        for item, anime_id in pares
        if anime_id is not None and item.lancamento is not None
    }
    if not do_feed:
        return

    try:
        async with sessionmaker() as sessao:
            resultado = await sessao.execute(
                select(Anime.id, Anime.lancamento_atualizado_em).where(
                    Anime.id.in_(list(do_feed))
                )
            )
            carimbo_por_id = dict(resultado.all())

        limite = datetime.now(UTC) - timedelta(seconds=_TTL_LANCAMENTO_S)
        velhos = {
            anime_id: lancamento
            for anime_id, lancamento in do_feed.items()
            if _lancamento_esta_velho(carimbo_por_id.get(anime_id), limite)
        }
        await atualizar_lancamentos_em_lote(sessionmaker, velhos)
    except SQLAlchemyError as excecao:
        logger.warning(
            "refresh oportunista de lançamento no cruzamento do feed falhou "
            "(%d candidato(s)): %s",
            len(do_feed),
            excecao,
        )


def agendar_refresh_de_lancamento(sessionmaker: _SessionMaker, anime: Anime) -> None:
    """F4b — dispara, sem bloquear, uma busca lazy do estado de lançamento à
    AniList quando a página de um anime em lançamento é aberta com dado velho.
    `GET /api/animes/{id}` chama e segue: o resultado entra no banco para a
    próxima leitura, não para esta.

    No-op silencioso (nenhuma destas condições é anormal, então sem log) quando:
    o anime não tem `anilist_id`; o status não é `EM_LANCAMENTO` nem nulo
    (`FINALIZADO`/`CANCELADO` não ganham episódios); o dado ainda está dentro do
    TTL; já há uma busca em voo para este anime; ou não há event loop rodando."""
    if anime.anilist_id is None:
        return
    if anime.status_lancamento not in (StatusLancamento.EM_LANCAMENTO, None):
        return
    limite = datetime.now(UTC) - timedelta(seconds=_TTL_LANCAMENTO_S)
    if not _lancamento_esta_velho(anime.lancamento_atualizado_em, limite):
        return

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    anime_id = anime.id
    if anime_id in _refreshs_de_lancamento_em_voo:
        return

    anilist_id = anime.anilist_id
    tarefa = loop.create_task(_buscar_e_persistir_lancamento(sessionmaker, anime_id, anilist_id))
    _refreshs_de_lancamento_em_voo[anime_id] = tarefa
    tarefa.add_done_callback(lambda _tarefa: _refreshs_de_lancamento_em_voo.pop(anime_id, None))


async def _buscar_e_persistir_lancamento(
    sessionmaker: _SessionMaker, anime_id: int, anilist_id: int
) -> None:
    """Corpo da `Task` fire-and-forget de F4b. Toda exceção esperada (provedor
    fora do ar, timeout, erro de banco) vira `warning` e morre aqui — nunca
    propaga para o event loop. `CancelledError` e erros inesperados propagam de
    propósito."""
    try:
        lancamento = await servico.buscar_lancamento_por_anilist_id(anilist_id)
        if lancamento is not None:
            await atualizar_lancamento(sessionmaker, anime_id, lancamento)
    except (FalhaDeMetadados, TimeoutError, SQLAlchemyError) as excecao:
        logger.warning(
            "refresh lazy de lançamento falhou para anime_id=%s anilist_id=%s: %s",
            anime_id,
            anilist_id,
            excecao,
        )


async def enriquecer_anime_criado(
    sessionmaker: _SessionMaker,
    anime_id: int,
    titulo: str,
    *,
    anilist_id: int | None,
    kitsu_id: int | None,
    capa_url: str | None,
    sinopse: str | None,
) -> None:
    """Preenche metadados do anime recém-obtido/criado (`POST
    /api/admin/animes`). Se o request já trouxe algum campo, persiste direto
    — evita rebuscar um provedor externo por um dado que já veio no payload
    (importa pro rate limit do AniList/Kitsu). Senão, tenta enriquecer por
    título em best-effort: falha do provedor vira warning, nunca bloqueia a
    criação do anime (que já aconteceu antes desta chamada)."""
    algum_campo_veio_no_payload = (
        anilist_id is not None
        or kitsu_id is not None
        or capa_url is not None
        or sinopse is not None
    )
    if algum_campo_veio_no_payload:
        metadados = MetadadosDeAnime(
            capa_url=capa_url, sinopse=sinopse, anilist_id=anilist_id, kitsu_id=kitsu_id
        )
        await aplicar_metadados(sessionmaker, anime_id, metadados)
        return

    try:
        metadados = await asyncio.wait_for(
            servico.buscar_por_titulo(titulo), timeout=_TETO_ENRIQUECIMENTO_S
        )
    except (FalhaDeMetadados, TimeoutError) as excecao:
        logger.warning(
            "enriquecimento de metadados best-effort falhou para anime_id=%s titulo=%r: %s",
            anime_id,
            titulo,
            excecao,
        )
        return

    if metadados is not None:
        await aplicar_metadados(sessionmaker, anime_id, metadados)

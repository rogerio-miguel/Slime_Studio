"""Orquestração de metadados externos (`integrations/`) com o catálogo local
— mesmo papel de `api/servicos/fontes.py`, mas para `integrations/servico.py`
em vez de `extractors/`. Não importa `fastapi` nem Pydantic (regra de
dependência da Clean Architecture, CLAUDE.md §1); `api/rotas/animes.py`
traduz para schemas.
"""

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.erros import FalhaDeMetadados
from core.texto import slugificar
from db.catalogo import (
    aplicar_metadados,
    localizar_animes_por_anilist_id,
    localizar_animes_por_slug,
)
from integrations import servico
from integrations.base import AnimeEmAlta, MetadadosDeAnime

logger = logging.getLogger(__name__)

_SessionMaker = async_sessionmaker[AsyncSession]

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
    return pares


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

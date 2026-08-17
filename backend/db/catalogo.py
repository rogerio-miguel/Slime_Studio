"""Get-or-create de `Anime` + criação de `Episodio`+`Job` — compartilhado entre o
CLI (`scripts/enfileirar_local.py`) e a API (`api/servicos/jobs.py`), pra evitar
drift de tratamento de `IntegrityError`/get-or-create entre os dois produtores de
job (ESPECIFICACAO.md §5, Passo 1.3 do plano da Fase 3).
"""

import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.enums import StatusEpisodio, TipoEpisodio, VersaoEpisodio
from core.erros import EpisodioJaExiste, ErroSlimeStudio
from core.texto import slugificar
from db.fila import criar_job
from integrations.base import MetadadosDeAnime
from models.anime import Anime
from models.episodio import Episodio

logger = logging.getLogger(__name__)

_SessionMaker = async_sessionmaker[AsyncSession]


async def obter_ou_criar_anime_id(sessionmaker: _SessionMaker, titulo: str, ano: int | None) -> int:
    slug = slugificar(titulo)
    async with sessionmaker() as sessao:
        resultado = await sessao.execute(select(Anime.id).where(Anime.slug == slug))
        anime_id = resultado.scalar_one_or_none()
        if anime_id is not None:
            return anime_id

        anime = Anime(titulo=titulo, slug=slug, ano=ano)
        sessao.add(anime)
        try:
            await sessao.commit()
        except IntegrityError as excecao:
            await sessao.rollback()
            anime_id = await _localizar_anime_existente(sessao, slug)
            if anime_id is None:
                raise ErroSlimeStudio(
                    f"conflito ao criar anime (slug={slug!r}) mas nenhum registro foi encontrado"
                ) from excecao
            return anime_id
        return anime.id


async def _localizar_anime_existente(sessao: AsyncSession, slug: str) -> int | None:
    resultado = await sessao.execute(select(Anime.id).where(Anime.slug == slug))
    return resultado.scalar_one_or_none()


async def aplicar_metadados(
    sessionmaker: _SessionMaker, anime_id: int, metadados: MetadadosDeAnime
) -> None:
    """Preenche só os campos de `Anime` que estão `NULL` hoje — idempotente,
    nunca sobrescreve dado já existente/confirmado (cadastro manual que já
    veio com capa/sinopse no payload, ou um enriquecimento anterior).

    `anilist_id` é `unique=True` (`models/anime.py`): se outra linha já usa
    esse id, a escrita do metadado é revertida sozinha (`rollback`) sem
    afetar o `Anime` já criado — quem chama (`api/servicos/descoberta.py`)
    não deve ter o cadastro do anime bloqueado por um conflito de metadado
    secundário."""
    async with sessionmaker() as sessao:
        anime = await sessao.get(Anime, anime_id)
        if anime is None:
            return

        if anime.capa_path is None and metadados.capa_url is not None:
            anime.capa_path = metadados.capa_url
        if anime.sinopse is None and metadados.sinopse is not None:
            anime.sinopse = metadados.sinopse
        if anime.anilist_id is None and metadados.anilist_id is not None:
            anime.anilist_id = metadados.anilist_id
        if anime.kitsu_id is None and metadados.kitsu_id is not None:
            anime.kitsu_id = metadados.kitsu_id

        try:
            await sessao.commit()
        except IntegrityError as excecao:
            await sessao.rollback()
            logger.warning(
                "anilist_id=%s já usado por outro anime; metadado ignorado (anime_id=%s): %s",
                metadados.anilist_id,
                anime_id,
                excecao,
            )


async def localizar_animes_por_slug(
    sessionmaker: _SessionMaker, slugs: list[str]
) -> dict[str, int]:
    """Cruzamento em lote slug -> `Anime.id` local, usado por
    `api/servicos/descoberta.py` como *fallback* de
    `localizar_animes_por_anilist_id` (necessário para itens vindos do
    Kitsu, que não carregam `anilist_id`). Slugs sem correspondência
    simplesmente não aparecem no dict devolvido — ausência não é erro, é
    "ainda não catalogado"."""
    if not slugs:
        return {}
    async with sessionmaker() as sessao:
        resultado = await sessao.execute(select(Anime.slug, Anime.id).where(Anime.slug.in_(slugs)))
        return dict(resultado.all())


async def localizar_animes_por_anilist_id(
    sessionmaker: _SessionMaker, anilist_ids: list[int]
) -> dict[int, int]:
    """Cruzamento em lote `anilist_id` -> `Anime.id` local — prioridade sobre
    `localizar_animes_por_slug` no cruzamento do feed "em alta"
    (`api/servicos/descoberta.py`): `anilist_id` é único
    (`models/anime.py::Anime.anilist_id`) e não sofre falso-negativo por
    subtítulo/pontuação/ordem de palavra divergente entre o título do
    provedor e o título usado ao catalogar localmente, ao contrário do
    slug."""
    if not anilist_ids:
        return {}
    async with sessionmaker() as sessao:
        resultado = await sessao.execute(
            select(Anime.anilist_id, Anime.id).where(Anime.anilist_id.in_(anilist_ids))
        )
        return dict(resultado.all())


async def criar_episodio_e_job(
    sessionmaker: _SessionMaker,
    anime_id: int,
    *,
    numero: int,
    tipo: TipoEpisodio,
    versao: VersaoEpisodio,
    url_fonte: str,
    site_origem: str,
    titulo_episodio: str | None = None,
    duracao_esperada_s: int | None = None,
) -> int:
    """Cria o `Episodio` e, em seguida, o `Job` (via `db.fila.criar_job`) — duas
    transações curtas, não uma (mesma filosofia de sessão-por-operação do resto de
    `db/`). Na pior janela (processo morre entre as duas escritas) o resultado é
    um episódio `pendente` sem job — recuperável manualmente — nunca um job órfão
    sem episódio.

    Levanta `EpisodioJaExiste` se a identidade (`anime_id`, `numero`, `tipo`,
    `versao`) já existir (`uq_episodio_identidade`) — CLI e API decidem o que
    fazer com isso (a API mapeia para 409).
    """
    episodio_id = await _inserir_episodio(
        sessionmaker,
        anime_id,
        numero=numero,
        tipo=tipo,
        versao=versao,
        url_fonte=url_fonte,
        site_origem=site_origem,
        titulo_episodio=titulo_episodio,
    )
    return await criar_job(sessionmaker, episodio_id, duracao_esperada_s)


async def _inserir_episodio(
    sessionmaker: _SessionMaker,
    anime_id: int,
    *,
    numero: int,
    tipo: TipoEpisodio,
    versao: VersaoEpisodio,
    url_fonte: str,
    site_origem: str,
    titulo_episodio: str | None,
) -> int:
    async with sessionmaker() as sessao:
        episodio = Episodio(
            anime_id=anime_id,
            numero=numero,
            titulo=titulo_episodio,
            tipo=tipo,
            versao=versao,
            url_fonte=url_fonte,
            site_origem=site_origem,
            status=StatusEpisodio.PENDENTE,
        )
        sessao.add(episodio)
        try:
            await sessao.commit()
        except IntegrityError as excecao:
            await sessao.rollback()
            episodio_id = await _localizar_episodio_existente(
                sessao, anime_id, numero, tipo, versao
            )
            raise EpisodioJaExiste(episodio_id) from excecao
        return episodio.id


async def _localizar_episodio_existente(
    sessao: AsyncSession, anime_id: int, numero: int, tipo: TipoEpisodio, versao: VersaoEpisodio
) -> int | None:
    resultado = await sessao.execute(
        select(Episodio.id).where(
            Episodio.anime_id == anime_id,
            Episodio.numero == numero,
            Episodio.tipo == tipo,
            Episodio.versao == versao,
        )
    )
    return resultado.scalar_one_or_none()

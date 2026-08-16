"""Get-or-create de `Anime` + criação de `Episodio`+`Job` — compartilhado entre o
CLI (`scripts/enfileirar_local.py`) e a API (`api/servicos/jobs.py`), pra evitar
drift de tratamento de `IntegrityError`/get-or-create entre os dois produtores de
job (ESPECIFICACAO.md §5, Passo 1.3 do plano da Fase 3).
"""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.enums import StatusEpisodio, TipoEpisodio, VersaoEpisodio
from core.erros import EpisodioJaExiste, ErroSlimeStudio
from core.texto import slugificar
from db.fila import criar_job
from models.anime import Anime
from models.episodio import Episodio

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

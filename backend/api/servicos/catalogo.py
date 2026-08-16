"""Remoção de catálogo (anime/episódio) — apaga linha e arquivos em disco juntos
(HLS + raw) — e cálculo de uso de disco por mídia (ESPECIFICACAO.md §5, Passo 5
do plano da Fase 3).

Sessão própria por operação (mesmo padrão de `db/fila.py`) — não importa
`fastapi`.
"""

import shutil

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config import Config
from core.enums import ESTADOS_EM_EXECUCAO
from core.erros import JobEmExecucao
from core.midia import diretorio_do_episodio
from extractors.download import caminho_raw
from models.anime import Anime
from models.episodio import Episodio
from models.job import Job

_SessionMaker = async_sessionmaker[AsyncSession]


async def remover_episodio(sessionmaker: _SessionMaker, config: Config, episodio_id: int) -> bool:
    """Remove o `Episodio` e seus arquivos (HLS + raw) em disco. Devolve `False`
    se o episódio não existir — quem chama decide se isso é um 404.

    Levanta `JobEmExecucao` se houver um `Job` ativo para este episódio: com
    `Job.episodio_id` em `ondelete="CASCADE"`, apagar o episódio embaixo de um
    worker em processamento apagaria o `Job` sem ele perceber (heartbeat/
    progresso passam a afetar 0 linhas, silenciosamente) e removeria o
    diretório que `empacotar()` pode estar escrevendo agora."""
    async with sessionmaker() as sessao:
        episodio = await sessao.get(Episodio, episodio_id)
        if episodio is None:
            return False

        job_ativo_id = await _job_ativo_do_episodio(sessao, episodio_id)
        if job_ativo_id is not None:
            raise JobEmExecucao(job_ativo_id)

        anime = await sessao.get(Anime, episodio.anime_id)

        if anime is not None:
            _remover_arquivos_do_episodio(config, anime.slug, episodio)

        await sessao.delete(episodio)
        await sessao.commit()
        return True


async def remover_anime(sessionmaker: _SessionMaker, config: Config, anime_id: int) -> bool:
    """Remove o `Anime` (cascata apaga `Episodio`/`Job`/`FonteAnime` via
    `ondelete="CASCADE"`) e os arquivos de todos os seus episódios em disco.
    Devolve `False` se o anime não existir.

    Levanta `JobEmExecucao` se qualquer episódio do anime tiver um `Job` ativo
    — mesmo risco de `remover_episodio`, aqui multiplicado por todos os
    episódios que a cascata apagaria."""
    async with sessionmaker() as sessao:
        anime = await sessao.get(Anime, anime_id)
        if anime is None:
            return False

        job_ativo_id = await _job_ativo_do_anime(sessao, anime_id)
        if job_ativo_id is not None:
            raise JobEmExecucao(job_ativo_id)

        episodios = (
            await sessao.execute(select(Episodio).where(Episodio.anime_id == anime_id))
        ).scalars()
        for episodio in episodios:
            _remover_arquivos_do_episodio(config, anime.slug, episodio)

        await sessao.delete(anime)
        await sessao.commit()
        return True


async def _job_ativo_do_episodio(sessao: AsyncSession, episodio_id: int) -> int | None:
    resultado = await sessao.execute(
        select(Job.id).where(Job.episodio_id == episodio_id, Job.status.in_(ESTADOS_EM_EXECUCAO))
    )
    return resultado.scalars().first()


async def _job_ativo_do_anime(sessao: AsyncSession, anime_id: int) -> int | None:
    resultado = await sessao.execute(
        select(Job.id)
        .join(Episodio, Job.episodio_id == Episodio.id)
        .where(Episodio.anime_id == anime_id, Job.status.in_(ESTADOS_EM_EXECUCAO))
    )
    return resultado.scalars().first()


async def uso_de_disco(sessionmaker: _SessionMaker, config: Config) -> tuple[int, int, int]:
    """`(total_bytes, livre_bytes, usado_por_midia_bytes)`. Os dois primeiros vêm
    de `shutil.disk_usage` no mount de `MEDIA_ROOT`; o terceiro é a soma de
    `Episodio.tamanho_bytes` — não o uso real do filesystem (que incluiria
    `raw/` e sobras de reprocessamento). Sem "candidatos a limpeza" nesta fase
    (plano §4) — só o agregado."""
    uso = shutil.disk_usage(config.media_root)
    async with sessionmaker() as sessao:
        resultado = await sessao.execute(select(Episodio.tamanho_bytes))
        usado_por_midia = sum(tamanho for (tamanho,) in resultado if tamanho is not None)
    return uso.total, uso.free, usado_por_midia


def _remover_arquivos_do_episodio(config: Config, anime_slug: str, episodio: Episodio) -> None:
    """Melhor esforço (`ignore_errors=True`/`missing_ok=True`) — o registro no
    banco já foi (ou está prestes a ser) apagado; um arquivo que resiste à
    remoção não deve impedir a operação, só fica órfão em disco para limpeza
    manual."""
    if episodio.hls_path is not None:
        diretorio_hls = diretorio_do_episodio(
            config.media_root, anime_slug, episodio.numero, episodio.tipo, episodio.versao
        )
        shutil.rmtree(diretorio_hls, ignore_errors=True)

    caminho_bruto = caminho_raw(
        config.media_root, anime_slug, episodio.numero, episodio.tipo, episodio.versao
    )
    caminho_bruto.unlink(missing_ok=True)

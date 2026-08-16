"""Produtor de jobs a partir de um arquivo de vídeo local (Fase 1 — sem API ainda).

Uso:
    uv run python -m scripts.enfileirar_local --arquivo /caminho/ep01.mkv \\
        --anime "Slime Datta Ken" --numero 1
"""

import argparse
import asyncio
import logging
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config import Config, carregar_config
from core.enums import SITE_LOCAL, StatusEpisodio, StatusJob, TipoEpisodio, VersaoEpisodio
from core.erros import ErroSlimeStudio
from core.texto import slugificar
from db.engine import criar_engine, criar_sessionmaker
from models.anime import Anime
from models.episodio import Episodio
from models.job import Job

_SessionMaker = async_sessionmaker[AsyncSession]


@dataclass(frozen=True, slots=True)
class Argumentos:
    arquivo: Path
    anime: str
    numero: int
    ano: int | None
    tipo: TipoEpisodio
    versao: VersaoEpisodio
    titulo_episodio: str | None
    duracao_esperada_s: int | None


def analisar_argumentos(argv: Sequence[str]) -> Argumentos:
    parser = argparse.ArgumentParser(
        description="Cadastra um episódio a partir de um arquivo de vídeo local e o enfileira."
    )
    parser.add_argument(
        "--arquivo", type=Path, required=True, help="Caminho do arquivo de vídeo de origem."
    )
    parser.add_argument(
        "--anime", required=True, help="Título do anime (usado para gerar/casar o slug)."
    )
    parser.add_argument("--numero", type=int, required=True, help="Número do episódio.")
    parser.add_argument(
        "--ano", type=int, default=None, help="Ano/temporada (seasonYear do AniList, se souber)."
    )
    parser.add_argument(
        "--tipo",
        choices=[tipo.value for tipo in TipoEpisodio],
        default=TipoEpisodio.REGULAR.value,
    )
    parser.add_argument(
        "--versao",
        choices=[versao.value for versao in VersaoEpisodio],
        default=VersaoEpisodio.LEGENDADO.value,
    )
    parser.add_argument("--titulo-episodio", dest="titulo_episodio", default=None)
    parser.add_argument(
        "--duracao-esperada-s",
        dest="duracao_esperada_s",
        type=int,
        default=None,
        help="Duração esperada em segundos, para checagem de sanidade (opcional).",
    )

    args = parser.parse_args(argv)
    return Argumentos(
        arquivo=args.arquivo,
        anime=args.anime,
        numero=args.numero,
        ano=args.ano,
        tipo=TipoEpisodio(args.tipo),
        versao=VersaoEpisodio(args.versao),
        titulo_episodio=args.titulo_episodio,
        duracao_esperada_s=args.duracao_esperada_s,
    )


async def enfileirar(args: Argumentos, config: Config) -> int:
    """Get-or-create do `Anime` por slug, cria `Episodio` + `Job` e devolve o `job_id`."""
    engine = criar_engine(config)
    sessionmaker = criar_sessionmaker(engine)
    try:
        anime_id = await _obter_ou_criar_anime_id(sessionmaker, args.anime, args.ano)
        return await _criar_episodio_e_job(sessionmaker, anime_id, args)
    finally:
        await engine.dispose()


async def _obter_ou_criar_anime_id(
    sessionmaker: _SessionMaker, titulo: str, ano: int | None
) -> int:
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


async def _criar_episodio_e_job(
    sessionmaker: _SessionMaker, anime_id: int, args: Argumentos
) -> int:
    async with sessionmaker() as sessao:
        episodio = Episodio(
            anime_id=anime_id,
            numero=args.numero,
            titulo=args.titulo_episodio,
            tipo=args.tipo,
            versao=args.versao,
            url_fonte=str(args.arquivo.resolve()),
            site_origem=SITE_LOCAL,
            status=StatusEpisodio.PENDENTE,
        )
        sessao.add(episodio)
        try:
            await sessao.flush()
        except IntegrityError as excecao:
            await sessao.rollback()
            episodio_id = await _localizar_episodio_existente(sessao, anime_id, args)
            raise ErroSlimeStudio(f"episódio já cadastrado, id={episodio_id}") from excecao

        job = Job(
            episodio_id=episodio.id,
            status=StatusJob.NA_FILA,
            duracao_esperada_s=args.duracao_esperada_s,
        )
        sessao.add(job)
        await sessao.commit()
        return job.id


async def _localizar_episodio_existente(
    sessao: AsyncSession, anime_id: int, args: Argumentos
) -> int | None:
    resultado = await sessao.execute(
        select(Episodio.id).where(
            Episodio.anime_id == anime_id,
            Episodio.numero == args.numero,
            Episodio.tipo == args.tipo,
            Episodio.versao == args.versao,
        )
    )
    return resultado.scalar_one_or_none()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = analisar_argumentos(sys.argv[1:])
    config = carregar_config()
    job_id = asyncio.run(enfileirar(args, config))
    print(job_id)


if __name__ == "__main__":
    main()

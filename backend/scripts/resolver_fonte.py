"""CLI para resolver (ou confirmar manualmente) a fonte de site de um anime já
cadastrado, sem API (Fase 2, ESPECIFICACAO.md §3A) — desempata `ConfirmacaoNecessaria`
via `input()`.

Uso:
    uv run python -m scripts.resolver_fonte --anime-slug slime-datta-ken
"""

import argparse
import asyncio
import logging
import sys
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config import Config, carregar_config
from core.enums import VersaoEpisodio
from core.erros import ErroSlimeStudio
from db.engine import criar_engine, criar_sessionmaker
from extractors.resolucao import (
    ConfirmacaoNecessaria,
    FonteResolvida,
    VersaoIndisponivel,
    confirmar_fonte,
    resolver_fonte_do_anime,
)
from models.anime import Anime

_SessionMaker = async_sessionmaker[AsyncSession]


@dataclass(frozen=True, slots=True)
class Argumentos:
    anime_slug: str
    versao: VersaoEpisodio


def analisar_argumentos(argv: Sequence[str]) -> Argumentos:
    parser = argparse.ArgumentParser(
        description="Resolve (ou confirma manualmente) a fonte de site de um anime já cadastrado."
    )
    parser.add_argument("--anime-slug", required=True, help="Slug do anime (Anime.slug).")
    parser.add_argument(
        "--versao",
        choices=[VersaoEpisodio.LEGENDADO.value, VersaoEpisodio.DUBLADO.value],
        default=VersaoEpisodio.LEGENDADO.value,
        help="Versão a resolver (default: legendado).",
    )
    args = parser.parse_args(argv)
    return Argumentos(anime_slug=args.anime_slug, versao=VersaoEpisodio(args.versao))


async def resolver(args: Argumentos, config: Config) -> FonteResolvida:
    engine = criar_engine(config)
    sessionmaker = criar_sessionmaker(engine)
    try:
        anime = await _carregar_anime(sessionmaker, args.anime_slug)
        resultado = await resolver_fonte_do_anime(sessionmaker, anime, args.versao)
        if isinstance(resultado, FonteResolvida):
            return resultado
        if isinstance(resultado, VersaoIndisponivel):
            raise ErroSlimeStudio(
                f"nenhuma fonte disponível para a versão {resultado.versao.value!r} de"
                f" {anime.titulo!r}"
            )
        return await _confirmar_via_input(sessionmaker, anime, resultado)
    finally:
        await engine.dispose()


async def _carregar_anime(sessionmaker: _SessionMaker, slug: str) -> Anime:
    async with sessionmaker() as sessao:
        resultado = await sessao.execute(select(Anime).where(Anime.slug == slug))
        anime = resultado.scalar_one_or_none()
        if anime is None:
            raise ErroSlimeStudio(f"anime não encontrado (slug={slug!r})")
        return anime


async def _confirmar_via_input(
    sessionmaker: _SessionMaker, anime: Anime, confirmacao: ConfirmacaoNecessaria
) -> FonteResolvida:
    print(f"Múltiplos candidatos em {confirmacao.dominio} para {anime.titulo!r}:")
    for indice, candidato in enumerate(confirmacao.candidatos, start=1):
        print(f"  {indice}. {candidato.titulo_exibicao} ({candidato.url})")

    escolha = _ler_escolha(len(confirmacao.candidatos))
    candidato_escolhido = confirmacao.candidatos[escolha - 1]
    return await confirmar_fonte(sessionmaker, anime, confirmacao.dominio, candidato_escolhido)


def _ler_escolha(total: int) -> int:
    while True:
        bruto = input(f"Escolha [1-{total}]: ").strip()
        try:
            escolha = int(bruto)
        except ValueError:
            print("Entrada inválida, digite um número.")
            continue
        if 1 <= escolha <= total:
            return escolha
        print(f"Escolha fora do intervalo [1-{total}].")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = analisar_argumentos(sys.argv[1:])
    config = carregar_config()
    resultado = asyncio.run(resolver(args, config))
    print(f"Fonte gravada: {resultado.dominio} / {resultado.identificador}")


if __name__ == "__main__":
    main()

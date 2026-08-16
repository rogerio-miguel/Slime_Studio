"""Produtor de jobs a partir de um arquivo de vídeo local (Fase 1 — sem API ainda).

Wrapper fino de CLI sobre `db/catalogo.py` — a criação de anime/episódio/job é
compartilhada com a API (`api/servicos/jobs.py`), evitando drift entre os dois
produtores de job (ESPECIFICACAO.md §5, Passo 1.3 do plano da Fase 3).

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

from core.config import Config, carregar_config
from core.enums import SITE_LOCAL, TipoEpisodio, VersaoEpisodio
from db import catalogo
from db.engine import criar_engine, criar_sessionmaker


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
        anime_id = await catalogo.obter_ou_criar_anime_id(sessionmaker, args.anime, args.ano)
        return await catalogo.criar_episodio_e_job(
            sessionmaker,
            anime_id,
            numero=args.numero,
            tipo=args.tipo,
            versao=args.versao,
            url_fonte=str(args.arquivo.resolve()),
            site_origem=SITE_LOCAL,
            titulo_episodio=args.titulo_episodio,
            duracao_esperada_s=args.duracao_esperada_s,
        )
    finally:
        await engine.dispose()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = analisar_argumentos(sys.argv[1:])
    config = carregar_config()
    job_id = asyncio.run(enfileirar(args, config))
    print(job_id)


if __name__ == "__main__":
    main()

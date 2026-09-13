"""Backfill DESCARTÁVEL: preenche `Episodio.titulo`/`sinopse` (TMDB) dos
episódios já capturados antes de `info_de_episodio` existir em
`api/servicos/jobs.py::criar_job_site` — hoje ficam `NULL` pra sempre, sem
retentativa automática.

Só grava onde `titulo IS NULL` ou `sinopse IS NULL` (nunca sobrescreve um valor já resolvido).
Idempotente/re-executável; apagar depois de rodar.

Uso:
    uv run python -m scripts.backfill_titulo_episodio
"""

import asyncio
import logging

from sqlalchemy import or_, select

from api.servicos.fontes import info_de_episodio
from core.config import carregar_config
from db.engine import criar_engine, criar_sessionmaker
from integrations.registro import instalar_provedores_de_arte
from models.anime import Anime
from models.episodio import Episodio

logger = logging.getLogger(__name__)

# Mesma folga de `rerresolver_banners.py` (rate limit do TMDB).
_PAUSA_ENTRE_CHAMADAS_S = 0.3


async def backfill() -> tuple[int, int]:
    """`(processados, preenchidos)`."""
    config = carregar_config()
    instalar_provedores_de_arte(config.tmdb_token)
    engine = criar_engine(config)
    sessionmaker = criar_sessionmaker(engine)
    try:
        async with sessionmaker() as sessao:
            linhas = (
                await sessao.execute(
                    select(Episodio.id, Episodio.anime_id, Episodio.numero, Anime)
                    .join(Anime, Anime.id == Episodio.anime_id)
                    .where(or_(Episodio.titulo.is_(None), Episodio.sinopse.is_(None)))
                    .order_by(Episodio.anime_id, Episodio.numero)
                )
            ).all()

        logger.info("%d episódio(s) sem título", len(linhas))
        preenchidos = 0
        for episodio_id, anime_id, numero, anime in linhas:
            info = await info_de_episodio(sessionmaker, anime, numero)
            await asyncio.sleep(_PAUSA_ENTRE_CHAMADAS_S)
            if info is None or (info.nome is None and info.sinopse is None):
                logger.info(
                    "anime %s (%r) ep %s: TMDB não devolveu título/sinopse — mantido",
                    anime_id,
                    anime.titulo,
                    numero,
                )
                continue

            async with sessionmaker() as sessao:
                episodio = await sessao.get(Episodio, episodio_id)
                episodio.titulo = info.nome
                episodio.sinopse = info.sinopse
                await sessao.commit()
            preenchidos += 1
            logger.info(
                "anime %s (%r) ep %s: titulo=%r", anime_id, anime.titulo, numero, info.nome
            )
        return len(linhas), preenchidos
    finally:
        await engine.dispose()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    processados, preenchidos = asyncio.run(backfill())
    print(f"processados={processados} preenchidos={preenchidos}")


if __name__ == "__main__":
    main()

"""Backfill DESCARTÁVEL: troca `Anime.sinopse` (inglês da AniList, gravada uma
vez e nunca mais atualizada) pela pt-BR do TMDB, pela regra de
`core/sinopse.py::escolher_sinopse` — 1ª temporada usa a da série; continuação
usa a da temporada (se o TMDB tiver) ou a da série quando a AniList é genérica.

Pula filme/OVA/ONA (`formato_midia` preenchido): a premissa da série não descreve
uma obra avulsa. Só grava quando o texto muda; nunca apaga nem cria sinopse. Idempotente (uma
segunda rodada devolve os mesmos textos). `--dry-run` só lista. Apagar depois
de rodar.

Uso:
    uv run python -m scripts.backfill_sinopse_anime [--dry-run]
"""

import asyncio
import logging
import sys

from sqlalchemy import select

from api.servicos.fontes import _titulo_base_da_franquia
from core.config import carregar_config
from core.sinopse import escolher_sinopse
from db.engine import criar_engine, criar_sessionmaker
from integrations import servico as servico_metadados
from integrations.registro import instalar_provedores_de_arte
from models.anime import Anime

logger = logging.getLogger(__name__)

# Mesma folga de `rerresolver_banners.py` (rate limit do TMDB).
_PAUSA_ENTRE_CHAMADAS_S = 0.3


async def backfill(*, dry_run: bool) -> tuple[int, int]:
    """`(processados, trocados)`."""
    config = carregar_config()
    instalar_provedores_de_arte(config.tmdb_token)
    engine = criar_engine(config)
    sessionmaker = criar_sessionmaker(engine)
    try:
        async with sessionmaker() as sessao:
            animes = (
                (
                    await sessao.execute(
                        select(Anime)
                        .where(Anime.sinopse.is_not(None), Anime.formato_midia.is_(None))
                        .order_by(Anime.id)
                    )
                )
                .scalars()
                .all()
            )

        trocados = 0
        for anime in animes:
            temporada = anime.numero_temporada or 1
            titulo_base = await _titulo_base_da_franquia(sessionmaker, anime)
            arte = await servico_metadados.buscar_arte_por_titulo(titulo_base, anime.ano)
            temporada_ptbr = None
            if temporada > 1:
                temporada_ptbr = await servico_metadados.buscar_sinopse_da_temporada(
                    titulo_base, anime.ano, temporada
                )
            await asyncio.sleep(_PAUSA_ENTRE_CHAMADAS_S)

            nova = escolher_sinopse(
                anime.sinopse,
                serie_ptbr=arte.sinopse_serie if arte else None,
                temporada_ptbr=temporada_ptbr,
                primeira_temporada=temporada == 1,
            )
            if nova == anime.sinopse:
                logger.info("anime %s (%r): mantido", anime.id, anime.titulo)
                continue

            trocados += 1
            logger.info("anime %s (%r) T%s: %r", anime.id, anime.titulo, temporada, nova[:70])
            if dry_run:
                continue
            async with sessionmaker() as sessao:
                registro = await sessao.get(Anime, anime.id)
                registro.sinopse = nova
                await sessao.commit()
        return len(animes), trocados
    finally:
        await engine.dispose()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    processados, trocados = asyncio.run(backfill(dry_run="--dry-run" in sys.argv))
    print(f"processados={processados} trocados={trocados}")


if __name__ == "__main__":
    main()

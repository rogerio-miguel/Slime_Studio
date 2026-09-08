"""Re-resolve o `banner_path` de TODOS os animes catalogados pelo TMDB —
retroativo à correção de `integrations/tmdb.py::_melhor_resultado` (a distância
de ano elegia spin-off recente no lugar da série principal) e à adição de
`_melhor_backdrop` (backdrop sem texto / mais votado no lugar do `backdrop_path`
default). Sem isso, animes já catalogados ficam com o banner errado gravado.

Sobrescrita EXPLÍCITA via `db.catalogo.sobrescrever_arte` (não o só-quando-nulo
de `aplicar_metadados`) — mas nunca apaga: banner nulo do TMDB preserva o
existente (AniList). Re-executável e idempotente; descartável depois de rodar.

Uso:
    uv run python -m scripts.rerresolver_banners
"""

import asyncio
import logging

from sqlalchemy import select

from core.config import carregar_config
from db.catalogo import sobrescrever_arte
from db.engine import criar_engine, criar_sessionmaker
from integrations import servico
from integrations.registro import instalar_provedores_de_arte
from models.anime import Anime

logger = logging.getLogger(__name__)

# Respeita o rate limit do TMDB com folga (~50 req/s permitido; 0.3s é
# conservador e o catálogo tem dezenas de linhas).
_PAUSA_ENTRE_CHAMADAS_S = 0.3


async def rerresolver() -> tuple[int, int]:
    """`(processados, sobrescritos)`."""
    config = carregar_config()
    instalar_provedores_de_arte(config.tmdb_token)
    engine = criar_engine(config)
    sessionmaker = criar_sessionmaker(engine)
    try:
        async with sessionmaker() as sessao:
            linhas = (
                await sessao.execute(
                    select(Anime.id, Anime.titulo, Anime.ano, Anime.banner_path).order_by(Anime.id)
                )
            ).all()

        logger.info("%d anime(s) no catálogo", len(linhas))
        sobrescritos = 0
        for anime_id, titulo, ano, banner_antigo in linhas:
            arte = await servico.buscar_arte_por_titulo(titulo, ano)
            await asyncio.sleep(_PAUSA_ENTRE_CHAMADAS_S)
            if arte is None or arte.banner_url is None:
                logger.info("anime %s (%r): TMDB não devolveu banner — mantido", anime_id, titulo)
                continue
            if arte.banner_url == banner_antigo:
                continue
            await sobrescrever_arte(sessionmaker, anime_id, arte)
            sobrescritos += 1
            logger.info("anime %s (%r): banner -> %s", anime_id, titulo, arte.banner_url)
        return len(linhas), sobrescritos
    finally:
        await engine.dispose()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    processados, sobrescritos = asyncio.run(rerresolver())
    print(f"processados={processados} sobrescritos={sobrescritos}")


if __name__ == "__main__":
    main()

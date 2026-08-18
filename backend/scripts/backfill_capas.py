"""Backfill de capa para animes já catalogados sem `capa_path` — retroativo ao
fix de `frontend/src/paginas/Inicio.jsx::materializarFonteEIrPara` (a capa já
resolvida na busca em fontes não era repassada na criação do anime, então a
criação sempre dependia do enriquecimento por título, que é best-effort e
podia falhar silenciosamente e deixar `capa_path=None` de vez).

Reaproveita `api/servicos/descoberta.py::enriquecer_anime_criado` (mesma
lógica best-effort usada na criação via API) — chamado aqui com todos os
campos de metadado em `None` força o caminho de busca por título, pulando o
curto-circuito de "algum campo já veio no payload".

Uso:
    uv run python -m scripts.backfill_capas
"""

import asyncio
import logging

from sqlalchemy import select

from api.servicos.descoberta import enriquecer_anime_criado
from core.config import carregar_config
from db.engine import criar_engine, criar_sessionmaker
from models.anime import Anime

logger = logging.getLogger(__name__)


async def backfill() -> int:
    config = carregar_config()
    engine = criar_engine(config)
    sessionmaker = criar_sessionmaker(engine)
    try:
        async with sessionmaker() as sessao:
            resultado = await sessao.execute(
                select(Anime.id, Anime.titulo).where(Anime.capa_path.is_(None))
            )
            pendentes = resultado.all()

        logger.info("%d anime(s) sem capa encontrados", len(pendentes))
        for anime_id, titulo in pendentes:
            await enriquecer_anime_criado(
                sessionmaker,
                anime_id,
                titulo,
                anilist_id=None,
                kitsu_id=None,
                capa_url=None,
                sinopse=None,
            )
        return len(pendentes)
    finally:
        await engine.dispose()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    total = asyncio.run(backfill())
    print(f"processados={total} (ver logs acima para corrigidos/sem-match)")


if __name__ == "__main__":
    main()

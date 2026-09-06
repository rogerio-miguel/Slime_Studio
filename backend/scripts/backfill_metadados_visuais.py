"""Backfill único de metadados de provedor para os animes já catalogados a que
ainda falta algum campo — banner, cor dominante da capa, sinopse, gêneros e ano.

Retroativo às migrations `d4b7e2f019ac` (`Anime.banner_path`/`Anime.capa_cor`) e
`e7c4b1a9d2f0` (`Anime.generos`): os animes cadastrados antes delas ficam com as
colunas `NULL` — não há backfill automático, mesma política das outras colunas
de metadado.

Dois passos independentes:

  1. animes COM `anilist_id`: busca por id
     (`integrations.servico.buscar_metadados_por_anilist_id`) e aplica TODOS os
     metadados que vierem (`db.catalogo.aplicar_metadados`, só-quando-nulo) —
     sem exigir que a AniList tenha banner (ao contrário da versão anterior
     deste script, que pulava o anime inteiro quando o banner faltava).

  2. animes SEM `anilist_id`: busca por TÍTULO
     (`integrations.servico.buscar_por_titulo`, cadeia AniList→Kitsu). Casamento
     por título é heurístico — cada match aplicado vai nos logs com o `titulo`
     para auditoria manual.

Script único de migração de dados: re-executável e idempotente (o `WHERE` de
cada passo só pega quem ainda está sem algum campo; `aplicar_metadados` é
só-quando-nulo) e descartável depois de rodar em produção.

Uso:
    uv run python -m scripts.backfill_metadados_visuais
"""

import asyncio
import logging

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config import carregar_config
from core.erros import FalhaDeMetadados
from db.catalogo import aplicar_metadados
from db.engine import criar_engine, criar_sessionmaker
from integrations import servico
from integrations.registro import instalar_provedores_de_arte
from models.anime import Anime

logger = logging.getLogger(__name__)

_SessionMaker = async_sessionmaker[AsyncSession]

# Pausa entre chamadas a provedor — respeita o rate limit público da AniList
# (90 req/min); 1s deixa folga larga mesmo com o catálogo inteiro pendente.
_PAUSA_ENTRE_CHAMADAS_S = 1.0

# Anime a que falte QUALQUER uma destas colunas entra na fila do passo. O passo
# por id não olha `capa_path` (anime com `anilist_id` já foi catalogado com
# capa); o passo por título não olha `banner_path` (a AniList raramente casa
# por título e o Kitsu não tem banner).
_FALTA_METADADO_COM_ID = or_(
    Anime.banner_path.is_(None),
    Anime.sinopse.is_(None),
    Anime.generos.is_(None),
    Anime.ano.is_(None),
)
_FALTA_METADADO_SEM_ID = or_(
    Anime.sinopse.is_(None),
    Anime.generos.is_(None),
    Anime.capa_path.is_(None),
    Anime.ano.is_(None),
)


async def _passo_com_anilist_id(sessionmaker: _SessionMaker) -> tuple[int, int]:
    """Devolve `(pendentes, preenchidos)` do passo por id AniList."""
    async with sessionmaker() as sessao:
        resultado = await sessao.execute(
            select(Anime.id, Anime.anilist_id, Anime.titulo).where(
                Anime.anilist_id.is_not(None), _FALTA_METADADO_COM_ID
            )
        )
        pendentes = resultado.all()

    logger.info("passo 1: %d anime(s) com anilist_id e algum metadado faltando", len(pendentes))
    preenchidos = 0
    for indice, (anime_id, anilist_id, titulo) in enumerate(pendentes):
        if indice:
            await asyncio.sleep(_PAUSA_ENTRE_CHAMADAS_S)
        try:
            metadados = await servico.buscar_metadados_por_anilist_id(anilist_id)
        except FalhaDeMetadados as excecao:
            logger.warning("anime %s (%r): provedores falharam: %s", anime_id, titulo, excecao)
            continue

        if metadados is None:
            logger.info("anime %s (%r): provedor não resolveu o id", anime_id, titulo)
            continue

        await aplicar_metadados(sessionmaker, anime_id, metadados)
        preenchidos += 1
        logger.info("anime %s (%r): metadados aplicados", anime_id, titulo)
    return len(pendentes), preenchidos


async def _passo_por_titulo(sessionmaker: _SessionMaker) -> tuple[int, int]:
    """Devolve `(pendentes, preenchidos)` do passo por casamento de título."""
    async with sessionmaker() as sessao:
        resultado = await sessao.execute(
            select(Anime.id, Anime.titulo).where(
                Anime.anilist_id.is_(None), _FALTA_METADADO_SEM_ID
            )
        )
        pendentes = resultado.all()

    logger.info("passo 2: %d anime(s) sem anilist_id e algum metadado faltando", len(pendentes))
    preenchidos = 0
    for indice, (anime_id, titulo) in enumerate(pendentes):
        if indice:
            await asyncio.sleep(_PAUSA_ENTRE_CHAMADAS_S)
        try:
            metadados = await servico.buscar_por_titulo(titulo)
        except FalhaDeMetadados as excecao:
            logger.warning("anime %s (%r): provedores falharam: %s", anime_id, titulo, excecao)
            continue

        if metadados is None:
            logger.info("anime %s (%r): nenhum provedor casou o título", anime_id, titulo)
            continue

        await aplicar_metadados(sessionmaker, anime_id, metadados)
        preenchidos += 1
        logger.info(
            "anime %s: metadados aplicados por casamento de título %r (auditar)",
            anime_id,
            titulo,
        )
    return len(pendentes), preenchidos


async def backfill() -> tuple[tuple[int, int], tuple[int, int]]:
    """Devolve `((pendentes, preenchidos) do passo com anilist_id, idem do passo
    por título)`."""
    config = carregar_config()
    instalar_provedores_de_arte(config.tmdb_token)
    engine = criar_engine(config)
    sessionmaker = criar_sessionmaker(engine)
    try:
        com_id = await _passo_com_anilist_id(sessionmaker)
        por_titulo = await _passo_por_titulo(sessionmaker)
        return com_id, por_titulo
    finally:
        await engine.dispose()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    (pend_id, prench_id), (pend_titulo, prench_titulo) = asyncio.run(backfill())
    print(
        f"com_anilist_id: pendentes={pend_id} preenchidos={prench_id} | "
        f"por_titulo: pendentes={pend_titulo} preenchidos={prench_titulo} "
        "(ver logs para detalhes e casamentos de título a auditar)"
    )


if __name__ == "__main__":
    main()

"""Backfill de capa (pôster) via AniList para animes já catalogados com
`anilist_id` — reverte a refinação de capa por temporada do TMDB
(`PLANO_ARTE_TMDB.md`), removida porque a AniList já modela cada temporada
como uma `Media` própria (capa por temporada correta por construção),
diferente do TMDB, que agrupa a série inteira sob um único id.

Para todo `Anime` com `anilist_id` não-nulo (ou só `--anime-id`, se
restringido), busca de novo os metadados na AniList
(`integrations.servico.buscar_metadados_por_anilist_id`) e sobrescreve
`Anime.capa_path` com `metadados.capa_url` quando não for `None`, via
`db.catalogo.sobrescrever_capa` — sobrescrita INCONDICIONAL (substitui até
uma capa já preenchida, ex. pôster de série do TMDB gravado por um backfill
anterior), ao contrário de `aplicar_metadados` (só-quando-nulo).

`buscar_metadados_por_anilist_id` já faz overlay de banner via TMDB por baixo
dos panos (`integrations/servico.py::_com_arte`) — isso é esperado e não é
desfeito aqui; só a `capa_url` do resultado é usada.

Sequencial (nunca paralelo, CLAUDE.md): `asyncio.sleep(1s)` entre chamadas de
rede, nunca depois da última. Falha de UM anime (exceção do provedor) loga e
segue pro próximo — não aborta o lote inteiro. Anime sem `anilist_id` é
pulado com `logger.info` (não é erro: nem todo anime tem id AniList).

Flags:

  --dry-run     Loga o que faria, INCLUSIVE a `capa_url` real que resolveria
                — bate a rede mesmo em dry-run, sem gravar no banco. Diferente
                de `scripts/backfill_metadados_visuais.py` (que evita rede em
                dry-run porque seus passos têm efeito cumulativo um sobre o
                outro dentro da mesma execução): aqui cada anime é resolvido
                isoladamente, sem efeito colateral entre eles, então bater a
                rede em dry-run só tem valor — é o único jeito de mostrar a
                capa real que seria gravada, útil pra auditar antes de rodar
                de verdade.
  --anime-id N  Restringe o backfill a um único anime.

Uso:
    uv run python -m scripts.backfill_capa_anilist --dry-run
    uv run python -m scripts.backfill_capa_anilist
    uv run python -m scripts.backfill_capa_anilist --anime-id 42
"""

import argparse
import asyncio
import logging
import sys
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config import carregar_config
from core.erros import FalhaDeMetadados
from db.catalogo import sobrescrever_capa
from db.engine import criar_engine, criar_sessionmaker
from integrations import servico
from integrations.registro import instalar_provedores_de_arte
from models.anime import Anime

logger = logging.getLogger(__name__)

_SessionMaker = async_sessionmaker[AsyncSession]

# Pausa entre chamadas de rede — mesma folga de
# `scripts/backfill_metadados_visuais.py` frente ao rate limit da AniList/TMDB.
_PAUSA_ENTRE_CHAMADAS_S = 1.0


@dataclass(frozen=True, slots=True)
class Argumentos:
    dry_run: bool
    anime_id: int | None


def analisar_argumentos(argv: Sequence[str]) -> Argumentos:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill de capa (pôster) via AniList para animes catalogados com "
            "anilist_id — reversão da refinação de capa por temporada do TMDB."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Loga o que faria — inclusive a capa real que resolveria (bate a rede) — "
        "sem gravar no banco.",
    )
    parser.add_argument(
        "--anime-id", type=int, default=None, help="Restringe o backfill a um único anime."
    )
    args = parser.parse_args(argv)
    return Argumentos(dry_run=args.dry_run, anime_id=args.anime_id)


async def _carregar_candidatos(
    sessionmaker: _SessionMaker, *, anime_id: int | None
) -> list[tuple[int, int, str]]:
    """Devolve `[(anime_id, anilist_id, titulo), ...]` dos animes catalogados
    com `anilist_id` não-nulo (ou só o `--anime-id`, se restringido)."""
    async with sessionmaker() as sessao:
        if anime_id is not None:
            anime = await sessao.get(Anime, anime_id)
            if anime is None:
                logger.warning("anime %s: não encontrado", anime_id)
                return []
            if anime.anilist_id is None:
                logger.info("anime %s (%r): sem anilist_id, pulado", anime_id, anime.titulo)
                return []
            return [(anime.id, anime.anilist_id, anime.titulo)]

        resultado = await sessao.execute(
            select(Anime.id, Anime.anilist_id, Anime.titulo).where(
                Anime.anilist_id.is_not(None)
            )
        )
        return list(resultado.all())


async def _passo_backfill_capa(
    sessionmaker: _SessionMaker, *, anime_id: int | None, dry_run: bool
) -> int:
    """Devolve quantos animes tiveram (ou teriam, em `--dry-run`) capa
    sobrescrita."""
    candidatos = await _carregar_candidatos(sessionmaker, anime_id=anime_id)
    logger.info("%d anime(s) com anilist_id a re-resolver capa", len(candidatos))

    resolvidos = 0
    for indice, (anime_id_atual, anilist_id, titulo) in enumerate(candidatos):
        if indice:
            await asyncio.sleep(_PAUSA_ENTRE_CHAMADAS_S)
        try:
            metadados = await servico.buscar_metadados_por_anilist_id(anilist_id)
        except FalhaDeMetadados as excecao:
            logger.warning(
                "anime %s (%r): provedores falharam: %s", anime_id_atual, titulo, excecao
            )
            continue

        if metadados is None:
            logger.info("anime %s (%r): provedor não resolveu o id", anime_id_atual, titulo)
            continue
        if metadados.capa_url is None:
            logger.info("anime %s (%r): AniList não trouxe capa", anime_id_atual, titulo)
            continue

        if dry_run:
            logger.info(
                "anime %s (%r): capa seria sobrescrita para %r (dry-run, não gravado)",
                anime_id_atual,
                titulo,
                metadados.capa_url,
            )
            resolvidos += 1
            continue

        await sobrescrever_capa(sessionmaker, anime_id_atual, metadados.capa_url)
        resolvidos += 1
        logger.info("anime %s (%r): capa sobrescrita", anime_id_atual, titulo)
    return resolvidos


async def backfill(args: Argumentos) -> int:
    """Devolve quantos animes tiveram (ou teriam, em `--dry-run`) capa
    sobrescrita."""
    config = carregar_config()
    instalar_provedores_de_arte(config.tmdb_token)
    engine = criar_engine(config)
    sessionmaker = criar_sessionmaker(engine)
    try:
        return await _passo_backfill_capa(
            sessionmaker, anime_id=args.anime_id, dry_run=args.dry_run
        )
    finally:
        await engine.dispose()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = analisar_argumentos(sys.argv[1:])
    resolvidos = asyncio.run(backfill(args))
    prefixo = "[dry-run] " if args.dry_run else ""
    print(f"{prefixo}capa sobrescrita em {resolvidos} anime(s) (ver logs para detalhes)")


if __name__ == "__main__":
    main()

"""Backfill de posição na série (`numero_temporada` ordinal + `serie_ancora`)
via walk de `relations` da AniList para animes já catalogados com `anilist_id`
— liga `integrations.servico.resolver_serie` + `core.temporada.conciliar_posicao`
ao catálogo existente (Fatia 3e do plano da Fase 3; a materialização de anime
novo já chama o mesmo caminho em `api/servicos/descoberta.py::
_resolver_e_aplicar_serie`).

Para cada `Anime` com `anilist_id` não-nulo (ou só `--anime-id`, se
restringido), anda o grafo de `relations` SÓ PARA TRÁS
(`servico.resolver_serie`, D1), concilia o ordinal do grafo com o marcador do
título (`core.temporada.separar_temporada` — o marcador vence, D2) e grava via
`db.catalogo.aplicar_posicao_na_serie`, que preenche SÓ os campos ainda `NULL`.
Re-executável: roda de novo depois de a AniList voltar e preenche o que ficou
em branco numa passada anterior.

O `_memo_serie` de processo de `integrations/servico.py` faz cada franquia
custar ~1 caminhada — T2/T3 catalogadas reaproveitam o caminho já andado pela
primeira da cadeia.

Sequencial (nunca paralelo, CLAUDE.md): `asyncio.sleep(1s)` entre animes, nunca
depois do último. Falha de UM anime (exceção do provedor) loga e segue pro
próximo — não aborta o lote. Anime sem `anilist_id` é pulado com `logger.info`
(não é erro: nem todo anime tem id AniList).

Flags:

  --dry-run     Loga a posição que resolveria — bate a rede, sem gravar.
  --anime-id N  Restringe o backfill a um único anime.

Uso:
    uv run python -m scripts.backfill_serie --dry-run
    uv run python -m scripts.backfill_serie
    uv run python -m scripts.backfill_serie --anime-id 42
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
from core.temporada import conciliar_posicao, separar_temporada
from db.catalogo import aplicar_posicao_na_serie
from db.engine import criar_engine, criar_sessionmaker
from integrations import servico
from models.anime import Anime

logger = logging.getLogger(__name__)

_SessionMaker = async_sessionmaker[AsyncSession]

# Pausa entre chamadas de rede — mesma folga de `scripts/backfill_capa_anilist.py`
# frente ao rate limit da AniList.
_PAUSA_ENTRE_CHAMADAS_S = 1.0


@dataclass(frozen=True, slots=True)
class Argumentos:
    dry_run: bool
    anime_id: int | None


def analisar_argumentos(argv: Sequence[str]) -> Argumentos:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill de posição na série (numero_temporada ordinal + serie_ancora) "
            "via walk de relations da AniList para animes catalogados com anilist_id."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Loga a posição que resolveria (bate a rede) sem gravar no banco.",
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


async def _passo_backfill_serie(
    sessionmaker: _SessionMaker, *, anime_id: int | None, dry_run: bool
) -> int:
    """Devolve quantos animes tiveram (ou teriam, em `--dry-run`) posição
    gravada."""
    candidatos = await _carregar_candidatos(sessionmaker, anime_id=anime_id)
    logger.info("%d anime(s) com anilist_id a resolver posição na série", len(candidatos))

    resolvidos = 0
    for indice, (anime_id_atual, anilist_id, titulo) in enumerate(candidatos):
        if indice:
            await asyncio.sleep(_PAUSA_ENTRE_CHAMADAS_S)
        try:
            serie = await servico.resolver_serie(anilist_id)
        except FalhaDeMetadados as excecao:
            logger.warning(
                "anime %s (%r): provedores falharam: %s", anime_id_atual, titulo, excecao
            )
            continue

        marcador = separar_temporada(titulo)[1]
        ordinal_do_grafo = serie.ordinal if serie is not None else None
        ancora_do_grafo = serie.ancora if serie is not None else None
        posicao = conciliar_posicao(
            marcador=marcador,
            ordinal_do_grafo=ordinal_do_grafo,
            ancora_do_grafo=ancora_do_grafo,
            anilist_id=anilist_id,
        )

        if posicao.numero_temporada is None and posicao.serie_ancora is None:
            logger.info(
                "anime %s (%r): grafo não resolveu e título sem marcador — nada a gravar",
                anime_id_atual,
                titulo,
            )
            continue

        if (
            marcador is not None
            and ordinal_do_grafo is not None
            and marcador != ordinal_do_grafo
        ):
            logger.info(
                "anime %s (%r): divergência marcador=%s vs grafo=%s (fica o marcador)",
                anime_id_atual,
                titulo,
                marcador,
                ordinal_do_grafo,
            )

        if dry_run:
            logger.info(
                "anime %s (%r): resolveria numero_temporada=%s serie_ancora=%s "
                "(dry-run, não gravado)",
                anime_id_atual,
                titulo,
                posicao.numero_temporada,
                posicao.serie_ancora,
            )
            resolvidos += 1
            continue

        await aplicar_posicao_na_serie(sessionmaker, anime_id_atual, posicao)
        resolvidos += 1
        logger.info(
            "anime %s (%r): posição aplicada (só-quando-NULL) — "
            "numero_temporada=%s serie_ancora=%s",
            anime_id_atual,
            titulo,
            posicao.numero_temporada,
            posicao.serie_ancora,
        )
    return resolvidos


async def backfill(args: Argumentos) -> int:
    """Devolve quantos animes tiveram (ou teriam, em `--dry-run`) posição
    gravada."""
    config = carregar_config()
    engine = criar_engine(config)
    sessionmaker = criar_sessionmaker(engine)
    try:
        return await _passo_backfill_serie(
            sessionmaker, anime_id=args.anime_id, dry_run=args.dry_run
        )
    finally:
        await engine.dispose()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = analisar_argumentos(sys.argv[1:])
    resolvidos = asyncio.run(backfill(args))
    prefixo = "[dry-run] " if args.dry_run else ""
    print(f"{prefixo}posição na série resolvida em {resolvidos} anime(s) (ver logs)")


if __name__ == "__main__":
    main()

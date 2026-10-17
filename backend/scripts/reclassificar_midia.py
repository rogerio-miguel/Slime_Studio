"""Reclassifica série×extra (`integrations/classificacao.py`) nos animes já
catalogados com `anilist_id` — o catálogo anterior ao classificador tratava todo
ONA como extra (`Anime.formato_midia` preenchido), então séries como "Wan Ren Zhi
Shang" ficaram fora do seletor/numeração. Também rebaixa o que nasceu série mas
tem aresta `PARENT` (criação que caiu num 429 antes do 2º estágio).

Por anime: `servico.classificar_midia` (relações da AniList) decide;
`descoberta.reclassificar_midia` aplica (promove refazendo posição e franquia
como numa criação; rebaixa ancorando na série-mãe). Resposta "não sei"
(provedor fora do ar, sem `format`) PULA o anime — nunca promove nem rebaixa por
falha de rede. Re-executável e idempotente.

Sequencial, `asyncio.sleep(2.5s)` entre animes (rate limit da AniList), falha de
um anime loga e segue. Mexe só em animes cuja classificação MUDA; o resto fica
intocado.

Flags:

  --dry-run     Mostra o que mudaria — bate a rede, não grava.
  --anime-id N  Restringe a um único anime.

Uso:
    uv run python -m scripts.reclassificar_midia --dry-run
    uv run python -m scripts.reclassificar_midia
    uv run python -m scripts.reclassificar_midia --anime-id 140
"""

import argparse
import asyncio
import logging
import sys
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.servicos.descoberta import reclassificar_midia
from core.config import carregar_config
from core.erros import FalhaDeMetadados
from db.engine import criar_engine, criar_sessionmaker
from integrations import servico
from models.anime import Anime

logger = logging.getLogger(__name__)

_SessionMaker = async_sessionmaker[AsyncSession]

# A AniList limitou a ~30 chamadas/min (429 em rajada, medido em 2026-10-04): 1s por
# anime estourava o limite e o circuit breaker de `servico` curto-circuitava o resto do lote.
_PAUSA_ENTRE_CHAMADAS_S = 2.5


@dataclass(frozen=True, slots=True)
class Argumentos:
    dry_run: bool
    anime_id: int | None


def analisar_argumentos(argv: Sequence[str]) -> Argumentos:
    parser = argparse.ArgumentParser(
        description="Reclassifica série×extra nos animes catalogados com anilist_id."
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Mostra o que mudaria sem gravar no banco."
    )
    parser.add_argument("--anime-id", type=int, default=None, help="Restringe a um anime.")
    args = parser.parse_args(argv)
    return Argumentos(dry_run=args.dry_run, anime_id=args.anime_id)


async def _carregar_candidatos(
    sessionmaker: _SessionMaker, *, anime_id: int | None
) -> list[tuple[int, int, str, str | None]]:
    """`[(anime_id, anilist_id, titulo, formato_midia), ...]` dos animes com
    `anilist_id` (ou só o `--anime-id`)."""
    consulta = select(Anime.id, Anime.anilist_id, Anime.titulo, Anime.formato_midia).where(
        Anime.anilist_id.is_not(None)
    )
    if anime_id is not None:
        consulta = consulta.where(Anime.id == anime_id)
    async with sessionmaker() as sessao:
        return [tuple(linha) for linha in (await sessao.execute(consulta)).all()]


async def reclassificar(args: Argumentos) -> dict[str, int]:
    """Devolve a contagem por desfecho: `promovido`/`rebaixado` (ou o que
    seriam, em `--dry-run`), `inalterado`, `incerto` (provedor não respondeu) e
    `falha`."""
    config = carregar_config()
    engine = criar_engine(config)
    sessionmaker = criar_sessionmaker(engine)
    contagem = {"promovido": 0, "rebaixado": 0, "inalterado": 0, "incerto": 0, "falha": 0}
    try:
        candidatos = await _carregar_candidatos(sessionmaker, anime_id=args.anime_id)
        logger.info("%d anime(s) com anilist_id a reclassificar", len(candidatos))
        for indice, (anime_id, anilist_id, titulo, formato_atual) in enumerate(candidatos):
            if indice:
                await asyncio.sleep(_PAUSA_ENTRE_CHAMADAS_S)
            try:
                classificacao = await servico.classificar_midia(anilist_id)
                if classificacao is None:
                    logger.info(
                        "anime %s (%r): provedor não classificou — pulado", anime_id, titulo
                    )
                    contagem["incerto"] += 1
                    continue
                formato, serie = classificacao
                muda = serie == (formato_atual is not None)
                if not muda:
                    contagem["inalterado"] += 1
                    continue
                desfecho = "promovido" if serie else "rebaixado"
                if args.dry_run:
                    logger.info(
                        "anime %s (%r): seria %s (formato_midia=%s, format AniList=%s) — dry-run",
                        anime_id,
                        titulo,
                        desfecho,
                        formato_atual,
                        formato,
                    )
                else:
                    await reclassificar_midia(
                        sessionmaker,
                        anime_id,
                        titulo,
                        anilist_id,
                        formato_atual=formato_atual,
                        formato=formato,
                        serie=serie,
                    )
                    logger.info("anime %s (%r): %s", anime_id, titulo, desfecho)
                contagem[desfecho] += 1
            except FalhaDeMetadados as excecao:
                logger.warning("anime %s (%r): provedores falharam: %s", anime_id, titulo, excecao)
                contagem["falha"] += 1
    finally:
        await engine.dispose()
    return contagem


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = analisar_argumentos(sys.argv[1:])
    contagem = asyncio.run(reclassificar(args))
    prefixo = "[dry-run] " if args.dry_run else ""
    print(f"{prefixo}{contagem}")


if __name__ == "__main__":
    main()

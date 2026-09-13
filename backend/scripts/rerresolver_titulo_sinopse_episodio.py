"""Re-resolve `titulo`/`sinopse` (TMDB) de TODOS os episódios já capturados —
complementa `backfill_titulo_episodio.py` (que só preenche `NULL`, nunca
sobrescreve): depois que `integrations/tmdb.py::_preencher_com_fallback_en`
passou a completar com inglês o que falta em pt-BR, um episódio capturado
ANTES dessa mudança pode ter ficado com `sinopse`/`titulo` `NULL` pra sempre
(cai no caso do backfill), mas um capturado DEPOIS já pode ter gravado texto
em inglês que o TMDB, com o tempo, ganha tradução pt-BR pra — sem re-rodar
este script, o banco nunca alinha com o que a listagem remota (ao vivo, sem
persistir) já mostraria de qualquer forma.

Sobrescrita EXPLÍCITA (compara com o valor atual, grava se mudou) — mas nunca
apaga: campo `None` do TMDB preserva o texto já gravado, mesma convenção de
`rerresolver_banners.py`/`backfill_titulo_episodio.py`. Re-executável e
idempotente (uma segunda rodada sem novidade no TMDB não grava nada);
descartável quando não fizer mais sentido rodar.

Uso:
    uv run python -m scripts.rerresolver_titulo_sinopse_episodio
"""

import asyncio
import logging

from sqlalchemy import select

from api.servicos.fontes import info_de_episodio
from core.config import carregar_config
from db.engine import criar_engine, criar_sessionmaker
from integrations.registro import instalar_provedores_de_arte
from models.anime import Anime
from models.episodio import Episodio

logger = logging.getLogger(__name__)

# Mesma folga de `rerresolver_banners.py` (rate limit do TMDB).
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
                    select(
                        Episodio.id,
                        Episodio.anime_id,
                        Episodio.numero,
                        Episodio.titulo,
                        Episodio.sinopse,
                        Anime,
                    )
                    .join(Anime, Anime.id == Episodio.anime_id)
                    .order_by(Episodio.anime_id, Episodio.numero)
                )
            ).all()

        logger.info("%d episódio(s) capturado(s)", len(linhas))
        sobrescritos = 0
        for episodio_id, anime_id, numero, titulo_atual, sinopse_atual, anime in linhas:
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

            novo_titulo = info.nome if info.nome is not None else titulo_atual
            novo_sinopse = info.sinopse if info.sinopse is not None else sinopse_atual
            if novo_titulo == titulo_atual and novo_sinopse == sinopse_atual:
                continue

            async with sessionmaker() as sessao:
                episodio = await sessao.get(Episodio, episodio_id)
                episodio.titulo = novo_titulo
                episodio.sinopse = novo_sinopse
                await sessao.commit()
            sobrescritos += 1
            logger.info(
                "anime %s (%r) ep %s: titulo=%r sinopse=%s",
                anime_id,
                anime.titulo,
                numero,
                novo_titulo,
                "presente" if novo_sinopse else None,
            )
        return len(linhas), sobrescritos
    finally:
        await engine.dispose()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    processados, sobrescritos = asyncio.run(rerresolver())
    print(f"processados={processados} sobrescritos={sobrescritos}")


if __name__ == "__main__":
    main()

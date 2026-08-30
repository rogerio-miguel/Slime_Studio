"""Detector de episódios novos (badge no catálogo, ESPECIFICACAO.md §3F).

`episodios_novos` é cálculo puro sobre um `Anime` já carregado;
`contar_capturados_por_anime` é a leitura agregada que o alimenta em lote (uma
query para o catálogo inteiro, nunca por anime num loop). Não importa `fastapi`
nem Pydantic — `api/rotas/animes.py` é quem traduz o resultado para os esquemas
de saída (regra de dependência da Clean Architecture, CLAUDE.md §1).
"""

from collections.abc import Iterable

from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.enums import StatusEpisodio, StatusLancamento, TipoEpisodio
from models.anime import Anime
from models.episodio import Episodio

# Status que contam como "episódio já obtido" para o detector: `PRONTO` (arquivo
# em disco) e `LIBERADO` (já assistido, arquivos liberados, mas o usuário não
# quer vê-lo reaparecer como novo). `PENDENTE`/`FALHOU`/`SOMENTE_720P` ainda não
# renderam uma captura utilizável.
_STATUS_CAPTURADO = (StatusEpisodio.PRONTO, StatusEpisodio.LIBERADO)


def episodios_novos(anime: Anime, capturados: int) -> int:
    """Nº de episódios já lançados na fonte mas ainda não capturados localmente.

    Só faz sentido para anime `EM_LANCAMENTO`. `proximo_ep_numero` é o número do
    PRÓXIMO ep a ir ao ar, então já lançados = `proximo_ep_numero - 1`.
    Piso em 0: anime com mais capturados que o exibido (raro) não vira negativo.
    """
    if anime.status_lancamento is not StatusLancamento.EM_LANCAMENTO:
        return 0
    if anime.proximo_ep_numero is None:
        return 0
    return max(0, (anime.proximo_ep_numero - 1) - capturados)


async def contar_capturados_por_anime(sessao: AsyncSession, ids: Iterable[int]) -> dict[int, int]:
    """`{anime_id: nº de episódios REGULAR capturados}` para todos os `ids` numa
    única query agregada — `GET /api/animes` serializa o catálogo inteiro, um
    `SELECT` por anime seria N+1. `anime_id` ausente do dict = 0 capturados.

    `COUNT(DISTINCT numero)`: um episódio legendado + dublado são duas linhas mas
    conta como um capturado. `tipo == REGULAR`: OVA/especial/filme têm numeração
    própria e não entram na comparação com `proximo_ep_numero`.
    """
    lista_ids = list(ids)
    if not lista_ids:
        return {}
    resultado = await sessao.execute(
        select(Episodio.anime_id, func.count(distinct(Episodio.numero)))
        .where(
            Episodio.anime_id.in_(lista_ids),
            Episodio.tipo == TipoEpisodio.REGULAR,
            Episodio.status.in_(_STATUS_CAPTURADO),
        )
        .group_by(Episodio.anime_id)
    )
    return {anime_id: total for anime_id, total in resultado.all()}

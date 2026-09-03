"""Detector de episódios novos (badge no catálogo, ESPECIFICACAO.md §3F).

`episodios_novos` é cálculo puro sobre um `Anime` já carregado — compara
`Anime.episodios_na_fonte` (contagem da fonte real, alimentada por
`api/servicos/sondagem.py`) com a fronteira do que o usuário já acompanhou: o
maior `numero` de episódio REGULAR já capturado/assistido localmente. Usar a
fronteira em vez da contagem de capturados evita que buracos abaixo do episódio
mais recente (usuário que pulou episódios antigos) contem como novos.
`maior_numero_capturado_por_anime` é a leitura agregada que fornece essa
segunda metade em lote (uma query para o catálogo inteiro, nunca por anime num
loop). Não importa `fastapi` nem Pydantic — `api/rotas/animes.py` é quem traduz
o resultado para os esquemas de saída (regra de dependência da Clean
Architecture, CLAUDE.md §1).

O badge só aparece quando o anime está `EM_LANCAMENTO` — sem sub-trava de
sinal-vivo. A lógica de fronteira `MAX(numero)` já barra o falso-positivo do
episódio antigo pulado, então checar `proximo_ep_em`/`total_episodios_anilist`
não agregava nada e sumia o badge para animes `EM_LANCAMENTO` sem `anilist_id`.
`status_lancamento` é recalculado a cada request a partir da coluna homônima,
que `api/servicos/descoberta.py` mantém em dia via refresh oportunista de 6h —
se a AniList finaliza ou reabre um anime, o badge acompanha na próxima leitura;
não há flag persistida. Ver `episodios_novos`.
"""

from collections.abc import Iterable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.enums import StatusEpisodio, StatusLancamento, TipoEpisodio
from models.anime import Anime
from models.episodio import Episodio

# Status que contam como "episódio já obtido" para o detector: `PRONTO` (arquivo
# em disco) e `LIBERADO` (já assistido, arquivos liberados, mas o usuário não
# quer vê-lo reaparecer como novo). `PENDENTE`/`FALHOU`/`SOMENTE_720P` ainda não
# renderam uma captura utilizável.
_STATUS_CAPTURADO = (StatusEpisodio.PRONTO, StatusEpisodio.LIBERADO)


def episodios_novos(anime: Anime, maior_capturado: int) -> int:
    """Nº de episódios já disponíveis na fonte real (site) acima da fronteira do
    que o usuário acompanhou — 0 quando o anime não está `EM_LANCAMENTO`.

    `episodios_na_fonte` é a contagem da última sondagem bem-sucedida do site
    (`api/servicos/sondagem.py`); fica `None` enquanto nenhuma sondagem
    carimbou, e aí o badge é 0. `maior_capturado` é o maior `numero` de
    episódio REGULAR já capturado/assistido (0 se nenhum) — a comparação é com
    essa fronteira, não com a contagem de capturados, para que episódios
    antigos que o usuário pulou não inflem o badge. Piso em 0: fonte que largou
    episódios antigos (`episodios_na_fonte` abaixo da fronteira) não vira
    negativo.

    Gate: só `EM_LANCAMENTO`, sem sub-trava de sinal-vivo. A fronteira
    `maior_capturado` já mata o falso-positivo do episódio antigo pulado. O
    status é lido da coluna `status_lancamento` a cada request (mantida em dia
    por `api/servicos/descoberta.py`): se a AniList finaliza o anime o badge
    some na próxima leitura, se reabre ele volta — não há flag persistida.
    """
    if anime.episodios_na_fonte is None:
        return 0
    if anime.status_lancamento is not StatusLancamento.EM_LANCAMENTO:
        return 0
    return max(0, anime.episodios_na_fonte - maior_capturado)


async def maior_numero_capturado_por_anime(
    sessao: AsyncSession, ids: Iterable[int]
) -> dict[int, int]:
    """`{anime_id: maior numero de episódio REGULAR já capturado}` para todos os
    `ids` numa única query agregada — `GET /api/animes` serializa o catálogo
    inteiro, um `SELECT` por anime seria N+1. `anime_id` ausente do dict = 0
    (nenhum episódio capturado).

    `MAX(numero)`: a fronteira do que o usuário acompanhou, não quantos
    episódios tem — buraco abaixo do mais recente (episódio antigo pulado) não
    conta como pendente. `tipo == REGULAR`: OVA/especial/filme têm numeração
    própria e não entram na comparação com `episodios_na_fonte`.
    """
    lista_ids = list(ids)
    if not lista_ids:
        return {}
    resultado = await sessao.execute(
        select(Episodio.anime_id, func.max(Episodio.numero))
        .where(
            Episodio.anime_id.in_(lista_ids),
            Episodio.tipo == TipoEpisodio.REGULAR,
            Episodio.status.in_(_STATUS_CAPTURADO),
        )
        .group_by(Episodio.anime_id)
    )
    return {anime_id: maior for anime_id, maior in resultado.all()}

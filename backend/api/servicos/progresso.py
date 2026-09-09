"""Feature "continuar assistindo" — leitura da prateleira da Inicio. Não
importa `fastapi` nem Pydantic (regra de dependência da Clean Architecture,
CLAUDE.md §1); `api/rotas/episodios.py` traduz o resultado para
`ContinuarAssistindoSaida`.
"""

from collections.abc import Sequence

from sqlalchemy import Row, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.enums import StatusEpisodio
from models.anime import Anime
from models.episodio import Episodio

_SessionMaker = async_sessionmaker[AsyncSession]

_LIMITE_PADRAO = 12
# Mesmo limiar de "assistido" usado no player (`usePontoDeAssistido.js`) — um
# episódio que já passou disso deveria ter sido liberado (`liberar_episodio`)
# em vez de continuar aparecendo aqui; a query também cobre o caso de o
# usuário ter fechado a aba antes do listener de saída rodar.
_LIMIAR_CONCLUSAO = 0.9


async def listar_continuar_assistindo(
    sessionmaker: _SessionMaker, limite: int = _LIMITE_PADRAO
) -> Sequence[Row]:
    """Episódios com progresso salvo, ainda `PRONTO` (arquivo em disco) e
    abaixo de `_LIMIAR_CONCLUSAO` da duração quando esta é conhecida —
    episódios sem `duracao_s` (worker não conseguiu sondar) não são
    excluídos por essa checagem, só não entram no auto-limpa. Mais recente
    primeiro (`progresso_atualizado_em`)."""
    async with sessionmaker() as sessao:
        resultado = await sessao.execute(
            select(
                Episodio.id.label("episodio_id"),
                Episodio.anime_id.label("anime_id"),
                Anime.titulo.label("anime_titulo"),
                # `capa_path` é a still TMDB do episódio (`api/servicos/jobs.py
                # ::still_de_episodio`) — pode ser `NULL` (TMDB não achou);
                # `COALESCE` cai pra arte do anime nesse caso, mesmo fallback
                # de `PaginaDoAnime.jsx::thumbDoAnime`, nunca o thumb cru da
                # fonte de scraping.
                func.coalesce(Episodio.capa_path, Anime.banner_path, Anime.capa_path).label(
                    "thumb"
                ),
                Episodio.numero.label("numero"),
                Episodio.titulo.label("titulo"),
                Episodio.progresso_s.label("progresso_s"),
                Episodio.duracao_s.label("duracao_s"),
            )
            .join(Anime, Episodio.anime_id == Anime.id)
            .where(
                Episodio.progresso_s.is_not(None),
                Episodio.status == StatusEpisodio.PRONTO,
                or_(
                    Episodio.duracao_s.is_(None),
                    Episodio.progresso_s < Episodio.duracao_s * _LIMIAR_CONCLUSAO,
                ),
            )
            .order_by(Episodio.progresso_atualizado_em.desc())
            .limit(limite)
        )
        return resultado.all()

"""Aquecimento do catálogo: agenda, sem bloquear, a sondagem da fonte real e a
atualização de status dos animes que a política de ciclo de vida
(`core/ciclo_de_vida.py`) manda verificar.

Só o zelador de fontes (`api/servicos/zelador.py`) chama: nenhuma leitura de
página dispara verificação. Tudo fire-and-forget — o resultado entra no banco
para a PRÓXIMA leitura do catálogo.
"""

from collections.abc import Collection

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.servicos import descoberta as servico_descoberta
from api.servicos import lancamentos as servico_lancamentos
from api.servicos import sondagem as servico_sondagem
from models.anime import Anime

_SessionMaker = async_sessionmaker[AsyncSession]


async def aquecer_catalogo(
    sessionmaker: _SessionMaker,
    sessao: AsyncSession,
    animes: list[Anime],
    grupos_de_franquia: dict[int, list[object]],
    com_episodios: Collection[int],
    *,
    max_sondagens: int | None = None,
) -> None:
    """`animes`/`grupos_de_franquia`: o catálogo visível (`catalogo.animes_do_catalogo`).
    `com_episodios`: ids com ao menos um `Episodio`. `max_sondagens`: teto de
    sondagens desta passada; `None` usa o teto por lote de `agendar_sondagens`.

    Zero `await` de rede aqui: só leituras de banco para montar o agendamento."""
    ids = [anime.id for anime in animes]
    versoes = await servico_sondagem.versoes_de_sondagem_por_anime(sessao, ids)
    # Anime SEM nenhuma `FonteAnime` não entra em `versoes` e a sondagem o
    # pularia pra sempre; a política (`deve_resolver_fonte`) manda resolver a
    # fonte de quem a perdeu (migração `26791d90cb31`), de temporada nova de
    # franquia que o usuário terminou e de estreia/anime em exibição nunca aberto.
    # `em_espera` (backoff persistido) corta quem falhou há pouco — a varredura é
    # cara (todos os sites) e um anime não encontrado em lugar nenhum a repetia
    # a cada visita.
    em_espera = await servico_sondagem.ids_em_espera(sessao, ids)
    novas = await servico_lancamentos.temporadas_novas(sessao, grupos_de_franquia)
    a_resolver = await servico_sondagem.versoes_para_resolver_fonte(
        sessao,
        animes,
        versoes,
        com_episodios=com_episodios,
        temporadas_novas=novas,
        em_espera=em_espera,
    )

    argumentos_de_teto = {} if max_sondagens is None else {"max_sondagens": max_sondagens}
    servico_sondagem.agendar_sondagens(
        sessionmaker,
        animes,
        {**versoes, **a_resolver},
        a_resolver=frozenset(a_resolver),
        em_espera=em_espera,
        **argumentos_de_teto,
    )
    servico_descoberta.agendar_refreshs_do_catalogo(sessionmaker, animes)

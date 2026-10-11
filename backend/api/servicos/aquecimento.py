"""Aquecimento do catálogo: agenda, sem bloquear, a sondagem da fonte real e a
atualização de status dos animes que a política de ciclo de vida
(`core/ciclo_de_vida.py`) manda verificar.

Mesma lógica para quem chama: a Galeria (`GET /api/animes?aquecer=true`) e o
zelador de fontes (`api/servicos/zelador.py`). Tudo fire-and-forget — o resultado
entra no banco para a PRÓXIMA leitura do catálogo.
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
    # Reparo de fonte perdida (2026-09-15, migração
    # `26791d90cb31_invalida_fonte_anime_do_animefire_one`): anime com episódio
    # capturado mas ZERO `FonteAnime` mapeada nunca ganha entrada em
    # `versoes_de_sondagem_por_anime` (não há fonte pra consultar) e
    # `agendar_sondagens` o pularia pra sempre — só um `versao_confirmada_
    # mais_recente` nulo pro badge Dublado/Legendado sumir do card sem nenhum
    # jeito automático de voltar. Palpite de versão vem do próprio episódio já
    # capturado; `ignorar_gate_de_status` deixa isto tentar mesmo pra anime
    # `FINALIZADO` (o gate normal de status não se aplica aqui — é reparo
    # pontual, não sondagem contínua de contagem).
    # `em_espera` (backoff persistido) corta quem falhou há pouco, inclusive a
    # varredura cara (todos os extratores, sem fonte mapeada pra atalhar) — sem
    # isto, um anime não encontrado em lugar nenhum repetia a varredura inteira.
    em_espera = await servico_sondagem.ids_em_espera(sessao, ids)
    ids_sem_fonte_com_episodios = [
        aid for aid in ids if aid in com_episodios and aid not in versoes and aid not in em_espera
    ]
    versoes_de_reparo = await servico_sondagem.versoes_para_reresolver_fonte_perdida(
        sessao, ids_sem_fonte_com_episodios
    )
    # Temporada nova de franquia que o usuário terminou: sem episódio local não há
    # fonte mapeada, então o badge nunca acenderia sozinho — mesmo reparo acima,
    # com palpite de versão herdado da temporada anterior.
    novas = await servico_lancamentos.temporadas_novas(sessao, grupos_de_franquia)
    versoes_de_temporadas_novas = await servico_sondagem.versoes_de_reparo_de_temporadas_novas(
        sessao, novas, versoes
    )
    versoes_de_reparo = {**versoes_de_reparo, **versoes_de_temporadas_novas}
    versoes = {**versoes, **versoes_de_reparo}

    argumentos_de_teto = {} if max_sondagens is None else {"max_sondagens": max_sondagens}
    servico_sondagem.agendar_sondagens(
        sessionmaker,
        animes,
        versoes,
        ignorar_gate_de_status=frozenset(versoes_de_reparo),
        em_espera=em_espera,
        **argumentos_de_teto,
    )
    servico_descoberta.agendar_refreshs_do_catalogo(sessionmaker, animes)

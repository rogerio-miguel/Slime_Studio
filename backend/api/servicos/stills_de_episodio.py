"""Still/nome/sinopse de episódio vindos do TMDB (`integrations/`): o overlay
best-effort da listagem de exibição (`sobrepor_stills_de_episodios`, em lote) e a
consulta pontual da captura (`info_de_episodio`). Consumido por
`api/servicos/fontes.py`, `jobs.py` e `progresso.py`; nunca bloqueia nem falha o
chamador — sem resposta a tempo, vale a arte do próprio anime."""

import asyncio
import logging
from dataclasses import replace

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db.franquias import offset_de_temporada, titulo_base_da_franquia
from fontes.adaptadores.base import EpisodioRemoto
from integrations import servico as servico_metadados
from integrations.base import InfoDeEpisodio
from models.anime import Anime
from models.episodio import Episodio

logger = logging.getLogger(__name__)

_SessionMaker = async_sessionmaker[AsyncSession]

# Mesma concorrência/deadline de `api/servicos/capas.py::_consultar_capas` —
# outro enriquecimento best-effort sobre `integrations/servico.py`, mesma
# ordem de grandeza de chamadas em paralelo.
_CONCORRENCIA_STILLS = 5
_TETO_LOTE_STILLS_S = 18

# Teto do lookup de UM episódio (`info_de_episodio`, usado na captura — ver
# `api/servicos/jobs.py`), fora do lote, então sem a proteção do
# `asyncio.wait(timeout=...)` acima.
_TETO_STILL_UNICO_S = 9


async def _info_do_tmdb(
    anime: Anime, titulo_base: str, numero: int, temporada: int | None
) -> InfoDeEpisodio | None:
    """`buscar_info_de_episodio` pelo título da franquia e, se o TMDB não achar a
    série, pelo `titulo_ingles`. O TMDB indexa muita série asiática só pelo nome
    inglês/nativo ("Above Myriads"), nunca pelo romaji da AniList ("Wan Ren Zhi
    Shang") — sem esta reserva todo episódio caía no banner, sem nome nem still,
    mesmo com a série completa no TMDB. Mesma ordem inglês→romaji do overlay de
    banner (`integrations/servico.py`), aqui com o romaji primeiro porque é o que
    já casa a maioria das séries."""
    info = await servico_metadados.buscar_info_de_episodio(
        titulo_base, anime.ano, numero, temporada
    )
    if info is None and anime.titulo_ingles and anime.titulo_ingles != titulo_base:
        info = await servico_metadados.buscar_info_de_episodio(
            anime.titulo_ingles, anime.ano, numero, temporada
        )
    return info


async def _info_direto_ou_absoluto(
    anime: Anime, titulo_base: str, numero: int, offset_de_temporada: int
) -> InfoDeEpisodio | None:
    """Still/nome/sinopse TMDB de um episódio: tenta primeiro o par DIRETO
    (`numero` dentro da temporada, `anime.numero_temporada`) — o caso comum,
    onde o TMDB tem uma season própria pra cada temporada da AniList. Só cai
    pro número ABSOLUTO (`offset_de_temporada + numero`, `temporada=None`)
    quando o direto não acha nada E há offset pra tentar — a franquia
    "achatada" numa season só no TMDB (ex. Kusuriya no Hitorigoto — 2
    temporadas na AniList, 1 season de 48 no TMDB).

    Direto primeiro, não o inverso: `offset_de_temporada` (`_offset_de_
    temporada`) só soma `total_episodios_anilist` das temporadas irmãs JÁ
    CATALOGADAS localmente com o mesmo `serie_ancora` — uma irmã anterior
    ainda não catalogada (comum: só as temporadas mais recentes de uma
    franquia longa costumam estar no catálogo) faz a soma sair sub-contada, e
    o número absoluto calculado cai sobre a info de OUTRO episódio (real,
    mas do lugar errado da série) em vez de vir vazio. Tentar o direto antes
    evita esse erro de atribuição sempre que o TMDB de fato tem a temporada
    separada — só recorre ao absoluto (com o mesmo risco de offset incompleto
    de sempre) quando o direto genuinamente não encontra a temporada.

    `titulo_base` (`titulo_base_da_franquia`) substitui `anime.titulo` nas
    duas chamadas — título de temporada sem marcador reconhecível (ex.
    "Nome. 2", número solto) faria o TMDB não achar a série nenhuma vez."""
    info = await _info_do_tmdb(anime, titulo_base, numero, anime.numero_temporada)
    if info is not None or not offset_de_temporada:
        return info
    return await _info_do_tmdb(anime, titulo_base, offset_de_temporada + numero, None)


async def info_de_episodio(
    sessionmaker: _SessionMaker, anime: Anime, numero: int
) -> InfoDeEpisodio | None:
    """Still/nome/sinopse TMDB de UM episódio — usado na CAPTURA
    (`api/servicos/jobs.py`) pra gravar `Episodio.capa_path`/`titulo`/
    `sinopse`, ao contrário de `sobrepor_stills_de_episodios` (lote,
    exibição). Mesma estratégia direto-depois-absoluto de `_info_direto_ou_
    absoluto`; sem a concorrência/semáforo do lote, só um episódio.
    `offset_de_temporada` (consulta ao banco) só roda quando o direto falha
    — poupa a consulta no caso comum.

    Best-effort com teto próprio (`_TETO_STILL_UNICO_S`, fora do `_chamar`
    interno de `integrations/servico.py`), um por tentativa: qualquer
    falha/timeout vira `None` e é logada — a captura não pode travar nem
    falhar por causa de thumb/sinopse."""
    try:
        titulo_base = await titulo_base_da_franquia(sessionmaker, anime)
        info = await asyncio.wait_for(
            _info_do_tmdb(anime, titulo_base, numero, anime.numero_temporada),
            timeout=_TETO_STILL_UNICO_S,
        )
        if info is not None:
            return info

        offset = await offset_de_temporada(sessionmaker, anime)
        if not offset:
            return None
        return await asyncio.wait_for(
            _info_do_tmdb(anime, titulo_base, offset + numero, None),
            timeout=_TETO_STILL_UNICO_S,
        )
    except Exception as excecao:
        logger.warning(
            "info TMDB best-effort falhou pro episódio %s de %r na captura: %s",
            numero,
            anime.titulo,
            excecao,
        )
        return None


async def sobrepor_stills_de_episodios(
    sessionmaker: _SessionMaker,
    anime: Anime,
    episodios: list[EpisodioRemoto],
    offset_de_temporada: int = 0,
) -> list[EpisodioRemoto]:
    """Overlay best-effort de thumb/nome/sinopse TMDB (Fatia 5/6,
    `PLANO_ARTE_TMDB.md`) sobre `EpisodioRemoto.thumb_url`/`titulo`/`sinopse`.

    Cada episódio tenta primeiro o par DIRETO (`episodio.numero`,
    `anime.numero_temporada`) e só cai pro ABSOLUTO (`offset_de_temporada +
    numero`, `temporada=None`, deixando a `TabelaDeTemporadas` do TMDB achar a
    season) quando o direto não acha nada — ver `_info_direto_ou_absoluto`
    pro porquê dessa ordem (offset incompleto de uma temporada irmã ainda não
    catalogada localmente já causou still de episódio ERRADO, não só ausente).

    O fallback de THUMB quando o TMDB não acha (id não resolvido, temporada
    fora do range, still nulo) ou quando o lote não termina a tempo é a arte
    do PRÓPRIO anime (`anime.banner_path` ou `anime.capa_path`) — NUNCA MAIS o
    `thumb_url` que o extractor trouxe (pedido explícito do usuário: thumb de
    episódio não vem mais da fonte de scraping, só do TMDB ou da arte do
    anime já catalogada). `titulo`/`sinopse` não têm fallback equivalente
    (nenhum extractor os expõe) — ficam `None` quando o TMDB não acha ou não
    tem tradução pt-BR. Episódio sem `numero` (rótulo não numérico, ex.
    "Especial") não tem como mapear pro TMDB — cai direto no fallback, sem
    tentar.

    Mesma mecânica de concorrência/deadline de
    `api/servicos/capas.py::_consultar_capas`: `asyncio.wait` (não
    `wait_for`) pra aproveitar o que já terminou dentro do prazo; o que
    ainda estiver pendente é cancelado e a cancelação é aguardada antes de
    devolver — a *task* nunca some rodando solta.
    """
    fallback = anime.banner_path or anime.capa_path
    resultado = [replace(ep, thumb_url=fallback) for ep in episodios]

    indices_elegiveis = [indice for indice, ep in enumerate(episodios) if ep.numero is not None]
    if not indices_elegiveis:
        return resultado

    titulo_base = await titulo_base_da_franquia(sessionmaker, anime)
    semaforo = asyncio.Semaphore(_CONCORRENCIA_STILLS)

    async def _buscar_um(indice: int) -> tuple[int, InfoDeEpisodio | None]:
        episodio = episodios[indice]
        async with semaforo:
            try:
                info = await _info_direto_ou_absoluto(
                    anime, titulo_base, episodio.numero, offset_de_temporada
                )
            except Exception as excecao:
                # Captura ampla e intencional (mesmo espírito de
                # `api/servicos/capas.py::_consultar_um`): este overlay é
                # best-effort, nenhuma falha de provedor pode derrubar a
                # listagem nem os demais episódios do lote.
                logger.warning(
                    "overlay de still/nome/sinopse best-effort falhou pro episódio %s de %r: %s",
                    episodio.numero,
                    anime.titulo,
                    excecao,
                )
                return indice, None
        return indice, info

    tasks = [asyncio.ensure_future(_buscar_um(indice)) for indice in indices_elegiveis]
    concluidas, pendentes = await asyncio.wait(tasks, timeout=_TETO_LOTE_STILLS_S)
    if pendentes:
        for tarefa in pendentes:
            tarefa.cancel()
        await asyncio.gather(*pendentes, return_exceptions=True)

    infos_por_numero: dict[int, InfoDeEpisodio] = {}
    for tarefa in concluidas:
        indice, info = tarefa.result()
        if info is None:
            continue
        resultado[indice] = replace(
            resultado[indice],
            thumb_url=info.still_url or fallback,
            titulo=info.nome,
            sinopse=info.sinopse,
        )
        infos_por_numero[episodios[indice].numero] = info

    await _atualizar_textos_gravados(sessionmaker, anime, infos_por_numero)
    return resultado


def _texto_atualizado(gravado: str | None, novo: str | None, novo_em_fallback: bool) -> str | None:
    """Texto a persistir: `novo` só substitui o gravado quando é pt-BR de verdade
    (ex. o TMDB ganhou a tradução desde a captura); em fallback (en-US) só
    preenche um campo vazio — nunca regride um texto melhor já gravado. `None`
    nunca apaga."""
    if novo is None:
        return gravado
    if gravado is None or not novo_em_fallback:
        return novo
    return gravado


async def _atualizar_textos_gravados(
    sessionmaker: _SessionMaker, anime: Anime, infos_por_numero: dict[int, InfoDeEpisodio]
) -> None:
    """Alinha `Episodio.titulo`/`sinopse` já gravados com o que o overlay acabou
    de resolver — "Continuar assistindo" lê só o valor gravado, então sem isto
    um nome em inglês de fallback ficaria pra sempre depois que o TMDB ganha o
    pt-BR. Best-effort: a listagem não pode falhar por causa disto."""
    if not infos_por_numero:
        return
    try:
        async with sessionmaker() as sessao:
            locais = await sessao.scalars(
                select(Episodio).where(
                    Episodio.anime_id == anime.id, Episodio.numero.in_(infos_por_numero)
                )
            )
            for episodio in locais:
                info = infos_por_numero[episodio.numero]
                episodio.titulo = _texto_atualizado(
                    episodio.titulo, info.nome, info.nome_em_fallback
                )
                episodio.sinopse = _texto_atualizado(
                    episodio.sinopse, info.sinopse, info.sinopse_em_fallback
                )
            await sessao.commit()
    except Exception as excecao:
        logger.warning(
            "atualização best-effort de título/sinopse gravados falhou pro anime %r: %s",
            anime.titulo,
            excecao,
        )

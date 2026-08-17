"""Resolução automática de fonte com fallback entre sites (ESPECIFICACAO.md §3A
item 2 / §10, Fase 2/3).
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.erros import FonteNaoEncontrada
from core.texto import slugificar
from extractors import circuit_breaker, resiliencia
from extractors.base import ResultadoBusca
from extractors.registro import EXTRATORES
from models.anime import Anime
from models.fonte_anime import FonteAnime

_SessionMaker = async_sessionmaker[AsyncSession]


@dataclass(frozen=True, slots=True)
class FonteResolvida:
    dominio: str
    identificador: str


@dataclass(frozen=True, slots=True)
class ConfirmacaoNecessaria:
    dominio: str
    candidatos: list[ResultadoBusca]


async def resolver_fonte_do_anime(
    sessionmaker: _SessionMaker, anime: Anime
) -> FonteResolvida | ConfirmacaoNecessaria:
    """1. `FonteAnime` já mapeada -> devolve direto (a de maior prioridade).
    2. Sem mapeamento: percorre `EXTRATORES` em ordem, pulando os em cooldown.
    3. 1 candidato -> resolve; N candidatos -> desambigua por título (exatamente
       um match exato) ou devolve `ConfirmacaoNecessaria`.
    4. Resolvido -> grava `FonteAnime`.
    """
    mapeadas = await _fontes_mapeadas_ordenadas(sessionmaker, anime.id)
    if mapeadas:
        preferida = mapeadas[0]
        return FonteResolvida(
            dominio=preferida.site_dominio, identificador=preferida.identificador_no_site
        )

    for indice, extrator in enumerate(EXTRATORES):
        if await circuit_breaker.esta_em_cooldown(sessionmaker, extrator.dominio):
            continue

        candidatos = await resiliencia.chamar(
            sessionmaker, extrator, lambda cliente, ex=extrator: ex.buscar(cliente, anime.titulo)
        )
        if not candidatos:
            continue

        escolhido = _desambiguar(anime.titulo, candidatos)
        if escolhido is None:
            return ConfirmacaoNecessaria(dominio=extrator.dominio, candidatos=candidatos)

        await _gravar_fonte_anime(
            sessionmaker, anime.id, extrator.dominio, escolhido.identificador, prioridade=indice
        )
        return FonteResolvida(dominio=extrator.dominio, identificador=escolhido.identificador)

    raise FonteNaoEncontrada(f"nenhum site encontrou {anime.titulo!r}")


async def proximo_site_para(
    sessionmaker: _SessionMaker, anime: Anime, dominio_que_falhou: str
) -> FonteResolvida | None:
    """Próximo domínio na ordem de prioridade depois de `dominio_que_falhou` —
    usado quando um site já mapeado falha de extração (não confundir com
    `resolver_fonte_do_anime`, que pode pedir confirmação: aqui o job já está em
    andamento e não há quem confirme, então um site novo ambíguo é simplesmente
    pulado, não devolvido como `ConfirmacaoNecessaria`).
    """
    mapeadas = await _fontes_mapeadas_ordenadas(sessionmaker, anime.id)
    prioridade_falhou = next(
        (fonte.prioridade for fonte in mapeadas if fonte.site_dominio == dominio_que_falhou), None
    )
    if prioridade_falhou is not None:
        proxima_mapeada = next(
            (fonte for fonte in mapeadas if fonte.prioridade > prioridade_falhou), None
        )
        if proxima_mapeada is not None:
            return FonteResolvida(
                dominio=proxima_mapeada.site_dominio,
                identificador=proxima_mapeada.identificador_no_site,
            )

    dominios_ja_conhecidos = {fonte.site_dominio for fonte in mapeadas} | {dominio_que_falhou}
    for indice, extrator in enumerate(EXTRATORES):
        if extrator.dominio in dominios_ja_conhecidos:
            continue
        if await circuit_breaker.esta_em_cooldown(sessionmaker, extrator.dominio):
            continue

        candidatos = await resiliencia.chamar(
            sessionmaker, extrator, lambda cliente, ex=extrator: ex.buscar(cliente, anime.titulo)
        )
        escolhido = _desambiguar(anime.titulo, candidatos) if candidatos else None
        if escolhido is None:
            continue

        await _gravar_fonte_anime(
            sessionmaker, anime.id, extrator.dominio, escolhido.identificador, prioridade=indice
        )
        return FonteResolvida(dominio=extrator.dominio, identificador=escolhido.identificador)

    return None


def _desambiguar(titulo_anime: str, candidatos: list[ResultadoBusca]) -> ResultadoBusca | None:
    if len(candidatos) == 1:
        return candidatos[0]

    slug_anime = slugificar(titulo_anime)
    correspondentes = [
        candidato for candidato in candidatos if slugificar(candidato.titulo_exibicao) == slug_anime
    ]
    return correspondentes[0] if len(correspondentes) == 1 else None


async def _fontes_mapeadas_ordenadas(
    sessionmaker: _SessionMaker, anime_id: int
) -> list[FonteAnime]:
    async with sessionmaker() as sessao:
        resultado = await sessao.execute(
            select(FonteAnime)
            .where(FonteAnime.anime_id == anime_id)
            .order_by(FonteAnime.prioridade)
        )
        return list(resultado.scalars())


async def confirmar_fonte(
    sessionmaker: _SessionMaker, anime: Anime, dominio: str, candidato: ResultadoBusca
) -> FonteResolvida:
    """Grava a escolha manual de um candidato de `ConfirmacaoNecessaria` — usado por
    `scripts/resolver_fonte.py`, que desempata via `input()` na ausência de API."""
    prioridade = next(
        (indice for indice, extrator in enumerate(EXTRATORES) if extrator.dominio == dominio), 0
    )
    await _gravar_fonte_anime(
        sessionmaker, anime.id, dominio, candidato.identificador, prioridade=prioridade
    )
    return FonteResolvida(dominio=dominio, identificador=candidato.identificador)


async def _gravar_fonte_anime(
    sessionmaker: _SessionMaker,
    anime_id: int,
    dominio: str,
    identificador: str,
    *,
    prioridade: int,
) -> None:
    async with sessionmaker() as sessao:
        existente = await sessao.get(FonteAnime, (anime_id, dominio))
        if existente is None:
            sessao.add(
                FonteAnime(
                    anime_id=anime_id,
                    site_dominio=dominio,
                    identificador_no_site=identificador,
                    prioridade=prioridade,
                )
            )
        else:
            existente.identificador_no_site = identificador
            existente.prioridade = prioridade
        await sessao.commit()

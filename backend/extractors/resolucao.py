"""Resolução automática de fonte com fallback entre sites (ESPECIFICACAO.md §3A
item 2 / §10, Fase 2/3) — versão consciente de legendado/dublado (Fase 2 da
modelagem dublado/legendado).
"""

from dataclasses import dataclass
from typing import Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.enums import VersaoDeFonte, VersaoEpisodio
from core.texto import slugificar
from extractors import circuit_breaker, resiliencia
from extractors.base import ExtratorDeSite, ResultadoBusca
from extractors.registro import EXTRATORES
from extractors.versao import remover_marcador_de_versao
from models.anime import Anime
from models.fonte_anime import FonteAnime

_SessionMaker = async_sessionmaker[AsyncSession]

# `VersaoEpisodio` (LEGENDADO/DUBLADO) -> `VersaoDeFonte` correspondente — as
# duas têm o mesmo valor de string por design (`core/enums.py`), mas são
# enums separados de propósito (não fundir), daí o mapeamento explícito em
# vez de reinterpretar um pelo outro por acaso de implementação.
_MAPA_VERSAO_EPISODIO_PARA_FONTE: Final[dict[VersaoEpisodio, VersaoDeFonte]] = {
    VersaoEpisodio.LEGENDADO: VersaoDeFonte.LEGENDADO,
    VersaoEpisodio.DUBLADO: VersaoDeFonte.DUBLADO,
}


@dataclass(frozen=True, slots=True)
class FonteResolvida:
    dominio: str
    identificador: str
    # O que a fonte resolvida realmente é: confirmada igual à versão pedida,
    # ou `NAO_DIFERENCIADA` (site não separa, chamador nunca deve tratar como
    # confirmação da versão pedida — `api/servicos/jobs.py` deriva
    # `Episodio.versao = DESCONHECIDA` nesse caso, nunca do request).
    versao_da_fonte: VersaoDeFonte


@dataclass(frozen=True, slots=True)
class ConfirmacaoNecessaria:
    dominio: str
    candidatos: list[ResultadoBusca]


@dataclass(frozen=True, slots=True)
class VersaoIndisponivel:
    """Nenhum site, mapeado ou buscado ao vivo, consegue servir `versao` — nem
    confirmada, nem `NAO_DIFERENCIADA`."""

    versao: VersaoEpisodio


async def resolver_fonte_do_anime(
    sessionmaker: _SessionMaker, anime: Anime, versao: VersaoEpisodio
) -> FonteResolvida | ConfirmacaoNecessaria | VersaoIndisponivel:
    """`versao` é a versão PEDIDA pelo cliente — só `LEGENDADO`/`DUBLADO`
    (nunca `DESCONHECIDA`, que não é uma versão pedível, só um estado de
    `Episodio` de fonte não-diferenciada).

    1. `FonteAnime` já mapeadas: uma linha CONFIRMADA da `versao` pedida, em
       QUALQUER site mapeado, sempre vence sobre uma `NAO_DIFERENCIADA` de
       outro site de prioridade maior — confirmação exata de versão pesa mais
       que prioridade de site. Só na ausência de qualquer confirmação exata
       cai para a primeira `NAO_DIFERENCIADA` encontrada, na ordem de
       prioridade.
    2. Nenhum mapeamento serve: percorre `EXTRATORES` em ordem, buscando ao
       vivo. Sites que diferenciam versão (`diferencia_versao=True`)
       particionam os candidatos por versão e desambiguam dentro da
       partição pedida; a outra partição é persistida de graça quando também
       desambigua sem custo de rede extra. Sites que não diferenciam seguem
       o comportamento de sempre (desambigua no pool inteiro,
       `NAO_DIFERENCIADA`).
    3. Nenhum site (mapeado ou buscado) serve a versão pedida -> `VersaoIndisponivel`.
    """
    if versao not in (VersaoEpisodio.LEGENDADO, VersaoEpisodio.DUBLADO):
        raise ValueError(
            f"versão pedida a resolver_fonte_do_anime deve ser LEGENDADO ou"
            f" DUBLADO, recebido {versao!r}"
        )
    versao_confirmada = _MAPA_VERSAO_EPISODIO_PARA_FONTE[versao]

    mapeadas = await _fontes_mapeadas_ordenadas(sessionmaker, anime.id)
    resolvida = _resolver_em_mapeadas(mapeadas, versao_confirmada)
    if resolvida is not None:
        return resolvida

    for indice, extrator in enumerate(EXTRATORES):
        if await circuit_breaker.esta_em_cooldown(sessionmaker, extrator.dominio):
            continue

        candidatos = await resiliencia.chamar(
            sessionmaker, extrator, lambda cliente, ex=extrator: ex.buscar(cliente, anime.titulo)
        )
        if not candidatos:
            continue

        if extrator.diferencia_versao:
            resultado = await _resolver_no_site_que_diferencia(
                sessionmaker, anime, extrator, indice, candidatos, versao
            )
            if resultado is not None:
                return resultado
            continue  # partição pedida vazia neste site — não desiste, tenta o próximo

        return await _resolver_no_site_nao_diferenciado(
            sessionmaker, anime, extrator, indice, candidatos
        )

    return VersaoIndisponivel(versao=versao)


async def proximo_site_para(
    sessionmaker: _SessionMaker, anime: Anime, dominio_que_falhou: str, versao: VersaoEpisodio
) -> FonteResolvida | None:
    """Próximo domínio na ordem de prioridade depois de `dominio_que_falhou` —
    usado quando um site já mapeado falha de extração (não confundir com
    `resolver_fonte_do_anime`, que pode pedir confirmação: aqui o job já está em
    andamento e não há quem confirme, então um site novo ambíguo é simplesmente
    pulado, não devolvido como `ConfirmacaoNecessaria`).

    `versao` aqui é `Episodio.versao` de quem está com download em andamento
    (`extractors/servico.py::baixar_com_fallback_de_site`) — ao contrário de
    `resolver_fonte_do_anime`, PODE ser `DESCONHECIDA` (episódio veio de fonte
    `NAO_DIFERENCIADA`, sem versão pedida de verdade pra preservar): nesse
    caso a busca de fallback ignora a dimensão de versão por completo
    (comportamento anterior a esta fase — primeira fonte disponível, sem
    exigir capacidade de versão nenhuma).
    """
    mapeadas = await _fontes_mapeadas_ordenadas(sessionmaker, anime.id)
    prioridade_falhou = next(
        (fonte.prioridade for fonte in mapeadas if fonte.site_dominio == dominio_que_falhou), None
    )
    if prioridade_falhou is not None:
        candidatas_mapeadas = [fonte for fonte in mapeadas if fonte.prioridade > prioridade_falhou]
        resolvida = _proxima_mapeada_capaz(candidatas_mapeadas, versao)
        if resolvida is not None:
            return resolvida

    dominios_ja_conhecidos = {fonte.site_dominio for fonte in mapeadas} | {dominio_que_falhou}
    for indice, extrator in enumerate(EXTRATORES):
        if extrator.dominio in dominios_ja_conhecidos:
            continue
        if await circuit_breaker.esta_em_cooldown(sessionmaker, extrator.dominio):
            continue

        candidatos = await resiliencia.chamar(
            sessionmaker, extrator, lambda cliente, ex=extrator: ex.buscar(cliente, anime.titulo)
        )
        if not candidatos:
            continue

        if extrator.diferencia_versao and versao != VersaoEpisodio.DESCONHECIDA:
            resultado = await _resolver_no_site_que_diferencia(
                sessionmaker, anime, extrator, indice, candidatos, versao
            )
            if isinstance(resultado, FonteResolvida):
                return resultado
            continue  # ConfirmacaoNecessaria ou partição vazia: sem quem confirme, pula

        escolhido = _desambiguar(anime.titulo, candidatos)
        if escolhido is None:
            continue

        versao_de_fonte = _versao_de_fonte_do_candidato_generico(extrator, escolhido)
        await _gravar_fonte_anime(
            sessionmaker,
            anime.id,
            extrator.dominio,
            escolhido.identificador,
            versao_de_fonte,
            prioridade=indice,
        )
        return FonteResolvida(
            dominio=extrator.dominio,
            identificador=escolhido.identificador,
            versao_da_fonte=versao_de_fonte,
        )

    return None


def _resolver_em_mapeadas(
    mapeadas: list[FonteAnime], versao_confirmada: VersaoDeFonte
) -> FonteResolvida | None:
    """Percorre os sites já mapeados (na ordem de prioridade — `mapeadas` já
    vem ordenada por `FonteAnime.prioridade`) e devolve a primeira fonte capaz
    de servir `versao_confirmada`: uma linha CONFIRMADA da versão pedida, em
    QUALQUER site mapeado, sempre vence sobre uma `NAO_DIFERENCIADA` de outro
    site de prioridade maior — confirmação exata de versão pesa mais que
    prioridade de site (bug corrigido: antes, o primeiro site com QUALQUER
    linha mapeada — mesmo só `NAO_DIFERENCIADA` — vencia sem olhar se outro
    site tinha a versão exata confirmada)."""
    confirmada = next((f for f in mapeadas if f.versao == versao_confirmada), None)
    if confirmada is not None:
        return FonteResolvida(
            dominio=confirmada.site_dominio,
            identificador=confirmada.identificador_no_site,
            versao_da_fonte=versao_confirmada,
        )
    nao_diferenciada = next(
        (f for f in mapeadas if f.versao == VersaoDeFonte.NAO_DIFERENCIADA), None
    )
    if nao_diferenciada is not None:
        return FonteResolvida(
            dominio=nao_diferenciada.site_dominio,
            identificador=nao_diferenciada.identificador_no_site,
            versao_da_fonte=VersaoDeFonte.NAO_DIFERENCIADA,
        )
    return None


def _proxima_mapeada_capaz(
    mapeadas: list[FonteAnime], versao: VersaoEpisodio
) -> FonteResolvida | None:
    """Variante de `_resolver_em_mapeadas` usada por `proximo_site_para`,
    tolerante a `VersaoEpisodio.DESCONHECIDA` (sem versão pedida de verdade a
    preservar): nesse caso usa a 1ª fonte mapeada disponível, na ordem de
    prioridade, sem checar capacidade de versão (comportamento anterior a
    esta fase)."""
    if versao == VersaoEpisodio.DESCONHECIDA:
        if not mapeadas:
            return None
        primeira = mapeadas[0]
        return FonteResolvida(
            dominio=primeira.site_dominio,
            identificador=primeira.identificador_no_site,
            versao_da_fonte=primeira.versao,
        )
    return _resolver_em_mapeadas(mapeadas, _MAPA_VERSAO_EPISODIO_PARA_FONTE[versao])


async def _resolver_no_site_que_diferencia(
    sessionmaker: _SessionMaker,
    anime: Anime,
    extrator: ExtratorDeSite,
    indice: int,
    candidatos: list[ResultadoBusca],
    versao_pedida: VersaoEpisodio,
) -> FonteResolvida | ConfirmacaoNecessaria | None:
    """`None` = partição da versão pedida veio vazia neste site (site não tem
    essa versão) — o chamador decide se continua pro próximo site."""
    por_versao: dict[VersaoEpisodio, list[ResultadoBusca]] = {}
    for candidato in candidatos:
        if candidato.versao is not None:
            por_versao.setdefault(candidato.versao, []).append(candidato)

    particao_pedida = por_versao.get(versao_pedida, [])
    if not particao_pedida:
        return None

    escolhido = _desambiguar_por_versao(anime.titulo, particao_pedida)
    if escolhido is None:
        return ConfirmacaoNecessaria(dominio=extrator.dominio, candidatos=particao_pedida)

    versao_confirmada = _MAPA_VERSAO_EPISODIO_PARA_FONTE[versao_pedida]
    await _gravar_fonte_anime(
        sessionmaker,
        anime.id,
        extrator.dominio,
        escolhido.identificador,
        versao_confirmada,
        prioridade=indice,
    )

    # Dado grátis: a outra versão veio na mesma busca — se ela também
    # desambigua sem ambiguidade, persiste também, sem custo de rede extra.
    # Ambiguidade na outra partição não bloqueia nada, só não persiste.
    outra_versao = (
        VersaoEpisodio.DUBLADO if versao_pedida == VersaoEpisodio.LEGENDADO
        else VersaoEpisodio.LEGENDADO
    )
    particao_outra = por_versao.get(outra_versao, [])
    if particao_outra:
        escolhido_outra = _desambiguar_por_versao(anime.titulo, particao_outra)
        if escolhido_outra is not None:
            await _gravar_fonte_anime(
                sessionmaker,
                anime.id,
                extrator.dominio,
                escolhido_outra.identificador,
                _MAPA_VERSAO_EPISODIO_PARA_FONTE[outra_versao],
                prioridade=indice,
            )

    return FonteResolvida(
        dominio=extrator.dominio,
        identificador=escolhido.identificador,
        versao_da_fonte=versao_confirmada,
    )


async def _resolver_no_site_nao_diferenciado(
    sessionmaker: _SessionMaker,
    anime: Anime,
    extrator: ExtratorDeSite,
    indice: int,
    candidatos: list[ResultadoBusca],
) -> FonteResolvida | ConfirmacaoNecessaria:
    """Comportamento idêntico ao de antes desta fase — sem particionamento por
    versão, fonte gravada sempre como `NAO_DIFERENCIADA`."""
    escolhido = _desambiguar(anime.titulo, candidatos)
    if escolhido is None:
        return ConfirmacaoNecessaria(dominio=extrator.dominio, candidatos=candidatos)

    await _gravar_fonte_anime(
        sessionmaker,
        anime.id,
        extrator.dominio,
        escolhido.identificador,
        VersaoDeFonte.NAO_DIFERENCIADA,
        prioridade=indice,
    )
    return FonteResolvida(
        dominio=extrator.dominio,
        identificador=escolhido.identificador,
        versao_da_fonte=VersaoDeFonte.NAO_DIFERENCIADA,
    )


def _versao_de_fonte_do_candidato_generico(
    extrator: ExtratorDeSite, candidato: ResultadoBusca
) -> VersaoDeFonte:
    """Usada só pelo ramo "sem versão pedida de verdade" de `proximo_site_para`
    (`_proxima_mapeada_capaz`/descoberta ao vivo com `versao=DESCONHECIDA`):
    site que não diferencia, ou candidato sem marcador detectado mesmo em site
    que diferencia, grava como `NAO_DIFERENCIADA` — nunca assume confirmação
    que não foi pedida."""
    if not extrator.diferencia_versao or candidato.versao is None:
        return VersaoDeFonte.NAO_DIFERENCIADA
    return _MAPA_VERSAO_EPISODIO_PARA_FONTE[candidato.versao]


def _desambiguar(titulo_anime: str, candidatos: list[ResultadoBusca]) -> ResultadoBusca | None:
    if len(candidatos) == 1:
        return candidatos[0]

    slug_anime = slugificar(titulo_anime)
    correspondentes = [
        candidato for candidato in candidatos if slugificar(candidato.titulo_exibicao) == slug_anime
    ]
    return correspondentes[0] if len(correspondentes) == 1 else None


def _desambiguar_por_versao(
    titulo_anime: str, candidatos: list[ResultadoBusca]
) -> ResultadoBusca | None:
    """Mesma lógica de `_desambiguar`, mas compara o slug do candidato SEM o
    marcador de versão (ex. "Nome Dublado" -> "Nome") contra o slug base do
    anime — os candidatos aqui já vêm de uma partição por versão de um site
    que diferencia, então título/slug do candidato costuma carregar o
    marcador que o título do anime cadastrado não tem.

    Remove o marcador do `identificador` (slug), não do `titulo_exibicao`: o
    título de exibição varia de formatação por site — AnimeFire envolve o
    marcador em parênteses ("Nome (Dublado)"), fora da fronteira de token
    `-`/espaço que `remover_marcador_de_versao` exige, então nunca seria
    removido do título e o slug resultante nunca bateria com `slug_anime`. O
    identificador já é slug (hifens), onde o marcador sempre está isolado por
    `-`/início/fim — mesma convenção nos dois sites hoje."""
    if len(candidatos) == 1:
        return candidatos[0]

    slug_anime = slugificar(titulo_anime)
    correspondentes = [
        candidato
        for candidato in candidatos
        if slugificar(remover_marcador_de_versao(candidato.identificador)) == slug_anime
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
    `scripts/resolver_fonte.py`, que desempata via `input()` na ausência de API.

    `versao_da_fonte` gravada é derivada de `candidato.versao` (presente
    quando veio da partição de um site que diferencia versão — a mesma
    `ConfirmacaoNecessaria` que `resolver_fonte_do_anime` devolve já é
    restrita a uma única partição/versão, nunca mistura as duas) — na
    ausência de marcador (site que não diferencia), `NAO_DIFERENCIADA`.
    """
    prioridade = next(
        (indice for indice, extrator in enumerate(EXTRATORES) if extrator.dominio == dominio), 0
    )
    versao_da_fonte = (
        _MAPA_VERSAO_EPISODIO_PARA_FONTE[candidato.versao]
        if candidato.versao is not None
        else VersaoDeFonte.NAO_DIFERENCIADA
    )
    await _gravar_fonte_anime(
        sessionmaker,
        anime.id,
        dominio,
        candidato.identificador,
        versao_da_fonte,
        prioridade=prioridade,
    )
    return FonteResolvida(
        dominio=dominio, identificador=candidato.identificador, versao_da_fonte=versao_da_fonte
    )


async def _gravar_fonte_anime(
    sessionmaker: _SessionMaker,
    anime_id: int,
    dominio: str,
    identificador: str,
    versao: VersaoDeFonte,
    *,
    prioridade: int,
) -> None:
    async with sessionmaker() as sessao:
        existente = await sessao.get(FonteAnime, (anime_id, dominio, versao))
        if existente is None:
            sessao.add(
                FonteAnime(
                    anime_id=anime_id,
                    site_dominio=dominio,
                    versao=versao,
                    identificador_no_site=identificador,
                    prioridade=prioridade,
                )
            )
        else:
            existente.identificador_no_site = identificador
            existente.prioridade = prioridade
        await sessao.commit()

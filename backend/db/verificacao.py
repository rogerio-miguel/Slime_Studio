"""Persistência do estado de verificação (`VerificacaoDeAnime`) — a política de
backoff é de `core/ciclo_de_vida.py`; aqui só leitura e gravação."""

import logging
from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.ciclo_de_vida import CONTA_COMO_FALHA_DO_ANIME, proxima_tentativa
from core.enums import ResultadoDeVerificacao, TarefaDeVerificacao
from models.verificacao_de_anime import VerificacaoDeAnime

logger = logging.getLogger(__name__)

_SessionMaker = async_sessionmaker[AsyncSession]

_MAX_DETALHE = 200


async def ids_em_espera(
    sessao: AsyncSession,
    ids: Iterable[int],
    tarefa: TarefaDeVerificacao,
    agora: datetime | None = None,
) -> frozenset[int]:
    """`anime_id`s dentre `ids` cuja próxima tentativa de `tarefa` ainda está no
    futuro. Uma query; `ids` vazio não consulta."""
    lista_ids = list(ids)
    if not lista_ids:
        return frozenset()
    resultado = await sessao.execute(
        select(VerificacaoDeAnime.anime_id).where(
            VerificacaoDeAnime.anime_id.in_(lista_ids),
            VerificacaoDeAnime.tarefa == tarefa,
            VerificacaoDeAnime.proxima_em > (agora or datetime.now(UTC)),
        )
    )
    return frozenset(resultado.scalars())


async def tentativas_desde(
    sessao: AsyncSession, tarefa: TarefaDeVerificacao, desde: datetime
) -> int:
    """Quantos animes tiveram uma tentativa de `tarefa` a partir de `desde`. Guarda
    só a ÚLTIMA tentativa de cada anime, então é um limite inferior do volume real
    (um anime que falhou duas vezes na janela conta uma) — suficiente para o teto
    por hora, porque o backoff espaça as tentativas do mesmo anime."""
    resultado = await sessao.execute(
        select(func.count()).where(
            VerificacaoDeAnime.tarefa == tarefa, VerificacaoDeAnime.ultima_tentativa_em >= desde
        )
    )
    return resultado.scalar_one()


async def registrar_resultado(
    sessionmaker: _SessionMaker,
    anime_id: int,
    tarefa: TarefaDeVerificacao,
    resultado: ResultadoDeVerificacao,
    *,
    detalhe: str | None = None,
    dominio: str | None = None,
    proxima_apos_sucesso: datetime | None = None,
    agora: datetime | None = None,
) -> None:
    """Grava o desfecho de uma tentativa e agenda a próxima
    (`core.ciclo_de_vida.proxima_tentativa`; num `OK`, `proxima_apos_sucesso` —
    cadência ancorada no episódio, `proxima_sondagem_apos_sucesso` — sobrepõe o
    intervalo padrão). Sucesso zera as falhas seguidas;
    `SITE_INDISPONIVEL` as preserva (o culpado é o site). Anime que sumiu entre a
    sondagem e a escrita é no-op, como em `atualizar_contagem_na_fonte`.
    `dominio`: site que motivou a falha (só para `PRECISA_SESSAO`)."""
    agora = agora or datetime.now(UTC)
    async with sessionmaker() as sessao:
        linha = await sessao.get(VerificacaoDeAnime, (anime_id, tarefa))
        falhas_anteriores = linha.falhas_consecutivas if linha else 0
        if resultado is ResultadoDeVerificacao.OK:
            falhas = 0
        elif resultado in CONTA_COMO_FALHA_DO_ANIME:
            falhas = falhas_anteriores + 1
        else:
            falhas = falhas_anteriores
        campos = {
            "proxima_em": (
                proxima_apos_sucesso
                if resultado is ResultadoDeVerificacao.OK and proxima_apos_sucesso
                else proxima_tentativa(resultado, falhas, agora)
            ),
            "ultima_tentativa_em": agora,
            "ultimo_resultado": resultado,
            "falhas_consecutivas": falhas,
            "detalhe": detalhe[:_MAX_DETALHE] if detalhe else None,
            "dominio": dominio,
        }
        if resultado is ResultadoDeVerificacao.OK:
            campos["ultimo_sucesso_em"] = agora
        if linha is None:
            sessao.add(VerificacaoDeAnime(anime_id=anime_id, tarefa=tarefa, **campos))
        else:
            for nome, valor in campos.items():
                setattr(linha, nome, valor)
        try:
            await sessao.commit()
        except IntegrityError:
            await sessao.rollback()  # FK: o anime foi removido no meio da tentativa
            return
    logger.info(
        "verificacao anime_id=%s tarefa=%s resultado=%s falhas=%s proxima_em=%s dominio=%s",
        anime_id,
        tarefa.value,
        resultado.value,
        falhas,
        campos["proxima_em"].isoformat(),
        dominio,
    )


async def dominios_aguardando_sessao(
    sessao: AsyncSession, tarefa: TarefaDeVerificacao
) -> list[tuple[str, int]]:
    """`(domínio, um anime_id que falhou nele)` para cada site que rejeitou a
    sessão (`PRECISA_SESSAO`), o que tem mais animes esperando primeiro. O anime
    serve de amostra para o zelador renovar a sessão listando os episódios dele."""
    resultado = await sessao.execute(
        select(VerificacaoDeAnime.dominio, func.min(VerificacaoDeAnime.anime_id))
        .where(
            VerificacaoDeAnime.tarefa == tarefa,
            VerificacaoDeAnime.ultimo_resultado == ResultadoDeVerificacao.PRECISA_SESSAO,
            VerificacaoDeAnime.dominio.is_not(None),
        )
        .group_by(VerificacaoDeAnime.dominio)
        .order_by(func.count().desc(), VerificacaoDeAnime.dominio)
    )
    return [(dominio, anime_id) for dominio, anime_id in resultado.all()]


async def liberar_espera_por_sessao(
    sessionmaker: _SessionMaker,
    tarefa: TarefaDeVerificacao,
    dominio: str,
    agora: datetime | None = None,
) -> int:
    """Tira da espera os animes parados em `PRECISA_SESSAO` por `dominio`: a
    próxima tentativa passa a ser já — a sessão acabou de ser renovada e vale por
    pouco (TTL de 30 min), então esperar as 3h do backoff a desperdiçaria.
    Devolve quantos foram liberados."""
    agora = agora or datetime.now(UTC)
    async with sessionmaker() as sessao:
        resultado = await sessao.execute(
            update(VerificacaoDeAnime)
            .where(
                VerificacaoDeAnime.tarefa == tarefa,
                VerificacaoDeAnime.ultimo_resultado == ResultadoDeVerificacao.PRECISA_SESSAO,
                VerificacaoDeAnime.dominio == dominio,
                VerificacaoDeAnime.proxima_em > agora,
            )
            .values(proxima_em=agora)
        )
        await sessao.commit()
        return resultado.rowcount

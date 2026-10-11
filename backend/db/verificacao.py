"""Persistência do estado de verificação (`VerificacaoDeAnime`) — a política de
backoff é de `core/ciclo_de_vida.py`; aqui só leitura e gravação."""

from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.ciclo_de_vida import CONTA_COMO_FALHA_DO_ANIME, proxima_tentativa
from core.enums import ResultadoDeVerificacao, TarefaDeVerificacao
from models.verificacao_de_anime import VerificacaoDeAnime

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
    agora: datetime | None = None,
) -> None:
    """Grava o desfecho de uma tentativa e agenda a próxima
    (`core.ciclo_de_vida.proxima_tentativa`). Sucesso zera as falhas seguidas;
    `SITE_INDISPONIVEL` as preserva (o culpado é o site). Anime que sumiu entre a
    sondagem e a escrita é no-op, como em `atualizar_contagem_na_fonte`."""
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
            "proxima_em": proxima_tentativa(resultado, falhas, agora),
            "ultima_tentativa_em": agora,
            "ultimo_resultado": resultado,
            "falhas_consecutivas": falhas,
            "detalhe": detalhe[:_MAX_DETALHE] if detalhe else None,
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

"""Estado persistido de verificação (`db/verificacao.py`): backoff entre
tentativas, contagem de falhas seguidas e consulta de quem está em espera."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.enums import ResultadoDeVerificacao as R
from core.enums import TarefaDeVerificacao
from db import verificacao
from models.anime import Anime
from models.verificacao_de_anime import VerificacaoDeAnime

_SessionMaker = async_sessionmaker[AsyncSession]
_FONTE = TarefaDeVerificacao.FONTE
_T0 = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)


async def _criar_anime(sessionmaker: _SessionMaker, slug: str = "a") -> int:
    async with sessionmaker() as sessao:
        anime = Anime(titulo=slug, slug=slug)
        sessao.add(anime)
        await sessao.commit()
        return anime.id


async def _linha(sessionmaker: _SessionMaker, anime_id: int) -> VerificacaoDeAnime:
    async with sessionmaker() as sessao:
        linha = await sessao.get(VerificacaoDeAnime, (anime_id, _FONTE))
        assert linha is not None
        return linha


async def test_falhas_seguidas_crescem_e_sucesso_zera(sessionmaker_api: _SessionMaker):
    anime_id = await _criar_anime(sessionmaker_api)

    for n in (1, 2):
        await verificacao.registrar_resultado(
            sessionmaker_api, anime_id, _FONTE, R.NAO_ENCONTRADO, agora=_T0
        )
        assert (await _linha(sessionmaker_api, anime_id)).falhas_consecutivas == n
    assert (await _linha(sessionmaker_api, anime_id)).proxima_em == _T0 + timedelta(hours=12)

    await verificacao.registrar_resultado(sessionmaker_api, anime_id, _FONTE, R.OK, agora=_T0)
    linha = await _linha(sessionmaker_api, anime_id)
    assert linha.falhas_consecutivas == 0
    assert linha.ultimo_sucesso_em == _T0
    assert linha.proxima_em == _T0 + timedelta(hours=6)


async def test_site_indisponivel_nao_conta_contra_o_anime(sessionmaker_api: _SessionMaker):
    anime_id = await _criar_anime(sessionmaker_api)
    await verificacao.registrar_resultado(sessionmaker_api, anime_id, _FONTE, R.ERRO, agora=_T0)

    await verificacao.registrar_resultado(
        sessionmaker_api, anime_id, _FONTE, R.SITE_INDISPONIVEL, agora=_T0
    )

    linha = await _linha(sessionmaker_api, anime_id)
    assert linha.falhas_consecutivas == 1
    assert linha.ultimo_resultado is R.SITE_INDISPONIVEL


async def test_detalhe_e_truncado(sessionmaker_api: _SessionMaker):
    anime_id = await _criar_anime(sessionmaker_api)
    await verificacao.registrar_resultado(
        sessionmaker_api, anime_id, _FONTE, R.ERRO, detalhe="x" * 500, agora=_T0
    )
    assert len((await _linha(sessionmaker_api, anime_id)).detalhe) == 200


async def test_ids_em_espera_so_devolve_quem_ainda_nao_venceu(sessionmaker_api: _SessionMaker):
    preso = await _criar_anime(sessionmaker_api, "preso")
    vencido = await _criar_anime(sessionmaker_api, "vencido")
    limpo = await _criar_anime(sessionmaker_api, "limpo")
    await verificacao.registrar_resultado(
        sessionmaker_api, preso, _FONTE, R.PRECISA_SESSAO, agora=_T0
    )
    await verificacao.registrar_resultado(
        sessionmaker_api, vencido, _FONTE, R.PRECISA_SESSAO, agora=_T0 - timedelta(days=1)
    )

    async with sessionmaker_api() as sessao:
        em_espera = await verificacao.ids_em_espera(
            sessao, [preso, vencido, limpo], _FONTE, agora=_T0 + timedelta(hours=1)
        )
        vazio = await verificacao.ids_em_espera(sessao, [], _FONTE)

    assert em_espera == {preso}
    assert vazio == frozenset()


async def test_anime_removido_no_meio_da_tentativa_e_no_op(sessionmaker_api: _SessionMaker):
    await verificacao.registrar_resultado(sessionmaker_api, 9999, _FONTE, R.OK, agora=_T0)

    async with sessionmaker_api() as sessao:
        assert await sessao.get(VerificacaoDeAnime, (9999, _FONTE)) is None


@pytest.mark.parametrize("resultado", list(R))
async def test_todo_resultado_e_gravavel(sessionmaker_api: _SessionMaker, resultado: R):
    anime_id = await _criar_anime(sessionmaker_api)
    await verificacao.registrar_resultado(sessionmaker_api, anime_id, _FONTE, resultado, agora=_T0)
    assert (await _linha(sessionmaker_api, anime_id)).ultimo_resultado is resultado


async def test_tentativas_desde_conta_so_a_janela_e_a_tarefa(sessionmaker_api: _SessionMaker):
    recente = await _criar_anime(sessionmaker_api, "recente")
    antigo = await _criar_anime(sessionmaker_api, "antigo")
    await verificacao.registrar_resultado(
        sessionmaker_api, recente, _FONTE, R.OK, agora=_T0 - timedelta(minutes=5)
    )
    await verificacao.registrar_resultado(
        sessionmaker_api, antigo, _FONTE, R.ERRO, agora=_T0 - timedelta(hours=3)
    )

    async with sessionmaker_api() as sessao:
        total = await verificacao.tentativas_desde(sessao, _FONTE, _T0 - timedelta(hours=1))

    assert total == 1

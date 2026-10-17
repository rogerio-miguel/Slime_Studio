"""Uma passada do zelador: respeita o teto de sondagens por hora e agenda o mesmo
que a carona da Galeria."""

import asyncio
import contextlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.main import criar_app
from api.servicos import aquecimento, sondagem, zelador
from core.config import Config
from core.enums import ResultadoDeVerificacao, StatusLancamento, TarefaDeVerificacao
from db import verificacao
from models.anime import Anime

_SessionMaker = async_sessionmaker[AsyncSession]
_AGORA = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)


@pytest.fixture
def aquecimentos(monkeypatch: pytest.MonkeyPatch) -> list[int | None]:
    """Registra o `max_sondagens` de cada aquecimento disparado, sem rodar nada."""
    chamadas: list[int | None] = []

    async def _fake(sessionmaker, sessao, animes, grupos, com_episodios, *, max_sondagens=None):
        chamadas.append(max_sondagens)

    monkeypatch.setattr(aquecimento, "aquecer_catalogo", _fake)
    return chamadas


async def _criar_anime(sessionmaker: _SessionMaker, slug: str) -> int:
    async with sessionmaker() as sessao:
        anime = Anime(
            titulo=slug, slug=slug, status_lancamento=StatusLancamento.EM_LANCAMENTO
        )
        sessao.add(anime)
        await sessao.commit()
        return anime.id


async def test_passada_aquece_o_catalogo_com_o_orcamento_cheio(
    sessionmaker_api: _SessionMaker, aquecimentos
):
    await _criar_anime(sessionmaker_api, "a")
    z = zelador.Zelador(sessionmaker_api)

    await z.executar_passada(_AGORA)

    assert aquecimentos == [zelador.TETO_DE_SONDAGENS_POR_HORA]


async def test_tentativas_da_ultima_hora_descontam_do_orcamento(
    sessionmaker_api: _SessionMaker, aquecimentos
):
    anime_id = await _criar_anime(sessionmaker_api, "a")
    await verificacao.registrar_resultado(
        sessionmaker_api,
        anime_id,
        TarefaDeVerificacao.FONTE,
        ResultadoDeVerificacao.OK,
        agora=_AGORA - timedelta(minutes=10),
    )
    z = zelador.Zelador(sessionmaker_api)

    await z.executar_passada(_AGORA)

    assert aquecimentos == [zelador.TETO_DE_SONDAGENS_POR_HORA - 1]


async def test_tentativa_de_mais_de_uma_hora_atras_nao_conta(
    sessionmaker_api: _SessionMaker, aquecimentos
):
    anime_id = await _criar_anime(sessionmaker_api, "a")
    await verificacao.registrar_resultado(
        sessionmaker_api,
        anime_id,
        TarefaDeVerificacao.FONTE,
        ResultadoDeVerificacao.OK,
        agora=_AGORA - timedelta(hours=2),
    )
    z = zelador.Zelador(sessionmaker_api)

    await z.executar_passada(_AGORA)

    assert aquecimentos == [zelador.TETO_DE_SONDAGENS_POR_HORA]


async def test_orcamento_esgotado_nao_aquece(
    sessionmaker_api: _SessionMaker, aquecimentos, monkeypatch: pytest.MonkeyPatch
):
    await _criar_anime(sessionmaker_api, "a")
    monkeypatch.setattr(sondagem, "quantidade_em_voo", lambda: zelador.TETO_DE_SONDAGENS_POR_HORA)
    z = zelador.Zelador(sessionmaker_api)

    await z.executar_passada(_AGORA)

    assert aquecimentos == []


async def test_aquecer_catalogo_repassa_o_teto_de_sondagens(
    sessionmaker_api: _SessionMaker, monkeypatch: pytest.MonkeyPatch
):
    vistos: list[int] = []
    monkeypatch.setattr(
        sondagem,
        "agendar_sondagens",
        lambda *args, max_sondagens=sondagem._MAX_SONDAGENS_POR_LOTE, **kw: vistos.append(
            max_sondagens
        ),
    )
    monkeypatch.setattr(
        "api.servicos.descoberta.agendar_refreshs_do_catalogo", lambda *args: None
    )
    async with sessionmaker_api() as sessao:
        await aquecimento.aquecer_catalogo(sessionmaker_api, sessao, [], {}, set())
        await aquecimento.aquecer_catalogo(
            sessionmaker_api, sessao, [], {}, set(), max_sondagens=3
        )

    assert vistos == [sondagem._MAX_SONDAGENS_POR_LOTE, 3]


async def test_rodar_executa_passadas_e_sobrevive_a_uma_que_falha(
    sessionmaker_api: _SessionMaker, monkeypatch: pytest.MonkeyPatch
):
    z = zelador.Zelador(sessionmaker_api, intervalo_s=0, espera_inicial_s=0)
    chamadas: list[int] = []

    async def _passada(agora=None):
        chamadas.append(len(chamadas))
        if len(chamadas) == 1:
            raise RuntimeError("falha de banco")

    monkeypatch.setattr(z, "executar_passada", _passada)

    tarefa = asyncio.create_task(z.rodar())
    while len(chamadas) < 3:
        await asyncio.sleep(0)
    tarefa.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await tarefa

    assert len(chamadas) >= 3


async def test_lifespan_sobe_o_zelador_so_quando_ativo(
    config_api: Config, monkeypatch: pytest.MonkeyPatch
):
    iniciados: list[bool] = []

    async def _rodar(self):
        iniciados.append(True)
        await asyncio.sleep(3600)

    monkeypatch.setattr(zelador.Zelador, "rodar", _rodar)

    for ativo in (False, True):
        app = criar_app(replace(config_api, zelador_ativo=ativo))
        async with app.router.lifespan_context(app):
            await asyncio.sleep(0)

    assert iniciados == [True]


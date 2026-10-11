"""Uma passada do zelador: respeita o interruptor do arquivo de horários e o teto
de sondagens por hora, e agenda o mesmo que a carona da Galeria."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.servicos import aquecimento, sondagem, zelador
from api.servicos.horarios import LeitorDeHorarios
from core.enums import ResultadoDeVerificacao, StatusLancamento, TarefaDeVerificacao
from db import verificacao
from models.anime import Anime

_SessionMaker = async_sessionmaker[AsyncSession]
_AGORA = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)


def _leitor(tmp_path: Path, texto: str) -> LeitorDeHorarios:
    (tmp_path / "horarios.toml").write_text(texto, encoding="utf-8")
    return LeitorDeHorarios(tmp_path)


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
    sessionmaker_api: _SessionMaker, tmp_path: Path, aquecimentos
):
    await _criar_anime(sessionmaker_api, "a")
    z = zelador.Zelador(sessionmaker_api, _leitor(tmp_path, "zelador_ativo = true"))

    await z.executar_passada(_AGORA)

    assert aquecimentos == [zelador.TETO_DE_SONDAGENS_POR_HORA]


async def test_zelador_desligado_no_arquivo_nao_faz_nada(
    sessionmaker_api: _SessionMaker, tmp_path: Path, aquecimentos
):
    z = zelador.Zelador(sessionmaker_api, _leitor(tmp_path, "zelador_ativo = false"))

    await z.executar_passada(_AGORA)

    assert aquecimentos == []


async def test_desligar_o_arquivo_com_a_api_no_ar_vale_na_proxima_passada(
    sessionmaker_api: _SessionMaker, tmp_path: Path, aquecimentos
):
    import os

    leitor = _leitor(tmp_path, "zelador_ativo = true")
    z = zelador.Zelador(sessionmaker_api, leitor)
    await z.executar_passada(_AGORA)
    arquivo = tmp_path / "horarios.toml"
    arquivo.write_text("zelador_ativo = false", encoding="utf-8")
    os.utime(arquivo, (4_000_000_000, 4_000_000_000))

    await z.executar_passada(_AGORA)

    assert len(aquecimentos) == 1


async def test_tentativas_da_ultima_hora_descontam_do_orcamento(
    sessionmaker_api: _SessionMaker, tmp_path: Path, aquecimentos
):
    anime_id = await _criar_anime(sessionmaker_api, "a")
    await verificacao.registrar_resultado(
        sessionmaker_api,
        anime_id,
        TarefaDeVerificacao.FONTE,
        ResultadoDeVerificacao.OK,
        agora=_AGORA - timedelta(minutes=10),
    )
    z = zelador.Zelador(sessionmaker_api, _leitor(tmp_path, "zelador_ativo = true"))

    await z.executar_passada(_AGORA)

    assert aquecimentos == [zelador.TETO_DE_SONDAGENS_POR_HORA - 1]


async def test_tentativa_de_mais_de_uma_hora_atras_nao_conta(
    sessionmaker_api: _SessionMaker, tmp_path: Path, aquecimentos
):
    anime_id = await _criar_anime(sessionmaker_api, "a")
    await verificacao.registrar_resultado(
        sessionmaker_api,
        anime_id,
        TarefaDeVerificacao.FONTE,
        ResultadoDeVerificacao.OK,
        agora=_AGORA - timedelta(hours=2),
    )
    z = zelador.Zelador(sessionmaker_api, _leitor(tmp_path, "zelador_ativo = true"))

    await z.executar_passada(_AGORA)

    assert aquecimentos == [zelador.TETO_DE_SONDAGENS_POR_HORA]


async def test_orcamento_esgotado_nao_aquece(
    sessionmaker_api: _SessionMaker, tmp_path: Path, aquecimentos, monkeypatch: pytest.MonkeyPatch
):
    await _criar_anime(sessionmaker_api, "a")
    monkeypatch.setattr(sondagem, "quantidade_em_voo", lambda: zelador.TETO_DE_SONDAGENS_POR_HORA)
    z = zelador.Zelador(sessionmaker_api, _leitor(tmp_path, "zelador_ativo = true"))

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

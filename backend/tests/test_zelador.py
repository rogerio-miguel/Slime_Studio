"""Uma passada do zelador: respeita o interruptor do arquivo de horários e o teto
de sondagens por hora, e agenda o mesmo que a carona da Galeria."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.servicos import aquecimento, sondagem, zelador
from api.servicos.horarios import LeitorDeHorarios
from core.enums import (
    ResultadoDeVerificacao,
    StatusLancamento,
    TarefaDeVerificacao,
    VersaoDeFonte,
)
from core.erros import SessaoRejeitada
from db import aberturas_de_navegador, verificacao
from extractors import circuit_breaker, sessao_cache
from models.anime import Anime
from models.fonte_anime import FonteAnime
from models.verificacao_de_anime import VerificacaoDeAnime

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


# --- renovação de sessão com navegador ---

_COM_JANELA = (
    'janelas_do_navegador = ["12:00-13:30"]\nteto_diario_de_aberturas = 2\nzelador_ativo = true'
)
_DENTRO_DA_JANELA = datetime(2026, 10, 11, 12, 30, tzinfo=UTC)
_FORA_DA_JANELA = datetime(2026, 10, 11, 15, 0, tzinfo=UTC)
_SITE = "bloqueado.io"


@pytest.fixture
def navegador(monkeypatch: pytest.MonkeyPatch):
    """Substitui a listagem que abriria o navegador; `abertas` registra as chamadas."""
    estado = type("Estado", (), {"abertas": [], "falhar": False})()

    async def _listar(sessionmaker, dominio, identificador, temporada):
        estado.abertas.append((dominio, identificador))
        if estado.falhar:
            raise SessaoRejeitada("cloudflare", dominio=dominio)
        return []

    monkeypatch.setattr(zelador, "listar_episodios_em", _listar)
    return estado


async def _anime_esperando_sessao(sessionmaker: _SessionMaker, quando: datetime) -> int:
    anime_id = await _criar_anime(sessionmaker, "esperando")
    async with sessionmaker() as sessao:
        sessao.add(
            FonteAnime(
                anime_id=anime_id,
                site_dominio=_SITE,
                versao=VersaoDeFonte.LEGENDADO,
                identificador_no_site="id-no-site",
                prioridade=0,
            )
        )
        await sessao.commit()
    await verificacao.registrar_resultado(
        sessionmaker,
        anime_id,
        TarefaDeVerificacao.FONTE,
        ResultadoDeVerificacao.PRECISA_SESSAO,
        dominio=_SITE,
        agora=quando,
    )
    return anime_id


async def _proxima_em(sessionmaker: _SessionMaker, anime_id: int) -> datetime:
    async with sessionmaker() as sessao:
        linha = await sessao.get(VerificacaoDeAnime, (anime_id, TarefaDeVerificacao.FONTE))
        return linha.proxima_em


async def _aberturas(sessionmaker: _SessionMaker) -> int:
    async with sessionmaker() as sessao:
        return await aberturas_de_navegador.aberturas_desde(
            sessao, datetime(2000, 1, 1, tzinfo=UTC)
        )


async def test_dentro_da_janela_abre_o_navegador_registra_e_libera_os_animes(
    sessionmaker_api: _SessionMaker, tmp_path: Path, aquecimentos, navegador
):
    anime_id = await _anime_esperando_sessao(sessionmaker_api, _DENTRO_DA_JANELA)
    assert await _proxima_em(sessionmaker_api, anime_id) > _DENTRO_DA_JANELA
    z = zelador.Zelador(sessionmaker_api, _leitor(tmp_path, _COM_JANELA))

    await z.executar_passada(_DENTRO_DA_JANELA)

    assert navegador.abertas == [(_SITE, "id-no-site")]
    assert await _aberturas(sessionmaker_api) == 1
    assert await _proxima_em(sessionmaker_api, anime_id) <= _DENTRO_DA_JANELA
    assert aquecimentos  # a sondagem dos liberados roda na mesma passada


async def test_fora_da_janela_nao_abre_o_navegador(
    sessionmaker_api: _SessionMaker, tmp_path: Path, aquecimentos, navegador
):
    anime_id = await _anime_esperando_sessao(sessionmaker_api, _FORA_DA_JANELA)
    z = zelador.Zelador(sessionmaker_api, _leitor(tmp_path, _COM_JANELA))

    await z.executar_passada(_FORA_DA_JANELA)

    assert navegador.abertas == []
    assert await _aberturas(sessionmaker_api) == 0
    assert await _proxima_em(sessionmaker_api, anime_id) > _FORA_DA_JANELA


async def test_sem_janelas_configuradas_o_navegador_nunca_abre(
    sessionmaker_api: _SessionMaker, tmp_path: Path, aquecimentos, navegador
):
    await _anime_esperando_sessao(sessionmaker_api, _DENTRO_DA_JANELA)
    z = zelador.Zelador(sessionmaker_api, _leitor(tmp_path, "zelador_ativo = true"))

    await z.executar_passada(_DENTRO_DA_JANELA)

    assert navegador.abertas == []


async def test_teto_diario_de_aberturas_e_respeitado(
    sessionmaker_api: _SessionMaker, tmp_path: Path, aquecimentos, navegador
):
    await _anime_esperando_sessao(sessionmaker_api, _DENTRO_DA_JANELA)
    for _ in range(2):  # teto = 2, já usado hoje
        await aberturas_de_navegador.registrar_abertura(
            sessionmaker_api, "outro.io", _DENTRO_DA_JANELA - timedelta(hours=3)
        )
    z = zelador.Zelador(sessionmaker_api, _leitor(tmp_path, _COM_JANELA))

    await z.executar_passada(_DENTRO_DA_JANELA)

    assert navegador.abertas == []


async def test_aberturas_de_ontem_nao_contam_no_teto_de_hoje(
    sessionmaker_api: _SessionMaker, tmp_path: Path, aquecimentos, navegador
):
    await _anime_esperando_sessao(sessionmaker_api, _DENTRO_DA_JANELA)
    for _ in range(2):
        await aberturas_de_navegador.registrar_abertura(
            sessionmaker_api, "outro.io", _DENTRO_DA_JANELA - timedelta(days=1)
        )
    z = zelador.Zelador(sessionmaker_api, _leitor(tmp_path, _COM_JANELA))

    await z.executar_passada(_DENTRO_DA_JANELA)

    assert len(navegador.abertas) == 1


async def test_sessao_ja_valida_libera_sem_abrir_o_navegador(
    sessionmaker_api: _SessionMaker, tmp_path: Path, aquecimentos, navegador
):
    anime_id = await _anime_esperando_sessao(sessionmaker_api, _DENTRO_DA_JANELA)
    await sessao_cache.salvar(sessionmaker_api, _SITE, {"cf_clearance": "x"}, "UA", ttl_s=3600)
    z = zelador.Zelador(sessionmaker_api, _leitor(tmp_path, _COM_JANELA))

    await z.executar_passada(_DENTRO_DA_JANELA)

    assert navegador.abertas == []
    assert await _aberturas(sessionmaker_api) == 0
    assert await _proxima_em(sessionmaker_api, anime_id) <= _DENTRO_DA_JANELA


async def test_renovacao_que_falha_conta_no_teto_e_nao_libera(
    sessionmaker_api: _SessionMaker, tmp_path: Path, aquecimentos, navegador
):
    navegador.falhar = True
    anime_id = await _anime_esperando_sessao(sessionmaker_api, _DENTRO_DA_JANELA)
    z = zelador.Zelador(sessionmaker_api, _leitor(tmp_path, _COM_JANELA))

    await z.executar_passada(_DENTRO_DA_JANELA)

    assert await _aberturas(sessionmaker_api) == 1
    assert await _proxima_em(sessionmaker_api, anime_id) > _DENTRO_DA_JANELA


async def test_site_em_cooldown_nao_abre_o_navegador(
    sessionmaker_api: _SessionMaker, tmp_path: Path, aquecimentos, navegador
):
    await _anime_esperando_sessao(sessionmaker_api, _DENTRO_DA_JANELA)
    for _ in range(4):
        await circuit_breaker.registrar_falha(sessionmaker_api, _SITE, RuntimeError("x"))
    z = zelador.Zelador(sessionmaker_api, _leitor(tmp_path, _COM_JANELA))

    await z.executar_passada(_DENTRO_DA_JANELA)

    assert navegador.abertas == []


async def test_sondagem_bloqueada_registra_o_dominio_que_pede_sessao(
    sessionmaker_api: _SessionMaker, monkeypatch: pytest.MonkeyPatch
):
    """Ponta a ponta: a falha de sessão em segundo plano carrega o domínio até o
    registro, que é o que o zelador usa para saber qual site renovar."""
    from extractors import resiliencia
    from extractors.base import ExtratorDeSite

    class _Site(ExtratorDeSite):
        dominio = _SITE
        exige_navegador = False

        def buscar(self, cliente, titulo):
            return []

        def listar_episodios(self, cliente, identificador, temporada=None):
            raise SessaoRejeitada("desafio Cloudflare")  # sem domínio, como no cliente real

        def resolver_midia(self, cliente, url_episodio):
            raise NotImplementedError

    async def _resolver_e_listar(sessionmaker, anime, versao, *, resolver_canonico, **_):
        await resiliencia.chamar(
            sessionmaker, _Site(), lambda c: _Site().listar_episodios(c, "x")
        )

    monkeypatch.setattr("api.servicos.sondagem.resolver_e_listar", _resolver_e_listar)
    anime_id = await _criar_anime(sessionmaker_api, "bloqueado")
    async with sessionmaker_api() as sessao:
        anime = await sessao.get(Anime, anime_id)

    await sondagem._sondar_e_persistir(
        sessionmaker_api, anime.id, sondagem.VersaoEpisodio.LEGENDADO
    )

    async with sessionmaker_api() as sessao:
        aguardando = await verificacao.dominios_aguardando_sessao(
            sessao, TarefaDeVerificacao.FONTE
        )
    assert aguardando == [(_SITE, anime_id)]


# --- laço e lifespan ---


async def test_laco_espera_antes_da_primeira_passada_e_repete(
    sessionmaker_api: _SessionMaker, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    import asyncio

    passadas: list[float] = []
    z = zelador.Zelador(
        sessionmaker_api,
        _leitor(tmp_path, "zelador_ativo = true"),
        intervalo_s=0.05,
        espera_inicial_s=0.2,
    )
    loop = asyncio.get_running_loop()
    inicio = loop.time()

    async def _passada(agora=None):
        passadas.append(loop.time() - inicio)

    monkeypatch.setattr(z, "executar_passada", _passada)
    tarefa = asyncio.create_task(z.rodar())
    await asyncio.sleep(0.45)
    tarefa.cancel()
    with pytest.raises(asyncio.CancelledError):
        await tarefa

    assert passadas[0] >= 0.2  # esperou a partida assentar
    assert len(passadas) >= 3  # e seguiu repetindo


async def test_passada_que_falha_nao_derruba_o_laco(
    sessionmaker_api: _SessionMaker, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog
):
    import asyncio

    chamadas: list[int] = []
    z = zelador.Zelador(
        sessionmaker_api,
        _leitor(tmp_path, "zelador_ativo = true"),
        intervalo_s=0.02,
        espera_inicial_s=0,
    )

    async def _passada(agora=None):
        chamadas.append(1)
        raise RuntimeError("banco fora do ar")

    monkeypatch.setattr(z, "executar_passada", _passada)
    with caplog.at_level("ERROR", logger="api.servicos.zelador"):
        tarefa = asyncio.create_task(z.rodar())
        await asyncio.sleep(0.15)
        tarefa.cancel()
        with pytest.raises(asyncio.CancelledError):
            await tarefa

    assert len(chamadas) >= 2
    assert "passada falhou" in caplog.text


async def test_lifespan_sobe_o_zelador_e_o_cancela_ao_desligar(config_api):
    import asyncio

    from api.main import criar_app

    aplicativo = criar_app(config_api)
    async with aplicativo.router.lifespan_context(aplicativo):
        assert isinstance(aplicativo.state.zelador, zelador.Zelador)
        tarefas = [t for t in asyncio.all_tasks() if t.get_name() == "zelador-de-fontes"]
        assert len(tarefas) == 1 and not tarefas[0].done()

    assert tarefas[0].cancelled()

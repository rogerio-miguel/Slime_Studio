"""Testes de `api/servicos/sondagem.py` — sondagem fire-and-forget da fonte
real (site) de um anime em lançamento para contar episódios disponíveis.

`api.servicos.sondagem.resolver_e_listar` (o nome importado no módulo) é
monkeypatchado em todos os testes — nunca toca extractor/rede real. As `Task`
disparadas por `agendar_sondagens` rodam contra o banco de teste
(`sessionmaker_api`); a drenagem via `gather` sem `return_exceptions` garante
que uma corotina fire-and-forget nunca propaga exceção.
"""

import asyncio
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.servicos import sondagem
from api.servicos.fontes import FonteComEpisodios
from core.enums import (
    ResultadoDeVerificacao,
    StatusLancamento,
    TarefaDeVerificacao,
    VersaoDeFonte,
    VersaoEpisodio,
)
from core.erros import (
    FalhaDeExtracao,
    FonteAmbigua,
    FonteNaoEncontrada,
    SessaoRejeitada,
    SiteEmCooldown,
    VersaoIndisponivelError,
)
from extractors.base import EpisodioRemoto
from models.anime import Anime
from models.fonte_anime import FonteAnime

_SessionMaker = async_sessionmaker[AsyncSession]
_LEG = VersaoEpisodio.LEGENDADO


def _fonte(dominio: str, episodios: list) -> FonteComEpisodios:
    """Retorno de `resolver_e_listar` com o mínimo que a sondagem lê."""
    return FonteComEpisodios(
        dominio=dominio,
        identificador="stub",
        versao_da_fonte=VersaoDeFonte.NAO_DIFERENCIADA,
        episodios=episodios,
    )


# `sondagem._sondagens_em_voo`/`_semaforo_de_sondagem` são isolados por
# `_isola_sondagens_de_fonte` (autouse) em `tests/conftest.py`.


async def _drenar_sondagens() -> None:
    """Aguarda toda `Task` de sondagem em voo terminar. `gather` sem
    `return_exceptions`: se `_sondar_e_persistir` deixasse escapar uma exceção,
    este await a re-levanta e o teste falha."""
    for _ in range(20):
        pendentes = [t for t in sondagem._sondagens_em_voo.values() if not t.done()]
        if not pendentes:
            break
        await asyncio.gather(*pendentes)
    await asyncio.sleep(0)


async def _criar_anime(sessionmaker: _SessionMaker, slug: str, **campos) -> int:
    async with sessionmaker() as sessao:
        anime = Anime(titulo=slug.replace("-", " ").title(), slug=slug, **campos)
        sessao.add(anime)
        await sessao.commit()
        return anime.id


async def _mapear_fonte(
    sessionmaker: _SessionMaker,
    anime_id: int,
    *,
    dominio: str = "site.io",
    versao: VersaoDeFonte = VersaoDeFonte.LEGENDADO,
    resolvido_em: datetime | None = None,
) -> None:
    async with sessionmaker() as sessao:
        sessao.add(
            FonteAnime(
                anime_id=anime_id,
                site_dominio=dominio,
                versao=versao,
                identificador_no_site="id-no-site",
                prioridade=0,
                resolvido_em=resolvido_em or datetime.now(UTC),
            )
        )
        await sessao.commit()


async def _carregar(sessionmaker: _SessionMaker, *anime_ids: int) -> list[Anime]:
    async with sessionmaker() as sessao:
        resultado = await sessao.execute(select(Anime).where(Anime.id.in_(anime_ids)))
        return list(resultado.scalars())


def _ep(rotulo: str, numero: int | None) -> EpisodioRemoto:
    return EpisodioRemoto(rotulo=rotulo, numero=numero, url=f"https://site/{rotulo}")


def _espiar_sondagem(
    monkeypatch: pytest.MonkeyPatch, *, episodios: list[EpisodioRemoto] | None = None
) -> list[tuple[int, VersaoEpisodio]]:
    """Substitui `resolver_e_listar` por um espião que registra
    `(anime.id, versao)` e devolve um resultado fixo."""
    chamadas: list[tuple[int, VersaoEpisodio]] = []

    async def _fake(sessionmaker, anime, versao, *, resolver_canonico):
        chamadas.append((anime.id, versao))
        return _fonte(dominio="site.io", episodios=episodios or [])

    monkeypatch.setattr("api.servicos.sondagem.resolver_e_listar", _fake)
    return chamadas


# --- versao_de_sondagem: tradução de UMA versão ---


@pytest.mark.parametrize(
    ("versao_de_fonte", "esperada"),
    [
        (VersaoDeFonte.LEGENDADO, VersaoEpisodio.LEGENDADO),
        (VersaoDeFonte.DUBLADO, VersaoEpisodio.DUBLADO),
        (VersaoDeFonte.NAO_DIFERENCIADA, VersaoEpisodio.LEGENDADO),
    ],
)
def test_versao_de_sondagem_traduz_cada_versao_de_fonte(
    versao_de_fonte: VersaoDeFonte, esperada: VersaoEpisodio
):
    assert sondagem.versao_de_sondagem(versao_de_fonte) == esperada


def test_versao_de_sondagem_nunca_devolve_desconhecida():
    """`DESCONHECIDA` faria `resolver_fonte_do_anime` levantar `ValueError` —
    `NAO_DIFERENCIADA` tem de virar `LEGENDADO`, nunca isso."""
    assert all(
        sondagem.versao_de_sondagem(vf) is not VersaoEpisodio.DESCONHECIDA
        for vf in VersaoDeFonte
    )


# --- versoes_de_sondagem_por_anime ---


async def test_versoes_escolhe_linha_de_maior_resolvido_em(sessionmaker_api: _SessionMaker):
    """Fonte dublada recente vs. legendada antiga: vence a mais recente
    (`resolvido_em`), não a "de menor prioridade"/mais exata."""
    anime_id = await _criar_anime(sessionmaker_api, "duas-fontes")
    await _mapear_fonte(
        sessionmaker_api,
        anime_id,
        dominio="legendado.io",
        resolvido_em=datetime.now(UTC) - timedelta(days=3),
    )
    await _mapear_fonte(
        sessionmaker_api, anime_id, dominio="dublado.io", versao=VersaoDeFonte.DUBLADO
    )

    async with sessionmaker_api() as sessao:
        versoes = await sondagem.versoes_de_sondagem_por_anime(sessao, [anime_id])

    assert versoes == {anime_id: VersaoEpisodio.DUBLADO}


async def test_versoes_nao_diferenciada_recente_vira_legendado(sessionmaker_api: _SessionMaker):
    anime_id = await _criar_anime(sessionmaker_api, "nao-dif")
    await _mapear_fonte(
        sessionmaker_api,
        anime_id,
        dominio="legendado.io",
        resolvido_em=datetime.now(UTC) - timedelta(days=1),
    )
    await _mapear_fonte(
        sessionmaker_api, anime_id, dominio="naodif.io", versao=VersaoDeFonte.NAO_DIFERENCIADA
    )

    async with sessionmaker_api() as sessao:
        versoes = await sondagem.versoes_de_sondagem_por_anime(sessao, [anime_id])

    assert versoes == {anime_id: VersaoEpisodio.LEGENDADO}
    assert VersaoEpisodio.DESCONHECIDA not in versoes.values()


async def test_versoes_anime_sem_fonte_e_ids_vazio(sessionmaker_api: _SessionMaker):
    anime_id = await _criar_anime(sessionmaker_api, "sem-fonte")

    async with sessionmaker_api() as sessao:
        assert await sondagem.versoes_de_sondagem_por_anime(sessao, [anime_id]) == {}
        assert await sondagem.versoes_de_sondagem_por_anime(sessao, []) == {}


# --- agendar_sondagens: gate ---


async def test_gate_barra_status_finalizado(
    sessionmaker_api: _SessionMaker, monkeypatch: pytest.MonkeyPatch
):
    chamadas = _espiar_sondagem(monkeypatch)
    anime_id = await _criar_anime(
        sessionmaker_api, "finalizado", status_lancamento=StatusLancamento.FINALIZADO
    )
    await _mapear_fonte(sessionmaker_api, anime_id)

    animes = await _carregar(sessionmaker_api, anime_id)
    sondagem.agendar_sondagens(sessionmaker_api, animes, {anime_id: _LEG})
    await _drenar_sondagens()

    assert chamadas == []
    assert sondagem._sondagens_em_voo == {}


async def test_gate_barra_finalizado_incompleto_antigo(
    sessionmaker_api: _SessionMaker, monkeypatch: pytest.MonkeyPatch
):
    chamadas = _espiar_sondagem(monkeypatch)
    anime_id = await _criar_anime(
        sessionmaker_api,
        "finalizado-antigo",
        status_lancamento=StatusLancamento.FINALIZADO,
        total_episodios_anilist=13,
        episodios_na_fonte=12,
        estreia_em=date(2015, 1, 9),
    )
    await _mapear_fonte(sessionmaker_api, anime_id)

    animes = await _carregar(sessionmaker_api, anime_id)
    sondagem.agendar_sondagens(sessionmaker_api, animes, {anime_id: _LEG})
    await _drenar_sondagens()

    assert chamadas == []


async def test_gate_libera_finalizado_incompleto_recente(
    sessionmaker_api: _SessionMaker, monkeypatch: pytest.MonkeyPatch
):
    chamadas = _espiar_sondagem(monkeypatch)
    anime_id = await _criar_anime(
        sessionmaker_api,
        "finalizado-recente",
        status_lancamento=StatusLancamento.FINALIZADO,
        total_episodios_anilist=12,
        episodios_na_fonte=11,
        estreia_em=date.today() - timedelta(weeks=13),
    )
    await _mapear_fonte(sessionmaker_api, anime_id)

    animes = await _carregar(sessionmaker_api, anime_id)
    sondagem.agendar_sondagens(sessionmaker_api, animes, {anime_id: _LEG})
    await _drenar_sondagens()

    assert len(chamadas) == 1


async def test_gate_barra_anime_sem_fonte_mapeada(
    sessionmaker_api: _SessionMaker, monkeypatch: pytest.MonkeyPatch
):
    chamadas = _espiar_sondagem(monkeypatch)
    anime_id = await _criar_anime(
        sessionmaker_api, "sem-mapa", status_lancamento=StatusLancamento.EM_LANCAMENTO
    )

    animes = await _carregar(sessionmaker_api, anime_id)
    sondagem.agendar_sondagens(sessionmaker_api, animes, {})
    await _drenar_sondagens()

    assert chamadas == []


async def test_gate_barra_carimbo_dentro_do_ttl(
    sessionmaker_api: _SessionMaker, monkeypatch: pytest.MonkeyPatch
):
    chamadas = _espiar_sondagem(monkeypatch)
    anime_id = await _criar_anime(
        sessionmaker_api,
        "fresco",
        status_lancamento=StatusLancamento.EM_LANCAMENTO,
        fonte_verificada_em=datetime.now(UTC) - timedelta(hours=1),
    )
    await _mapear_fonte(sessionmaker_api, anime_id)

    animes = await _carregar(sessionmaker_api, anime_id)
    sondagem.agendar_sondagens(sessionmaker_api, animes, {anime_id: _LEG})
    await _drenar_sondagens()

    assert chamadas == []


async def test_gate_barra_anime_ja_em_voo(
    sessionmaker_api: _SessionMaker, monkeypatch: pytest.MonkeyPatch
):
    chamadas = _espiar_sondagem(monkeypatch)
    anime_id = await _criar_anime(
        sessionmaker_api, "em-voo", status_lancamento=StatusLancamento.EM_LANCAMENTO
    )
    await _mapear_fonte(sessionmaker_api, anime_id)

    dummy = asyncio.get_running_loop().create_task(asyncio.Event().wait())
    sondagem._sondagens_em_voo[anime_id] = dummy

    animes = await _carregar(sessionmaker_api, anime_id)
    sondagem.agendar_sondagens(sessionmaker_api, animes, {anime_id: _LEG})
    await asyncio.sleep(0)

    assert chamadas == []
    assert list(sondagem._sondagens_em_voo) == [anime_id]  # só o dummy; fixture o cancela


async def test_gate_barra_status_none_ate_o_status_ser_aquecido(
    sessionmaker_api: _SessionMaker, monkeypatch: pytest.MonkeyPatch
):
    chamadas = _espiar_sondagem(monkeypatch)
    anime_id = await _criar_anime(sessionmaker_api, "status-nulo")  # status_lancamento None
    await _mapear_fonte(sessionmaker_api, anime_id)

    animes = await _carregar(sessionmaker_api, anime_id)
    sondagem.agendar_sondagens(sessionmaker_api, animes, {anime_id: _LEG})
    await _drenar_sondagens()

    assert chamadas == []


# --- agendar_sondagens: teto e dedupe ---


async def test_teto_de_lote_pega_os_8_de_carimbo_mais_antigo(
    sessionmaker_api: _SessionMaker, monkeypatch: pytest.MonkeyPatch
):
    chamadas = _espiar_sondagem(monkeypatch)
    base = datetime(2020, 1, 1, tzinfo=UTC)

    sem_carimbo = [
        await _criar_anime(
            sessionmaker_api,
            f"sem-carimbo-{i}",
            status_lancamento=StatusLancamento.EM_LANCAMENTO,
        )
        for i in range(4)
    ]
    com_carimbo = [
        await _criar_anime(
            sessionmaker_api,
            f"com-carimbo-{i}",
            status_lancamento=StatusLancamento.EM_LANCAMENTO,
            fonte_verificada_em=base + timedelta(days=i),
        )
        for i in range(8)
    ]

    todos = sem_carimbo + com_carimbo
    for aid in todos:
        await _mapear_fonte(sessionmaker_api, aid)
    versoes = {aid: _LEG for aid in todos}

    animes = await _carregar(sessionmaker_api, *todos)
    sondagem.agendar_sondagens(sessionmaker_api, animes, versoes)
    await _drenar_sondagens()

    assert len(chamadas) == 8
    agendados = {aid for aid, _ in chamadas}
    assert agendados == set(sem_carimbo) | set(com_carimbo[:4])


async def test_dedupe_duas_passadas_um_unico_task(
    sessionmaker_api: _SessionMaker, monkeypatch: pytest.MonkeyPatch
):
    chamadas = _espiar_sondagem(monkeypatch)
    anime_id = await _criar_anime(
        sessionmaker_api, "dedupe", status_lancamento=StatusLancamento.EM_LANCAMENTO
    )
    await _mapear_fonte(sessionmaker_api, anime_id)

    animes = await _carregar(sessionmaker_api, anime_id)
    sondagem.agendar_sondagens(sessionmaker_api, animes, {anime_id: _LEG})
    sondagem.agendar_sondagens(sessionmaker_api, animes, {anime_id: _LEG})

    assert len(sondagem._sondagens_em_voo) == 1

    await _drenar_sondagens()
    assert chamadas == [(anime_id, _LEG)]
    assert sondagem._sondagens_em_voo == {}


# --- _sondar_e_persistir: contagem e persistência ---


async def test_contagem_descarta_none_e_deduplica(
    sessionmaker_api: _SessionMaker, monkeypatch: pytest.MonkeyPatch
):
    _espiar_sondagem(
        monkeypatch,
        episodios=[_ep("1", 1), _ep("01", 1), _ep("2", 2), _ep("Especial", None)],
    )
    anime_id = await _criar_anime(
        sessionmaker_api, "contagem", status_lancamento=StatusLancamento.EM_LANCAMENTO
    )
    await _mapear_fonte(sessionmaker_api, anime_id)

    animes = await _carregar(sessionmaker_api, anime_id)
    sondagem.agendar_sondagens(sessionmaker_api, animes, {anime_id: _LEG})
    await _drenar_sondagens()

    async with sessionmaker_api() as sessao:
        assert (await sessao.get(Anime, anime_id)).episodios_na_fonte == 2


async def test_sondagem_bem_sucedida_persiste_as_tres_colunas(
    sessionmaker_api: _SessionMaker, monkeypatch: pytest.MonkeyPatch
):
    async def _fake(sessionmaker, anime, versao, *, resolver_canonico):
        return _fonte(
            dominio="animefire.one", episodios=[_ep("1", 1), _ep("2", 2), _ep("3", 3)]
        )

    monkeypatch.setattr("api.servicos.sondagem.resolver_e_listar", _fake)
    anime_id = await _criar_anime(
        sessionmaker_api, "persiste", status_lancamento=StatusLancamento.EM_LANCAMENTO
    )
    await _mapear_fonte(sessionmaker_api, anime_id, dominio="animefire.one")

    antes = datetime.now(UTC)
    animes = await _carregar(sessionmaker_api, anime_id)
    sondagem.agendar_sondagens(sessionmaker_api, animes, {anime_id: _LEG})
    await _drenar_sondagens()

    async with sessionmaker_api() as sessao:
        anime = await sessao.get(Anime, anime_id)
        assert anime.episodios_na_fonte == 3
        assert anime.fonte_verificada_dominio == "animefire.one"
        assert anime.fonte_verificada_em is not None
        assert anime.fonte_verificada_em >= antes


# --- _sondar_e_persistir: falha não carimba nem propaga ---


@pytest.mark.parametrize(
    "erro",
    [FalhaDeExtracao("site fora do ar"), FonteAmbigua("site.io", [])],
    ids=["falha-de-extracao", "fonte-ambigua"],
)
async def test_sondagem_falha_nao_toca_colunas_nem_propaga(
    sessionmaker_api: _SessionMaker,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    erro: Exception,
):
    async def _fake(sessionmaker, anime, versao, *, resolver_canonico):
        raise erro

    monkeypatch.setattr("api.servicos.sondagem.resolver_e_listar", _fake)
    anime_id = await _criar_anime(
        sessionmaker_api,
        "falha",
        status_lancamento=StatusLancamento.EM_LANCAMENTO,
        episodios_na_fonte=5,
        fonte_verificada_dominio="antigo.io",
    )
    await _mapear_fonte(sessionmaker_api, anime_id)

    with caplog.at_level("WARNING"):
        animes = await _carregar(sessionmaker_api, anime_id)
        sondagem.agendar_sondagens(sessionmaker_api, animes, {anime_id: _LEG})
        await _drenar_sondagens()  # gather sem return_exceptions: re-levantaria se propagasse

    assert "sondagem de fonte falhou" in caplog.text
    async with sessionmaker_api() as sessao:
        anime = await sessao.get(Anime, anime_id)
        assert anime.episodios_na_fonte == 5  # intacto
        assert anime.fonte_verificada_dominio == "antigo.io"
        assert anime.fonte_verificada_em is None


# --- semáforo: scrapes nunca sobrepostos ---


async def test_semaforo_serializa_sondagens(
    sessionmaker_api: _SessionMaker, monkeypatch: pytest.MonkeyPatch
):
    a1 = await _criar_anime(sessionmaker_api, "serial-1")
    a2 = await _criar_anime(sessionmaker_api, "serial-2")

    eventos: list[str] = []
    ativos = 0
    pico = 0

    async def _fake(sessionmaker, anime, versao, *, resolver_canonico):
        nonlocal ativos, pico
        ativos += 1
        pico = max(pico, ativos)
        eventos.append(f"entra-{anime.id}")
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        eventos.append(f"sai-{anime.id}")
        ativos -= 1
        return _fonte(dominio="site.io", episodios=[])

    monkeypatch.setattr("api.servicos.sondagem.resolver_e_listar", _fake)

    await asyncio.gather(
        sondagem._sondar_e_persistir(sessionmaker_api, a1, _LEG),
        sondagem._sondar_e_persistir(sessionmaker_api, a2, _LEG),
    )

    # `pico == 1` já prova serialização (sem semáforo, o 2º entraria antes do 1º
    # sair, levando `ativos` a 2); os índices confirmam cada "sai" colado no seu
    # "entra", sem depender de qual anime rodou primeiro.
    assert pico == 1
    assert len(eventos) == 4
    assert eventos.index(f"sai-{a1}") == eventos.index(f"entra-{a1}") + 1
    assert eventos.index(f"sai-{a2}") == eventos.index(f"entra-{a2}") + 1


# --- backoff persistido (verificacao_de_anime) ---


async def _verificacao_de(sessionmaker: _SessionMaker, anime_id: int):
    from models.verificacao_de_anime import VerificacaoDeAnime

    async with sessionmaker() as sessao:
        return await sessao.get(VerificacaoDeAnime, (anime_id, TarefaDeVerificacao.FONTE))


def _falhar_sondagem(monkeypatch: pytest.MonkeyPatch, excecao: Exception) -> list[int]:
    chamadas: list[int] = []

    async def _fake(sessionmaker, anime, versao, *, resolver_canonico):
        chamadas.append(anime.id)
        raise excecao

    monkeypatch.setattr("api.servicos.sondagem.resolver_e_listar", _fake)
    return chamadas


@pytest.mark.parametrize(
    ("excecao", "esperado"),
    [
        (SessaoRejeitada("cloudflare"), ResultadoDeVerificacao.PRECISA_SESSAO),
        (SiteEmCooldown("em cooldown"), ResultadoDeVerificacao.SITE_INDISPONIVEL),
        (FonteNaoEncontrada("404"), ResultadoDeVerificacao.NAO_ENCONTRADO),
        (VersaoIndisponivelError(VersaoEpisodio.DUBLADO), ResultadoDeVerificacao.NAO_ENCONTRADO),
        (FonteAmbigua("site.io", []), ResultadoDeVerificacao.AMBIGUO),
        (FalhaDeExtracao("genérica"), ResultadoDeVerificacao.ERRO),
        (TimeoutError("lento"), ResultadoDeVerificacao.ERRO),
    ],
)
async def test_falha_de_sondagem_e_registrada_com_o_resultado_certo(
    sessionmaker_api: _SessionMaker,
    monkeypatch: pytest.MonkeyPatch,
    excecao: Exception,
    esperado: ResultadoDeVerificacao,
):
    _falhar_sondagem(monkeypatch, excecao)
    anime_id = await _criar_anime(
        sessionmaker_api, "falha", status_lancamento=StatusLancamento.EM_LANCAMENTO
    )
    await _mapear_fonte(sessionmaker_api, anime_id)

    animes = await _carregar(sessionmaker_api, anime_id)
    sondagem.agendar_sondagens(sessionmaker_api, animes, {anime_id: _LEG})
    await _drenar_sondagens()

    linha = await _verificacao_de(sessionmaker_api, anime_id)
    assert linha.ultimo_resultado is esperado
    assert linha.proxima_em > datetime.now(UTC)


async def test_sucesso_de_sondagem_e_registrado(
    sessionmaker_api: _SessionMaker, monkeypatch: pytest.MonkeyPatch
):
    _espiar_sondagem(monkeypatch)
    anime_id = await _criar_anime(
        sessionmaker_api, "ok", status_lancamento=StatusLancamento.EM_LANCAMENTO
    )
    await _mapear_fonte(sessionmaker_api, anime_id)

    animes = await _carregar(sessionmaker_api, anime_id)
    sondagem.agendar_sondagens(sessionmaker_api, animes, {anime_id: _LEG})
    await _drenar_sondagens()

    linha = await _verificacao_de(sessionmaker_api, anime_id)
    assert linha.ultimo_resultado is ResultadoDeVerificacao.OK
    assert linha.falhas_consecutivas == 0


async def test_anime_que_falhou_nao_e_retentado_dentro_do_backoff(
    sessionmaker_api: _SessionMaker, monkeypatch: pytest.MonkeyPatch
):
    """Caso real (anime 163): Cloudflare rejeita a sessão e a Galeria não pode
    retentar a cada abertura."""
    chamadas = _falhar_sondagem(monkeypatch, SessaoRejeitada("cloudflare"))
    anime_id = await _criar_anime(
        sessionmaker_api, "preso", status_lancamento=StatusLancamento.EM_LANCAMENTO
    )
    await _mapear_fonte(sessionmaker_api, anime_id)
    animes = await _carregar(sessionmaker_api, anime_id)

    sondagem.agendar_sondagens(sessionmaker_api, animes, {anime_id: _LEG})
    await _drenar_sondagens()
    async with sessionmaker_api() as sessao:
        em_espera = await sondagem.ids_em_espera(sessao, [anime_id])
    sondagem.agendar_sondagens(
        sessionmaker_api, animes, {anime_id: _LEG}, em_espera=em_espera
    )
    await _drenar_sondagens()

    assert chamadas == [anime_id]


async def test_anime_em_espera_nao_ocupa_vaga_do_teto_de_lote(
    sessionmaker_api: _SessionMaker, monkeypatch: pytest.MonkeyPatch
):
    chamadas = _espiar_sondagem(monkeypatch)
    presos = [
        await _criar_anime(
            sessionmaker_api,
            f"preso-{i}",
            status_lancamento=StatusLancamento.EM_LANCAMENTO,
            fonte_verificada_em=datetime(2020, 1, 1, tzinfo=UTC),  # os mais antigos: vão primeiro
        )
        for i in range(sondagem._MAX_SONDAGENS_POR_LOTE)
    ]
    livre = await _criar_anime(
        sessionmaker_api, "livre", status_lancamento=StatusLancamento.EM_LANCAMENTO
    )
    for anime_id in [*presos, livre]:
        await _mapear_fonte(sessionmaker_api, anime_id)

    animes = await _carregar(sessionmaker_api, *presos, livre)
    sondagem.agendar_sondagens(
        sessionmaker_api,
        animes,
        {anime_id: _LEG for anime_id in [*presos, livre]},
        em_espera=frozenset(presos),
    )
    await _drenar_sondagens()

    assert [anime_id for anime_id, _ in chamadas] == [livre]

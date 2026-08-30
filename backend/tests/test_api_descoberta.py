"""Testes de `GET /api/animes/em-alta`, `GET /api/animes/{anime_id}` e
`POST /api/admin/animes` (`api/rotas/animes.py` -> `api/servicos/descoberta.py`).

A maioria dos testes de `/em-alta` monkeypatcha
`api.servicos.descoberta.listar_em_alta_com_catalogo` diretamente (mesmo
padrão de `tests/test_api_animes.py` para `api.servicos.fontes`) — nunca bate
na API real do AniList/Kitsu em teste. Os testes marcados "cruzamento real"
monkeypatcham uma camada abaixo (`integrations.servico.listar_em_alta` /
`integrations.servico.buscar_por_titulo`), deixando a lógica de cruzamento de
`api/servicos/descoberta.py` rodar de verdade contra o banco de teste.
"""

import asyncio
import contextlib
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.servicos import descoberta as servico_descoberta
from core.enums import StatusLancamento, VersaoDeFonte
from core.erros import FalhaDeMetadados
from core.texto import slugificar
from integrations.base import AnimeEmAlta, LancamentoDeAnime, MetadadosDeAnime
from models.anime import Anime
from models.fonte_anime import FonteAnime

_SessionMaker = async_sessionmaker[AsyncSession]


async def _criar_anime(sessionmaker: _SessionMaker, titulo: str, slug: str, **campos) -> int:
    async with sessionmaker() as sessao:
        anime = Anime(titulo=titulo, slug=slug, **campos)
        sessao.add(anime)
        await sessao.commit()
        return anime.id


@pytest.fixture(autouse=True)
async def _isola_refreshs_de_lancamento():
    """`descoberta._refreshs_de_lancamento_em_voo` é estado de módulo (dedupe +
    ref forte das `Task` de F4b). Zera antes e cancela/limpa o que sobrar depois,
    para nenhum teste vazar `Task` pendente para o próximo."""
    servico_descoberta._refreshs_de_lancamento_em_voo.clear()
    yield
    pendentes = list(servico_descoberta._refreshs_de_lancamento_em_voo.values())
    for tarefa in pendentes:
        tarefa.cancel()
    for tarefa in pendentes:
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await tarefa
    servico_descoberta._refreshs_de_lancamento_em_voo.clear()


async def _drenar_refreshs_de_lancamento() -> None:
    """Aguarda toda `Task` de refresh lazy de F4b em voo terminar. `gather` sem
    `return_exceptions`: se uma corotina fire-and-forget deixasse escapar uma
    exceção, este await a re-levanta e o teste falha — é a checagem de que
    `_buscar_e_persistir_lancamento` nunca propaga."""
    for _ in range(20):
        pendentes = [
            t for t in servico_descoberta._refreshs_de_lancamento_em_voo.values() if not t.done()
        ]
        if not pendentes:
            break
        await asyncio.gather(*pendentes)
    await asyncio.sleep(0)


async def test_em_alta_propaga_502_se_todos_provedores_falham(
    cliente: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    async def _listar_fake(sessionmaker):
        raise FalhaDeMetadados("todos os provedores de metadados falharam")

    monkeypatch.setattr("api.servicos.descoberta.listar_em_alta_com_catalogo", _listar_fake)

    resposta = await cliente.get("/api/animes/em-alta")

    assert resposta.status_code == 502


async def test_em_alta_cruza_com_anime_existente_no_catalogo_local(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker, monkeypatch: pytest.MonkeyPatch
):
    anime_id = await _criar_anime(sessionmaker_api, "Tensei Shitara Slime Datta Ken", "tensei")

    item = AnimeEmAlta(
        titulo_romaji="Tensei",
        titulo_ingles="That Time I Got Reincarnated as a Slime",
        capa_url="https://img/1.jpg",
        banner_url="https://img/1-banner.jpg",
        anilist_id=1,
    )

    async def _listar_fake(sessionmaker):
        return [(item, anime_id)]

    monkeypatch.setattr("api.servicos.descoberta.listar_em_alta_com_catalogo", _listar_fake)

    resposta = await cliente.get("/api/animes/em-alta")

    assert resposta.status_code == 200
    assert resposta.json() == [
        {
            "titulo_romaji": "Tensei",
            "titulo_ingles": "That Time I Got Reincarnated as a Slime",
            "capa_url": "https://img/1.jpg",
            "banner_url": "https://img/1-banner.jpg",
            "anilist_id": 1,
            "anime_id": anime_id,
        }
    ]


async def test_em_alta_sem_correspondencia_local_devolve_anime_id_none(
    cliente: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    item = AnimeEmAlta(
        titulo_romaji="Ainda Nao Catalogado",
        titulo_ingles=None,
        capa_url=None,
        banner_url=None,
        anilist_id=99,
    )

    async def _listar_fake(sessionmaker):
        return [(item, None)]

    monkeypatch.setattr("api.servicos.descoberta.listar_em_alta_com_catalogo", _listar_fake)

    resposta = await cliente.get("/api/animes/em-alta")

    assert resposta.status_code == 200
    assert resposta.json()[0]["anime_id"] is None


async def test_ordem_de_rotas_em_alta_nao_e_interpretado_como_anime_id(
    cliente: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    async def _listar_fake(sessionmaker):
        return []

    monkeypatch.setattr("api.servicos.descoberta.listar_em_alta_com_catalogo", _listar_fake)

    resposta = await cliente.get("/api/animes/em-alta")

    assert resposta.status_code == 200
    assert resposta.json() == []


async def test_obter_anime_detalhe_caminho_feliz(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker
):
    anime_id = await _criar_anime(sessionmaker_api, "Anime Detalhado", "anime-detalhado")

    resposta = await cliente.get(f"/api/animes/{anime_id}")

    assert resposta.status_code == 200
    assert resposta.json()["id"] == anime_id
    assert resposta.json()["titulo"] == "Anime Detalhado"
    # Sem nenhuma `FonteAnime` mapeada ainda, não há troca de fonte confirmada
    # a refletir.
    assert resposta.json()["versao_confirmada_mais_recente"] is None


async def test_obter_anime_404_para_id_inexistente(cliente: AsyncClient):
    resposta = await cliente.get("/api/animes/999999")

    assert resposta.status_code == 404


async def test_obter_anime_versao_confirmada_mais_recente_reflete_ultima_troca_de_fonte(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker
):
    """`versao_confirmada_mais_recente` segue a linha de `FonteAnime` com maior
    `resolvido_em` — não a de maior prioridade — mesmo sem nenhum episódio
    local capturado ainda nessa versão (troca de fonte via diálogo "Trocar
    fonte" sem download subsequente)."""
    anime_id = await _criar_anime(sessionmaker_api, "Anime Trocado", "anime-trocado")
    async with sessionmaker_api() as sessao:
        sessao.add_all(
            [
                FonteAnime(
                    anime_id=anime_id,
                    site_dominio="site-a.io",
                    versao=VersaoDeFonte.LEGENDADO,
                    identificador_no_site="a",
                    prioridade=0,
                    resolvido_em=datetime.now(UTC) - timedelta(hours=1),
                ),
                FonteAnime(
                    anime_id=anime_id,
                    site_dominio="site-b.io",
                    versao=VersaoDeFonte.DUBLADO,
                    identificador_no_site="b",
                    prioridade=1,
                    resolvido_em=datetime.now(UTC),
                ),
            ]
        )
        await sessao.commit()

    resposta = await cliente.get(f"/api/animes/{anime_id}")

    assert resposta.status_code == 200
    assert resposta.json()["versao_confirmada_mais_recente"] == "dublado"


async def test_obter_anime_versao_confirmada_mais_recente_nao_diferenciada_vira_desconhecida(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker
):
    anime_id = await _criar_anime(sessionmaker_api, "Anime Nao Diferenciado", "anime-nd")
    async with sessionmaker_api() as sessao:
        sessao.add(
            FonteAnime(
                anime_id=anime_id,
                site_dominio="site-a.io",
                versao=VersaoDeFonte.NAO_DIFERENCIADA,
                identificador_no_site="a",
                prioridade=0,
            )
        )
        await sessao.commit()

    resposta = await cliente.get(f"/api/animes/{anime_id}")

    assert resposta.status_code == 200
    assert resposta.json()["versao_confirmada_mais_recente"] == "desconhecida"


# --- cruzamento real (sem mock de `listar_em_alta_com_catalogo`) ---
#
# Os testes acima mockam o serviço de descoberta inteiro; os dois abaixo
# mockam uma camada mais funda (`integrations.servico.listar_em_alta`),
# deixando a lógica de cruzamento por anilist_id/slug de
# `api/servicos/descoberta.py::listar_em_alta_com_catalogo` rodar de verdade
# contra o catálogo local em teste.


async def test_em_alta_cruzamento_real_por_slug_contra_anime_pre_inserido(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker, monkeypatch: pytest.MonkeyPatch
):
    titulo = "Tensei Shitara Slime Datta Ken"
    anime_id = await _criar_anime(sessionmaker_api, titulo, slugificar(titulo))

    item = AnimeEmAlta(
        titulo_romaji=titulo,
        titulo_ingles="That Time I Got Reincarnated as a Slime",
        capa_url="https://img/1.jpg",
        banner_url="https://img/1-banner.jpg",
        anilist_id=None,  # força o cruzamento a cair no fallback de slug
    )

    async def _listar_em_alta_fake():
        return [item]

    monkeypatch.setattr("integrations.servico.listar_em_alta", _listar_em_alta_fake)

    resposta = await cliente.get("/api/animes/em-alta")

    assert resposta.status_code == 200
    assert resposta.json()[0]["anime_id"] == anime_id


async def test_listar_em_alta_com_catalogo_prioriza_anilist_id_sobre_slug(
    sessionmaker_api: _SessionMaker, monkeypatch: pytest.MonkeyPatch
):
    """`anilist_id` bate mas o slug do título romaji do provedor diverge do
    slug local (subtítulo diferente) — o cruzamento deve resolver via
    `anilist_id` mesmo assim, sem depender do slug."""
    anime_id = await _criar_anime(
        sessionmaker_api,
        "Slime - Título Cadastrado Localmente",
        "slime-titulo-cadastrado-localmente",
        anilist_id=555,
    )

    item = AnimeEmAlta(
        titulo_romaji="Tensei Shitara Slime Datta Ken",  # slug não bate com o local
        titulo_ingles=None,
        capa_url=None,
        banner_url=None,
        anilist_id=555,  # mas o anilist_id bate
    )

    async def _listar_em_alta_fake():
        return [item]

    monkeypatch.setattr("integrations.servico.listar_em_alta", _listar_em_alta_fake)

    pares = await servico_descoberta.listar_em_alta_com_catalogo(sessionmaker_api)

    assert pares == [(item, anime_id)]


# --- POST /api/admin/animes: enriquecimento best-effort ---


async def test_criar_anime_sem_metadado_tenta_enriquecer_via_provedor(
    cliente: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    chamadas = []

    async def _buscar_fake(titulo):
        chamadas.append(titulo)
        return MetadadosDeAnime(
            capa_url="https://img/capa.jpg", sinopse="Sinopse.", anilist_id=7, kitsu_id=None
        )

    monkeypatch.setattr("integrations.servico.buscar_por_titulo", _buscar_fake)

    resposta = await cliente.post("/api/admin/animes", json={"titulo": "Slime Enriquecido"})

    assert resposta.status_code == 200
    assert chamadas == ["Slime Enriquecido"]
    assert resposta.json()["capa_path"] == "https://img/capa.jpg"


async def test_criar_anime_com_metadado_persiste_direto_sem_chamar_provedor(
    cliente: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    chamadas = []

    async def _buscar_fake(titulo):
        chamadas.append(titulo)
        return None

    monkeypatch.setattr("integrations.servico.buscar_por_titulo", _buscar_fake)

    resposta = await cliente.post(
        "/api/admin/animes",
        json={
            "titulo": "Slime Com Metadado No Payload",
            "anilist_id": 10,
            "capa_url": "https://img/direto.jpg",
        },
    )

    assert resposta.status_code == 200
    assert chamadas == []
    assert resposta.json()["capa_path"] == "https://img/direto.jpg"


async def test_criar_anime_enriquecimento_falho_nao_bloqueia_criacao(
    cliente: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    async def _buscar_fake(titulo):
        raise FalhaDeMetadados("todos os provedores falharam")

    monkeypatch.setattr("integrations.servico.buscar_por_titulo", _buscar_fake)

    resposta = await cliente.post("/api/admin/animes", json={"titulo": "Slime Sem Sorte"})

    assert resposta.status_code == 200
    assert resposta.json()["capa_path"] is None


# --- F4a: refresh oportunista no cruzamento do feed "em alta" ---
#
# Mockam `integrations.servico.listar_em_alta` (camada abaixo), deixando
# `listar_em_alta_com_catalogo` -> `_refrescar_lancamentos_do_cruzamento` rodar
# de verdade contra o banco de teste. O feed já traz `lancamento`; a escrita só
# deve acontecer quando o dado local está velho (> `_TTL_LANCAMENTO_S`) ou nulo.


def _feed_com_lancamento(anilist_id: int, proximo_ep_numero: int) -> AnimeEmAlta:
    return AnimeEmAlta(
        titulo_romaji=f"Anime {anilist_id}",
        titulo_ingles=None,
        capa_url=None,
        banner_url=None,
        anilist_id=anilist_id,
        lancamento=LancamentoDeAnime(
            status=StatusLancamento.EM_LANCAMENTO,
            total_episodios=24,
            proximo_ep_numero=proximo_ep_numero,
            proximo_ep_em=None,
        ),
    )


async def test_em_alta_refresh_oportunista_nao_reescreve_dentro_do_ttl(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker, monkeypatch: pytest.MonkeyPatch
):
    anime_id = await _criar_anime(
        sessionmaker_api,
        "Slime Recente",
        "slime-recente",
        anilist_id=1,
        status_lancamento=StatusLancamento.EM_LANCAMENTO,
        proximo_ep_numero=3,
        lancamento_atualizado_em=datetime.now(UTC) - timedelta(hours=1),
    )

    async def _listar_em_alta_fake():
        return [_feed_com_lancamento(1, proximo_ep_numero=9)]

    monkeypatch.setattr("integrations.servico.listar_em_alta", _listar_em_alta_fake)

    resposta = await cliente.get("/api/animes/em-alta")

    assert resposta.status_code == 200
    async with sessionmaker_api() as sessao:
        anime = await sessao.get(Anime, anime_id)
        assert anime.proximo_ep_numero == 3  # feed trazia 9, mas o dado local é fresco
        assert anime.total_episodios_anilist is None


@pytest.mark.parametrize(
    "carimbo",
    [None, datetime(2020, 1, 1, tzinfo=UTC)],
    ids=["nulo", "mais-de-6h"],
)
async def test_em_alta_refresh_oportunista_reescreve_fora_do_ttl(
    cliente: AsyncClient,
    sessionmaker_api: _SessionMaker,
    monkeypatch: pytest.MonkeyPatch,
    carimbo: datetime | None,
):
    anime_id = await _criar_anime(
        sessionmaker_api,
        "Slime Velho",
        "slime-velho",
        anilist_id=1,
        status_lancamento=StatusLancamento.EM_LANCAMENTO,
        proximo_ep_numero=3,
        lancamento_atualizado_em=carimbo,
    )

    async def _listar_em_alta_fake():
        return [_feed_com_lancamento(1, proximo_ep_numero=9)]

    monkeypatch.setattr("integrations.servico.listar_em_alta", _listar_em_alta_fake)

    resposta = await cliente.get("/api/animes/em-alta")

    assert resposta.status_code == 200
    async with sessionmaker_api() as sessao:
        anime = await sessao.get(Anime, anime_id)
        assert anime.proximo_ep_numero == 9
        assert anime.total_episodios_anilist == 24
        assert anime.status_lancamento == StatusLancamento.EM_LANCAMENTO
        assert anime.lancamento_atualizado_em is not None


async def test_em_alta_refresh_oportunista_so_toca_itens_catalogados_e_com_lancamento(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker, monkeypatch: pytest.MonkeyPatch
):
    """Item sem `lancamento` no feed e item não catalogado localmente não entram
    no lote de escrita — só o par (catalogado, com lançamento) fora do TTL."""
    alvo = await _criar_anime(
        sessionmaker_api, "Slime Alvo", "slime-alvo", anilist_id=1, proximo_ep_numero=2
    )
    sem_lancamento = await _criar_anime(
        sessionmaker_api, "Slime Sem Bloco", "slime-sem-bloco", anilist_id=2, proximo_ep_numero=2
    )

    item_sem_bloco = AnimeEmAlta(
        titulo_romaji="Anime 2",
        titulo_ingles=None,
        capa_url=None,
        banner_url=None,
        anilist_id=2,
    )
    item_nao_catalogado = _feed_com_lancamento(999, proximo_ep_numero=5)

    async def _listar_em_alta_fake():
        return [_feed_com_lancamento(1, proximo_ep_numero=7), item_sem_bloco, item_nao_catalogado]

    monkeypatch.setattr("integrations.servico.listar_em_alta", _listar_em_alta_fake)

    resposta = await cliente.get("/api/animes/em-alta")

    assert resposta.status_code == 200
    async with sessionmaker_api() as sessao:
        assert (await sessao.get(Anime, alvo)).proximo_ep_numero == 7
        atualizado_sem_bloco = await sessao.get(Anime, sem_lancamento)
        assert atualizado_sem_bloco.proximo_ep_numero == 2  # feed não trouxe bloco
        assert atualizado_sem_bloco.lancamento_atualizado_em is None


async def test_em_alta_refresh_oportunista_erro_de_escrita_nao_derruba_home(
    cliente: AsyncClient,
    sessionmaker_api: _SessionMaker,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    await _criar_anime(
        sessionmaker_api, "Slime Home", "slime-home", anilist_id=1, proximo_ep_numero=1
    )

    async def _listar_em_alta_fake():
        return [_feed_com_lancamento(1, proximo_ep_numero=6)]

    async def _escrita_falha(*args, **kwargs):
        raise SQLAlchemyError("banco indisponível")

    monkeypatch.setattr("integrations.servico.listar_em_alta", _listar_em_alta_fake)
    monkeypatch.setattr("api.servicos.descoberta.atualizar_lancamentos_em_lote", _escrita_falha)

    with caplog.at_level("WARNING"):
        resposta = await cliente.get("/api/animes/em-alta")

    assert resposta.status_code == 200
    assert resposta.json()[0]["anilist_id"] == 1
    assert "refresh oportunista de lançamento" in caplog.text


# --- F4b: refresh lazy fire-and-forget ao abrir a página de um anime ---


async def test_obter_anime_agenda_refresh_lazy_fora_do_ttl(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker, monkeypatch: pytest.MonkeyPatch
):
    chamadas: list[int] = []
    novo = LancamentoDeAnime(
        status=StatusLancamento.EM_LANCAMENTO,
        total_episodios=None,
        proximo_ep_numero=5,
        proximo_ep_em=None,
    )

    async def _buscar_fake(anilist_id: int):
        chamadas.append(anilist_id)
        return novo

    monkeypatch.setattr("integrations.servico.buscar_lancamento_por_anilist_id", _buscar_fake)

    anime_id = await _criar_anime(
        sessionmaker_api,
        "Slime Lazy",
        "slime-lazy",
        anilist_id=77,
        status_lancamento=StatusLancamento.EM_LANCAMENTO,
        proximo_ep_numero=2,
        lancamento_atualizado_em=datetime.now(UTC) - timedelta(hours=7),
    )

    resposta = await cliente.get(f"/api/animes/{anime_id}")
    assert resposta.status_code == 200

    await _drenar_refreshs_de_lancamento()

    assert chamadas == [77]
    async with sessionmaker_api() as sessao:
        anime = await sessao.get(Anime, anime_id)
        assert anime.proximo_ep_numero == 5


@pytest.mark.parametrize(
    "campos",
    [
        {"anilist_id": None},
        {"anilist_id": 5, "status_lancamento": StatusLancamento.FINALIZADO},
        {"anilist_id": 5, "lancamento_atualizado_em": datetime.now(UTC) - timedelta(hours=1)},
    ],
    ids=["sem-anilist-id", "status-finalizado", "dentro-do-ttl"],
)
async def test_obter_anime_nao_agenda_refresh_lazy_quando_gate_barra(
    cliente: AsyncClient,
    sessionmaker_api: _SessionMaker,
    monkeypatch: pytest.MonkeyPatch,
    campos: dict,
):
    chamadas: list[int] = []

    async def _buscar_fake(anilist_id: int):
        chamadas.append(anilist_id)
        return None

    monkeypatch.setattr("integrations.servico.buscar_lancamento_por_anilist_id", _buscar_fake)

    anime_id = await _criar_anime(sessionmaker_api, "Slime Gate", "slime-gate", **campos)

    resposta = await cliente.get(f"/api/animes/{anime_id}")
    assert resposta.status_code == 200

    await _drenar_refreshs_de_lancamento()

    assert chamadas == []
    assert servico_descoberta._refreshs_de_lancamento_em_voo == {}


async def test_agendar_refresh_lazy_deduplica_chamadas_concorrentes(
    sessionmaker_api: _SessionMaker, monkeypatch: pytest.MonkeyPatch
):
    entrou = asyncio.Event()
    liberar = asyncio.Event()
    chamadas: list[int] = []

    async def _buscar_fake(anilist_id: int):
        chamadas.append(anilist_id)
        entrou.set()
        await liberar.wait()
        return None

    monkeypatch.setattr("integrations.servico.buscar_lancamento_por_anilist_id", _buscar_fake)

    anime = Anime(
        titulo="Slime Dedupe",
        slug="slime-dedupe",
        anilist_id=88,
        status_lancamento=StatusLancamento.EM_LANCAMENTO,
    )
    anime.id = 4242

    servico_descoberta.agendar_refresh_de_lancamento(sessionmaker_api, anime)
    servico_descoberta.agendar_refresh_de_lancamento(sessionmaker_api, anime)

    assert len(servico_descoberta._refreshs_de_lancamento_em_voo) == 1

    await asyncio.wait_for(entrou.wait(), timeout=1)
    assert chamadas == [88]

    liberar.set()
    await _drenar_refreshs_de_lancamento()
    assert servico_descoberta._refreshs_de_lancamento_em_voo == {}


async def test_obter_anime_refresh_lazy_falho_da_anilist_nao_propaga(
    cliente: AsyncClient,
    sessionmaker_api: _SessionMaker,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    async def _buscar_fake(anilist_id: int):
        raise FalhaDeMetadados("aniList fora do ar")

    monkeypatch.setattr("integrations.servico.buscar_lancamento_por_anilist_id", _buscar_fake)

    anime_id = await _criar_anime(
        sessionmaker_api,
        "Slime Falho",
        "slime-falho",
        anilist_id=5,
        status_lancamento=StatusLancamento.EM_LANCAMENTO,
        proximo_ep_numero=4,
        lancamento_atualizado_em=datetime.now(UTC) - timedelta(hours=8),
    )

    with caplog.at_level("WARNING"):
        resposta = await cliente.get(f"/api/animes/{anime_id}")
        assert resposta.status_code == 200
        # dado velho preservado no cálculo: (4 - 1) - 0 capturados
        assert resposta.json()["episodios_novos"] == 3
        # `gather` sem `return_exceptions` — re-levantaria se a corotina propagasse
        await _drenar_refreshs_de_lancamento()

    assert "refresh lazy de lançamento falhou" in caplog.text
    async with sessionmaker_api() as sessao:
        anime = await sessao.get(Anime, anime_id)
        assert anime.proximo_ep_numero == 4  # nada foi sobrescrito

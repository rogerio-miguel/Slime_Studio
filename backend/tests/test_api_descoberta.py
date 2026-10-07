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
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.servicos import descoberta as servico_descoberta
from api.servicos import sondagem
from api.servicos.fontes import FonteComEpisodios
from core.enums import StatusLancamento, VersaoDeFonte
from core.erros import FalhaDeMetadados
from core.texto import slugificar
from integrations.base import AnimeEmAlta, LancamentoDeAnime, MetadadosDeAnime
from models.anime import Anime
from models.fonte_anime import FonteAnime


def _fonte(dominio: str, episodios: list) -> FonteComEpisodios:
    """Retorno de `resolver_e_listar` com o mínimo que a sondagem lê."""
    return FonteComEpisodios(
        dominio=dominio,
        identificador="stub",
        versao_da_fonte=VersaoDeFonte.NAO_DIFERENCIADA,
        episodios=episodios,
    )

_SessionMaker = async_sessionmaker[AsyncSession]


async def _criar_anime(sessionmaker: _SessionMaker, titulo: str, slug: str, **campos) -> int:
    async with sessionmaker() as sessao:
        anime = Anime(titulo=titulo, slug=slug, **campos)
        sessao.add(anime)
        await sessao.commit()
        return anime.id


@pytest.fixture(autouse=True)
def _sondagem_da_fonte_sem_rede(monkeypatch: pytest.MonkeyPatch):
    """F12: `GET /api/animes/{id}` agenda uma sondagem fire-and-forget da fonte
    real quando o anime tem `FonteAnime` mapeada. Nenhum teste deste arquivo
    exercita a fonte de verdade (isso é `tests/test_api_sondagem.py`) — stub para
    a `Task` nunca tocar extractor/rede. Testes que precisam espiar a chamada
    re-`setattr`am por cima."""

    async def _fake(sessionmaker, anime, versao, *, resolver_canonico):
        return _fonte(dominio="stub.io", episodios=[])

    monkeypatch.setattr("api.servicos.sondagem.resolver_e_listar", _fake)


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


async def _drenar_sondagens() -> None:
    """Contraparte de `_drenar_refreshs_de_lancamento` para as `Task` de sondagem
    de F12 (`sondagem._sondagens_em_voo`, isoladas pelo autouse do conftest)."""
    for _ in range(20):
        pendentes = [t for t in sondagem._sondagens_em_voo.values() if not t.done()]
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

    quando = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
    item = AnimeEmAlta(
        titulo_romaji="Tensei",
        titulo_ingles="That Time I Got Reincarnated as a Slime",
        capa_url="https://img/1.jpg",
        banner_url="https://img/1-banner.jpg",
        anilist_id=1,
        ano_estreia=2018,
        generos=("Action", "Fantasy"),
        capa_cor="#1a2b3c",
        lancamento=LancamentoDeAnime(
            status=StatusLancamento.EM_LANCAMENTO,
            total_episodios=100,
            proximo_ep_numero=55,
            proximo_ep_em=quando,
        ),
    )

    async def _listar_fake(sessionmaker):
        return [(item, anime_id)]

    monkeypatch.setattr("api.servicos.descoberta.listar_em_alta_com_catalogo", _listar_fake)

    resposta = await cliente.get("/api/animes/em-alta")

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert len(corpo) == 1
    item_json = corpo[0]
    assert datetime.fromisoformat(item_json.pop("proximo_ep_em")) == quando
    assert item_json == {
        "titulo_romaji": "Tensei",
        "titulo_ingles": "That Time I Got Reincarnated as a Slime",
        "capa_url": "https://img/1.jpg",
        "banner_url": "https://img/1-banner.jpg",
        "anilist_id": 1,
        "anime_id": anime_id,
        "ano_estreia": 2018,
        "generos": ["Action", "Fantasy"],
        "capa_cor": "#1a2b3c",
        "status_lancamento": "em_lancamento",
        "proximo_ep_numero": 55,
        "total_episodios": 100,
        "sinopse": None,
        "formato": None,
        "episodio_lancado": None,
    }


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


async def test_em_alta_item_sem_lancamento_ecoa_defaults_do_carrossel(
    cliente: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """Item do feed sem bloco `lancamento` e sem gêneros/ano/cor (caminho
    degradado Kitsu): a resposta ainda traz os campos do carrossel, nos defaults
    — nunca `null` para `generos`, e `capa_cor` + os três escalares de
    lançamento `null`."""
    item = AnimeEmAlta(
        titulo_romaji="Sem Bloco De Lancamento",
        titulo_ingles=None,
        capa_url=None,
        banner_url=None,
        anilist_id=42,
    )

    async def _listar_fake(sessionmaker):
        return [(item, None)]

    monkeypatch.setattr("api.servicos.descoberta.listar_em_alta_com_catalogo", _listar_fake)

    resposta = await cliente.get("/api/animes/em-alta")

    assert resposta.status_code == 200
    corpo = resposta.json()[0]
    assert corpo["ano_estreia"] is None
    assert corpo["generos"] == []
    assert corpo["capa_cor"] is None
    assert corpo["status_lancamento"] is None
    assert corpo["proximo_ep_numero"] is None
    assert corpo["proximo_ep_em"] is None


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


# --- GET /api/animes/proxima-temporada ---


async def test_proxima_temporada_propaga_502_se_todos_provedores_falham(
    cliente: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    async def _fake(sessionmaker):
        raise FalhaDeMetadados("todos os provedores de metadados falharam")

    monkeypatch.setattr(
        "api.servicos.descoberta.listar_proxima_temporada_com_catalogo", _fake
    )

    resposta = await cliente.get("/api/animes/proxima-temporada")

    assert resposta.status_code == 502


async def test_proxima_temporada_cruzamento_real_por_anilist_id(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker, monkeypatch: pytest.MonkeyPatch
):
    anime_id = await _criar_anime(
        sessionmaker_api, "Título Local", "titulo-local", anilist_id=777
    )
    item = AnimeEmAlta(
        titulo_romaji="Próxima Estreia",
        titulo_ingles=None,
        capa_url="https://img/p.jpg",
        banner_url=None,
        anilist_id=777,
        ano_estreia=2027,
        generos=("Drama",),
        lancamento=LancamentoDeAnime(
            status=StatusLancamento.NAO_LANCADO,
            total_episodios=None,
            proximo_ep_numero=None,
            proximo_ep_em=None,
        ),
    )

    async def _listar_fake():
        return [item]

    monkeypatch.setattr("integrations.servico.listar_proxima_temporada", _listar_fake)

    resposta = await cliente.get("/api/animes/proxima-temporada")

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert len(corpo) == 1
    assert corpo[0]["anime_id"] == anime_id
    assert corpo[0]["status_lancamento"] == "nao_lancado"
    assert corpo[0]["generos"] == ["Drama"]


async def test_proxima_temporada_sem_correspondencia_local_devolve_anime_id_none(
    cliente: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    item = AnimeEmAlta(
        titulo_romaji="Nada Catalogado",
        titulo_ingles=None,
        capa_url=None,
        banner_url=None,
        anilist_id=404,
    )

    async def _listar_fake():
        return [item]

    monkeypatch.setattr("integrations.servico.listar_proxima_temporada", _listar_fake)

    resposta = await cliente.get("/api/animes/proxima-temporada")

    assert resposta.status_code == 200
    assert resposta.json()[0]["anime_id"] is None


async def test_proxima_temporada_nao_faz_refresh_oportunista_de_lancamento(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker, monkeypatch: pytest.MonkeyPatch
):
    """Diferença central em relação a `/api/animes/em-alta`: mesmo com um item
    catalogado e dado local bem velho, o cruzamento seco NÃO sobrescreve as
    colunas de lançamento (nenhuma chamada a `atualizar_lancamentos_em_lote`)."""
    anime_id = await _criar_anime(
        sessionmaker_api,
        "Prox Catalogado",
        "prox-catalogado",
        anilist_id=1,
        status_lancamento=StatusLancamento.EM_LANCAMENTO,
        proximo_ep_numero=3,
        lancamento_atualizado_em=datetime(2020, 1, 1, tzinfo=UTC),
    )

    async def _listar_fake():
        return [_feed_com_lancamento(1, proximo_ep_numero=9)]

    async def _escrita_proibida(*args, **kwargs):
        raise AssertionError("proxima-temporada não deve escrever lançamento do catálogo")

    monkeypatch.setattr("integrations.servico.listar_proxima_temporada", _listar_fake)
    monkeypatch.setattr(
        "api.servicos.descoberta.atualizar_lancamentos_em_lote", _escrita_proibida
    )

    resposta = await cliente.get("/api/animes/proxima-temporada")

    assert resposta.status_code == 200
    assert resposta.json()[0]["anime_id"] == anime_id
    async with sessionmaker_api() as sessao:
        anime = await sessao.get(Anime, anime_id)
        assert anime.proximo_ep_numero == 3  # feed trazia 9, mas não há refresh aqui


# --- GET /api/animes/fileiras-tematicas ---


async def test_fileiras_tematicas_propaga_502_se_todos_provedores_falham(
    cliente: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    async def _fake(sessionmaker):
        raise FalhaDeMetadados("todos os provedores de metadados falharam")

    monkeypatch.setattr("api.servicos.descoberta.listar_fileiras_tematicas_com_catalogo", _fake)

    resposta = await cliente.get("/api/animes/fileiras-tematicas")

    assert resposta.status_code == 502


async def test_ordem_de_rotas_fileiras_tematicas_nao_e_interpretado_como_anime_id(
    cliente: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    async def _fake(sessionmaker):
        return []

    monkeypatch.setattr("api.servicos.descoberta.listar_fileiras_tematicas_com_catalogo", _fake)

    resposta = await cliente.get("/api/animes/fileiras-tematicas")

    assert resposta.status_code == 200
    assert resposta.json() == []


async def test_fileiras_tematicas_cruza_com_catalogo_local_no_schema_de_resposta(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker, monkeypatch: pytest.MonkeyPatch
):
    """Uma fileira com um item catalogado (`anime_id` local) e um item sem
    correspondência (`None`) — o JSON de resposta reflete `{chave, itens}` por
    fileira, cada item no mesmo shape de `AnimeEmAltaSaida`."""
    anime_id = await _criar_anime(sessionmaker_api, "Tensei Shitara Slime Datta Ken", "tensei")

    catalogado = AnimeEmAlta(
        titulo_romaji="Tensei",
        titulo_ingles="That Time I Got Reincarnated as a Slime",
        capa_url="https://img/1.jpg",
        banner_url="https://img/1-banner.jpg",
        anilist_id=1,
        ano_estreia=2018,
        generos=("Action", "Fantasy"),
        capa_cor="#1a2b3c",
    )
    nao_catalogado = AnimeEmAlta(
        titulo_romaji="Ainda Nao Catalogado",
        titulo_ingles=None,
        capa_url=None,
        banner_url=None,
        anilist_id=99,
    )

    async def _fake(sessionmaker):
        return [("found_family", [(catalogado, anime_id), (nao_catalogado, None)])]

    monkeypatch.setattr("api.servicos.descoberta.listar_fileiras_tematicas_com_catalogo", _fake)

    resposta = await cliente.get("/api/animes/fileiras-tematicas")

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert len(corpo) == 1
    fileira = corpo[0]
    assert fileira["chave"] == "found_family"
    assert len(fileira["itens"]) == 2
    assert fileira["itens"][0]["anime_id"] == anime_id
    assert fileira["itens"][0]["titulo_romaji"] == "Tensei"
    assert fileira["itens"][0]["generos"] == ["Action", "Fantasy"]
    assert fileira["itens"][1]["anime_id"] is None
    assert fileira["itens"][1]["titulo_romaji"] == "Ainda Nao Catalogado"


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


async def test_criar_anime_com_banner_e_capa_cor_no_payload_persiste(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker, monkeypatch: pytest.MonkeyPatch
):
    """`banner_url`/`capa_cor` do item do feed da Home entram no curto-circuito de
    "algum campo veio no payload" (sem chamar provedor) e persistem em
    `Anime.banner_path`/`Anime.capa_cor`."""
    chamadas = []

    async def _buscar_fake(titulo):
        chamadas.append(titulo)
        return None

    monkeypatch.setattr("integrations.servico.buscar_por_titulo", _buscar_fake)

    resposta = await cliente.post(
        "/api/admin/animes",
        json={
            "titulo": "Slime Com Banner",
            "banner_url": "https://img/banner.jpg",
            "capa_cor": "#e4a15d",
        },
    )

    assert resposta.status_code == 200
    assert chamadas == []
    corpo = resposta.json()
    assert corpo["banner_path"] == "https://img/banner.jpg"
    assert corpo["capa_cor"] == "#e4a15d"
    async with sessionmaker_api() as sessao:
        anime = await sessao.get(Anime, corpo["id"])
        assert anime.banner_path == "https://img/banner.jpg"
        assert anime.capa_cor == "#e4a15d"


async def test_criar_anime_com_generos_no_payload_persiste_sem_chamar_provedor(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker, monkeypatch: pytest.MonkeyPatch
):
    """`generos` do item do feed da Home entra no curto-circuito de "algum campo
    veio no payload" (sem chamar provedor) e persiste em `Anime.generos`."""
    chamadas = []

    async def _buscar_fake(titulo):
        chamadas.append(titulo)
        return None

    monkeypatch.setattr("integrations.servico.buscar_por_titulo", _buscar_fake)

    resposta = await cliente.post(
        "/api/admin/animes",
        json={"titulo": "Slime Com Generos", "generos": ["Action", "Comedy"]},
    )

    assert resposta.status_code == 200
    assert chamadas == []
    async with sessionmaker_api() as sessao:
        anime = await sessao.get(Anime, resposta.json()["id"])
        assert anime.generos == ["Action", "Comedy"]


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


# --- F4a visual: backfill de banner/cor no cruzamento do feed "em alta" ---


def _feed_com_banner(anilist_id: int, *, banner_url: str, capa_cor: str | None) -> AnimeEmAlta:
    return AnimeEmAlta(
        titulo_romaji=f"Anime {anilist_id}",
        titulo_ingles=None,
        capa_url=None,
        banner_url=banner_url,
        anilist_id=anilist_id,
        capa_cor=capa_cor,
    )


async def test_em_alta_preenche_banner_de_anime_catalogado_sem_banner(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker, monkeypatch: pytest.MonkeyPatch
):
    anime_id = await _criar_anime(
        sessionmaker_api, "Slime Sem Banner", "slime-sem-banner", anilist_id=1
    )

    async def _listar_em_alta_fake():
        return [_feed_com_banner(1, banner_url="https://img/banner.jpg", capa_cor="#e4a15d")]

    monkeypatch.setattr("integrations.servico.listar_em_alta", _listar_em_alta_fake)

    resposta = await cliente.get("/api/animes/em-alta")

    assert resposta.status_code == 200
    async with sessionmaker_api() as sessao:
        anime = await sessao.get(Anime, anime_id)
        assert anime.banner_path == "https://img/banner.jpg"
        assert anime.capa_cor == "#e4a15d"


async def test_em_alta_nao_sobrescreve_banner_ja_gravado(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker, monkeypatch: pytest.MonkeyPatch
):
    anime_id = await _criar_anime(
        sessionmaker_api,
        "Slime Com Banner",
        "slime-com-banner",
        anilist_id=1,
        banner_path="https://original/banner.jpg",
        capa_cor="#000000",
    )

    async def _listar_em_alta_fake():
        return [_feed_com_banner(1, banner_url="https://novo/banner.jpg", capa_cor="#ffffff")]

    monkeypatch.setattr("integrations.servico.listar_em_alta", _listar_em_alta_fake)

    resposta = await cliente.get("/api/animes/em-alta")

    assert resposta.status_code == 200
    async with sessionmaker_api() as sessao:
        anime = await sessao.get(Anime, anime_id)
        assert anime.banner_path == "https://original/banner.jpg"
        assert anime.capa_cor == "#000000"


async def test_em_alta_backfill_de_banner_erro_de_escrita_nao_derruba_home(
    cliente: AsyncClient,
    sessionmaker_api: _SessionMaker,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    await _criar_anime(sessionmaker_api, "Slime Home Banner", "slime-home-banner", anilist_id=1)

    async def _listar_em_alta_fake():
        return [_feed_com_banner(1, banner_url="https://img/b.jpg", capa_cor=None)]

    async def _escrita_falha(*args, **kwargs):
        raise SQLAlchemyError("banco indisponível")

    monkeypatch.setattr("integrations.servico.listar_em_alta", _listar_em_alta_fake)
    monkeypatch.setattr(
        "api.servicos.descoberta.preencher_banner_visual_em_lote", _escrita_falha
    )

    with caplog.at_level("WARNING"):
        resposta = await cliente.get("/api/animes/em-alta")

    assert resposta.status_code == 200
    assert resposta.json()[0]["anilist_id"] == 1
    assert "backfill oportunista de banner" in caplog.text


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


async def test_obter_anime_agenda_refresh_lazy_para_status_nao_lancado(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker, monkeypatch: pytest.MonkeyPatch
):
    """O gate de `agendar_refresh_de_lancamento` também aceita `NAO_LANCADO`:
    abrir a página de um bookmark de estreia com `anilist_id` e dado velho
    agenda a busca lazy por id (antes só `EM_LANCAMENTO`/nulo passavam)."""
    chamadas: list[int] = []

    async def _buscar_fake(anilist_id: int):
        chamadas.append(anilist_id)
        return None

    monkeypatch.setattr("integrations.servico.buscar_lancamento_por_anilist_id", _buscar_fake)

    anime_id = await _criar_anime(
        sessionmaker_api,
        "Slime Estreia Futura",
        "slime-estreia-futura",
        anilist_id=99,
        status_lancamento=StatusLancamento.NAO_LANCADO,
        lancamento_atualizado_em=datetime.now(UTC) - timedelta(hours=7),
    )

    resposta = await cliente.get(f"/api/animes/{anime_id}")
    assert resposta.status_code == 200

    await _drenar_refreshs_de_lancamento()

    assert chamadas == [99]


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
        episodios_na_fonte=4,
        lancamento_atualizado_em=datetime.now(UTC) - timedelta(hours=8),
    )

    with caplog.at_level("WARNING"):
        resposta = await cliente.get(f"/api/animes/{anime_id}")
        assert resposta.status_code == 200
        # `gather` sem `return_exceptions` — re-levantaria se a corotina propagasse
        await _drenar_refreshs_de_lancamento()

    assert "refresh lazy de lançamento falhou" in caplog.text
    async with sessionmaker_api() as sessao:
        anime = await sessao.get(Anime, anime_id)
        assert anime.proximo_ep_numero == 4  # nada foi sobrescrito


async def test_obter_anime_agenda_sondagem_de_fonte_sem_regredir_refresh_de_lancamento(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker, monkeypatch: pytest.MonkeyPatch
):
    """F12 não engoliu o `agendar_refresh_de_lancamento` de F4b: abrir a página de
    um anime em lançamento com `FonteAnime` mapeada e dado velho dispara AS DUAS
    caronas fire-and-forget."""
    lancamentos: list[int] = []
    sondagens: list[int] = []

    async def _buscar_lancamento_fake(anilist_id: int):
        lancamentos.append(anilist_id)
        return None

    async def _sondar_fake(sessionmaker, anime, versao, *, resolver_canonico):
        sondagens.append(anime.id)
        return _fonte(dominio="stub.io", episodios=[])

    monkeypatch.setattr(
        "integrations.servico.buscar_lancamento_por_anilist_id", _buscar_lancamento_fake
    )
    monkeypatch.setattr("api.servicos.sondagem.resolver_e_listar", _sondar_fake)

    anime_id = await _criar_anime(
        sessionmaker_api,
        "Slime Coexiste",
        "slime-coexiste",
        anilist_id=321,
        status_lancamento=StatusLancamento.EM_LANCAMENTO,
        lancamento_atualizado_em=datetime.now(UTC) - timedelta(hours=8),
    )
    async with sessionmaker_api() as sessao:
        sessao.add(
            FonteAnime(
                anime_id=anime_id,
                site_dominio="site.io",
                versao=VersaoDeFonte.LEGENDADO,
                identificador_no_site="x",
                prioridade=0,
            )
        )
        await sessao.commit()

    resposta = await cliente.get(f"/api/animes/{anime_id}")
    assert resposta.status_code == 200

    await _drenar_refreshs_de_lancamento()
    await _drenar_sondagens()

    assert lancamentos == [321]
    assert sondagens == [anime_id]


# --- F14: listar catálogo aquece `status_lancamento` até um teto por request ---


async def test_agendar_refreshs_do_catalogo_limita_ao_teto_priorizando_mais_velhos(
    sessionmaker_api: _SessionMaker, monkeypatch: pytest.MonkeyPatch
):
    """12 animes elegíveis numa listagem de catálogo disparam no máximo
    `_MAX_REFRESHS_DE_LANCAMENTO_POR_LOTE` buscas à AniList — os de carimbo mais
    velho primeiro."""
    chamadas: list[int] = []

    async def _buscar_fake(anilist_id: int):
        chamadas.append(anilist_id)
        return None

    monkeypatch.setattr("integrations.servico.buscar_lancamento_por_anilist_id", _buscar_fake)

    base = datetime(2020, 1, 1, tzinfo=UTC)
    animes = []
    for i in range(12):
        anime = Anime(
            titulo=f"Slime {i}",
            slug=f"slime-{i}",
            anilist_id=1000 + i,
            status_lancamento=None,
            lancamento_atualizado_em=base + timedelta(hours=i),
        )
        anime.id = 500 + i
        animes.append(anime)

    servico_descoberta.agendar_refreshs_do_catalogo(sessionmaker_api, animes)

    assert len(servico_descoberta._refreshs_de_lancamento_em_voo) == 5
    await _drenar_refreshs_de_lancamento()
    assert sorted(chamadas) == [1000, 1001, 1002, 1003, 1004]


async def test_agendar_refreshs_do_catalogo_ignora_inelegiveis(
    sessionmaker_api: _SessionMaker, monkeypatch: pytest.MonkeyPatch
):
    """Mesmo gate de `agendar_refresh_de_lancamento`: sem `anilist_id`, status
    `FINALIZADO` ou carimbo dentro do TTL não disparam."""
    chamadas: list[int] = []

    async def _buscar_fake(anilist_id: int):
        chamadas.append(anilist_id)
        return None

    monkeypatch.setattr("integrations.servico.buscar_lancamento_por_anilist_id", _buscar_fake)

    def _anime(id_: int, **campos) -> Anime:
        anime = Anime(titulo=f"a{id_}", slug=f"a{id_}", **campos)
        anime.id = id_
        return anime

    animes = [
        _anime(1, status_lancamento=None),
        _anime(2, anilist_id=2, status_lancamento=StatusLancamento.FINALIZADO),
        _anime(
            3,
            anilist_id=3,
            status_lancamento=StatusLancamento.EM_LANCAMENTO,
            lancamento_atualizado_em=datetime.now(UTC),
        ),
        _anime(4, anilist_id=4, status_lancamento=StatusLancamento.EM_LANCAMENTO),
    ]

    servico_descoberta.agendar_refreshs_do_catalogo(sessionmaker_api, animes)
    await _drenar_refreshs_de_lancamento()

    assert chamadas == [4]


async def test_agendar_refreshs_do_catalogo_aquece_status_nao_lancado(
    sessionmaker_api: _SessionMaker, monkeypatch: pytest.MonkeyPatch
):
    """`NAO_LANCADO` entrou no gate de `_elegivel_para_aquecimento`: um bookmark
    de "Próximas estreias" com `anilist_id` e carimbo velho/ausente dispara a
    busca lazy por id — sem isso a data de estreia congelaria e o anime nunca
    transicionaria para `EM_LANCAMENTO`."""
    chamadas: list[int] = []

    async def _buscar_fake(anilist_id: int):
        chamadas.append(anilist_id)
        return None

    monkeypatch.setattr("integrations.servico.buscar_lancamento_por_anilist_id", _buscar_fake)

    def _anime(id_: int, **campos) -> Anime:
        anime = Anime(titulo=f"Estreia {id_}", slug=f"estreia-{id_}", **campos)
        anime.id = id_
        return anime

    animes = [
        _anime(1, anilist_id=11, status_lancamento=StatusLancamento.NAO_LANCADO),
        _anime(
            2,
            anilist_id=22,
            status_lancamento=StatusLancamento.NAO_LANCADO,
            lancamento_atualizado_em=datetime(2020, 1, 1, tzinfo=UTC),
        ),
    ]

    servico_descoberta.agendar_refreshs_do_catalogo(sessionmaker_api, animes)
    await _drenar_refreshs_de_lancamento()

    assert sorted(chamadas) == [11, 22]


# --- F14: aquecimento por TÍTULO dos animes sem `anilist_id` (via `GET
# /api/animes?aquecer=true` — a carona é opt-in, só a Galeria manda a flag) ---


async def test_agendar_refreshs_do_catalogo_busca_por_titulo_tem_teto_proprio(
    sessionmaker_api: _SessionMaker, monkeypatch: pytest.MonkeyPatch
):
    """Orçamentos independentes: animes sem `anilist_id` disparam no máximo
    `_MAX_BUSCAS_POR_TITULO_POR_LOTE` buscas por título (as de carimbo mais
    velho) E os 5 por id disparam na MESMA passada."""
    por_titulo: list[str] = []
    por_id: list[int] = []

    async def _buscar_por_titulo_fake(termo: str):
        por_titulo.append(termo)
        return None

    async def _buscar_por_id_fake(anilist_id: int):
        por_id.append(anilist_id)
        return None

    monkeypatch.setattr("integrations.servico.buscar_por_titulo", _buscar_por_titulo_fake)
    monkeypatch.setattr(
        "integrations.servico.buscar_lancamento_por_anilist_id", _buscar_por_id_fake
    )

    base = datetime(2020, 1, 1, tzinfo=UTC)
    animes: list[Anime] = []
    for i in range(6):
        anime = Anime(
            titulo=f"Anime Sem Anilist {i}",
            slug=f"anime-sem-anilist-{i}",
            status_lancamento=None,
            lancamento_atualizado_em=base + timedelta(hours=i),
        )
        anime.id = 700 + i
        animes.append(anime)
    for i in range(8):
        anime = Anime(
            titulo=f"Anime Com Anilist {i}",
            slug=f"anime-com-anilist-{i}",
            anilist_id=2000 + i,
            status_lancamento=None,
            lancamento_atualizado_em=base + timedelta(hours=i),
        )
        anime.id = 800 + i
        animes.append(anime)

    servico_descoberta.agendar_refreshs_do_catalogo(sessionmaker_api, animes)
    await _drenar_refreshs_de_lancamento()

    assert por_titulo == ["Anime Sem Anilist 0", "Anime Sem Anilist 1"]
    assert sorted(por_id) == [2000, 2001, 2002, 2003, 2004]


async def test_listar_animes_aquece_por_titulo_hit_corroborado_persiste_id_e_bloco(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker, monkeypatch: pytest.MonkeyPatch
):
    titulo = "Hanaori-san wa Tensei shitemo Kenka ga Shitai"
    anime_id = await _criar_anime(
        sessionmaker_api, titulo, slugificar(titulo), status_lancamento=None
    )

    async def _buscar_fake(termo: str):
        return MetadadosDeAnime(
            capa_url="https://img/x.jpg",
            sinopse="NAO DEVE PERSISTIR",
            anilist_id=987,
            kitsu_id=555,
            titulo_romaji=titulo,
            titulo_ingles=None,
            lancamento=LancamentoDeAnime(
                status=StatusLancamento.EM_LANCAMENTO,
                total_episodios=12,
                proximo_ep_numero=5,
                proximo_ep_em=None,
            ),
        )

    monkeypatch.setattr("integrations.servico.buscar_por_titulo", _buscar_fake)

    resposta = await cliente.get("/api/animes?aquecer=true")
    assert resposta.status_code == 200
    await _drenar_refreshs_de_lancamento()

    async with sessionmaker_api() as sessao:
        anime = await sessao.get(Anime, anime_id)
        assert anime.anilist_id == 987  # slug do termo == slug do romaji -> corrobora
        assert anime.status_lancamento == StatusLancamento.EM_LANCAMENTO
        assert anime.proximo_ep_numero == 5
        assert anime.total_episodios_anilist == 12
        assert anime.lancamento_atualizado_em is not None
        # match por título é heurístico — capa/sinopse/kitsu_id nunca entram
        assert anime.capa_path is None
        assert anime.sinopse is None
        assert anime.kitsu_id is None


async def test_listar_animes_aquece_por_titulo_sem_corroboracao_nao_grava_anilist_id(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker, monkeypatch: pytest.MonkeyPatch
):
    anime_id = await _criar_anime(
        sessionmaker_api, "Meu Anime Local", "meu-anime-local", status_lancamento=None
    )

    async def _buscar_fake(termo: str):
        return MetadadosDeAnime(
            capa_url=None,
            sinopse=None,
            anilist_id=111,
            kitsu_id=None,
            titulo_romaji="Titulo Totalmente Diferente",
            titulo_ingles="Another Unrelated Title",
            lancamento=LancamentoDeAnime(
                status=StatusLancamento.EM_LANCAMENTO,
                total_episodios=None,
                proximo_ep_numero=3,
                proximo_ep_em=None,
            ),
        )

    monkeypatch.setattr("integrations.servico.buscar_por_titulo", _buscar_fake)

    resposta = await cliente.get("/api/animes?aquecer=true")
    assert resposta.status_code == 200
    await _drenar_refreshs_de_lancamento()

    async with sessionmaker_api() as sessao:
        anime = await sessao.get(Anime, anime_id)
        assert anime.anilist_id is None  # romaji/inglês divergentes -> não grava
        assert anime.status_lancamento == StatusLancamento.EM_LANCAMENTO  # bloco persiste
        assert anime.proximo_ep_numero == 3
        assert anime.lancamento_atualizado_em is not None  # carimbo escrito


async def test_listar_animes_aquece_por_titulo_remove_marcador_de_versao_do_termo(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker, monkeypatch: pytest.MonkeyPatch
):
    titulo_local = "Fuufu Ijou, Koibito Miman. (Dublado)"
    romaji = "Fuufu Ijou, Koibito Miman."
    anime_id = await _criar_anime(
        sessionmaker_api, titulo_local, slugificar(titulo_local), status_lancamento=None
    )
    termos: list[str] = []

    async def _buscar_fake(termo: str):
        termos.append(termo)
        return MetadadosDeAnime(
            capa_url=None,
            sinopse=None,
            anilist_id=321,
            kitsu_id=None,
            titulo_romaji=romaji,
            titulo_ingles=None,
            lancamento=LancamentoDeAnime(
                status=StatusLancamento.EM_LANCAMENTO,
                total_episodios=12,
                proximo_ep_numero=7,
                proximo_ep_em=None,
            ),
        )

    monkeypatch.setattr("integrations.servico.buscar_por_titulo", _buscar_fake)

    resposta = await cliente.get("/api/animes?aquecer=true")
    assert resposta.status_code == 200
    await _drenar_refreshs_de_lancamento()

    assert termos == [romaji]  # "(Dublado)" removido antes de consultar o provedor
    async with sessionmaker_api() as sessao:
        anime = await sessao.get(Anime, anime_id)
        assert anime.anilist_id == 321  # slug(termo) == slug(romaji) -> corrobora


async def test_listar_animes_aquece_por_titulo_cache_negativo_bloqueia_rebusca_no_ttl(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker, monkeypatch: pytest.MonkeyPatch
):
    anime_id = await _criar_anime(
        sessionmaker_api, "Nunca Achado", "nunca-achado", status_lancamento=None
    )
    chamadas: list[str] = []

    async def _buscar_fake(termo: str):
        chamadas.append(termo)
        return None

    monkeypatch.setattr("integrations.servico.buscar_por_titulo", _buscar_fake)

    primeira = await cliente.get("/api/animes?aquecer=true")
    assert primeira.status_code == 200
    await _drenar_refreshs_de_lancamento()

    async with sessionmaker_api() as sessao:
        anime = await sessao.get(Anime, anime_id)
        assert anime.lancamento_atualizado_em is not None  # cache negativo carimbado
        assert anime.status_lancamento is None  # nada foi achado

    segunda = await cliente.get("/api/animes?aquecer=true")
    assert segunda.status_code == 200
    await _drenar_refreshs_de_lancamento()

    assert chamadas == ["Nunca Achado"]  # 2ª passada não re-busca (dentro do TTL)


async def test_listar_animes_aquece_por_titulo_falha_de_provedor_nao_carimba(
    cliente: AsyncClient,
    sessionmaker_api: _SessionMaker,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    anime_id = await _criar_anime(
        sessionmaker_api, "Provedor Fora Do Ar", "provedor-fora-do-ar", status_lancamento=None
    )
    chamadas: list[str] = []

    async def _buscar_fake(termo: str):
        chamadas.append(termo)
        raise FalhaDeMetadados("todos os provedores de metadados falharam")

    monkeypatch.setattr("integrations.servico.buscar_por_titulo", _buscar_fake)

    with caplog.at_level("WARNING"):
        primeira = await cliente.get("/api/animes?aquecer=true")
        assert primeira.status_code == 200
        # `gather` sem `return_exceptions` — re-levantaria se a corotina propagasse
        await _drenar_refreshs_de_lancamento()

    assert "aquecimento de lançamento por título falhou" in caplog.text
    async with sessionmaker_api() as sessao:
        anime = await sessao.get(Anime, anime_id)
        assert anime.lancamento_atualizado_em is None  # falha não carimba

    segunda = await cliente.get("/api/animes?aquecer=true")
    assert segunda.status_code == 200
    await _drenar_refreshs_de_lancamento()
    assert chamadas == ["Provedor Fora Do Ar", "Provedor Fora Do Ar"]  # tenta de novo


async def test_agendar_refreshs_do_catalogo_por_titulo_respeita_o_gate(
    sessionmaker_api: _SessionMaker, monkeypatch: pytest.MonkeyPatch
):
    """Sem `anilist_id` mas `FINALIZADO`, ou dentro do TTL: não dispara busca
    por título."""
    chamadas: list[str] = []

    async def _buscar_fake(termo: str):
        chamadas.append(termo)
        return None

    monkeypatch.setattr("integrations.servico.buscar_por_titulo", _buscar_fake)

    def _anime(id_: int, **campos) -> Anime:
        anime = Anime(titulo=f"Titulo {id_}", slug=f"titulo-{id_}", **campos)
        anime.id = id_
        return anime

    animes = [
        _anime(1, status_lancamento=StatusLancamento.FINALIZADO),
        _anime(
            2,
            status_lancamento=StatusLancamento.EM_LANCAMENTO,
            lancamento_atualizado_em=datetime.now(UTC),
        ),
        _anime(3, status_lancamento=None),
    ]

    servico_descoberta.agendar_refreshs_do_catalogo(sessionmaker_api, animes)
    await _drenar_refreshs_de_lancamento()

    assert chamadas == ["Titulo 3"]


async def test_obter_anime_sem_anilist_id_nao_dispara_busca_por_titulo(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker, monkeypatch: pytest.MonkeyPatch
):
    """D5: o aquecimento por título é só da galeria (`GET /api/animes`). A página
    do anime (`GET /api/animes/{id}`) nunca dispara busca por título."""
    chamadas: list[str] = []

    async def _buscar_fake(termo: str):
        chamadas.append(termo)
        return None

    monkeypatch.setattr("integrations.servico.buscar_por_titulo", _buscar_fake)

    anime_id = await _criar_anime(
        sessionmaker_api, "So Na Galeria", "so-na-galeria", status_lancamento=None
    )

    resposta = await cliente.get(f"/api/animes/{anime_id}")
    assert resposta.status_code == 200
    await _drenar_refreshs_de_lancamento()

    assert chamadas == []
    assert servico_descoberta._refreshs_de_lancamento_em_voo == {}


async def test_em_alta_banner_escolhido_vence_o_do_feed_sem_vazar_para_banner_path(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker, monkeypatch: pytest.MonkeyPatch
):
    anime_id = await _criar_anime(
        sessionmaker_api, "Slime Escolhido", "slime-escolhido", anilist_id=1,
        banner_escolhido="https://escolhido/banner.jpg",
    )

    async def _listar_em_alta_fake():
        return [_feed_com_banner(1, banner_url="https://feed/banner.jpg", capa_cor="#e4a15d")]

    monkeypatch.setattr("integrations.servico.listar_em_alta", _listar_em_alta_fake)

    resposta = await cliente.get("/api/animes/em-alta")

    assert resposta.status_code == 200
    assert resposta.json()[0]["banner_url"] == "https://escolhido/banner.jpg"
    async with sessionmaker_api() as sessao:
        anime = await sessao.get(Anime, anime_id)
        assert anime.banner_path == "https://feed/banner.jpg"


async def test_em_alta_banner_escolhido_vale_para_temporada_irma_da_franquia(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker, monkeypatch: pytest.MonkeyPatch
):
    # A escolha mora só na T1; a T2 (catalogada depois) herda pela franquia.
    await _criar_anime(
        sessionmaker_api, "Slime Franquia", "slime-franquia", anilist_id=1,
        serie_ancora=10, banner_escolhido="https://escolhido/banner.jpg",
    )
    await _criar_anime(
        sessionmaker_api, "Slime Franquia 2", "slime-franquia-2", anilist_id=2, serie_ancora=10
    )

    async def _listar_em_alta_fake():
        return [_feed_com_banner(2, banner_url="https://feed/t2.jpg", capa_cor="#e4a15d")]

    monkeypatch.setattr("integrations.servico.listar_em_alta", _listar_em_alta_fake)

    resposta = await cliente.get("/api/animes/em-alta")

    assert resposta.json()[0]["banner_url"] == "https://escolhido/banner.jpg"


async def test_em_alta_sem_banner_escolhido_mantem_o_do_feed(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker, monkeypatch: pytest.MonkeyPatch
):
    await _criar_anime(sessionmaker_api, "Slime Padrao", "slime-padrao", anilist_id=1)

    async def _listar_em_alta_fake():
        return [
            _feed_com_banner(1, banner_url="https://feed/banner.jpg", capa_cor="#e4a15d"),
            _feed_com_banner(99, banner_url="https://feed/fora.jpg", capa_cor="#000000"),
        ]

    monkeypatch.setattr("integrations.servico.listar_em_alta", _listar_em_alta_fake)

    resposta = await cliente.get("/api/animes/em-alta")

    assert [i["banner_url"] for i in resposta.json()] == [
        "https://feed/banner.jpg",
        "https://feed/fora.jpg",
    ]


async def test_em_alta_sem_banner_do_provedor_cai_no_banner_do_catalogo(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker, monkeypatch: pytest.MonkeyPatch
):
    # Temporada nova na AniList vem sem banner; o catálogo tem o da franquia (T1).
    await _criar_anime(
        sessionmaker_api, "Slime Franquia", "slime-franquia", anilist_id=1,
        serie_ancora=10, banner_path="https://catalogo/t1.jpg",
    )
    await _criar_anime(
        sessionmaker_api, "Slime Franquia 2", "slime-franquia-2", anilist_id=2, serie_ancora=10
    )

    async def _listar_em_alta_fake():
        return [
            AnimeEmAlta(
                titulo_romaji="Anime 2", titulo_ingles=None, capa_url="https://feed/capa.jpg",
                banner_url=None, anilist_id=2,
            ),
            AnimeEmAlta(
                titulo_romaji="Anime 99", titulo_ingles=None, capa_url="https://feed/capa99.jpg",
                banner_url=None, anilist_id=99,
            ),
        ]

    monkeypatch.setattr("integrations.servico.listar_em_alta", _listar_em_alta_fake)

    resposta = await cliente.get("/api/animes/em-alta")

    # Não catalogado (99) segue sem banner; catalogado herda o da franquia.
    assert [i["banner_url"] for i in resposta.json()] == ["https://catalogo/t1.jpg", None]


async def test_em_alta_banner_da_propria_temporada_vence_o_do_provedor_e_o_da_franquia(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker, monkeypatch: pytest.MonkeyPatch
):
    # T2 tem banner próprio no catálogo: vence o do provedor e o da T1.
    await _criar_anime(
        sessionmaker_api, "Slime Franquia", "slime-franquia", anilist_id=1,
        serie_ancora=10, numero_temporada=1, banner_path="https://catalogo/t1.jpg",
    )
    await _criar_anime(
        sessionmaker_api, "Slime Franquia 2", "slime-franquia-2", anilist_id=2,
        serie_ancora=10, numero_temporada=2, banner_path="https://catalogo/t2.jpg",
    )

    async def _listar_em_alta_fake():
        return [_feed_com_banner(2, banner_url="https://feed/t2.jpg", capa_cor="#e4a15d")]

    monkeypatch.setattr("integrations.servico.listar_em_alta", _listar_em_alta_fake)

    resposta = await cliente.get("/api/animes/em-alta")

    assert resposta.json()[0]["banner_url"] == "https://catalogo/t2.jpg"


@pytest.mark.parametrize(
    ("rota", "feed"),
    [
        ("/api/animes/em-alta", "listar_em_alta"),
        ("/api/animes/novos-lancamentos", "listar_novos_lancamentos"),
        ("/api/animes/proxima-temporada", "listar_proxima_temporada"),
    ],
)
async def test_feed_sincroniza_capa_do_catalogo_quando_a_anilist_troca(
    cliente: AsyncClient,
    sessionmaker_api: _SessionMaker,
    monkeypatch: pytest.MonkeyPatch,
    rota: str,
    feed: str,
):
    anime_id = await _criar_anime(
        sessionmaker_api, "Slime Capa", "slime-capa", anilist_id=1,
        capa_path="https://anilist/placeholder.jpg", capa_cor="#111111",
    )
    outro = await _criar_anime(
        sessionmaker_api, "Slime Igual", "slime-igual", anilist_id=2,
        capa_path="https://anilist/igual.jpg", capa_cor="#222222",
    )

    async def _feed_fake():
        return [
            AnimeEmAlta(
                titulo_romaji="Slime Capa", titulo_ingles=None, anilist_id=1,
                capa_url="https://anilist/oficial.jpg", banner_url=None, capa_cor="#e45dc9",
            ),
            AnimeEmAlta(
                titulo_romaji="Slime Igual", titulo_ingles=None, anilist_id=2,
                capa_url="https://anilist/igual.jpg", banner_url=None, capa_cor=None,
            ),
        ]

    monkeypatch.setattr(f"integrations.servico.{feed}", _feed_fake)

    resposta = await cliente.get(rota)

    assert resposta.status_code == 200
    async with sessionmaker_api() as sessao:
        trocada = await sessao.get(Anime, anime_id)
        igual = await sessao.get(Anime, outro)
    assert (trocada.capa_path, trocada.capa_cor) == ("https://anilist/oficial.jpg", "#e45dc9")
    # Capa igual não é reescrita, e `capa_cor` ausente no feed não zera a conhecida.
    assert (igual.capa_path, igual.capa_cor) == ("https://anilist/igual.jpg", "#222222")

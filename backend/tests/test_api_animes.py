"""Testes de `GET /api/admin/animes/{id}/episodios-remotos`
(`api/rotas/animes.py` -> `api/servicos/fontes.py`). Resolução de fonte remota é
monkeypatchada nos nomes importados em `api.servicos.fontes` — mesmo padrão de
`tests/test_api_jobs.py` para o modo "site" de criação de job.

Cobre também o detector de episódios novos (`api/servicos/lancamentos.py` +
`GET /api/animes` / `GET /api/animes/{id}`)."""

import asyncio
from datetime import UTC, date, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.servicos import sondagem
from api.servicos.catalogo import ids_com_episodios
from api.servicos.fontes import EpisodiosRemotosResultado
from api.servicos.lancamentos import episodios_novos, maior_numero_capturado_por_anime
from core.enums import StatusEpisodio, StatusLancamento, TipoEpisodio, VersaoDeFonte, VersaoEpisodio
from core.erros import FalhaDeExtracao
from extractors.base import EpisodioRemoto, ResultadoBusca
from extractors.resolucao import ConfirmacaoNecessaria, FonteResolvida
from integrations.base import AnimeEmAlta
from models.anime import Anime
from models.episodio import Episodio
from models.fonte_anime import FonteAnime

_SessionMaker = async_sessionmaker[AsyncSession]


async def _criar_anime(sessionmaker: _SessionMaker, titulo: str) -> int:
    async with sessionmaker() as sessao:
        anime = Anime(titulo=titulo, slug=titulo.lower().replace(" ", "-"))
        sessao.add(anime)
        await sessao.commit()
        return anime.id


async def test_listar_episodios_remotos_caminho_feliz(
    cliente: AsyncClient,
    sessionmaker_api: _SessionMaker,
    monkeypatch: pytest.MonkeyPatch,
):
    anime_id = await _criar_anime(sessionmaker_api, "Anime Remoto")

    async def _resolver_fake(sessionmaker, anime, versao):
        return FonteResolvida(
            dominio="animefire.io",
            identificador="42",
            versao_da_fonte=VersaoDeFonte.NAO_DIFERENCIADA,
        )

    async def _listar_fake(sessionmaker, dominio, identificador):
        return [
            EpisodioRemoto(
                rotulo="1",
                numero=1,
                url="https://x/ep1",
                thumb_url="https://animefire.io/img/video/42/1.webp",
            ),
            EpisodioRemoto(rotulo="2", numero=2, url="https://x/ep2"),
            EpisodioRemoto(rotulo="especial", numero=None, url="https://x/ep-especial"),
        ]

    monkeypatch.setattr("api.servicos.fontes.resolver_fonte_do_anime", _resolver_fake)
    monkeypatch.setattr("api.servicos.fontes.listar_episodios_em", _listar_fake)

    resposta = await cliente.get(f"/api/admin/animes/{anime_id}/episodios-remotos")

    assert resposta.status_code == 200
    assert resposta.json() == {
        "dominio": "animefire.io",
        "episodios": [
            {"rotulo": "1", "numero": 1, "thumb_url": "https://animefire.io/img/video/42/1.webp"},
            {"rotulo": "2", "numero": 2, "thumb_url": None},
            {"rotulo": "especial", "numero": None, "thumb_url": None},
        ],
    }


async def test_listar_episodios_remotos_fonte_ambigua_409(
    cliente: AsyncClient,
    sessionmaker_api: _SessionMaker,
    monkeypatch: pytest.MonkeyPatch,
):
    anime_id = await _criar_anime(sessionmaker_api, "Anime Remoto Ambíguo")

    async def _resolver_fake(sessionmaker, anime, versao):
        return ConfirmacaoNecessaria(
            dominio="animefire.io",
            candidatos=[
                ResultadoBusca(titulo_exibicao="A", identificador="1", url="https://x/1"),
                ResultadoBusca(titulo_exibicao="B", identificador="2", url="https://x/2"),
            ],
        )

    monkeypatch.setattr("api.servicos.fontes.resolver_fonte_do_anime", _resolver_fake)

    resposta = await cliente.get(f"/api/admin/animes/{anime_id}/episodios-remotos")

    assert resposta.status_code == 409
    assert resposta.json()["detail"]["motivo"] == "fonte_ambigua"


async def test_listar_episodios_remotos_anime_inexistente_404(cliente: AsyncClient):
    resposta = await cliente.get("/api/admin/animes/999999/episodios-remotos")

    assert resposta.status_code == 404


# --- detector de episódios novos: api/servicos/lancamentos.py ---


def _anime_em_memoria(**campos) -> Anime:
    return Anime(titulo="X", slug="x", **campos)


def _futuro() -> datetime:
    return datetime.now(UTC) + timedelta(days=1)


def test_episodios_novos_conta_acima_da_fronteira_acompanhada():
    anime = _anime_em_memoria(
        status_lancamento=StatusLancamento.EM_LANCAMENTO,
        episodios_na_fonte=5,
    )
    # fonte no ep 5, usuário acompanhou até o ep 3 -> 2 novos
    assert episodios_novos(anime, maior_capturado=3) == 2


def test_episodios_novos_ignora_buraco_abaixo_da_fronteira():
    # regressão: usuário foi direto ao ep 4 (eps 1-3 nunca capturados); a fonte
    # tem 4 eps -> fronteira 4, badge 0 (contagem de capturados daria 3)
    anime = _anime_em_memoria(
        status_lancamento=StatusLancamento.EM_LANCAMENTO,
        episodios_na_fonte=4,
    )
    assert episodios_novos(anime, maior_capturado=4) == 0


def test_episodios_novos_sem_captura_conta_a_fonte_inteira():
    anime = _anime_em_memoria(
        status_lancamento=StatusLancamento.EM_LANCAMENTO,
        episodios_na_fonte=6,
    )
    assert episodios_novos(anime, maior_capturado=0) == 6


def test_episodios_novos_zero_para_status_diferente_de_em_lancamento():
    anime = _anime_em_memoria(
        status_lancamento=StatusLancamento.FINALIZADO, episodios_na_fonte=12
    )
    assert episodios_novos(anime, maior_capturado=0) == 0


def test_episodios_novos_zero_quando_contagem_da_fonte_nula():
    anime = _anime_em_memoria(
        status_lancamento=StatusLancamento.EM_LANCAMENTO,
        episodios_na_fonte=None,
    )
    assert episodios_novos(anime, maior_capturado=0) == 0


def test_episodios_novos_zero_quando_status_lancamento_nulo():
    # `None is not EM_LANCAMENTO` -> 0, mesmo com a contagem da fonte conhecida e
    # `proximo_ep_em` no futuro (que antes fazia o `None` passar pela perna 1)
    anime = _anime_em_memoria(
        status_lancamento=None, episodios_na_fonte=6, proximo_ep_em=_futuro()
    )
    assert episodios_novos(anime, maior_capturado=0) == 0


def test_episodios_novos_nao_fica_negativo():
    # fonte largou episódios antigos: episodios_na_fonte abaixo da fronteira
    anime = _anime_em_memoria(
        status_lancamento=StatusLancamento.EM_LANCAMENTO,
        episodios_na_fonte=3,
    )
    assert episodios_novos(anime, maior_capturado=5) == 0


def test_episodios_novos_em_lancamento_sem_dados_anilist_conta_a_fonte():
    # caso Hanaori-san (id 19): `EM_LANCAMENTO` sem `anilist_id` /
    # `total_episodios_anilist` / `proximo_ep_em`. A sub-trava de sinal-vivo
    # (removida) zerava o badge; agora só a fronteira `MAX(numero)` decide.
    anime = _anime_em_memoria(
        status_lancamento=StatusLancamento.EM_LANCAMENTO,
        anilist_id=None,
        total_episodios_anilist=None,
        proximo_ep_em=None,
        episodios_na_fonte=8,
    )
    assert episodios_novos(anime, maior_capturado=6) == 2


# --- detector de episódios novos: fronteira em lote + GET /api/animes ---


async def _criar_anime_catalogado(
    sessionmaker: _SessionMaker,
    titulo: str,
    *,
    status_lancamento: StatusLancamento | None = None,
    episodios_na_fonte: int | None = None,
    fonte_verificada_em: datetime | None = None,
    proximo_ep_em: datetime | None = None,
    estreia_em: date | None = None,
) -> int:
    async with sessionmaker() as sessao:
        anime = Anime(
            titulo=titulo,
            slug=titulo.lower().replace(" ", "-"),
            status_lancamento=status_lancamento,
            episodios_na_fonte=episodios_na_fonte,
            fonte_verificada_em=fonte_verificada_em,
            proximo_ep_em=proximo_ep_em,
            estreia_em=estreia_em,
        )
        sessao.add(anime)
        await sessao.commit()
        return anime.id


async def _mapear_fonte(
    sessionmaker: _SessionMaker,
    anime_id: int,
    *,
    dominio: str = "site.io",
    versao: VersaoDeFonte = VersaoDeFonte.LEGENDADO,
) -> None:
    async with sessionmaker() as sessao:
        sessao.add(
            FonteAnime(
                anime_id=anime_id,
                site_dominio=dominio,
                versao=versao,
                identificador_no_site="id-no-site",
                prioridade=0,
            )
        )
        await sessao.commit()


def _ep_remoto(rotulo: str, numero: int | None) -> EpisodioRemoto:
    return EpisodioRemoto(rotulo=rotulo, numero=numero, url=f"https://x/{rotulo}")


async def _drenar_sondagens() -> None:
    """Aguarda toda `Task` de sondagem fire-and-forget em voo terminar. `gather`
    sem `return_exceptions`: re-levanta se `_sondar_e_persistir` deixar escapar
    exceção."""
    for _ in range(20):
        pendentes = [t for t in sondagem._sondagens_em_voo.values() if not t.done()]
        if not pendentes:
            break
        await asyncio.gather(*pendentes)
    await asyncio.sleep(0)


async def _capturar_episodio(
    sessionmaker: _SessionMaker,
    anime_id: int,
    *,
    numero: int,
    tipo: TipoEpisodio = TipoEpisodio.REGULAR,
    versao: VersaoEpisodio = VersaoEpisodio.LEGENDADO,
    status: StatusEpisodio = StatusEpisodio.PRONTO,
) -> None:
    async with sessionmaker() as sessao:
        sessao.add(
            Episodio(
                anime_id=anime_id,
                numero=numero,
                tipo=tipo,
                versao=versao,
                url_fonte="/x.mkv",
                site_origem="local",
                status=status,
            )
        )
        await sessao.commit()


async def test_maior_numero_capturado_por_anime_ignora_versao_tipo_e_status(
    sessionmaker_api: _SessionMaker,
):
    anime_id = await _criar_anime_catalogado(sessionmaker_api, "Anime Fronteira")
    # ep 1 legendado + dublado: duas linhas, mesma fronteira
    await _capturar_episodio(sessionmaker_api, anime_id, numero=1, versao=VersaoEpisodio.LEGENDADO)
    await _capturar_episodio(sessionmaker_api, anime_id, numero=1, versao=VersaoEpisodio.DUBLADO)
    await _capturar_episodio(sessionmaker_api, anime_id, numero=2)
    # ep 3 nunca capturado (buraco); ep 4 LIBERADO leva a fronteira a 4
    await _capturar_episodio(sessionmaker_api, anime_id, numero=4, status=StatusEpisodio.LIBERADO)
    # ep 5 só PENDENTE: não é captura utilizável, não move a fronteira
    await _capturar_episodio(sessionmaker_api, anime_id, numero=5, status=StatusEpisodio.PENDENTE)
    # OVA de número maior não conta (numeração própria)
    await _capturar_episodio(sessionmaker_api, anime_id, numero=9, tipo=TipoEpisodio.OVA)

    async with sessionmaker_api() as sessao:
        fronteira = await maior_numero_capturado_por_anime(sessao, [anime_id])

    assert fronteira == {anime_id: 4}  # maior numero REGULAR PRONTO/LIBERADO


async def test_maior_numero_capturado_por_anime_lista_vazia(sessionmaker_api: _SessionMaker):
    async with sessionmaker_api() as sessao:
        assert await maior_numero_capturado_por_anime(sessao, []) == {}


async def test_maior_numero_capturado_por_anime_id_ausente_e_zero(sessionmaker_api: _SessionMaker):
    anime_id = await _criar_anime_catalogado(sessionmaker_api, "Anime Sem Episodio")

    async with sessionmaker_api() as sessao:
        fronteira = await maior_numero_capturado_por_anime(sessao, [anime_id])

    assert fronteira == {}


# --- rótulo de estreia do card de bookmark: catalogo.ids_com_episodios ---


async def test_ids_com_episodios_lista_vazia_devolve_set_vazio(sessionmaker_api: _SessionMaker):
    # Guard de lista vazia (`IN ()` inválido no SQLite): retorna antes de tocar
    # o banco.
    async with sessionmaker_api() as sessao:
        assert await ids_com_episodios(sessao, []) == set()


async def test_ids_com_episodios_conta_qualquer_linha_sem_filtrar_status(
    sessionmaker_api: _SessionMaker,
):
    # Ao contrário de `maior_numero_capturado_por_anime`, não filtra tipo/status:
    # uma captura só `PENDENTE` conta como "tem episódio".
    com_pendente = await _criar_anime_catalogado(sessionmaker_api, "Anime Pendente Cru")
    com_pronto = await _criar_anime_catalogado(sessionmaker_api, "Anime Pronto Cru")
    sem_nada = await _criar_anime_catalogado(sessionmaker_api, "Anime Sem Nada Cru")

    await _capturar_episodio(
        sessionmaker_api, com_pendente, numero=1, status=StatusEpisodio.PENDENTE
    )
    await _capturar_episodio(sessionmaker_api, com_pronto, numero=1)

    async with sessionmaker_api() as sessao:
        resultado = await ids_com_episodios(sessao, [com_pendente, com_pronto, sem_nada])

    assert resultado == {com_pendente, com_pronto}


async def test_listar_animes_calcula_episodios_novos_por_anime_em_uma_resposta(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker
):
    em_lancamento = await _criar_anime_catalogado(
        sessionmaker_api,
        "Anime Em Lancamento",
        status_lancamento=StatusLancamento.EM_LANCAMENTO,
        episodios_na_fonte=4,
        proximo_ep_em=_futuro(),
    )
    finalizado = await _criar_anime_catalogado(
        sessionmaker_api,
        "Anime Finalizado",
        status_lancamento=StatusLancamento.FINALIZADO,
        episodios_na_fonte=8,
    )
    await _capturar_episodio(sessionmaker_api, em_lancamento, numero=1)
    await _capturar_episodio(
        sessionmaker_api, em_lancamento, numero=1, versao=VersaoEpisodio.DUBLADO
    )
    await _capturar_episodio(sessionmaker_api, em_lancamento, numero=2)

    resposta = await cliente.get("/api/animes")

    assert resposta.status_code == 200
    por_id = {item["id"]: item for item in resposta.json()}
    assert por_id[em_lancamento]["episodios_novos"] == 2  # 4 na fonte, fronteira no ep 2
    assert por_id[em_lancamento]["status_lancamento"] == "em_lancamento"
    assert por_id[finalizado]["episodios_novos"] == 0  # status != EM_LANCAMENTO
    assert por_id[finalizado]["status_lancamento"] == "finalizado"


async def test_listar_animes_badge_zero_quando_usuario_pulou_episodios_antigos(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker
):
    """Regressão: usuário foi direto ao ep 4 (eps 1-3 nunca capturados). A fonte
    tem 4 eps -> badge 0, não 3 (a contagem de capturados daria 3)."""
    anime_id = await _criar_anime_catalogado(
        sessionmaker_api,
        "Anime Pulou Antigos",
        status_lancamento=StatusLancamento.EM_LANCAMENTO,
        episodios_na_fonte=4,
        proximo_ep_em=_futuro(),
    )
    await _capturar_episodio(sessionmaker_api, anime_id, numero=4)

    resposta = await cliente.get("/api/animes")

    assert resposta.status_code == 200
    item = next(i for i in resposta.json() if i["id"] == anime_id)
    assert item["episodios_novos"] == 0


async def test_listar_animes_preserva_campos_e_defaults_sem_lancamento(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker
):
    anime_id = await _criar_anime_catalogado(sessionmaker_api, "Anime Sem Lancamento")

    resposta = await cliente.get("/api/animes")

    assert resposta.status_code == 200
    item = next(i for i in resposta.json() if i["id"] == anime_id)
    assert item["slug"] == "anime-sem-lancamento"
    assert item["titulo"] == "Anime Sem Lancamento"
    assert "capa_path" in item
    assert "criado_em" in item
    assert item["status_lancamento"] is None
    assert item["episodios_novos"] == 0


async def test_listar_animes_expoe_tem_episodios_e_proximo_ep_em_numa_resposta(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker
):
    """`tem_episodios` conta QUALQUER linha de `Episodio` (rótulo de estreia do
    card de bookmark) — sem o filtro tipo/status de `maior_numero_capturado`: um
    episódio só `PENDENTE` (captura em andamento) e um episódio `numero=0` — as
    duas armadilhas — contam. `proximo_ep_em` sai serializado 1:1 da coluna
    homônima (ISO string), ou `None` quando ausente, na mesma resposta."""
    quando = datetime(2027, 1, 15, 12, 0, tzinfo=UTC)
    so_pendente = await _criar_anime_catalogado(
        sessionmaker_api, "Anime So Pendente", proximo_ep_em=quando
    )
    sem_episodio = await _criar_anime_catalogado(sessionmaker_api, "Anime Sem Episodio Algum")
    so_numero_zero = await _criar_anime_catalogado(sessionmaker_api, "Anime So Numero Zero")

    await _capturar_episodio(
        sessionmaker_api, so_pendente, numero=1, status=StatusEpisodio.PENDENTE
    )
    await _capturar_episodio(sessionmaker_api, so_numero_zero, numero=0)

    resposta = await cliente.get("/api/animes")

    assert resposta.status_code == 200
    por_id = {item["id"]: item for item in resposta.json()}

    assert por_id[so_pendente]["tem_episodios"] is True
    proximo_ep_em_bruto = por_id[so_pendente]["proximo_ep_em"]
    assert proximo_ep_em_bruto is not None
    assert datetime.fromisoformat(proximo_ep_em_bruto) == quando

    assert por_id[sem_episodio]["tem_episodios"] is False
    assert por_id[sem_episodio]["proximo_ep_em"] is None

    assert por_id[so_numero_zero]["tem_episodios"] is True


async def test_listar_animes_expoe_estreia_em_de_bookmark_nao_lancado(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker
):
    """Bookmark de "Próximas estreias" (`NAO_LANCADO`, sem `proximo_ep_em` ainda)
    com `estreia_em` no futuro: a coluna sai serializada 1:1 (ISO `YYYY-MM-DD`)
    em `GET /api/animes` para o card de bookmark montar o rótulo de data exata."""
    estreia = date(2027, 4, 15)
    com_estreia = await _criar_anime_catalogado(
        sessionmaker_api,
        "Anime Com Estreia",
        status_lancamento=StatusLancamento.NAO_LANCADO,
        estreia_em=estreia,
    )
    sem_estreia = await _criar_anime_catalogado(sessionmaker_api, "Anime Sem Estreia Col")

    resposta = await cliente.get("/api/animes")

    assert resposta.status_code == 200
    por_id = {item["id"]: item for item in resposta.json()}
    assert por_id[com_estreia]["estreia_em"] == "2027-04-15"
    assert por_id[sem_estreia]["estreia_em"] is None


async def test_obter_anime_detalhe_expoe_status_lancamento_mas_nunca_o_badge(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker
):
    anime_id = await _criar_anime_catalogado(
        sessionmaker_api,
        "Anime Detalhe Status",
        status_lancamento=StatusLancamento.EM_LANCAMENTO,
        episodios_na_fonte=3,
    )
    await _capturar_episodio(sessionmaker_api, anime_id, numero=1)

    resposta = await cliente.get(f"/api/animes/{anime_id}")

    assert resposta.status_code == 200
    assert resposta.json()["status_lancamento"] == "em_lancamento"
    # `episodios_novos` é badge só da galeria (`GET /api/animes`) — o detalhe
    # nunca expõe, mesmo no estado que na galeria daria badge 2.
    assert "episodios_novos" not in resposta.json()


async def test_obter_anime_detalhe_expoe_banner_e_capa_cor(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker
):
    async with sessionmaker_api() as sessao:
        anime = Anime(
            titulo="Anime Com Hero",
            slug="anime-com-hero",
            banner_path="https://img/banner.jpg",
            capa_cor="#e4a15d",
        )
        sessao.add(anime)
        await sessao.commit()
        anime_id = anime.id

    resposta = await cliente.get(f"/api/animes/{anime_id}")

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["banner_path"] == "https://img/banner.jpg"
    assert corpo["capa_cor"] == "#e4a15d"


async def test_obter_anime_detalhe_banner_e_capa_cor_null_por_padrao(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker
):
    anime_id = await _criar_anime_catalogado(sessionmaker_api, "Anime Sem Hero")

    resposta = await cliente.get(f"/api/animes/{anime_id}")

    assert resposta.status_code == 200
    assert resposta.json()["banner_path"] is None
    assert resposta.json()["capa_cor"] is None


async def test_obter_anime_detalhe_expoe_generos(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker
):
    async with sessionmaker_api() as sessao:
        anime = Anime(
            titulo="Anime Com Generos",
            slug="anime-com-generos",
            generos=["Action", "Comedy"],
        )
        sessao.add(anime)
        await sessao.commit()
        anime_id = anime.id

    resposta = await cliente.get(f"/api/animes/{anime_id}")

    assert resposta.status_code == 200
    assert resposta.json()["generos"] == ["Action", "Comedy"]


async def test_obter_anime_detalhe_generos_lista_vazia_por_padrao(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker
):
    anime_id = await _criar_anime_catalogado(sessionmaker_api, "Anime Sem Generos")

    resposta = await cliente.get(f"/api/animes/{anime_id}")

    assert resposta.status_code == 200
    assert resposta.json()["generos"] == []


async def test_em_alta_nao_expoe_o_badge_episodios_novos(
    cliente: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """`episodios_novos` é badge derivado só da galeria (`GET /api/animes`) — o
    feed "em alta" nunca o expõe. `status_lancamento` (e o resto do trio de
    lançamento), ao contrário, entrou no feed a partir da B2 para a tagline do
    carrossel; aqui o item não traz bloco, então sai `null`."""
    item = AnimeEmAlta(
        titulo_romaji="Em Alta",
        titulo_ingles=None,
        capa_url=None,
        banner_url=None,
        anilist_id=1,
    )

    async def _listar_fake(sessionmaker):
        return [(item, None)]

    monkeypatch.setattr("api.servicos.descoberta.listar_em_alta_com_catalogo", _listar_fake)

    resposta = await cliente.get("/api/animes/em-alta")

    assert resposta.status_code == 200
    corpo = resposta.json()[0]
    assert "episodios_novos" not in corpo
    assert corpo["status_lancamento"] is None


async def test_proxima_temporada_shape_e_ordem_de_rotas(
    cliente: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """`GET /api/animes/proxima-temporada` resolve para a rota do feed (não é
    lido como `anime_id="proxima-temporada"` por `/{anime_id}`) e devolve o
    shape de `AnimeEmAltaSaida`."""
    item = AnimeEmAlta(
        titulo_romaji="Próxima Estreia",
        titulo_ingles="Next Premiere",
        capa_url="https://img/p.jpg",
        banner_url=None,
        anilist_id=1,
        capa_cor="#e4a15d",
    )

    async def _listar_fake(sessionmaker):
        return [(item, None)]

    monkeypatch.setattr(
        "api.servicos.descoberta.listar_proxima_temporada_com_catalogo", _listar_fake
    )

    resposta = await cliente.get("/api/animes/proxima-temporada")

    assert resposta.status_code == 200
    corpo = resposta.json()[0]
    assert corpo == {
        "titulo_romaji": "Próxima Estreia",
        "titulo_ingles": "Next Premiere",
        "capa_url": "https://img/p.jpg",
        "banner_url": None,
        "anilist_id": 1,
        "anime_id": None,
        "ano_estreia": None,
        "generos": [],
        "capa_cor": "#e4a15d",
        "status_lancamento": None,
        "proximo_ep_numero": None,
        "proximo_ep_em": None,
    }


# --- F12: GET /api/animes* agenda sondagem fire-and-forget da fonte real ---


def _espiar_sondagem(
    monkeypatch: pytest.MonkeyPatch,
    *,
    episodios: list[EpisodioRemoto] | None = None,
    dominio: str = "animefire.io",
    erro: Exception | None = None,
) -> list[tuple[int, VersaoEpisodio]]:
    """Troca `sondagem.listar_episodios_remotos` por um espião: registra
    `(anime.id, versao)` e devolve um resultado fixo (ou levanta `erro`) — nunca
    toca extractor/rede real."""
    chamadas: list[tuple[int, VersaoEpisodio]] = []

    async def _fake(sessionmaker, anime, versao):
        chamadas.append((anime.id, versao))
        if erro is not None:
            raise erro
        return EpisodiosRemotosResultado(dominio=dominio, episodios=episodios or [])

    monkeypatch.setattr("api.servicos.sondagem.listar_episodios_remotos", _fake)
    return chamadas


async def test_listar_animes_agenda_sondagem_e_badge_atualiza_na_proxima_leitura(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker, monkeypatch: pytest.MonkeyPatch
):
    chamadas = _espiar_sondagem(
        monkeypatch, episodios=[_ep_remoto("1", 1), _ep_remoto("2", 2), _ep_remoto("3", 3)]
    )
    anime_id = await _criar_anime_catalogado(
        sessionmaker_api,
        "Anime Sondavel",
        status_lancamento=StatusLancamento.EM_LANCAMENTO,
        episodios_na_fonte=1,
        proximo_ep_em=_futuro(),
    )
    await _mapear_fonte(sessionmaker_api, anime_id)
    await _capturar_episodio(sessionmaker_api, anime_id, numero=1)

    primeira = await cliente.get("/api/animes")
    assert primeira.status_code == 200
    item = next(i for i in primeira.json() if i["id"] == anime_id)
    assert item["episodios_novos"] == 0  # badge desta leitura: 1 na fonte, fronteira no ep 1

    await _drenar_sondagens()
    assert chamadas == [(anime_id, VersaoEpisodio.LEGENDADO)]
    async with sessionmaker_api() as sessao:
        anime = await sessao.get(Anime, anime_id)
        assert anime.episodios_na_fonte == 3
        assert anime.fonte_verificada_dominio == "animefire.io"

    segunda = await cliente.get("/api/animes")
    item = next(i for i in segunda.json() if i["id"] == anime_id)
    assert item["episodios_novos"] == 2  # 3 na fonte, fronteira no ep 1


async def test_listar_animes_nao_agenda_sondagem_dentro_do_ttl(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker, monkeypatch: pytest.MonkeyPatch
):
    chamadas = _espiar_sondagem(monkeypatch)
    anime_id = await _criar_anime_catalogado(
        sessionmaker_api,
        "Anime Fonte Fresca",
        status_lancamento=StatusLancamento.EM_LANCAMENTO,
        episodios_na_fonte=2,
        fonte_verificada_em=datetime.now(UTC) - timedelta(hours=1),
    )
    await _mapear_fonte(sessionmaker_api, anime_id)

    resposta = await cliente.get("/api/animes")
    await _drenar_sondagens()

    assert resposta.status_code == 200
    assert chamadas == []


async def test_listar_animes_responde_200_com_badge_antigo_quando_sondagem_falha(
    cliente: AsyncClient,
    sessionmaker_api: _SessionMaker,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    _espiar_sondagem(monkeypatch, erro=FalhaDeExtracao("site fora do ar"))
    anime_id = await _criar_anime_catalogado(
        sessionmaker_api,
        "Anime Home Blindada",
        status_lancamento=StatusLancamento.EM_LANCAMENTO,
        episodios_na_fonte=5,
        proximo_ep_em=_futuro(),
    )
    await _mapear_fonte(sessionmaker_api, anime_id)

    with caplog.at_level("WARNING"):
        resposta = await cliente.get("/api/animes")
        assert resposta.status_code == 200
        item = next(i for i in resposta.json() if i["id"] == anime_id)
        assert item["episodios_novos"] == 5  # badge antigo; falha de site não derruba a home
        await _drenar_sondagens()  # gather sem return_exceptions: re-levantaria se propagasse

    assert "sondagem de fonte falhou" in caplog.text
    async with sessionmaker_api() as sessao:
        anime = await sessao.get(Anime, anime_id)
        assert anime.episodios_na_fonte == 5  # intacto
        assert anime.fonte_verificada_em is None


async def test_listar_animes_duas_chamadas_concorrentes_deduplicam_sondagem(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker, monkeypatch: pytest.MonkeyPatch
):
    chamadas = _espiar_sondagem(monkeypatch)
    anime_id = await _criar_anime_catalogado(
        sessionmaker_api, "Anime Dedupe Rota", status_lancamento=StatusLancamento.EM_LANCAMENTO
    )
    await _mapear_fonte(sessionmaker_api, anime_id)

    await asyncio.gather(cliente.get("/api/animes"), cliente.get("/api/animes"))
    await _drenar_sondagens()

    assert chamadas == [(anime_id, VersaoEpisodio.LEGENDADO)]  # 1 task, não 2


async def test_obter_anime_sem_linha_em_fonte_anime_nao_agenda_sondagem(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker, monkeypatch: pytest.MonkeyPatch
):
    chamadas = _espiar_sondagem(monkeypatch)
    anime_id = await _criar_anime_catalogado(
        sessionmaker_api,
        "Anime Detalhe Sem Fonte",
        status_lancamento=StatusLancamento.EM_LANCAMENTO,
        episodios_na_fonte=3,
    )

    resposta = await cliente.get(f"/api/animes/{anime_id}")
    await _drenar_sondagens()

    assert resposta.status_code == 200
    assert chamadas == []
    assert sondagem._sondagens_em_voo == {}

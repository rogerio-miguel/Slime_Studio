"""Testes de `GET /api/admin/animes/{id}/episodios-remotos`
(`api/rotas/animes.py` -> `api/servicos/fontes.py`). Resolução de fonte remota é
monkeypatchada nos nomes importados em `api.servicos.fontes` — mesmo padrão de
`tests/test_api_jobs.py` para o modo "site" de criação de job.

Cobre também o detector de episódios novos (`api/servicos/lancamentos.py` +
`GET /api/animes` / `GET /api/animes/{id}`)."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.servicos import sondagem
from api.servicos.fontes import EpisodiosRemotosResultado
from api.servicos.lancamentos import contar_capturados_por_anime, episodios_novos
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
            EpisodioRemoto(rotulo="1", numero=1, url="https://x/ep1"),
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
            {"rotulo": "1", "numero": 1},
            {"rotulo": "2", "numero": 2},
            {"rotulo": "especial", "numero": None},
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


def test_episodios_novos_em_lancamento_desconta_capturados():
    anime = _anime_em_memoria(
        status_lancamento=StatusLancamento.EM_LANCAMENTO, episodios_na_fonte=4
    )
    # 4 disponíveis na fonte, 2 capturados -> 2 novos
    assert episodios_novos(anime, capturados=2) == 2


def test_episodios_novos_zero_para_status_diferente_de_em_lancamento():
    anime = _anime_em_memoria(
        status_lancamento=StatusLancamento.FINALIZADO, episodios_na_fonte=12
    )
    assert episodios_novos(anime, capturados=0) == 0


def test_episodios_novos_zero_quando_contagem_da_fonte_nula():
    anime = _anime_em_memoria(
        status_lancamento=StatusLancamento.EM_LANCAMENTO, episodios_na_fonte=None
    )
    assert episodios_novos(anime, capturados=0) == 0


def test_episodios_novos_zero_quando_status_nulo_mesmo_com_contagem_da_fonte():
    # filtro estrito: só `EM_LANCAMENTO` ganha badge, nem `None` com contagem
    anime = _anime_em_memoria(status_lancamento=None, episodios_na_fonte=6)
    assert episodios_novos(anime, capturados=0) == 0


def test_episodios_novos_nao_fica_negativo():
    anime = _anime_em_memoria(
        status_lancamento=StatusLancamento.EM_LANCAMENTO, episodios_na_fonte=3
    )
    assert episodios_novos(anime, capturados=5) == 0


# --- detector de episódios novos: contagem em lote + GET /api/animes ---


async def _criar_anime_catalogado(
    sessionmaker: _SessionMaker,
    titulo: str,
    *,
    status_lancamento: StatusLancamento | None = None,
    episodios_na_fonte: int | None = None,
    fonte_verificada_em: datetime | None = None,
) -> int:
    async with sessionmaker() as sessao:
        anime = Anime(
            titulo=titulo,
            slug=titulo.lower().replace(" ", "-"),
            status_lancamento=status_lancamento,
            episodios_na_fonte=episodios_na_fonte,
            fonte_verificada_em=fonte_verificada_em,
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


async def test_contar_capturados_por_anime_distinct_numero_tipo_e_status(
    sessionmaker_api: _SessionMaker,
):
    anime_id = await _criar_anime_catalogado(sessionmaker_api, "Anime Contagem")
    # ep 1 legendado + dublado = 2 linhas, 1 capturado
    await _capturar_episodio(sessionmaker_api, anime_id, numero=1, versao=VersaoEpisodio.LEGENDADO)
    await _capturar_episodio(sessionmaker_api, anime_id, numero=1, versao=VersaoEpisodio.DUBLADO)
    await _capturar_episodio(sessionmaker_api, anime_id, numero=2)
    # LIBERADO também conta como capturado
    await _capturar_episodio(sessionmaker_api, anime_id, numero=4, status=StatusEpisodio.LIBERADO)
    # PENDENTE ainda não é captura utilizável
    await _capturar_episodio(sessionmaker_api, anime_id, numero=3, status=StatusEpisodio.PENDENTE)
    # OVA de mesmo número não conta (numeração própria)
    await _capturar_episodio(sessionmaker_api, anime_id, numero=1, tipo=TipoEpisodio.OVA)

    async with sessionmaker_api() as sessao:
        contagem = await contar_capturados_por_anime(sessao, [anime_id])

    assert contagem == {anime_id: 3}  # números REGULAR capturados: 1, 2, 4


async def test_contar_capturados_por_anime_lista_vazia(sessionmaker_api: _SessionMaker):
    async with sessionmaker_api() as sessao:
        assert await contar_capturados_por_anime(sessao, []) == {}


async def test_contar_capturados_por_anime_id_ausente_e_zero(sessionmaker_api: _SessionMaker):
    anime_id = await _criar_anime_catalogado(sessionmaker_api, "Anime Sem Episodio")

    async with sessionmaker_api() as sessao:
        contagem = await contar_capturados_por_anime(sessao, [anime_id])

    assert contagem == {}


async def test_listar_animes_calcula_episodios_novos_por_anime_em_uma_resposta(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker
):
    em_lancamento = await _criar_anime_catalogado(
        sessionmaker_api,
        "Anime Em Lancamento",
        status_lancamento=StatusLancamento.EM_LANCAMENTO,
        episodios_na_fonte=4,
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
    assert por_id[em_lancamento]["episodios_novos"] == 2  # 4 na fonte - 2 capturados
    assert por_id[em_lancamento]["status_lancamento"] == "em_lancamento"
    assert por_id[finalizado]["episodios_novos"] == 0  # status != EM_LANCAMENTO
    assert por_id[finalizado]["status_lancamento"] == "finalizado"


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


async def test_obter_anime_detalhe_inclui_episodios_novos(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker
):
    anime_id = await _criar_anime_catalogado(
        sessionmaker_api,
        "Anime Detalhe Novos",
        status_lancamento=StatusLancamento.EM_LANCAMENTO,
        episodios_na_fonte=3,
    )
    await _capturar_episodio(sessionmaker_api, anime_id, numero=1)

    resposta = await cliente.get(f"/api/animes/{anime_id}")

    assert resposta.status_code == 200
    assert resposta.json()["episodios_novos"] == 2  # 3 na fonte - 1 capturado
    assert resposta.json()["status_lancamento"] == "em_lancamento"


async def test_em_alta_nao_ganha_campos_do_detector(
    cliente: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
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
    assert "status_lancamento" not in corpo


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
    )
    await _mapear_fonte(sessionmaker_api, anime_id)
    await _capturar_episodio(sessionmaker_api, anime_id, numero=1)

    primeira = await cliente.get("/api/animes")
    assert primeira.status_code == 200
    item = next(i for i in primeira.json() if i["id"] == anime_id)
    assert item["episodios_novos"] == 0  # badge desta leitura: 1 na fonte - 1 capturado

    await _drenar_sondagens()
    assert chamadas == [(anime_id, VersaoEpisodio.LEGENDADO)]
    async with sessionmaker_api() as sessao:
        anime = await sessao.get(Anime, anime_id)
        assert anime.episodios_na_fonte == 3
        assert anime.fonte_verificada_dominio == "animefire.io"

    segunda = await cliente.get("/api/animes")
    item = next(i for i in segunda.json() if i["id"] == anime_id)
    assert item["episodios_novos"] == 2  # 3 na fonte - 1 capturado


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

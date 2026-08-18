"""Feature "continuar assistindo": `api/servicos/progresso.py::listar_continuar_assistindo`
(inclusão/exclusão por status e pelo limiar de 90%) e as rotas
`GET /api/episodios/continuar-assistindo`, `GET /api/episodios/{id}` e
`POST /api/episodios/{id}/progresso` (`api/rotas/episodios.py`)."""

from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.servicos.progresso import listar_continuar_assistindo
from core.enums import StatusEpisodio, TipoEpisodio, VersaoEpisodio
from models.anime import Anime
from models.episodio import Episodio

_SessionMaker = async_sessionmaker[AsyncSession]


async def _criar_anime(sessionmaker: _SessionMaker, titulo: str) -> int:
    slug = titulo.lower().replace(" ", "-")
    async with sessionmaker() as sessao:
        anime = Anime(titulo=titulo, slug=slug)
        sessao.add(anime)
        await sessao.commit()
        return anime.id


async def _criar_episodio(
    sessionmaker: _SessionMaker,
    anime_id: int,
    *,
    numero: int = 1,
    status: StatusEpisodio = StatusEpisodio.PRONTO,
    duracao_s: int | None = 1200,
    progresso_s: int | None = None,
    progresso_atualizado_em: datetime | None = None,
) -> int:
    async with sessionmaker() as sessao:
        episodio = Episodio(
            anime_id=anime_id,
            numero=numero,
            tipo=TipoEpisodio.REGULAR,
            versao=VersaoEpisodio.LEGENDADO,
            url_fonte="/qualquer.mkv",
            site_origem="local",
            status=status,
            hls_path="qualquer/master.m3u8" if status == StatusEpisodio.PRONTO else None,
            duracao_s=duracao_s,
            progresso_s=progresso_s,
            progresso_atualizado_em=progresso_atualizado_em,
        )
        sessao.add(episodio)
        await sessao.commit()
        return episodio.id


# --- api/servicos/progresso.py::listar_continuar_assistindo ---


async def test_listar_continuar_assistindo_inclui_pronto_com_progresso_abaixo_do_limiar(
    sessionmaker_api: _SessionMaker,
):
    anime_id = await _criar_anime(sessionmaker_api, "Anime Continuar")
    episodio_id = await _criar_episodio(
        sessionmaker_api,
        anime_id,
        duracao_s=1200,
        progresso_s=600,
        progresso_atualizado_em=datetime.now(UTC),
    )

    linhas = await listar_continuar_assistindo(sessionmaker_api)

    assert [linha.episodio_id for linha in linhas] == [episodio_id]


async def test_listar_continuar_assistindo_exclui_sem_progresso(sessionmaker_api: _SessionMaker):
    anime_id = await _criar_anime(sessionmaker_api, "Anime Sem Progresso")
    await _criar_episodio(sessionmaker_api, anime_id, progresso_s=None)

    linhas = await listar_continuar_assistindo(sessionmaker_api)

    assert linhas == []


async def test_listar_continuar_assistindo_exclui_status_diferente_de_pronto(
    sessionmaker_api: _SessionMaker,
):
    anime_id = await _criar_anime(sessionmaker_api, "Anime Liberado")
    await _criar_episodio(
        sessionmaker_api,
        anime_id,
        status=StatusEpisodio.LIBERADO,
        progresso_s=300,
        progresso_atualizado_em=datetime.now(UTC),
    )

    linhas = await listar_continuar_assistindo(sessionmaker_api)

    assert linhas == []


async def test_listar_continuar_assistindo_exclui_acima_do_limiar_de_90_pct(
    sessionmaker_api: _SessionMaker,
):
    anime_id = await _criar_anime(sessionmaker_api, "Anime Quase Terminado")
    await _criar_episodio(
        sessionmaker_api,
        anime_id,
        duracao_s=1200,
        progresso_s=1100,  # 91.6% — acima do limiar
        progresso_atualizado_em=datetime.now(UTC),
    )

    linhas = await listar_continuar_assistindo(sessionmaker_api)

    assert linhas == []


async def test_listar_continuar_assistindo_inclui_sem_duracao_conhecida(
    sessionmaker_api: _SessionMaker,
):
    anime_id = await _criar_anime(sessionmaker_api, "Anime Sem Duracao")
    episodio_id = await _criar_episodio(
        sessionmaker_api,
        anime_id,
        duracao_s=None,
        progresso_s=600,
        progresso_atualizado_em=datetime.now(UTC),
    )

    linhas = await listar_continuar_assistindo(sessionmaker_api)

    assert [linha.episodio_id for linha in linhas] == [episodio_id]


async def test_listar_continuar_assistindo_ordena_por_atualizacao_mais_recente(
    sessionmaker_api: _SessionMaker,
):
    anime_id = await _criar_anime(sessionmaker_api, "Anime Ordenacao")
    agora = datetime.now(UTC)
    mais_antigo_id = await _criar_episodio(
        sessionmaker_api,
        anime_id,
        numero=1,
        progresso_s=100,
        progresso_atualizado_em=agora - timedelta(hours=1),
    )
    mais_recente_id = await _criar_episodio(
        sessionmaker_api, anime_id, numero=2, progresso_s=100, progresso_atualizado_em=agora
    )

    linhas = await listar_continuar_assistindo(sessionmaker_api)

    assert [linha.episodio_id for linha in linhas] == [mais_recente_id, mais_antigo_id]


# --- GET /api/episodios/continuar-assistindo ---


async def test_rota_continuar_assistindo_devolve_itens_esperados(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker
):
    anime_id = await _criar_anime(sessionmaker_api, "Anime Rota Continuar")
    episodio_id = await _criar_episodio(
        sessionmaker_api,
        anime_id,
        numero=3,
        duracao_s=1200,
        progresso_s=600,
        progresso_atualizado_em=datetime.now(UTC),
    )

    resposta = await cliente.get("/api/episodios/continuar-assistindo")

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert len(corpo) == 1
    assert corpo[0]["episodio_id"] == episodio_id
    assert corpo[0]["anime_id"] == anime_id
    assert corpo[0]["numero"] == 3
    assert corpo[0]["progresso_s"] == 600
    assert corpo[0]["duracao_s"] == 1200


# --- GET /api/episodios/{id} ---


async def test_obter_episodio_devolve_dados(cliente: AsyncClient, sessionmaker_api: _SessionMaker):
    anime_id = await _criar_anime(sessionmaker_api, "Anime Obter Episodio")
    episodio_id = await _criar_episodio(sessionmaker_api, anime_id, progresso_s=42)

    resposta = await cliente.get(f"/api/episodios/{episodio_id}")

    assert resposta.status_code == 200
    assert resposta.json()["id"] == episodio_id
    assert resposta.json()["progresso_s"] == 42


async def test_obter_episodio_inexistente_404(cliente: AsyncClient):
    resposta = await cliente.get("/api/episodios/999999")

    assert resposta.status_code == 404


# --- POST /api/episodios/{id}/progresso ---


async def test_salvar_progresso_grava(cliente: AsyncClient, sessionmaker_api: _SessionMaker):
    anime_id = await _criar_anime(sessionmaker_api, "Anime Salvar Progresso")
    episodio_id = await _criar_episodio(sessionmaker_api, anime_id, duracao_s=1200)

    resposta = await cliente.post(f"/api/episodios/{episodio_id}/progresso", json={"segundos": 300})

    assert resposta.status_code == 204
    async with sessionmaker_api() as sessao:
        episodio = await sessao.get(Episodio, episodio_id)
        assert episodio.progresso_s == 300
        assert episodio.progresso_atualizado_em is not None


async def test_salvar_progresso_recusa_acima_do_limiar(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker
):
    anime_id = await _criar_anime(sessionmaker_api, "Anime Progresso Acima")
    episodio_id = await _criar_episodio(sessionmaker_api, anime_id, duracao_s=1200)

    resposta = await cliente.post(
        f"/api/episodios/{episodio_id}/progresso", json={"segundos": 1100}
    )

    assert resposta.status_code == 422
    async with sessionmaker_api() as sessao:
        episodio = await sessao.get(Episodio, episodio_id)
        assert episodio.progresso_s is None


async def test_salvar_progresso_episodio_inexistente_404(cliente: AsyncClient):
    resposta = await cliente.post("/api/episodios/999999/progresso", json={"segundos": 10})

    assert resposta.status_code == 404


async def test_salvar_progresso_segundos_negativo_422(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker
):
    anime_id = await _criar_anime(sessionmaker_api, "Anime Progresso Negativo")
    episodio_id = await _criar_episodio(sessionmaker_api, anime_id)

    resposta = await cliente.post(f"/api/episodios/{episodio_id}/progresso", json={"segundos": -1})

    assert resposta.status_code == 422

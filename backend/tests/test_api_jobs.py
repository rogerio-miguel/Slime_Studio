"""Testes de `api/rotas/jobs.py`: criação nos dois modos, listagem/filtro,
cancelar/retry. Resolução de fonte remota (modo "site") é monkeypatchada nos
nomes importados em `api.servicos.jobs` — o comportamento de
`extractors.resolucao`/`extractors.servico` em si já tem testes próprios
(`tests/test_resolucao.py`)."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.enums import StatusJob
from extractors.base import EpisodioRemoto, ResultadoBusca
from extractors.resolucao import ConfirmacaoNecessaria, FonteResolvida
from models.anime import Anime
from models.episodio import Episodio
from models.job import Job

_SessionMaker = async_sessionmaker[AsyncSession]


async def _criar_anime(sessionmaker: _SessionMaker, titulo: str) -> int:
    async with sessionmaker() as sessao:
        anime = Anime(titulo=titulo, slug=titulo.lower().replace(" ", "-"))
        sessao.add(anime)
        await sessao.commit()
        return anime.id


async def _criar_episodio_e_job(
    sessionmaker: _SessionMaker,
    anime_id: int,
    *,
    numero: int = 1,
    status: StatusJob = StatusJob.NA_FILA,
) -> tuple[int, int]:
    async with sessionmaker() as sessao:
        episodio = Episodio(
            anime_id=anime_id,
            numero=numero,
            tipo="regular",
            url_fonte="/qualquer.mkv",
            site_origem="local",
        )
        sessao.add(episodio)
        await sessao.commit()

        job = Job(episodio_id=episodio.id, status=status)
        sessao.add(job)
        await sessao.commit()
        return episodio.id, job.id


async def test_criar_job_modo_local(cliente_autenticado: AsyncClient):
    resposta = await cliente_autenticado.post(
        "/api/admin/jobs",
        json={
            "modo": "local",
            "anime": "Anime Local",
            "numero": 1,
            "tipo": "regular",
            "caminho_local": "/caminho/qualquer.mkv",
        },
    )

    assert resposta.status_code == 201
    assert isinstance(resposta.json()["job_id"], int)


async def test_criar_job_modo_local_episodio_duplicado_409(cliente_autenticado: AsyncClient):
    corpo = {
        "modo": "local",
        "anime": "Anime Duplicado",
        "numero": 1,
        "tipo": "regular",
        "caminho_local": "/caminho/qualquer.mkv",
    }
    primeira = await cliente_autenticado.post("/api/admin/jobs", json=corpo)
    assert primeira.status_code == 201

    segunda = await cliente_autenticado.post("/api/admin/jobs", json=corpo)
    assert segunda.status_code == 409
    assert segunda.json()["detail"]["motivo"] == "episodio_ja_existe"


async def test_criar_job_modo_site_anime_id_inexistente_404(cliente_autenticado: AsyncClient):
    resposta = await cliente_autenticado.post(
        "/api/admin/jobs",
        json={"modo": "site", "anime_id": 999999, "numero": 1, "tipo": "regular"},
    )

    assert resposta.status_code == 404


async def test_criar_job_modo_site_ambiguo_409(
    cliente_autenticado: AsyncClient,
    sessionmaker_api: _SessionMaker,
    monkeypatch: pytest.MonkeyPatch,
):
    anime_id = await _criar_anime(sessionmaker_api, "Anime Ambíguo")

    async def _resolver_fake(sessionmaker, anime):
        return ConfirmacaoNecessaria(
            dominio="animefire.io",
            candidatos=[
                ResultadoBusca(
                    titulo_exibicao="Anime Ambíguo A", identificador="1", url="https://x/1"
                ),
                ResultadoBusca(
                    titulo_exibicao="Anime Ambíguo B", identificador="2", url="https://x/2"
                ),
            ],
        )

    monkeypatch.setattr("api.servicos.jobs.resolver_fonte_do_anime", _resolver_fake)

    resposta = await cliente_autenticado.post(
        "/api/admin/jobs",
        json={"modo": "site", "anime_id": anime_id, "numero": 1, "tipo": "regular"},
    )

    assert resposta.status_code == 409
    assert resposta.json()["detail"]["motivo"] == "fonte_ambigua"


async def test_criar_job_modo_site_episodio_nao_encontrado_404(
    cliente_autenticado: AsyncClient,
    sessionmaker_api: _SessionMaker,
    monkeypatch: pytest.MonkeyPatch,
):
    anime_id = await _criar_anime(sessionmaker_api, "Anime Sem Episodio")

    async def _resolver_fake(sessionmaker, anime):
        return FonteResolvida(dominio="animefire.io", identificador="42")

    async def _listar_fake(sessionmaker, dominio, identificador):
        return [EpisodioRemoto(numero=2, url="https://x/ep2")]

    monkeypatch.setattr("api.servicos.jobs.resolver_fonte_do_anime", _resolver_fake)
    monkeypatch.setattr("api.servicos.jobs.listar_episodios_em", _listar_fake)

    resposta = await cliente_autenticado.post(
        "/api/admin/jobs",
        json={"modo": "site", "anime_id": anime_id, "numero": 1, "tipo": "regular"},
    )

    assert resposta.status_code == 404


async def test_listar_jobs_com_filtro_de_status(
    cliente_autenticado: AsyncClient, sessionmaker_api: _SessionMaker
):
    anime_id = await _criar_anime(sessionmaker_api, "Anime Listagem")
    await _criar_episodio_e_job(sessionmaker_api, anime_id, numero=1, status=StatusJob.NA_FILA)
    await _criar_episodio_e_job(sessionmaker_api, anime_id, numero=2, status=StatusJob.PRONTO)

    resposta = await cliente_autenticado.get("/api/admin/jobs", params={"status": "pronto"})

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert len(corpo) == 1
    assert corpo[0]["status"] == "pronto"


async def test_obter_job_inexistente_404(cliente_autenticado: AsyncClient):
    resposta = await cliente_autenticado.get("/api/admin/jobs/999999")

    assert resposta.status_code == 404


async def test_cancelar_job_na_fila_cancela_direto(
    cliente_autenticado: AsyncClient, sessionmaker_api: _SessionMaker
):
    anime_id = await _criar_anime(sessionmaker_api, "Anime Cancelar Fila")
    _, job_id = await _criar_episodio_e_job(sessionmaker_api, anime_id, status=StatusJob.NA_FILA)

    resposta = await cliente_autenticado.post(f"/api/admin/jobs/{job_id}/cancelar")

    assert resposta.status_code == 202
    assert resposta.json()["status"] == "cancelado"


async def test_cancelar_job_em_execucao_marca_cancelando(
    cliente_autenticado: AsyncClient, sessionmaker_api: _SessionMaker
):
    anime_id = await _criar_anime(sessionmaker_api, "Anime Cancelar Execucao")
    _, job_id = await _criar_episodio_e_job(
        sessionmaker_api, anime_id, status=StatusJob.TRANSCODIFICANDO
    )

    resposta = await cliente_autenticado.post(f"/api/admin/jobs/{job_id}/cancelar")

    assert resposta.status_code == 202
    assert resposta.json()["status"] == "cancelando"


async def test_cancelar_job_ja_finalizado_409(
    cliente_autenticado: AsyncClient, sessionmaker_api: _SessionMaker
):
    anime_id = await _criar_anime(sessionmaker_api, "Anime Cancelar Pronto")
    _, job_id = await _criar_episodio_e_job(sessionmaker_api, anime_id, status=StatusJob.PRONTO)

    resposta = await cliente_autenticado.post(f"/api/admin/jobs/{job_id}/cancelar")

    assert resposta.status_code == 409


async def test_cancelar_job_inexistente_404(cliente_autenticado: AsyncClient):
    resposta = await cliente_autenticado.post("/api/admin/jobs/999999/cancelar")

    assert resposta.status_code == 404


async def test_retry_job_falhou_volta_para_fila(
    cliente_autenticado: AsyncClient, sessionmaker_api: _SessionMaker
):
    anime_id = await _criar_anime(sessionmaker_api, "Anime Retry")
    _, job_id = await _criar_episodio_e_job(sessionmaker_api, anime_id, status=StatusJob.FALHOU)

    resposta = await cliente_autenticado.post(f"/api/admin/jobs/{job_id}/retry")

    assert resposta.status_code == 200
    assert resposta.json()["job_id"] == job_id


async def test_retry_job_nao_retentavel_409(
    cliente_autenticado: AsyncClient, sessionmaker_api: _SessionMaker
):
    anime_id = await _criar_anime(sessionmaker_api, "Anime Retry Invalido")
    _, job_id = await _criar_episodio_e_job(sessionmaker_api, anime_id, status=StatusJob.NA_FILA)

    resposta = await cliente_autenticado.post(f"/api/admin/jobs/{job_id}/retry")

    assert resposta.status_code == 409


async def test_retry_job_inexistente_404(cliente_autenticado: AsyncClient):
    resposta = await cliente_autenticado.post("/api/admin/jobs/999999/retry")

    assert resposta.status_code == 404

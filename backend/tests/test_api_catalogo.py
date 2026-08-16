"""Testes de `DELETE /api/admin/episodios/{id}` e `DELETE /api/admin/animes/{id}`
(`api/rotas/episodios.py`, `api/rotas/animes.py` -> `api/servicos/catalogo.py`) —
caminho feliz (remove linha + arquivos em disco) e o 409 de `JobEmExecucao`
quando há um `Job` em `ESTADOS_EM_EXECUCAO` associado (achado 6 da revisão da
Fase 3)."""

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config import Config
from core.enums import StatusJob, TipoEpisodio, VersaoEpisodio
from core.midia import diretorio_do_episodio
from models.anime import Anime
from models.episodio import Episodio
from models.job import Job

_SessionMaker = async_sessionmaker[AsyncSession]


async def _criar_anime(sessionmaker: _SessionMaker, titulo: str) -> tuple[int, str]:
    slug = titulo.lower().replace(" ", "-")
    async with sessionmaker() as sessao:
        anime = Anime(titulo=titulo, slug=slug)
        sessao.add(anime)
        await sessao.commit()
        return anime.id, slug


async def _criar_episodio(
    sessionmaker: _SessionMaker, anime_id: int, *, numero: int = 1, hls_path: str | None = None
) -> int:
    async with sessionmaker() as sessao:
        episodio = Episodio(
            anime_id=anime_id,
            numero=numero,
            tipo=TipoEpisodio.REGULAR,
            versao=VersaoEpisodio.LEGENDADO,
            url_fonte="/qualquer.mkv",
            site_origem="local",
            hls_path=hls_path,
        )
        sessao.add(episodio)
        await sessao.commit()
        return episodio.id


async def _criar_job(sessionmaker: _SessionMaker, episodio_id: int, status: StatusJob) -> int:
    async with sessionmaker() as sessao:
        job = Job(episodio_id=episodio_id, status=status)
        sessao.add(job)
        await sessao.commit()
        return job.id


async def _episodio_existe(sessionmaker: _SessionMaker, episodio_id: int) -> bool:
    async with sessionmaker() as sessao:
        return await sessao.get(Episodio, episodio_id) is not None


async def _anime_existe(sessionmaker: _SessionMaker, anime_id: int) -> bool:
    async with sessionmaker() as sessao:
        return await sessao.get(Anime, anime_id) is not None


# --- DELETE /api/admin/episodios/{id} ---


async def test_remover_episodio_sem_job_apaga_linha_e_arquivos(
    cliente_autenticado: AsyncClient, sessionmaker_api: _SessionMaker, config_api: Config
):
    anime_id, slug = await _criar_anime(sessionmaker_api, "Anime Remover Episodio")
    diretorio = diretorio_do_episodio(
        config_api.media_root, slug, 1, TipoEpisodio.REGULAR, VersaoEpisodio.LEGENDADO
    )
    diretorio.mkdir(parents=True)
    (diretorio / "master.m3u8").write_text("#EXTM3U\n")
    hls_path = str((diretorio / "master.m3u8").relative_to(config_api.media_root))
    episodio_id = await _criar_episodio(sessionmaker_api, anime_id, hls_path=hls_path)

    resposta = await cliente_autenticado.delete(f"/api/admin/episodios/{episodio_id}")

    assert resposta.status_code == 204
    assert not await _episodio_existe(sessionmaker_api, episodio_id)
    assert not diretorio.exists()


async def test_remover_episodio_com_job_finalizado_remove(
    cliente_autenticado: AsyncClient, sessionmaker_api: _SessionMaker
):
    anime_id, _ = await _criar_anime(sessionmaker_api, "Anime Episodio Job Pronto")
    episodio_id = await _criar_episodio(sessionmaker_api, anime_id)
    await _criar_job(sessionmaker_api, episodio_id, StatusJob.PRONTO)

    resposta = await cliente_autenticado.delete(f"/api/admin/episodios/{episodio_id}")

    assert resposta.status_code == 204
    assert not await _episodio_existe(sessionmaker_api, episodio_id)


async def test_remover_episodio_com_job_em_execucao_409(
    cliente_autenticado: AsyncClient, sessionmaker_api: _SessionMaker
):
    anime_id, _ = await _criar_anime(sessionmaker_api, "Anime Episodio Job Ativo")
    episodio_id = await _criar_episodio(sessionmaker_api, anime_id)
    job_id = await _criar_job(sessionmaker_api, episodio_id, StatusJob.TRANSCODIFICANDO)

    resposta = await cliente_autenticado.delete(f"/api/admin/episodios/{episodio_id}")

    assert resposta.status_code == 409
    assert resposta.json() == {"detail": {"motivo": "job_em_execucao", "job_id": job_id}}
    assert await _episodio_existe(sessionmaker_api, episodio_id)


async def test_remover_episodio_inexistente_404(cliente_autenticado: AsyncClient):
    resposta = await cliente_autenticado.delete("/api/admin/episodios/999999")

    assert resposta.status_code == 404


async def test_remover_episodio_sem_cookie_401(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker
):
    anime_id, _ = await _criar_anime(sessionmaker_api, "Anime Episodio Sem Auth")
    episodio_id = await _criar_episodio(sessionmaker_api, anime_id)

    resposta = await cliente.delete(f"/api/admin/episodios/{episodio_id}")

    assert resposta.status_code == 401
    assert await _episodio_existe(sessionmaker_api, episodio_id)


# --- DELETE /api/admin/animes/{id} ---


async def test_remover_anime_sem_jobs_remove_cascata(
    cliente_autenticado: AsyncClient, sessionmaker_api: _SessionMaker
):
    anime_id, _ = await _criar_anime(sessionmaker_api, "Anime Remover Cascata")
    await _criar_episodio(sessionmaker_api, anime_id, numero=1)
    await _criar_episodio(sessionmaker_api, anime_id, numero=2)

    resposta = await cliente_autenticado.delete(f"/api/admin/animes/{anime_id}")

    assert resposta.status_code == 204
    assert not await _anime_existe(sessionmaker_api, anime_id)

    async with sessionmaker_api() as sessao:
        restantes = (
            await sessao.execute(select(Episodio).where(Episodio.anime_id == anime_id))
        ).scalars().all()
    assert restantes == []


async def test_remover_anime_com_episodio_com_job_ativo_409(
    cliente_autenticado: AsyncClient, sessionmaker_api: _SessionMaker
):
    anime_id, _ = await _criar_anime(sessionmaker_api, "Anime Multi Episodio Ativo")
    await _criar_episodio(sessionmaker_api, anime_id, numero=1)
    episodio_ativo_id = await _criar_episodio(sessionmaker_api, anime_id, numero=2)
    job_id = await _criar_job(sessionmaker_api, episodio_ativo_id, StatusJob.BAIXANDO)

    resposta = await cliente_autenticado.delete(f"/api/admin/animes/{anime_id}")

    assert resposta.status_code == 409
    assert resposta.json() == {"detail": {"motivo": "job_em_execucao", "job_id": job_id}}
    assert await _anime_existe(sessionmaker_api, anime_id)


async def test_remover_anime_inexistente_404(cliente_autenticado: AsyncClient):
    resposta = await cliente_autenticado.delete("/api/admin/animes/999999")

    assert resposta.status_code == 404


async def test_remover_anime_sem_cookie_401(cliente: AsyncClient, sessionmaker_api: _SessionMaker):
    anime_id, _ = await _criar_anime(sessionmaker_api, "Anime Sem Auth Delete")

    resposta = await cliente.delete(f"/api/admin/animes/{anime_id}")

    assert resposta.status_code == 401
    assert await _anime_existe(sessionmaker_api, anime_id)

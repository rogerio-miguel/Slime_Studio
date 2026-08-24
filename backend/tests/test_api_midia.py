"""Testes de `api/servicos/midia.py::resolver_caminho` (guarda de path
traversal, unitários) e das rotas HLS de `api/rotas/episodios.py` (integração
via `httpx`, atrás do gate de autenticação — D1 do plano: sem `StaticFiles`).

A guarda de traversal em si é coberta de forma determinística nos testes
unitários de `resolver_caminho`; não há teste de traversal na camada HTTP
porque normalização de `..` na URL é comportamento do cliente/ASGI, não da
aplicação — testar isso ali seria testar `httpx`, não `resolver_caminho`.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.servicos.midia import RecursoDeMidiaInvalido, resolver_caminho
from core.config import Config
from models.anime import Anime
from models.episodio import Episodio

_SessionMaker = async_sessionmaker[AsyncSession]


def _episodio_solto(hls_path: str | None) -> Episodio:
    """`Episodio` não persistido — `resolver_caminho` só lê `id`/`hls_path`."""
    return Episodio(
        id=1,
        anime_id=1,
        numero=1,
        tipo="regular",
        url_fonte="/x",
        site_origem="local",
        hls_path=hls_path,
    )


async def _inserir_episodio_com_hls(
    sessionmaker: _SessionMaker, *, titulo_anime: str, hls_path: str | None
) -> int:
    async with sessionmaker() as sessao:
        anime = Anime(titulo=titulo_anime, slug=titulo_anime.lower().replace(" ", "-"))
        sessao.add(anime)
        await sessao.flush()
        episodio = Episodio(
            anime_id=anime.id,
            numero=1,
            tipo="regular",
            url_fonte="/x",
            site_origem="local",
            hls_path=hls_path,
        )
        sessao.add(episodio)
        await sessao.commit()
        return episodio.id


# --- unitários: api/servicos/midia.py::resolver_caminho ---


async def test_resolver_caminho_valido(config_api: Config):
    diretorio = config_api.media_root / "anime" / "ep1"
    diretorio.mkdir(parents=True)
    (diretorio / "master.m3u8").write_text("#EXTM3U")
    (diretorio / "index.m3u8").write_text("#EXTM3U")

    caminho = resolver_caminho(
        config_api, _episodio_solto("anime/ep1/master.m3u8"), "index.m3u8"
    )

    assert caminho == (diretorio / "index.m3u8").resolve()


async def test_resolver_caminho_traversal_rejeitado(config_api: Config):
    diretorio = config_api.media_root / "anime" / "ep1"
    diretorio.mkdir(parents=True)
    (diretorio / "master.m3u8").write_text("#EXTM3U")
    (config_api.media_root / "segredo.txt").write_text("nao deveria ser lido")

    with pytest.raises(RecursoDeMidiaInvalido):
        resolver_caminho(config_api, _episodio_solto("anime/ep1/master.m3u8"), "../segredo.txt")


async def test_resolver_caminho_extensao_nao_permitida(config_api: Config):
    diretorio = config_api.media_root / "anime" / "ep1"
    diretorio.mkdir(parents=True)
    (diretorio / "master.m3u8").write_text("#EXTM3U")
    (diretorio / "chave.txt").write_text("x")

    with pytest.raises(RecursoDeMidiaInvalido):
        resolver_caminho(config_api, _episodio_solto("anime/ep1/master.m3u8"), "chave.txt")


async def test_resolver_caminho_arquivo_ausente(config_api: Config):
    diretorio = config_api.media_root / "anime" / "ep1"
    diretorio.mkdir(parents=True)
    (diretorio / "master.m3u8").write_text("#EXTM3U")

    with pytest.raises(RecursoDeMidiaInvalido):
        resolver_caminho(config_api, _episodio_solto("anime/ep1/master.m3u8"), "seg_00001.ts")


async def test_resolver_caminho_sem_hls_path(config_api: Config):
    with pytest.raises(RecursoDeMidiaInvalido):
        resolver_caminho(config_api, _episodio_solto(None), "index.m3u8")


# --- integração: api/rotas/episodios.py (playlist/segmento) ---


async def test_playlist_m3u8_servida_com_sucesso(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker, config_api: Config
):
    diretorio = config_api.media_root / "anime" / "ep1"
    diretorio.mkdir(parents=True)
    (diretorio / "master.m3u8").write_text("#EXTM3U\n")

    episodio_id = await _inserir_episodio_com_hls(
        sessionmaker_api, titulo_anime="Anime Midia", hls_path="anime/ep1/master.m3u8"
    )

    resposta = await cliente.get(f"/api/episodios/{episodio_id}/playlist.m3u8")

    assert resposta.status_code == 200
    assert resposta.headers["content-type"].startswith("application/vnd.apple.mpegurl")


async def test_playlist_m3u8_sem_hls_devolve_404(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker
):
    episodio_id = await _inserir_episodio_com_hls(
        sessionmaker_api, titulo_anime="Anime Sem HLS", hls_path=None
    )

    resposta = await cliente.get(f"/api/episodios/{episodio_id}/playlist.m3u8")

    assert resposta.status_code == 404


async def test_playlist_m3u8_episodio_inexistente_404(cliente: AsyncClient):
    resposta = await cliente.get("/api/episodios/999999/playlist.m3u8")

    assert resposta.status_code == 404


async def test_segmento_servido_com_sucesso(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker, config_api: Config
):
    diretorio = config_api.media_root / "anime" / "ep2"
    diretorio.mkdir(parents=True)
    (diretorio / "master.m3u8").write_text("#EXTM3U\n")
    (diretorio / "seg_00001.ts").write_bytes(b"dados-fake-do-segmento")

    episodio_id = await _inserir_episodio_com_hls(
        sessionmaker_api, titulo_anime="Anime Segmento", hls_path="anime/ep2/master.m3u8"
    )

    resposta = await cliente.get(f"/api/episodios/{episodio_id}/seg_00001.ts")

    assert resposta.status_code == 200
    assert resposta.content == b"dados-fake-do-segmento"
    assert resposta.headers["cache-control"] == "private, max-age=0, must-revalidate"

"""Fixtures compartilhadas de teste. `ClienteFalso` é usado por todo teste de
parsing de extrator (`test_animefire.py`, `test_animesdrive.py`), sem tocar
rede — auto-carregado pelo pytest, `tests/` não é pacote então zero atrito de
import.

`config_api`/`app_pronto`/`cliente` são para os testes de `api/` (`test_api_*.py`)
— mesmo padrão de `Config` com `tmp_path` + arquivo SQLite real de
`tests/test_fila.py` (WAL não funciona em `:memory:`), schema via
`Base.metadata.create_all` (não Alembic)."""

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.main import criar_app
from core.config import Config
from db.engine import criar_engine
from models.base import Base


class ClienteFalso:
    """Implementação de `ClienteDeSite` que devolve respostas pré-programadas por
    URL, em vez de tocar rede. URL não mapeada é erro de teste (`AssertionError`),
    não `None` silencioso."""

    def __init__(
        self,
        *,
        html_por_url: dict[str, str] | None = None,
        json_por_url: dict[str, object] | None = None,
    ) -> None:
        self._html_por_url = html_por_url or {}
        self._json_por_url = json_por_url or {}

    def obter_html(self, url: str, *, timeout_s: int) -> str:
        assert url in self._html_por_url, f"URL não mapeada no ClienteFalso: {url}"
        return self._html_por_url[url]

    def obter_json(self, url: str, *, timeout_s: int) -> dict | list:
        assert url in self._json_por_url, f"URL não mapeada no ClienteFalso: {url}"
        return self._json_por_url[url]

    def cookies(self) -> dict[str, str]:
        return {}

    def user_agent(self) -> str:
        return "ClienteFalso/1.0"


@pytest.fixture
def cliente_falso():
    """Fábrica de `ClienteFalso` — uso: `cliente_falso(html_por_url={...})`."""

    def _fabrica(
        *,
        html_por_url: dict[str, str] | None = None,
        json_por_url: dict[str, object] | None = None,
    ) -> ClienteFalso:
        return ClienteFalso(html_por_url=html_por_url, json_por_url=json_por_url)

    return _fabrica


@pytest.fixture
async def config_api(tmp_path: Path) -> Config:
    return Config(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        media_root=tmp_path / "media",
        raiz_repo=tmp_path,
        ffmpeg=Path("/usr/bin/ffmpeg"),
        ffprobe=Path("/usr/bin/ffprobe"),
        caminho_lock=tmp_path / "worker.lock",
    )


@pytest.fixture
async def app_pronto(config_api: Config):
    """App com schema já criado e lifespan já rodando (`app.state.sessionmaker`
    etc. disponíveis) — sem isso as rotas quebrariam com `AttributeError` ao
    acessar `request.app.state.*` (`api/dependencias.py`)."""
    engine_schema = criar_engine(config_api)
    async with engine_schema.begin() as conexao:
        await conexao.run_sync(Base.metadata.create_all)
    await engine_schema.dispose()

    aplicativo = criar_app(config_api)
    async with aplicativo.router.lifespan_context(aplicativo):
        yield aplicativo


@pytest.fixture
async def cliente(app_pronto):
    transporte = ASGITransport(app=app_pronto)
    async with AsyncClient(transport=transporte, base_url="http://test") as client:
        yield client


@pytest.fixture
async def sessionmaker_api(app_pronto) -> async_sessionmaker[AsyncSession]:
    """Sessionmaker da mesma engine que o app usa — para os testes prepararem
    dados (`Anime`/`Episodio`/`Job`) direto no banco antes de bater na API."""
    return app_pronto.state.sessionmaker

"""Fixtures compartilhadas de teste. `ClienteFalso` é usado por todo teste de
parsing de extrator (`test_animefire.py`, `test_animesdrive.py`), sem tocar
rede — auto-carregado pelo pytest, `tests/` não é pacote então zero atrito de
import.

`config_api`/`app_pronto`/`cliente` são para os testes de `api/` (`test_api_*.py`)
— mesmo padrão de `Config` com `tmp_path` + arquivo SQLite real de
`tests/test_fila.py` (WAL não funciona em `:memory:`), schema via
`Base.metadata.create_all` (não Alembic)."""

import asyncio
import contextlib
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.main import criar_app
from api.servicos import busca as servico_busca
from api.servicos import descoberta, sondagem
from core.config import Config
from db.engine import criar_engine
from extractors import rede_segura
from integrations import anilist
from integrations import servico as servico_metadados
from models.base import Base


@pytest.fixture(autouse=True)
async def _isola_sondagens_de_fonte():
    """`sondagem._sondagens_em_voo` e `sondagem._semaforo_de_sondagem` são estado
    de módulo. A partir de F12 as rotas `GET /api/animes` e `GET /api/animes/{id}`
    agendam sondagens fire-and-forget, então qualquer teste de `test_api_*.py`
    que bata nelas pode deixar uma `Task` pendente vazar para o event loop do
    próximo teste ("Task was destroyed but it is pending") — daí o isolamento
    ficar no conftest, não num único arquivo.

    O dict é zerado antes e o que sobrar é cancelado/drenado depois. O semáforo é
    recriado por teste: `asyncio.Semaphore` liga-se ao primeiro event loop que o
    aguarda e o pytest-asyncio dá um loop novo por teste — sem recriar, o 2º
    teste que o tocasse quebraria com "bound to a different event loop". Em
    produção o processo tem um loop só, então é acomodação de teste, não bug.
    """
    sondagem._sondagens_em_voo.clear()
    sondagem._semaforo_de_sondagem = asyncio.Semaphore(1)
    yield
    # Cancela ANTES de aguardar: uma `Task` fire-and-forget pode estar presa num
    # `await` que nunca completa (semáforo, `wait_for` de rede). Testes que
    # querem drenar de verdade chamam o próprio `_drenar_sondagens` antes daqui.
    pendentes = list(sondagem._sondagens_em_voo.values())
    for tarefa in pendentes:
        tarefa.cancel()
    for tarefa in pendentes:
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await tarefa
    sondagem._sondagens_em_voo.clear()


@pytest.fixture(autouse=True)
async def _isola_refreshs_de_lancamento():
    """`descoberta._refreshs_de_lancamento_em_voo` é estado de módulo (dedupe +
    ref forte das `Task` de F4b/F14 — refresh lazy por id E aquecimento por
    título). Zera antes e cancela/limpa o que sobrar depois, para nenhum teste
    vazar `Task` pendente para o próximo.

    Global no conftest (não local a um arquivo): a partir de F14 `GET /api/animes`
    agenda buscas por título fire-and-forget para animes sem `anilist_id`, então
    qualquer teste de `test_api_*.py` que bata na listagem pode deixar uma `Task`
    pendente — mesma razão de `_isola_sondagens_de_fonte` acima.
    """
    descoberta._refreshs_de_lancamento_em_voo.clear()
    descoberta._reparos_de_classificacao_em_voo.clear()
    descoberta._reparos_de_classificacao_recentes.clear()
    yield
    pendentes = [
        *descoberta._refreshs_de_lancamento_em_voo.values(),
        *descoberta._reparos_de_classificacao_em_voo.values(),
    ]
    # Drena ANTES de cancelar (ao contrário de `_isola_sondagens_de_fonte`, cujas
    # `Task` podem ficar presas num semáforo/`wait_for` de rede): com os stubs de
    # rede em vigor estas terminam em ms, e uma `Task` cancelada no meio de um
    # `await` do aiosqlite deixa a worker thread retomando um loop já fechado
    # (`PytestUnhandledThreadExceptionWarning`). O que não terminar no tempo
    # limite ainda é cancelado.
    if pendentes:
        with contextlib.suppress(Exception):
            await asyncio.wait(pendentes, timeout=5)
    for tarefa in pendentes:
        tarefa.cancel()
    for tarefa in pendentes:
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await tarefa
    descoberta._refreshs_de_lancamento_em_voo.clear()
    descoberta._reparos_de_classificacao_em_voo.clear()
    descoberta._reparos_de_classificacao_recentes.clear()


@pytest.fixture(autouse=True)
def _isola_cache_de_busca_de_fontes():
    """`api.servicos.busca._cache_de_busca` é estado de módulo: sem zerar, dois
    testes que buscam o mesmo título com fontes fake diferentes se contaminariam."""
    servico_busca._cache_de_busca.clear()
    yield
    servico_busca._cache_de_busca.clear()


@pytest.fixture(autouse=True)
def _isola_cache_de_relacoes():
    """`anilist._cache_de_relacoes` é estado de módulo: sem zerar, dois testes que
    usam o mesmo `anilist_id` com respostas diferentes se contaminariam."""
    anilist._cache_de_relacoes.clear()
    yield
    anilist._cache_de_relacoes.clear()


@pytest.fixture(autouse=True)
def _isola_cooldown_de_provedor(monkeypatch: pytest.MonkeyPatch):
    """`integrations.servico._cooldown_por_provedor` é estado de módulo (circuit
    breaker "lite" em memória — `falhas_consecutivas`/`cooldown_ate` por
    provedor). Um teste que faz um provedor fake estourar `ConnectionError`/
    `TimeoutError` deixa o provedor "degradado" no dict por até 15s de
    `time.monotonic` reais — o suficiente para curto-circuitar chamadas de
    testes seguintes na mesma execução. Zera antes de cada teste."""
    monkeypatch.setattr(servico_metadados, "_cooldown_por_provedor", {})


@pytest.fixture(autouse=True)
def _isola_persistencia_de_feeds(monkeypatch: pytest.MonkeyPatch):
    """`integrations.servico._persistir_feed` é estado de módulo, instalado pelo
    lifespan de `criar_app` apontando pro engine daquele teste. Sem restaurar, o
    teste seguinte persistiria num engine já descartado."""
    monkeypatch.setattr(servico_metadados, "_persistir_feed", None)


@pytest.fixture(autouse=True)
def _busca_de_metadados_por_titulo_sem_rede(monkeypatch: pytest.MonkeyPatch):
    """F14: `GET /api/animes` agenda uma busca por título fire-and-forget
    (`integrations.servico.buscar_por_titulo`, cadeia AniList→Kitsu) para cada
    anime catalogado sem `anilist_id` e com carimbo velho — exercitado de forma
    difusa por `test_api_animes.py`. Stub global para a `Task` nunca tocar rede;
    devolve `None` ("provedor respondeu, não achou"). Testes que querem espiar
    a chamada re-`setattr`am por cima (mesmo padrão de `_sondagem_da_fonte_sem_rede`
    em `test_api_descoberta.py`).

    `test_integrations_metadados.py` sobrescreve esta fixture com um no-op: lá o
    alvo do teste é a própria `servico.buscar_por_titulo`.
    """

    async def _sem_resultado(titulo):
        return None

    monkeypatch.setattr("integrations.servico.buscar_por_titulo", _sem_resultado)


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

    def fechar(self) -> None:
        """Sem recurso a liberar — existe só para completar `ClienteDeSite`."""


@pytest.fixture(autouse=True)
def _dns_publico_por_padrao(monkeypatch):
    """Nenhum teste faz DNS real: todo nome resolve pra um IP público. Os testes de
    `rede_segura` sobrescrevem isto pra simular nome que resolve pra IP interno."""
    monkeypatch.setattr(rede_segura, "resolver_dns", lambda hostname: ["93.184.216.34"])


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
    # `localhost`: o `TrustedHostMiddleware` da API rejeita `Host: test`.
    async with AsyncClient(transport=transporte, base_url="http://localhost") as client:
        yield client


@pytest.fixture
async def sessionmaker_api(app_pronto) -> async_sessionmaker[AsyncSession]:
    """Sessionmaker da mesma engine que o app usa — para os testes prepararem
    dados (`Anime`/`Episodio`/`Job`) direto no banco antes de bater na API."""
    return app_pronto.state.sessionmaker

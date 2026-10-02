"""Fábrica da aplicação FastAPI (ESPECIFICACAO.md §5/§7/§8.1) — `criar_app(config)`
monta lifespan (engine/sessionmaker/hub de eventos em `app.state`), CORS,
routers e handlers de exceção. Sem app global: testes injetam `Config` de teste
(mesmo padrão de `worker/__main__.py::principal`, que recebe `Config` em vez de
carregá-la sozinho).
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import partial

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.eventos import Assinantes, MonitorDeFila
from api.rotas import animes, episodios, jobs, saude, sites, thumb, ws
from api.seguranca import CabecalhosDeSeguranca, LimitesDeTaxa, ProtecaoDeOrigem
from api.servicos import cache_de_feeds
from core.config import Config
from core.erros import (
    EpisodioJaExiste,
    ErroSlimeStudio,
    FalhaDeExtracao,
    FalhaDeMetadados,
    FonteAmbigua,
    FonteInvalida,
    FonteNaoEncontrada,
    JobEmExecucao,
    SiteEmCooldown,
    VersaoIndisponivelError,
)
from db.engine import criar_engine, criar_sessionmaker
from integrations import servico as servico_metadados
from integrations.registro import instalar_provedores_de_arte

logger = logging.getLogger(__name__)

# Caminho recomendado para o frontend (Fase 4) é o proxy de dev do Vite
# (same-origin, dispensa CORS por completo); sem proxy, `hls.js` com
# `crossOrigin='anonymous'` (D1 de sessão anterior) exige que a origem esteja
# na allowlist de CORS para o browser completar o request cross-origin.
_ORIGENS_PERMITIDAS = ["http://localhost:5173", "http://127.0.0.1:5173"]
# `Host` sem porta (o `TrustedHostMiddleware` a descarta). Com o proxy do Vite sem
# `changeOrigin`, o `Host` que chega aqui é o do navegador (`localhost:5173`).
_HOSTS_PERMITIDOS = ["localhost", "127.0.0.1"]


async def _ligar_persistencia_de_feeds(sessionmaker: async_sessionmaker[AsyncSession]) -> None:
    """Feeds da Home sobrevivem a reinício: o último resultado bom volta como cache
    "velho" (servido na hora, revalidado em segundo plano) em vez de a 1ª abertura
    esperar a busca AniList + TMDB inteira. Falha aqui nunca impede a API de subir."""
    servico_metadados.instalar_persistencia_de_feeds(
        partial(cache_de_feeds.gravar_feed, sessionmaker)
    )
    try:
        feeds = await cache_de_feeds.carregar_feeds_persistidos(sessionmaker)
    except SQLAlchemyError as excecao:
        logger.warning(
            "cache de feeds não restaurado (rode `uv run alembic upgrade head`?): %s", excecao
        )
        return
    servico_metadados.restaurar_feeds_persistidos(feeds)


def criar_app(config: Config) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = criar_engine(config)
        sessionmaker = criar_sessionmaker(engine)
        assinantes = Assinantes()
        monitor = MonitorDeFila(sessionmaker, assinantes)
        instalar_provedores_de_arte(config.tmdb_token)
        await _ligar_persistencia_de_feeds(sessionmaker)

        app.state.config = config
        app.state.sessionmaker = sessionmaker
        app.state.assinantes = assinantes
        app.state.limites = LimitesDeTaxa()
        app.state.monitor = monitor

        try:
            yield
        finally:
            await monitor.parar()
            await engine.dispose()

    app = FastAPI(title="Slime Studio API", lifespan=lifespan)

    # Ordem de `add_middleware`: o último adicionado é o mais externo. `Host` é
    # checado primeiro (DNS rebinding), depois o CORS, depois a origem das escritas.
    app.add_middleware(ProtecaoDeOrigem, origens_permitidas=_ORIGENS_PERMITIDAS)
    app.add_middleware(CabecalhosDeSeguranca)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_ORIGENS_PERMITIDAS,
        # Sem cookie nem auth (o front usa `credentials: 'same-origin'`); `Range` é do
        # `hls.js` cross-origin, `Content-Type` do JSON das escritas.
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "Range"],
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=_HOSTS_PERMITIDOS)

    app.include_router(saude.router_publico)
    app.include_router(saude.router_admin)
    app.include_router(jobs.router)
    app.include_router(animes.router)
    app.include_router(animes.router_publico)
    app.include_router(episodios.router)
    app.include_router(episodios.router_admin)
    app.include_router(thumb.router)
    app.include_router(sites.router)
    app.include_router(ws.router)

    _registrar_handlers_de_excecao(app)
    return app


def _registrar_handlers_de_excecao(app: FastAPI) -> None:
    """Registrado por tipo de exceção (não `try/except` por rota) — o dispatch do
    Starlette percorre o MRO da exceção levantada, então registrar tanto a
    classe-base (`FalhaDeExtracao`) quanto subclasses específicas
    (`SiteEmCooldown`, `FonteNaoEncontrada`) funciona: a mais específica vence.
    """

    @app.exception_handler(FonteInvalida)
    async def _fonte_invalida(request: Request, excecao: FonteInvalida) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(excecao)})

    @app.exception_handler(FonteNaoEncontrada)
    async def _fonte_nao_encontrada(request: Request, excecao: FonteNaoEncontrada) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(excecao)})

    @app.exception_handler(SiteEmCooldown)
    async def _site_em_cooldown(request: Request, excecao: SiteEmCooldown) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": str(excecao)})

    @app.exception_handler(FonteAmbigua)
    async def _fonte_ambigua(request: Request, excecao: FonteAmbigua) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={
                "detail": {
                    "motivo": "fonte_ambigua",
                    "dominio": excecao.dominio,
                    "candidatos": excecao.candidatos,
                }
            },
        )

    @app.exception_handler(VersaoIndisponivelError)
    async def _versao_indisponivel(
        request: Request, excecao: VersaoIndisponivelError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={"detail": {"motivo": "versao_indisponivel", "versao": excecao.versao.value}},
        )

    @app.exception_handler(EpisodioJaExiste)
    async def _episodio_ja_existe(request: Request, excecao: EpisodioJaExiste) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={
                "detail": {"motivo": "episodio_ja_existe", "episodio_id": excecao.episodio_id}
            },
        )

    @app.exception_handler(JobEmExecucao)
    async def _job_em_execucao(request: Request, excecao: JobEmExecucao) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={"detail": {"motivo": "job_em_execucao", "job_id": excecao.job_id}},
        )

    @app.exception_handler(FalhaDeExtracao)
    async def _falha_de_extracao(request: Request, excecao: FalhaDeExtracao) -> JSONResponse:
        # A mensagem crua traz URL, caminho temporário e cauda de stderr: fica no log.
        logger.warning("falha de extração na API: %s", excecao, exc_info=excecao)
        onde = f" em {excecao.dominio}" if excecao.dominio else ""
        return JSONResponse(
            status_code=502, content={"detail": f"falha ao extrair de fonte externa{onde}"}
        )

    @app.exception_handler(FalhaDeMetadados)
    async def _falha_de_metadados(request: Request, excecao: FalhaDeMetadados) -> JSONResponse:
        logger.warning("falha de metadados na API: %s", excecao, exc_info=excecao)
        return JSONResponse(
            status_code=502, content={"detail": "falha ao consultar provedores de metadados"}
        )

    @app.exception_handler(ErroSlimeStudio)
    async def _erro_generico(request: Request, excecao: ErroSlimeStudio) -> JSONResponse:
        logger.exception("erro não mapeado na API", exc_info=excecao)
        return JSONResponse(status_code=500, content={"detail": "erro interno"})

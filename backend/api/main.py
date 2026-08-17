"""Fábrica da aplicação FastAPI (ESPECIFICACAO.md §5/§7/§8.1) — `criar_app(config)`
monta lifespan (engine/sessionmaker/hub de eventos em `app.state`), CORS,
routers e handlers de exceção. Sem app global: testes injetam `Config` de teste
(mesmo padrão de `worker/__main__.py::principal`, que recebe `Config` em vez de
carregá-la sozinho).
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.eventos import Assinantes, MonitorDeFila
from api.rotas import animes, episodios, jobs, saude, sites, ws
from core.config import Config
from core.erros import (
    EpisodioJaExiste,
    ErroSlimeStudio,
    FalhaDeExtracao,
    FonteAmbigua,
    FonteInvalida,
    FonteNaoEncontrada,
    JobEmExecucao,
    SiteEmCooldown,
)
from db.engine import criar_engine, criar_sessionmaker

logger = logging.getLogger(__name__)

# Caminho recomendado para o frontend (Fase 4) é o proxy de dev do Vite
# (same-origin, dispensa CORS por completo); sem proxy, `hls.js` com
# `crossOrigin='anonymous'` (D1 de sessão anterior) exige que a origem esteja
# na allowlist de CORS para o browser completar o request cross-origin.
_ORIGENS_PERMITIDAS = ["http://localhost:5173", "http://127.0.0.1:5173"]


def criar_app(config: Config) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = criar_engine(config)
        sessionmaker = criar_sessionmaker(engine)
        assinantes = Assinantes()
        monitor = MonitorDeFila(sessionmaker, assinantes)

        app.state.config = config
        app.state.sessionmaker = sessionmaker
        app.state.assinantes = assinantes
        app.state.monitor = monitor

        try:
            yield
        finally:
            await monitor.parar()
            await engine.dispose()

    app = FastAPI(title="Slime Studio API", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_ORIGENS_PERMITIDAS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(saude.router_publico)
    app.include_router(saude.router_admin)
    app.include_router(jobs.router)
    app.include_router(animes.router)
    app.include_router(animes.router_publico)
    app.include_router(episodios.router)
    app.include_router(episodios.router_admin)
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
        return JSONResponse(status_code=502, content={"detail": str(excecao)})

    @app.exception_handler(ErroSlimeStudio)
    async def _erro_generico(request: Request, excecao: ErroSlimeStudio) -> JSONResponse:
        logger.exception("erro não mapeado na API", exc_info=excecao)
        return JSONResponse(status_code=500, content={"detail": "erro interno"})

"""Fábrica da aplicação FastAPI (ESPECIFICACAO.md §5/§7/§8.1) — `criar_app(config)`
monta lifespan (engine/sessionmaker/hub de eventos em `app.state`), CORS,
routers e handlers de exceção. Sem app global: testes injetam `Config` de teste
(mesmo padrão de `worker/__main__.py::principal`, que recebe `Config` em vez de
carregá-la sozinho).
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.dependencias import exigir_autenticacao
from api.eventos import Assinantes, MonitorDeFila
from api.rotas import animes, auth, episodios, jobs, saude, sites, ws
from core.config import Config
from core.erros import (
    EpisodioJaExiste,
    ErroDeConfiguracao,
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

_TAMANHO_MINIMO_TOKEN = 16
# Caminho recomendado para o frontend (Fase 4) é o proxy de dev do Vite
# (same-origin, dispensa CORS por completo); sem proxy, `hls.js` precisa de
# `xhrSetup` configurando `withCredentials` para o browser anexar o cookie de
# sessão em requisições cross-origin.
_ORIGENS_PERMITIDAS = ["http://localhost:5173", "http://127.0.0.1:5173"]


def criar_app(config: Config) -> FastAPI:
    _validar_token_admin(config)

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

    gate = [Depends(exigir_autenticacao)]
    # Sem `FastAPI(dependencies=[...])` global: isso cairia em cima das rotas WS
    # também, com o gate HTTP errado (`HTTPException` em vez de
    # `WebSocketException`) — cada router recebe o gate certo explicitamente.
    app.include_router(auth.router)
    app.include_router(saude.router_publico)
    app.include_router(saude.router_admin, dependencies=gate)
    app.include_router(jobs.router, dependencies=gate)
    app.include_router(animes.router, dependencies=gate)
    app.include_router(animes.router_publico, dependencies=gate)
    app.include_router(episodios.router, dependencies=gate)
    app.include_router(episodios.router_admin, dependencies=gate)
    app.include_router(sites.router, dependencies=gate)
    app.include_router(ws.router)

    _registrar_handlers_de_excecao(app)
    return app


def _validar_token_admin(config: Config) -> None:
    """`ErroDeConfiguracao` (não uma exceção própria): a validação mora aqui, não
    em `core/config.py::carregar_config`, porque o worker não usa este token e
    não deve morrer por causa dele — só o boot da API exige."""
    token = config.admin_access_token
    if token is None or len(token) < _TAMANHO_MINIMO_TOKEN:
        raise ErroDeConfiguracao(
            "ADMIN_ACCESS_TOKEN ausente ou curto demais (mínimo "
            f"{_TAMANHO_MINIMO_TOKEN} caracteres). Gere um com: "
            'python -c "import secrets; print(secrets.token_urlsafe(32))"'
        )


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

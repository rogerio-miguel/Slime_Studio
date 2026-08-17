"""`/api/health` (liveness) + `/api/admin/disco`/`/api/admin/worker` (operação
do painel admin).

Dois routers só pela diferença de prefixo de URL (`/api` vs. `/api/admin`) —
sem gate de autenticação, a API é de uso local/pessoal (CLAUDE.md). O corpo de
`/api/health` é deliberadamente mínimo (`{"status": "ok"}`, sem versão nem
estado do banco) para não vazar detalhe de implementação a quem quer que
consiga alcançar a porta.
"""

import fcntl

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.dependencias import obter_config, obter_sessionmaker
from api.esquemas import DiscoSaida, SaudeSaida, WorkerSaida
from api.servicos import catalogo as servico_catalogo
from core.config import Config

_SessionMaker = async_sessionmaker[AsyncSession]

router_publico = APIRouter(tags=["saude"])
router_admin = APIRouter(prefix="/api/admin", tags=["admin-operacao"])


@router_publico.get("/api/health", response_model=SaudeSaida)
async def saude() -> SaudeSaida:
    return SaudeSaida(status="ok")


@router_admin.get("/disco", response_model=DiscoSaida)
async def disco(
    config: Config = Depends(obter_config),
    sessionmaker: _SessionMaker = Depends(obter_sessionmaker),
) -> DiscoSaida:
    total, livre, usado_por_midia = await servico_catalogo.uso_de_disco(sessionmaker, config)
    return DiscoSaida(total_bytes=total, livre_bytes=livre, usado_por_midia_bytes=usado_por_midia)


@router_admin.get("/worker", response_model=WorkerSaida)
async def worker(config: Config = Depends(obter_config)) -> WorkerSaida:
    return WorkerSaida(vivo=_worker_esta_vivo(config))


def _worker_esta_vivo(config: Config) -> bool:
    """D6 do plano: deriva "vivo" tentando adquirir o mesmo flock que
    `worker/bloqueio.py::BloqueioDeInstancia` usa. Abre em modo `"r"` — nunca
    `"w"`, que truncaria o arquivo e apagaria o PID escrito pelo worker.
    Arquivo inexistente = worker nunca rodou (não é "vivo")."""
    if not config.caminho_lock.exists():
        return False
    with open(config.caminho_lock) as arquivo:
        try:
            fcntl.flock(arquivo, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return True
        else:
            fcntl.flock(arquivo, fcntl.LOCK_UN)
            return False

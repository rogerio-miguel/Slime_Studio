"""Rotas de autenticação (`/api/auth/*`) — as únicas montadas sem o gate
`exigir_autenticacao` (junto de `/api/health`), já que são o próprio mecanismo
de autenticação (ESPECIFICACAO.md §5/§8.2)."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from api.dependencias import obter_config
from api.esquemas import DesbloquearRequest, EstadoAutenticacaoSaida
from api.seguranca import NOME_COOKIE, limpar_cookie, setar_cookie, token_valido
from core.config import Config

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/desbloquear", status_code=status.HTTP_204_NO_CONTENT)
async def desbloquear(
    corpo: DesbloquearRequest, response: Response, config: Config = Depends(obter_config)
) -> None:
    if config.admin_access_token is None or not token_valido(
        corpo.token, config.admin_access_token
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="token inválido")
    setar_cookie(response, corpo.token)


@router.post("/sair", status_code=status.HTTP_204_NO_CONTENT)
async def sair(response: Response) -> None:
    limpar_cookie(response)


@router.get("/estado", response_model=EstadoAutenticacaoSaida)
async def estado(
    request: Request, config: Config = Depends(obter_config)
) -> EstadoAutenticacaoSaida:
    cookie = request.cookies.get(NOME_COOKIE)
    autenticado = config.admin_access_token is not None and token_valido(
        cookie, config.admin_access_token
    )
    return EstadoAutenticacaoSaida(autenticado=autenticado)

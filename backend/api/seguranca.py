"""Autenticação por token único (ESPECIFICACAO.md §5/§8.2) — sem login completo:
um `ADMIN_ACCESS_TOKEN` fixo (gerado uma vez, `.env`), comparado via cookie
`HttpOnly`. Nunca por header — o cookie é o único transporte do token.

Sem token CSRF separado: `SameSite=Lax` já impede o navegador de anexar o cookie
em requisições cross-site que não sejam navegação de topo (GET), o que cobre o
vetor de POST cross-site que um token CSRF existiria para mitigar.

Sem rate limit no desbloqueio (`api/rotas/auth.py::POST /api/auth/desbloquear`):
o token tem no mínimo 16 caracteres de entropia (validado no boot da API,
`api/main.py::_validar_token_admin`) e a instância nunca é exposta publicamente
(ESPECIFICACAO.md §8.2/§8.3) — força bruta de rede não é uma ameaça real neste
modelo de uso local.
"""

import hmac

from fastapi import Response

NOME_COOKIE = "slime_sessao"
_MAX_AGE_S = 30 * 24 * 3600  # 30 dias


def token_valido(cookie: str | None, esperado: str) -> bool:
    """Comparação em tempo constante (`hmac.compare_digest`) — nunca `==` para
    não vazar o tamanho do prefixo correto por timing."""
    if cookie is None:
        return False
    return hmac.compare_digest(cookie, esperado)


def setar_cookie(response: Response, token: str) -> None:
    # secure=False fixo: o uso suportado desta API é sempre local/loopback
    # (ESPECIFICACAO.md §8.2 proíbe exposição pública) — não há HTTPS no cenário
    # suportado, então `secure=True` só quebraria o cookie sem ganho real.
    response.set_cookie(
        NOME_COOKIE,
        token,
        max_age=_MAX_AGE_S,
        httponly=True,
        samesite="lax",
        secure=False,
        path="/",
    )


def limpar_cookie(response: Response) -> None:
    response.delete_cookie(NOME_COOKIE, path="/")

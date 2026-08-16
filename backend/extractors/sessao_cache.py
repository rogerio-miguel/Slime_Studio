"""CRUD de `SessaoBypass` — cache de sessão/cookies por site (ESPECIFICACAO.md §3A item 1).

Sessões curtas por operação, mesmo idioma de `worker/fila.py`.
"""

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from models.sessao_bypass import SessaoBypass

_SessionMaker = async_sessionmaker[AsyncSession]


@dataclass(frozen=True, slots=True)
class ContextoDeSessao:
    cookies: dict[str, str]
    user_agent: str


async def carregar(sessionmaker: _SessionMaker, dominio: str) -> ContextoDeSessao | None:
    """Devolve a sessão cacheada de `dominio`, ou `None` se não houver uma ou se
    `expira_estimado_em` já passou (sessão vencida é tratada como ausente, nunca
    usada às cegas)."""
    async with sessionmaker() as sessao:
        registro = await sessao.get(SessaoBypass, dominio)
        if registro is None or registro.expira_estimado_em <= datetime.now(UTC):
            return None
        return ContextoDeSessao(
            cookies=json.loads(registro.cookies_json), user_agent=registro.user_agent
        )


async def salvar(
    sessionmaker: _SessionMaker,
    dominio: str,
    cookies: dict[str, str],
    user_agent: str,
    *,
    ttl_s: int,
) -> None:
    """Upsert da sessão de `dominio`."""
    agora = datetime.now(UTC)
    expira_em = agora + timedelta(seconds=ttl_s)
    async with sessionmaker() as sessao:
        registro = await sessao.get(SessaoBypass, dominio)
        if registro is None:
            sessao.add(
                SessaoBypass(
                    site_dominio=dominio,
                    cookies_json=json.dumps(cookies),
                    user_agent=user_agent,
                    criado_em=agora,
                    expira_estimado_em=expira_em,
                )
            )
        else:
            registro.cookies_json = json.dumps(cookies)
            registro.user_agent = user_agent
            registro.criado_em = agora
            registro.expira_estimado_em = expira_em
        await sessao.commit()


async def invalidar(sessionmaker: _SessionMaker, dominio: str) -> None:
    async with sessionmaker() as sessao:
        await sessao.execute(delete(SessaoBypass).where(SessaoBypass.site_dominio == dominio))
        await sessao.commit()

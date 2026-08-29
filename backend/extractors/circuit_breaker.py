"""Circuit breaker por site sobre `EstadoSite` (ESPECIFICACAO.md §3A item 2).

"Degradado"/cooldown é estado **derivado** de `cooldown_ate > now()` — nunca um
campo booleano próprio (mesma decisão documentada em `models/estado_site.py`).
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from models.estado_site import EstadoSite

_SessionMaker = async_sessionmaker[AsyncSession]

# Backoff crescente para as primeiras falhas consecutivas (ESPECIFICACAO.md §3A
# item 2: "30s -> 2min -> 10min"); a partir da falha seguinte (>_LIMITE_PARA_COOLDOWN,
# que é len(_BACKOFF_S)), o site é considerado degradado e entra no cooldown cheio.
_BACKOFF_S: tuple[int, ...] = (30, 120, 600)
_LIMITE_PARA_COOLDOWN = len(_BACKOFF_S)
_COOLDOWN_S = 3600


async def esta_em_cooldown(sessionmaker: _SessionMaker, dominio: str) -> bool:
    async with sessionmaker() as sessao:
        estado = await sessao.get(EstadoSite, dominio)
        if estado is None:
            return False
        return estado.cooldown_ate > datetime.now(UTC)


async def obter_cooldown_ate(sessionmaker: _SessionMaker, dominio: str) -> datetime | None:
    """Timestamp até quando `dominio` está em cooldown — usado para compor
    mensagens legíveis (`extractors/busca/servico.py::buscar_por_site_com_variantes`).
    `None` sem registro prévio, mesmo contrato de ausência de `esta_em_cooldown`."""
    async with sessionmaker() as sessao:
        estado = await sessao.get(EstadoSite, dominio)
        return estado.cooldown_ate if estado is not None else None


async def registrar_sucesso(sessionmaker: _SessionMaker, dominio: str) -> None:
    """Zera `falhas_consecutivas` e limpa o cooldown. Sem registro prévio, não há o
    que zerar — nada a fazer."""
    async with sessionmaker() as sessao:
        estado = await sessao.get(EstadoSite, dominio)
        if estado is None:
            return
        estado.falhas_consecutivas = 0
        estado.cooldown_ate = datetime.now(UTC)
        await sessao.commit()


async def registrar_falha(sessionmaker: _SessionMaker, dominio: str, erro: Exception) -> None:
    agora = datetime.now(UTC)
    async with sessionmaker() as sessao:
        estado = await sessao.get(EstadoSite, dominio)
        if estado is None:
            estado = EstadoSite(site_dominio=dominio, falhas_consecutivas=0, cooldown_ate=agora)
            sessao.add(estado)

        estado.falhas_consecutivas += 1
        estado.ultima_falha_em = agora
        estado.ultimo_erro = str(erro)
        estado.cooldown_ate = agora + timedelta(seconds=_backoff_s(estado.falhas_consecutivas))
        await sessao.commit()


def _backoff_s(falhas_consecutivas: int) -> int:
    if falhas_consecutivas > _LIMITE_PARA_COOLDOWN:
        return _COOLDOWN_S
    return _BACKOFF_S[falhas_consecutivas - 1]

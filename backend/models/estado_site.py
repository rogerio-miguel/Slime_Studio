"""Modelo `EstadoSite` (ESPECIFICACAO.md §4/§3A item 2) — circuit breaker por site.

"Degradado" é estado **derivado** (`cooldown_ate > now()`), não um campo próprio
— evita drift entre os dois, conforme o documento de especificação.
"""

from datetime import UTC, datetime

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, ColunaDataHoraUTC


class EstadoSite(Base):
    __tablename__ = "estado_site"

    site_dominio: Mapped[str] = mapped_column(String, primary_key=True)
    falhas_consecutivas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cooldown_ate: Mapped[datetime] = mapped_column(
        ColunaDataHoraUTC(), nullable=False, default=lambda: datetime.now(UTC)
    )
    ultima_falha_em: Mapped[datetime | None] = mapped_column(ColunaDataHoraUTC(), nullable=True)
    ultimo_erro: Mapped[str | None] = mapped_column(String, nullable=True)

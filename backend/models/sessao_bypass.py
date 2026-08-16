"""Modelo `SessaoBypass` (ESPECIFICACAO.md §4/§3A item 1) — cache de sessão/cookies por site."""

from datetime import UTC, datetime

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, ColunaDataHoraUTC


class SessaoBypass(Base):
    __tablename__ = "sessao_bypass"

    site_dominio: Mapped[str] = mapped_column(String, primary_key=True)
    cookies_json: Mapped[str] = mapped_column(Text, nullable=False)
    user_agent: Mapped[str] = mapped_column(String, nullable=False)
    criado_em: Mapped[datetime] = mapped_column(
        ColunaDataHoraUTC(), nullable=False, default=lambda: datetime.now(UTC)
    )
    expira_estimado_em: Mapped[datetime] = mapped_column(ColunaDataHoraUTC(), nullable=False)

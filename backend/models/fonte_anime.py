"""Modelo `FonteAnime` (ESPECIFICACAO.md §4/§3A) — cache do mapeamento anime↔site."""

from datetime import UTC, datetime

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, ColunaDataHoraUTC


class FonteAnime(Base):
    __tablename__ = "fonte_anime"

    anime_id: Mapped[int] = mapped_column(
        ForeignKey("anime.id", ondelete="CASCADE"), primary_key=True
    )
    site_dominio: Mapped[str] = mapped_column(String, primary_key=True)
    identificador_no_site: Mapped[str] = mapped_column(String, nullable=False)
    prioridade: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    resolvido_em: Mapped[datetime] = mapped_column(
        ColunaDataHoraUTC(), nullable=False, default=lambda: datetime.now(UTC)
    )

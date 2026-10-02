"""Modelo `CacheDeFeed` — último resultado bom de cada feed de descoberta da Home.

Existe só para a Home não pagar o custo de uma cache fria (busca AniList + overlay de
arte TMDB por item, dezenas de segundos) a cada reinício da API: o feed persistido é
servido na hora como "velho" e revalidado em segundo plano (`integrations/servico.py`).
Não é fonte de verdade de nada — pode ser apagado a qualquer momento.
"""

from datetime import datetime

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, ColunaDataHoraUTC


class CacheDeFeed(Base):
    __tablename__ = "cache_de_feed"

    chave: Mapped[str] = mapped_column(String, primary_key=True)
    itens_json: Mapped[str] = mapped_column(Text, nullable=False)
    atualizado_em: Mapped[datetime] = mapped_column(ColunaDataHoraUTC(), nullable=False)

"""Modelo `AberturaDeNavegador` — cada vez que o zelador de fontes abriu o
navegador (Chrome visível) sozinho para renovar uma sessão do Cloudflare.

Existe só para o teto diário (`teto_diario_de_aberturas` em `config/horarios.toml`)
sobreviver a reinício da API: contado em memória, um restart devolveria o teto
inteiro. Registrada ANTES da tentativa — uma abertura que falhou também incomodou.
"""

from datetime import datetime

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, ColunaDataHoraUTC


class AberturaDeNavegador(Base):
    __tablename__ = "abertura_de_navegador"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dominio: Mapped[str] = mapped_column(String, nullable=False)
    aberta_em: Mapped[datetime] = mapped_column(ColunaDataHoraUTC(), nullable=False, index=True)

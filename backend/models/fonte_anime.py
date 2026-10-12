"""Modelo `FonteAnime` (ESPECIFICACAO.md §4/§3A) — cache do mapeamento anime↔site.

PK `(anime_id, site_dominio, versao)`: um mesmo site pode ter uma linha
mapeada por versão (`VersaoDeFonte.LEGENDADO`/`DUBLADO`, confirmadas) mais,
opcionalmente, uma linha `NAO_DIFERENCIADA` (site que não separa versão no
markup) — nunca duas linhas colidindo na mesma versão para o mesmo site
(Fase 2 da modelagem dublado/legendado, `fontes/resolucao.py`).
"""

from datetime import UTC, datetime

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from core.enums import OrigemDeFonte, VersaoDeFonte
from models.base import Base, ColunaDataHoraUTC


class FonteAnime(Base):
    __tablename__ = "fonte_anime"

    anime_id: Mapped[int] = mapped_column(
        ForeignKey("anime.id", ondelete="CASCADE"), primary_key=True
    )
    site_dominio: Mapped[str] = mapped_column(String, primary_key=True)
    # Sem default de propósito: quem grava esta linha sempre sabe se a fonte
    # foi confirmada (LEGENDADO/DUBLADO) ou é `NAO_DIFERENCIADA` — nunca um
    # valor implícito aqui (CLAUDE.md §4, erro/estado nunca silencioso).
    versao: Mapped[VersaoDeFonte] = mapped_column(
        SAEnum(VersaoDeFonte, native_enum=False, validate_strings=True),
        primary_key=True,
    )
    identificador_no_site: Mapped[str] = mapped_column(String, nullable=False)
    prioridade: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    resolvido_em: Mapped[datetime] = mapped_column(
        ColunaDataHoraUTC(), nullable=False, default=lambda: datetime.now(UTC)
    )
    # Quem decidiu este mapeamento. Quem grava informa sempre (ver
    # `fontes/resolucao.py::_gravar_fonte_anime`); o default só protege linha
    # criada fora dessas rotas (script, teste) e é o conservador: tratar como
    # MANUAL nunca deixa uma troca automática passar por cima de uma escolha.
    origem: Mapped[OrigemDeFonte] = mapped_column(
        SAEnum(OrigemDeFonte, native_enum=False, validate_strings=True),
        nullable=False,
        default=OrigemDeFonte.MANUAL,
        server_default=text("'MANUAL'"),
    )

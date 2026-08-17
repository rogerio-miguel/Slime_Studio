"""Modelo `Anime` — cada linha é uma temporada (ESPECIFICACAO.md §4/§3F)."""

from datetime import UTC, datetime

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, ColunaDataHoraUTC


class Anime(Base):
    __tablename__ = "anime"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    titulo: Mapped[str] = mapped_column(String, nullable=False)
    slug: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    # Nullable: o cadastro pelo busca-e-confirma do AniList (§3F, Fase 3) preenche
    # ano/capa_path/sinopse/anilist_id depois da criação; o produtor de jobs da
    # Fase 1 (scripts/enfileirar_local.py) cria o Anime só com titulo/slug.
    ano: Mapped[int | None] = mapped_column(Integer, nullable=True)
    anilist_id: Mapped[int | None] = mapped_column(Integer, unique=True, nullable=True)
    kitsu_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Nome enganoso (herdado do schema original) — guarda uma URL do
    # provedor de metadados (AniList/Kitsu), não um caminho em disco local.
    # `Episodio.capa_path` segue a mesma convenção; renomear os dois
    # expandiria o escopo desta leva, então só documentado aqui.
    capa_path: Mapped[str | None] = mapped_column(String, nullable=True)
    sinopse: Mapped[str | None] = mapped_column(String, nullable=True)
    total_episodios_anilist: Mapped[int | None] = mapped_column(Integer, nullable=True)
    criado_em: Mapped[datetime] = mapped_column(
        ColunaDataHoraUTC(), nullable=False, default=lambda: datetime.now(UTC)
    )

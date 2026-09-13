"""Modelo `Episodio` (ESPECIFICACAO.md §4/§3D/§3F).

`hls_path` é gravado **relativo a `MEDIA_ROOT`**, nunca absoluto — um caminho
absoluto quebraria no dual-boot Windows/Zorin (mesmo risco já registrado para
`MEDIA_ROOT`/`SCRATCH_ROOT` na seção 6 do documento de especificação).
"""

from datetime import UTC, datetime

from sqlalchemy import JSON, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from core.enums import StatusEpisodio, TipoEpisodio, VersaoEpisodio
from models.base import Base, ColunaDataHoraUTC


class Episodio(Base):
    __tablename__ = "episodio"
    __table_args__ = (
        UniqueConstraint("anime_id", "numero", "tipo", "versao", name="uq_episodio_identidade"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    anime_id: Mapped[int] = mapped_column(
        ForeignKey("anime.id", ondelete="CASCADE"), nullable=False, index=True
    )
    numero: Mapped[int] = mapped_column(Integer, nullable=False)
    # Nullable: só confirmado ao enfileirar (§3F); o produtor de jobs pode não
    # ter um título ainda no momento da criação. Hoje vem do overlay TMDB
    # (`api/servicos/jobs.py::criar_job_site`, `info_de_episodio`) — nenhum
    # extractor de scraping expõe título de episódio.
    titulo: Mapped[str | None] = mapped_column(String, nullable=True)
    # Sinopse do episódio via TMDB (mesma fonte/momento de `titulo` acima) —
    # nullable e sem backfill: episódio já capturado antes desta coluna fica
    # `NULL` até uma recaptura.
    sinopse: Mapped[str | None] = mapped_column(String, nullable=True)
    numero_fonte: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tipo: Mapped[TipoEpisodio] = mapped_column(
        SAEnum(TipoEpisodio, native_enum=False, validate_strings=True), nullable=False
    )
    versao: Mapped[VersaoEpisodio] = mapped_column(
        SAEnum(VersaoEpisodio, native_enum=False, validate_strings=True),
        nullable=False,
        default=VersaoEpisodio.LEGENDADO,
    )
    url_fonte: Mapped[str] = mapped_column(String, nullable=False)
    site_origem: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[StatusEpisodio] = mapped_column(
        SAEnum(StatusEpisodio, native_enum=False, validate_strings=True),
        nullable=False,
        default=StatusEpisodio.PENDENTE,
    )
    # Nullable: só preenchido pelo worker ao concluir o empacotamento
    # (worker/executor.py, transação final de "pronto").
    hls_path: Mapped[str | None] = mapped_column(String, nullable=True)
    renditions_disponiveis: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    capa_path: Mapped[str | None] = mapped_column(String, nullable=True)
    tamanho_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duracao_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Posição de reprodução (Feature "continuar assistindo") — 1:1 com
    # `Episodio`, sem tabela própria (app local mono-usuário). Nullable: nunca
    # assistido parcialmente ainda. `progresso_atualizado_em` ordena a
    # prateleira "Continuar assistindo" (mais recente primeiro) —
    # `api/servicos/progresso.py::listar_continuar_assistindo`.
    progresso_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    progresso_atualizado_em: Mapped[datetime | None] = mapped_column(
        ColunaDataHoraUTC(), nullable=True
    )
    assistido_em: Mapped[datetime | None] = mapped_column(ColunaDataHoraUTC(), nullable=True)
    criado_em: Mapped[datetime] = mapped_column(
        ColunaDataHoraUTC(), nullable=False, default=lambda: datetime.now(UTC)
    )

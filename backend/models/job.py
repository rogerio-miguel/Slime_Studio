"""Modelo `Job` (ESPECIFICACAO.md §4/§3B) — fila de processamento persistida.

`chunk_atual`/`total_chunks` existem no schema hoje mas ficam sem uso até o ramo
de upscaling em lote entrar em produção (pós-gatilho, §12) — não removê-los.
"""

from datetime import UTC, datetime

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from core.enums import StatusJob
from models.base import Base, ColunaDataHoraUTC


class Job(Base):
    __tablename__ = "job"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    episodio_id: Mapped[int] = mapped_column(
        ForeignKey("episodio.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[StatusJob] = mapped_column(
        SAEnum(StatusJob, native_enum=False, validate_strings=True),
        nullable=False,
        default=StatusJob.NA_FILA,
        index=True,
    )
    etapa_atual: Mapped[str | None] = mapped_column(String, nullable=True)
    progresso_pct: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Repassado por scripts/enfileirar_local.py (flag --duracao-esperada-s, opcional) até
    # worker/pipeline/validacao.py::decidir_plano como checagem de sanidade da duração
    # sondada; nulo quando o produtor de jobs não a informa.
    duracao_esperada_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunk_atual: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_chunks: Mapped[int | None] = mapped_column(Integer, nullable=True)
    erro_msg: Mapped[str | None] = mapped_column(String, nullable=True)
    tentativas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    criado_em: Mapped[datetime] = mapped_column(
        ColunaDataHoraUTC(), nullable=False, default=lambda: datetime.now(UTC)
    )
    iniciado_em: Mapped[datetime | None] = mapped_column(ColunaDataHoraUTC(), nullable=True)
    finalizado_em: Mapped[datetime | None] = mapped_column(ColunaDataHoraUTC(), nullable=True)
    proxima_tentativa_em: Mapped[datetime | None] = mapped_column(
        ColunaDataHoraUTC(), nullable=True
    )
    heartbeat_em: Mapped[datetime | None] = mapped_column(ColunaDataHoraUTC(), nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String, nullable=True)
    cancelamento_solicitado: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

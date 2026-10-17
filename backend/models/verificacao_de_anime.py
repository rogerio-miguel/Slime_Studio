"""Modelo `VerificacaoDeAnime` — estado persistido de cada verificação periódica
de um anime (hoje, a sondagem da fonte).

Existe para falha ter memória: sem isto, uma sondagem que falhava (ex. Cloudflare
rejeitando a sessão) era retentada a cada abertura da Galeria e o único cooldown
vivia num dict em memória que o restart zerava. `proxima_em` é o único campo que
o gate consulta; o resto é diagnóstico ("por que este anime não foi sondado?").
Não toca `Anime.fonte_verificada_em`, que segue sendo o carimbo do último SUCESSO.
"""

from datetime import datetime

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from core.enums import ResultadoDeVerificacao, TarefaDeVerificacao
from models.base import Base, ColunaDataHoraUTC


class VerificacaoDeAnime(Base):
    __tablename__ = "verificacao_de_anime"
    __table_args__ = (Index("ix_verificacao_de_anime_proxima_em", "proxima_em"),)

    anime_id: Mapped[int] = mapped_column(
        ForeignKey("anime.id", ondelete="CASCADE"), primary_key=True
    )
    tarefa: Mapped[TarefaDeVerificacao] = mapped_column(
        SAEnum(TarefaDeVerificacao, native_enum=False, validate_strings=True),
        primary_key=True,
    )
    proxima_em: Mapped[datetime] = mapped_column(ColunaDataHoraUTC(), nullable=False)
    ultima_tentativa_em: Mapped[datetime] = mapped_column(ColunaDataHoraUTC(), nullable=False)
    ultimo_sucesso_em: Mapped[datetime | None] = mapped_column(ColunaDataHoraUTC(), nullable=True)
    ultimo_resultado: Mapped[ResultadoDeVerificacao] = mapped_column(
        SAEnum(ResultadoDeVerificacao, native_enum=False, validate_strings=True),
        nullable=False,
    )
    falhas_consecutivas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Classe do erro (sem a mensagem, que pode carregar URL), truncada: diagnóstico.
    detalhe: Mapped[str | None] = mapped_column(String, nullable=True)

"""Enums de domínio do Slime Studio (ESPECIFICACAO.md, seções 3B/3F/4).

Domínio puro — sem import de SQLAlchemy nem de nenhum framework. `models/` é quem
adapta estes enums para colunas de banco (`SAEnum`), nunca o contrário.
"""

from enum import StrEnum
from typing import Final

# Discriminador do modo "arquivo local" em `Episodio.site_origem` — distingue do
# domínio de um site real (ex. "animefire.io") para decidir se `resolver_fonte`
# (worker/pipeline/fonte.py) pula a extração remota.
SITE_LOCAL: Final[str] = "local"


class StatusJob(StrEnum):
    """Estados do `Job` ao longo do pipeline (ESPECIFICACAO.md §3B).

    Inclui os estados do ramo de upscaling em lote (`extraindo_frames`, `upscaling`,
    `remontando`, `pausado`) mesmo sem lógica implementada nesta fase — são
    pós-gatilho (§12) e o schema/enum já os reserva por decisão explícita do
    documento ("não removê-los").
    """

    NA_FILA = "na_fila"
    BAIXANDO = "baixando"
    VALIDANDO_FONTE = "validando_fonte"
    TRANSCODIFICANDO = "transcodificando"
    EXTRAINDO_FRAMES = "extraindo_frames"
    UPSCALING = "upscaling"
    REMONTANDO = "remontando"
    EMPACOTANDO_HLS = "empacotando_hls"
    PRONTO = "pronto"
    FALHOU = "falhou"
    FALHOU_EXTRACAO = "falhou_extracao"
    AGUARDANDO_INTERVENCAO = "aguardando_intervencao"
    CANCELANDO = "cancelando"
    CANCELADO = "cancelado"
    PAUSADO = "pausado"


class TipoEpisodio(StrEnum):
    REGULAR = "regular"
    OVA = "ova"
    ESPECIAL = "especial"
    FILME = "filme"


class VersaoEpisodio(StrEnum):
    LEGENDADO = "legendado"
    DUBLADO = "dublado"


class StatusEpisodio(StrEnum):
    PENDENTE = "pendente"
    PRONTO = "pronto"
    FALHOU = "falhou"
    SOMENTE_720P = "somente_720p"


# Estados que contam como "em andamento" para fins de reclaim por heartbeat
# (worker/fila.py: reciclar_jobs_orfaos). Um job travado em qualquer um destes
# estados, com heartbeat velho, volta para `na_fila`.
ESTADOS_EM_EXECUCAO: frozenset[StatusJob] = frozenset(
    {
        StatusJob.BAIXANDO,
        StatusJob.VALIDANDO_FONTE,
        StatusJob.TRANSCODIFICANDO,
        StatusJob.EXTRAINDO_FRAMES,
        StatusJob.UPSCALING,
        StatusJob.REMONTANDO,
        StatusJob.EMPACOTANDO_HLS,
        StatusJob.CANCELANDO,
    }
)

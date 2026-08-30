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
    """Versão do arquivo capturado — o que o usuário assiste (`Episodio`)."""

    LEGENDADO = "legendado"
    DUBLADO = "dublado"
    # Fonte é `VersaoDeFonte.NAO_DIFERENCIADA` (site não separa legendado de
    # dublado no próprio markup) — o episódio capturado sob ela nunca herda
    # cegamente o que o cliente pediu, é rotulado `DESCONHECIDA` (worker/jobs.py).
    DESCONHECIDA = "desconhecida"


class VersaoDeFonte(StrEnum):
    """Estado do *mapeamento* de uma fonte (`FonteAnime`) — o que o site oferece,
    não o episódio. Mantido separado de `VersaoEpisodio` de propósito: não
    fundir os dois enums."""

    LEGENDADO = "legendado"
    DUBLADO = "dublado"
    NAO_DIFERENCIADA = "nao_diferenciada"


class StatusEpisodio(StrEnum):
    PENDENTE = "pendente"
    PRONTO = "pronto"
    FALHOU = "falhou"
    SOMENTE_720P = "somente_720p"
    # Terminou de ser assistido (limiar de `usePontoDeAssistido`) e teve seus
    # arquivos em disco liberados (`api/servicos/catalogo.py::
    # liberar_episodio`) — distinto de `PENDENTE` (nunca chegou a ser
    # capturado) porque preserva `assistido_em`/`url_fonte`/`site_origem` da
    # captura original; uma recaptura volta o episódio para `PENDENTE`
    # (D2, `api/servicos/jobs.py::criar_job_site`).
    LIBERADO = "liberado"


class StatusLancamento(StrEnum):
    """Estado de lançamento de um `Anime` — espelha `MediaStatus` da AniList.

    Alimenta o detector de episódios novos (badge no catálogo): só animes em
    `EM_LANCAMENTO` recebem o refresh oportunista de `proximo_ep_*`. Persistido
    como name (não value), igual aos demais enums de `models/` (`SAEnum(...,
    native_enum=False)`).
    """

    EM_LANCAMENTO = "em_lancamento"
    FINALIZADO = "finalizado"
    NAO_LANCADO = "nao_lancado"
    CANCELADO = "cancelado"
    HIATO = "hiato"


# Estados que contam como "em andamento" para fins de reclaim por heartbeat
# (db/fila.py: reciclar_jobs_orfaos). Um job travado em qualquer um destes
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

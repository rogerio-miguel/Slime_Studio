"""Orquestra o processamento de um `Job`, do claim até `pronto`/`falhou`
(ESPECIFICACAO.md §3B).

Cada transição de estado usa uma sessão curta — nunca segura escrita aberta
durante a execução do `ffmpeg`. `FonteInvalida`/`FalhaDeFerramenta` são erros
de negócio esperados (log em `warning`, sem traceback ruidoso); qualquer outra
exceção loga em `exception` (com traceback) antes de marcar falha. O carregamento
do job/episódio também roda dentro do `try` — se ele falhar, a exceção não escapa
sem tratamento; quando o `Job` existe (o join com episódio/anime é que falhou), a
tentativa de `falhar()` chega a marcá-lo com `etapa_atual`/`erro_msg` preenchidos.

`FalhaDeExtracao` (Fase 2, ESPECIFICACAO.md §3A) é tratada à parte de
`FonteInvalida`/`FalhaDeFerramenta`: uma falha de extração retentável não é
"falhou" definitivo — o job volta pra fila como `falhou_extracao` com backoff
(`_BACKOFF_EXTRACAO_S`) e o episódio continua `pendente`; só esgotar as
tentativas ou uma falha não-retentável (`EstruturaDoSiteMudou`) vira
`aguardando_intervencao`.
"""

import logging
import shutil
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config import Config
from core.enums import StatusEpisodio, StatusJob
from core.erros import ErroSlimeStudio, FalhaDeExtracao, FalhaDeFerramenta, FonteInvalida
from core.midia import diretorio_do_episodio
from db.fila import (
    atualizar_status,
    concluir,
    falhar,
    falhar_extracao,
    marcar_aguardando_intervencao,
)
from models.anime import Anime
from models.episodio import Episodio
from models.job import Job
from worker.pipeline.fonte import resolver_fonte
from worker.pipeline.hls import empacotar
from worker.pipeline.validacao import conferir_decodificacao, decidir_plano, sondar

logger = logging.getLogger(__name__)

_SessionMaker = async_sessionmaker[AsyncSession]

# Mesma progressão documentada em ESPECIFICACAO.md §3A ("30s -> 2min -> 10min")
# do circuit breaker por site (`extractors/circuit_breaker.py::_BACKOFF_S`) —
# mantida como constante própria aqui porque governa o *job* (retentativa de
# um episódio específico), não o *site* (é um conceito relacionado, não o
# mesmo dado; `_BACKOFF_S` de lá é privado ao módulo do breaker).
_BACKOFF_EXTRACAO_S: tuple[int, ...] = (30, 120, 600)
_MAX_TENTATIVAS_EXTRACAO = 3


async def processar(job_id: int, sessionmaker: _SessionMaker, config: Config) -> None:
    etapa_atual = "carregando_job"
    destino: Path | None = None
    episodio_id: int | None = None

    try:
        job, episodio, anime = await _carregar_job_e_episodio(sessionmaker, job_id)
        episodio_id = episodio.id
        etapa_atual = StatusJob.BAIXANDO.value
        await atualizar_status(sessionmaker, job_id, StatusJob.BAIXANDO, etapa=etapa_atual)

        caminho_fonte = await resolver_fonte(sessionmaker, config, anime=anime, episodio=episodio)

        etapa_atual = StatusJob.VALIDANDO_FONTE.value
        await atualizar_status(
            sessionmaker, job_id, StatusJob.VALIDANDO_FONTE, etapa=etapa_atual
        )
        inicio = time.monotonic()
        sondagem = await sondar(caminho_fonte, config.ffprobe)
        # 5s (padrão de `conferir_decodificacao`) só pega corrupção no cabeçalho do
        # arquivo; episódios reais têm ~20-24min — 15s aumenta a chance de pegar
        # corrupção mais adiante sem tornar a checagem lenta.
        await conferir_decodificacao(caminho_fonte, config.ffmpeg, segundos=15)
        plano = decidir_plano(sondagem, duracao_esperada_s=job.duracao_esperada_s)
        logger.info(
            "job %s: validando_fonte concluída em %.1fs", job_id, time.monotonic() - inicio
        )

        # Uma única invocação de ffmpeg faz transcode (se necessário) e
        # empacotamento juntos — o status exibido só rotula qual dos dois
        # domina essa invocação, não são duas passadas.
        status_empacotamento = (
            StatusJob.TRANSCODIFICANDO
            if plano.exige_recodificacao
            else StatusJob.EMPACOTANDO_HLS
        )
        etapa_atual = status_empacotamento.value
        await atualizar_status(sessionmaker, job_id, status_empacotamento, etapa=etapa_atual)

        destino = diretorio_do_episodio(
            config.media_root, anime.slug, episodio.numero, episodio.tipo, episodio.versao
        )
        inicio = time.monotonic()
        resultado = await empacotar(
            caminho_fonte, destino, plano, sondagem, config.ffmpeg, config.media_root
        )
        if not resultado.master_absoluto.exists():
            raise FalhaDeFerramenta(
                f"master manifest ausente após empacotar: {resultado.master_absoluto}"
            )
        logger.info(
            "job %s: empacotamento HLS concluído em %.1fs", job_id, time.monotonic() - inicio
        )

        await _marcar_episodio_pronto(
            sessionmaker,
            episodio.id,
            hls_path=str(resultado.master_relativo),
            renditions=resultado.renditions,
            tamanho_bytes=resultado.tamanho_bytes,
            duracao_s=round(sondagem.duracao_s),
        )
        await concluir(sessionmaker, job_id)

    except FalhaDeExtracao as excecao:
        logger.warning("job %s: falha de extração em %s: %s", job_id, etapa_atual, excecao)
        if excecao.permite_retentativa and job.tentativas < _MAX_TENTATIVAS_EXTRACAO:
            indice_backoff = min(job.tentativas, len(_BACKOFF_EXTRACAO_S) - 1)
            proxima_tentativa_em = datetime.now(UTC) + timedelta(
                seconds=_BACKOFF_EXTRACAO_S[indice_backoff]
            )
            await falhar_extracao(
                sessionmaker,
                job_id,
                etapa=etapa_atual,
                erro=str(excecao),
                proxima_tentativa_em=proxima_tentativa_em,
            )
            # Episódio continua `pendente` — será retentado, não é falha definitiva.
        else:
            await marcar_aguardando_intervencao(
                sessionmaker, job_id, etapa=etapa_atual, erro=str(excecao)
            )
            if episodio_id is not None:
                await _marcar_episodio_falhou(sessionmaker, episodio_id)
        _remover_tmp_orfao(destino)
    except (FonteInvalida, FalhaDeFerramenta) as excecao:
        # `cauda_stderr` só existe em `FalhaDeFerramenta` (não em `FonteInvalida`) e
        # carrega o stderr do ffmpeg — sem ele no log o motivo real da falha some.
        cauda_stderr = getattr(excecao, "cauda_stderr", "")
        sufixo_stderr = f"\nstderr do ffmpeg: {cauda_stderr}" if cauda_stderr else ""
        logger.warning(
            "job %s: falhou em %s: %s%s", job_id, etapa_atual, excecao, sufixo_stderr
        )
        if episodio_id is not None:
            await _marcar_episodio_falhou(sessionmaker, episodio_id)
        await falhar(sessionmaker, job_id, etapa=etapa_atual, erro=str(excecao))
        _remover_tmp_orfao(destino)
    except Exception as excecao:
        logger.exception("job %s: falhou inesperadamente em %s", job_id, etapa_atual)
        if episodio_id is not None:
            await _marcar_episodio_falhou(sessionmaker, episodio_id)
        await falhar(sessionmaker, job_id, etapa=etapa_atual, erro=str(excecao))
        _remover_tmp_orfao(destino)


async def _carregar_job_e_episodio(
    sessionmaker: _SessionMaker, job_id: int
) -> tuple[Job, Episodio, Anime]:
    async with sessionmaker() as sessao:
        resultado = await sessao.execute(
            select(Job, Episodio, Anime)
            .join(Episodio, Job.episodio_id == Episodio.id)
            .join(Anime, Episodio.anime_id == Anime.id)
            .where(Job.id == job_id)
        )
        linha = resultado.first()
        if linha is None:
            raise ErroSlimeStudio(f"job {job_id} (ou seu episódio/anime) não encontrado")
        job, episodio, anime = linha
        return job, episodio, anime


async def _marcar_episodio_pronto(
    sessionmaker: _SessionMaker,
    episodio_id: int,
    *,
    hls_path: str,
    renditions: list[str],
    tamanho_bytes: int,
    duracao_s: int,
) -> None:
    async with sessionmaker() as sessao:
        episodio = await sessao.get(Episodio, episodio_id)
        if episodio is None:
            raise ErroSlimeStudio(f"episódio {episodio_id} desapareceu durante o processamento")
        episodio.hls_path = hls_path
        episodio.renditions_disponiveis = renditions
        episodio.tamanho_bytes = tamanho_bytes
        episodio.duracao_s = duracao_s
        episodio.status = StatusEpisodio.PRONTO
        await sessao.commit()


async def _marcar_episodio_falhou(sessionmaker: _SessionMaker, episodio_id: int) -> None:
    async with sessionmaker() as sessao:
        episodio = await sessao.get(Episodio, episodio_id)
        if episodio is None:
            logger.warning(
                "episódio %s desapareceu antes de poder ser marcado como falhou", episodio_id
            )
            return
        episodio.status = StatusEpisodio.FALHOU
        await sessao.commit()


def _remover_tmp_orfao(destino: Path | None) -> None:
    """Melhor esforço: `empacotar()` já remove seu próprio `.tmp` em qualquer
    falha interna; isto cobre o caso de a exceção ter vindo de fora dela."""
    if destino is None:
        return
    tmp = destino.with_name(destino.name + ".tmp")
    if tmp.exists():
        shutil.rmtree(tmp, ignore_errors=True)

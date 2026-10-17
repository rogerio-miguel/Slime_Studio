"""Runner único de subprocesso para `ffmpeg`/`ffprobe` (ESPECIFICACAO.md §3B/§3D).

Ponto único de execução de subprocesso externo do pipeline — o resto do worker
passa por aqui em vez de reimplementar `asyncio.create_subprocess_exec` por etapa.
"""

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from yt_dlp.version import __version__ as _VERSAO_DO_YTDLP

from core.erros import FalhaDeFerramenta

logger = logging.getLogger(__name__)

_TAMANHO_CAUDA_STDERR = 4000
# Sites de streaming mudam toda semana e o yt-dlp já teve advisories de execução de código
# (github.com/yt-dlp/yt-dlp/security): passado isto, o worker avisa no start.
_IDADE_MAXIMA_YTDLP_DIAS = 90


@dataclass(frozen=True, slots=True)
class ResultadoProcesso:
    codigo: int
    stdout: str
    stderr: str


async def executar(
    argumentos: Sequence[str], *, timeout_s: int | None = None
) -> ResultadoProcesso:
    """Executa um comando externo e aguarda a conclusão.

    stdin fechado (`DEVNULL`) para nunca bloquear esperando entrada interativa.
    Captura stdout/stderr via `communicate()` (evita deadlock de pipe cheio).
    Levanta `FalhaDeFerramenta` (com a cauda do stderr) se o código de saída for
    != 0, ou se o processo estourar `timeout_s` (o processo é morto nesse caso).
    Se a task que aguarda `executar()` for cancelada (shutdown cooperativo do
    worker, `worker/__main__.py`), o processo em voo também é morto antes da
    `CancelledError` se propagar — senão o subprocesso ficaria órfão.
    """
    processo = await asyncio.create_subprocess_exec(
        *argumentos,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout_bruto, stderr_bruto = await asyncio.wait_for(
            processo.communicate(), timeout=timeout_s
        )
    except TimeoutError as excecao:
        processo.kill()
        await processo.wait()
        raise FalhaDeFerramenta(
            f"comando excedeu timeout de {timeout_s}s: {' '.join(argumentos)}"
        ) from excecao
    except asyncio.CancelledError:
        processo.kill()
        await processo.wait()
        raise

    stdout = stdout_bruto.decode(errors="replace")
    stderr = stderr_bruto.decode(errors="replace")

    if processo.returncode != 0:
        raise FalhaDeFerramenta(
            f"comando falhou (código {processo.returncode}): {' '.join(argumentos)}",
            cauda_stderr=stderr[-_TAMANHO_CAUDA_STDERR:],
        )

    return ResultadoProcesso(codigo=processo.returncode, stdout=stdout, stderr=stderr)


def registrar_versao_do_ytdlp(*, versao: str = _VERSAO_DO_YTDLP, hoje: date | None = None) -> None:
    """Loga a versão do yt-dlp (`AAAA.MM.DD[.hhmmss]`) e avisa se passou de
    `_IDADE_MAXIMA_YTDLP_DIAS`. Formato inesperado também vira aviso, nunca silêncio."""
    hoje = hoje or date.today()
    try:
        ano, mes, dia = (int(parte) for parte in versao.split(".")[:3])
        idade_dias = (hoje - date(ano, mes, dia)).days
    except ValueError:
        logger.warning("yt-dlp: versão em formato inesperado (%r), idade não verificada", versao)
        return
    if idade_dias > _IDADE_MAXIMA_YTDLP_DIAS:
        logger.warning(
            "yt-dlp %s tem %d dias (limite %d): atualize com `uv lock --upgrade-package yt-dlp`"
            " e `uv sync`",
            versao,
            idade_dias,
            _IDADE_MAXIMA_YTDLP_DIAS,
        )
    else:
        logger.info("yt-dlp %s (%d dias)", versao, idade_dias)

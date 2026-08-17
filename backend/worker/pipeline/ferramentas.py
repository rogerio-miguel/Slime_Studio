"""Runner único de subprocesso para `ffmpeg`/`ffprobe` (ESPECIFICACAO.md §3B/§3D).

Ponto único de execução de subprocesso externo do pipeline — o resto do worker
passa por aqui em vez de reimplementar `asyncio.create_subprocess_exec` por etapa.
"""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass

from core.erros import FalhaDeFerramenta

_TAMANHO_CAUDA_STDERR = 4000


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

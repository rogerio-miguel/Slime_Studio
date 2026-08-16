"""Lock de instância única do worker (ESPECIFICACAO.md §3B).

O kernel libera o lock automaticamente quando o processo morre — o PID escrito
no arquivo serve só para diagnóstico manual, nunca é lido pela lógica.
"""

import fcntl
import os
from pathlib import Path
from typing import IO

from core.erros import WorkerJaEmExecucao


class BloqueioDeInstancia:
    def __init__(self, caminho: Path) -> None:
        self._caminho = caminho
        self._arquivo: IO[str] | None = None

    def __enter__(self) -> "BloqueioDeInstancia":
        self._caminho.parent.mkdir(parents=True, exist_ok=True)
        arquivo = open(self._caminho, "w")
        try:
            fcntl.flock(arquivo, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as excecao:
            arquivo.close()
            raise WorkerJaEmExecucao(
                f"já existe um worker rodando (lock: {self._caminho})"
            ) from excecao

        arquivo.write(str(os.getpid()))
        arquivo.flush()
        self._arquivo = arquivo
        return self

    def __exit__(self, *exc: object) -> None:
        if self._arquivo is not None:
            fcntl.flock(self._arquivo, fcntl.LOCK_UN)
            self._arquivo.close()
            self._arquivo = None

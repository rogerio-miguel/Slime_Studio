"""Sprite de miniaturas pra prévia de hover na barra de progresso do player.

Best-effort: ao contrário de `hls.py::empacotar` (obrigatório — sem HLS não
há episódio jogável), a ausência deste sprite só desliga a prévia de hover no
frontend, nunca falha o job (ver captura de `FalhaDeFerramenta` em
`worker/executor.py`). Por isso mora num módulo à parte, não dentro de
`hls.py`.

Convenção espelhada em `frontend/src/player/PreviaDeCena.jsx` (intervalo/grid
fixos nos dois lados, não persistidos em `Episodio` — arquivo de nome fixo no
mesmo diretório do HLS, servido pela rota catch-all de mídia já existente):
mudar os valores aqui exige mudar lá também.
"""

import math
from pathlib import Path

from worker.pipeline.ferramentas import executar

NOME_ARQUIVO = "storyboard.jpg"
# Espelhados em PreviaDeCena.jsx — ver docstring do módulo.
INTERVALO_S = 10
COLUNAS = 10
LARGURA_THUMB = 320
ALTURA_THUMB = 180


async def gerar_storyboard(
    fonte: Path, destino: Path, duracao_s: float, ffmpeg: Path
) -> None:
    """Extrai 1 frame a cada `INTERVALO_S` de `fonte` e monta um grid único
    (`tile`) em `destino/NOME_ARQUIVO`. `destino` já existe (chamado depois de
    `empacotar()`, mesmo diretório do HLS).

    Sem arquivo `.tmp`+promoção atômica como `empacotar()`: uma falha aqui não
    deixa o episódio inconsistente (o pior caso é o arquivo antigo/ausente
    continuar servindo, ou um 500 momentâneo se `executar` matar o processo
    no meio da escrita — `-y` na próxima tentativa sobrescreve limpo).
    """
    total_frames = max(1, math.ceil(duracao_s / INTERVALO_S))
    linhas = math.ceil(total_frames / COLUNAS)

    argumentos = [
        str(ffmpeg),
        "-nostdin",
        "-hide_banner",
        "-y",
        "-i",
        str(fonte),
        "-frames:v",
        "1",
        "-vf",
        f"fps=1/{INTERVALO_S},scale={LARGURA_THUMB}:{ALTURA_THUMB},tile={COLUNAS}x{linhas}",
        "-q:v",
        "4",
        str(destino / NOME_ARQUIVO),
    ]
    await executar(argumentos, timeout_s=None)

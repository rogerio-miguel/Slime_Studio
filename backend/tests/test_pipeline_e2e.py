"""Teste de integração ponta a ponta: validação + empacotamento HLS, sobre um
clipe de 5s sintético gerado via `ffmpeg -f lavfi -i testsrc` — nenhum asset de
mídia versionado no git.
"""

import shutil
from pathlib import Path

import pytest

from core.enums import TipoEpisodio, VersaoEpisodio
from core.midia import diretorio_do_episodio
from worker.pipeline.ferramentas import executar
from worker.pipeline.hls import empacotar
from worker.pipeline.validacao import conferir_decodificacao, decidir_plano, sondar

pytestmark = pytest.mark.integracao

_FFMPEG = shutil.which("ffmpeg")
_FFPROBE = shutil.which("ffprobe")


@pytest.mark.skipif(_FFMPEG is None or _FFPROBE is None, reason="ffmpeg/ffprobe não está no PATH")
async def test_pipeline_ponta_a_ponta_gera_master_e_segmentos(tmp_path: Path):
    ffmpeg = Path(_FFMPEG)
    ffprobe = Path(_FFPROBE)

    fonte = tmp_path / "fonte.mp4"
    await _gerar_clipe_sintetico(ffmpeg, fonte, duracao_s=5)

    sondagem = await sondar(fonte, ffprobe)
    await conferir_decodificacao(fonte, ffmpeg, segundos=2)
    plano = decidir_plano(sondagem)

    media_root = tmp_path / "media"
    destino = diretorio_do_episodio(
        media_root, "anime-teste", 1, TipoEpisodio.REGULAR, VersaoEpisodio.LEGENDADO
    )
    resultado = await empacotar(
        fonte, destino, plano, sondagem, ffmpeg, media_root, duracao_segmento_s=2
    )

    assert resultado.master_absoluto.exists()
    assert resultado.master_absoluto.name == "master.m3u8"
    assert list(destino.rglob("*.ts"))
    assert resultado.tamanho_bytes > 0


async def _gerar_clipe_sintetico(ffmpeg: Path, destino: Path, *, duracao_s: int) -> None:
    await executar(
        [
            str(ffmpeg),
            "-nostdin",
            "-hide_banner",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=duration={duracao_s}:size=1280x720:rate=24",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-profile:v",
            "high",
            str(destino),
        ],
        timeout_s=60,
    )

"""Testes de `_hints_de_bitrate()` — puros, sem subprocesso (worker/pipeline/hls.py).

Cobre o bug real que motivou o fix: em modo `copy`, o ffmpeg não tem como
calcular `BANDWIDTH` pro master manifest sozinho (aviso `Bandwidth info not
available` do próprio ffmpeg) e omite a variante — ver `hls.py::empacotar()`
e a checagem de `#EXT-X-STREAM-INF` no conteúdo do master gerado.
"""

import pytest

from core.erros import FalhaDeFerramenta
from worker.pipeline.hls import (
    _BITRATE_AUDIO_HINT_BPS,
    _BITRATE_VIDEO_HINT_MINIMO_BPS,
    _hints_de_bitrate,
)
from worker.pipeline.validacao import EstrategiaFluxo, PlanoDeEmpacotamento, SondagemMidia


def _sondagem(**overrides: object) -> SondagemMidia:
    padrao: dict[str, object] = {
        "duracao_s": 1440.0,
        "codec_video": "h264",
        "codec_audio": "aac",
        "pix_fmt": "yuv420p",
        "perfil_video": "High",
        "largura": 1280,
        "altura": 720,
        "tamanho_bytes": 200_000_000,
    }
    padrao.update(overrides)
    return SondagemMidia(**padrao)  # type: ignore[arg-type]


def _plano(**overrides: object) -> PlanoDeEmpacotamento:
    padrao: dict[str, object] = {
        "video": EstrategiaFluxo.COPIA,
        "audio": EstrategiaFluxo.COPIA,
        "rendition": "720p",
        "tem_audio": True,
    }
    padrao.update(overrides)
    return PlanoDeEmpacotamento(**padrao)  # type: ignore[arg-type]


def test_copia_video_e_audio_reserva_audio_fixo_e_resto_pro_video():
    sondagem = _sondagem(tamanho_bytes=200_000_000, duracao_s=1440.0)
    hint_video, hint_audio = _hints_de_bitrate(sondagem, _plano())

    bitrate_total_bps = int(200_000_000 * 8 / 1440.0)
    assert hint_audio == _BITRATE_AUDIO_HINT_BPS
    assert hint_video == bitrate_total_bps - _BITRATE_AUDIO_HINT_BPS


def test_copia_sem_audio_nao_reserva_nada_pro_audio():
    sondagem = _sondagem()
    plano = _plano(tem_audio=False, audio=EstrategiaFluxo.COPIA)
    hint_video, hint_audio = _hints_de_bitrate(sondagem, plano)

    bitrate_total_bps = int(sondagem.tamanho_bytes * 8 / sondagem.duracao_s)
    assert hint_audio is None
    assert hint_video == bitrate_total_bps


def test_recodifica_video_e_audio_nao_gera_hint_nenhum():
    plano = _plano(video=EstrategiaFluxo.RECODIFICA, audio=EstrategiaFluxo.RECODIFICA)
    hint_video, hint_audio = _hints_de_bitrate(_sondagem(), plano)

    assert (hint_video, hint_audio) == (None, None)


def test_so_audio_em_copia_gera_hint_so_de_audio():
    plano = _plano(video=EstrategiaFluxo.RECODIFICA, audio=EstrategiaFluxo.COPIA)
    hint_video, hint_audio = _hints_de_bitrate(_sondagem(), plano)

    assert hint_video is None
    assert hint_audio == _BITRATE_AUDIO_HINT_BPS


def test_fonte_muito_pequena_usa_piso_minimo_de_video():
    # tamanho ínfimo pra duração longa: bitrate total fica bem abaixo da
    # reserva de áudio — sem piso, `hint_video` sairia negativo.
    sondagem = _sondagem(tamanho_bytes=1_000, duracao_s=1440.0)
    hint_video, _ = _hints_de_bitrate(sondagem, _plano())

    assert hint_video == _BITRATE_VIDEO_HINT_MINIMO_BPS


@pytest.mark.parametrize("duracao_s", [0.0, -1.0])
def test_duracao_invalida_levanta_falha_de_ferramenta(duracao_s: float):
    sondagem = _sondagem(duracao_s=duracao_s)

    with pytest.raises(FalhaDeFerramenta):
        _hints_de_bitrate(sondagem, _plano())

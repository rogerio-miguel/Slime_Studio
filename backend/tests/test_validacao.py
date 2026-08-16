"""Testes de `decidir_plano()` — puros, sem subprocesso (worker/pipeline/validacao.py)."""

import pytest

from core.erros import FonteInvalida
from worker.pipeline.validacao import EstrategiaFluxo, SondagemMidia, decidir_plano


def _sondagem(**overrides: object) -> SondagemMidia:
    padrao: dict[str, object] = {
        "duracao_s": 1440.0,
        "codec_video": "h264",
        "codec_audio": "aac",
        "pix_fmt": "yuv420p",
        "perfil_video": "High",
        "largura": 1920,
        "altura": 1080,
        "tamanho_bytes": 500_000_000,
    }
    padrao.update(overrides)
    return SondagemMidia(**padrao)  # type: ignore[arg-type]


def test_h264_yuv420p_perfil_valido_copia_video_e_audio():
    plano = decidir_plano(_sondagem())

    assert plano.video is EstrategiaFluxo.COPIA
    assert plano.audio is EstrategiaFluxo.COPIA
    assert plano.rendition == "1080p"
    assert plano.exige_recodificacao is False


def test_hi10p_yuv420p10le_forca_recodificacao_de_video():
    plano = decidir_plano(_sondagem(pix_fmt="yuv420p10le"))

    assert plano.video is EstrategiaFluxo.RECODIFICA
    assert plano.exige_recodificacao is True


def test_audio_flac_forca_recodificacao_so_de_audio():
    plano = decidir_plano(_sondagem(codec_audio="flac"))

    assert plano.audio is EstrategiaFluxo.RECODIFICA
    assert plano.video is EstrategiaFluxo.COPIA


def test_sem_audio_e_valido_como_copia():
    plano = decidir_plano(_sondagem(codec_audio=None))

    assert plano.audio is EstrategiaFluxo.COPIA
    assert plano.tem_audio is False


def test_duracao_fora_da_tolerancia_levanta_fonte_invalida():
    with pytest.raises(FonteInvalida):
        decidir_plano(_sondagem(duracao_s=1000.0), duracao_esperada_s=1440)


def test_duracao_esperada_none_pula_checagem():
    plano = decidir_plano(_sondagem(duracao_s=1.0), duracao_esperada_s=None)

    assert plano.exige_recodificacao is False

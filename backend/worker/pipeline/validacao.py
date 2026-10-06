"""Etapa `validando_fonte` do pipeline (ESPECIFICACAO.md §3B).

Sonda a mídia via `ffprobe`, confirma que decodifica de fato via `ffmpeg`, e
decide — por fluxo, não globalmente — se vídeo/áudio podem ser copiados sem
recodificar no empacotamento HLS (§3D).
"""

import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from core.erros import FalhaDeFerramenta, FonteInvalida
from worker.pipeline.ferramentas import executar

# Hi10P (yuv420p10le) é comum em releases de anime e nenhum navegador o
# decodifica — daí a checagem de pix_fmt abaixo, além de codec/perfil.
_PERFIS_H264_COMPATIVEIS = {"Baseline", "Main", "High"}
# AV1 8-bit Main toca por software em qualquer Chrome/Firefox atual; Professional
# e 10-bit não têm garantia, então seguem pro transcode.
_PERFIS_AV1_COMPATIVEIS = {"Main"}
_TIMEOUT_SONDAGEM_S = 30


@dataclass(frozen=True, slots=True)
class SondagemMidia:
    duracao_s: float
    codec_video: str
    codec_audio: str | None
    pix_fmt: str
    perfil_video: str | None
    largura: int
    altura: int
    tamanho_bytes: int


class EstrategiaFluxo(StrEnum):
    COPIA = "copia"
    RECODIFICA = "recodifica"


@dataclass(frozen=True, slots=True)
class PlanoDeEmpacotamento:
    video: EstrategiaFluxo
    audio: EstrategiaFluxo
    rendition: str  # nome dinâmico, ex. "1080p", "720p" — derivado da altura real sondada
    # Campo além do que o plano original especificava para PlanoDeEmpacotamento
    # (video/audio/rendition): necessário porque `audio=COPIA` também cobre o
    # caso "sem áudio" (regra de decidir_plano abaixo), e o empacotador HLS
    # precisa saber se deve mapear um fluxo de áudio ou montar um
    # -var_stream_map só de vídeo — sem isso o ffmpeg falha em fontes sem
    # áudio. Ver nota de desvio no relatório final.
    tem_audio: bool
    # MPEG-TS não carrega AV1: vídeo copiado nesse codec exige segmentos fMP4.
    segmentos_fmp4: bool = False

    @property
    def exige_recodificacao(self) -> bool:
        return (
            self.video is EstrategiaFluxo.RECODIFICA or self.audio is EstrategiaFluxo.RECODIFICA
        )


async def sondar(caminho: Path, ffprobe: Path) -> SondagemMidia:
    """Sonda o arquivo via `ffprobe` e extrai os metadados necessários para decidir o plano."""
    resultado = await executar(
        [
            str(ffprobe),
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(caminho),
        ],
        timeout_s=_TIMEOUT_SONDAGEM_S,
    )

    try:
        dados = json.loads(resultado.stdout)
    except json.JSONDecodeError as excecao:
        raise FonteInvalida(f"ffprobe não retornou JSON válido para {caminho}") from excecao

    fluxo_video = _primeiro_fluxo(dados, "video")
    if fluxo_video is None:
        raise FonteInvalida(f"nenhum fluxo de vídeo encontrado em {caminho}")
    fluxo_audio = _primeiro_fluxo(dados, "audio")

    formato = dados.get("format", {})
    duracao_s = _extrair_duracao_s(formato, fluxo_video)
    tamanho_bytes = int(formato.get("size") or caminho.stat().st_size)

    return SondagemMidia(
        duracao_s=duracao_s,
        codec_video=fluxo_video.get("codec_name", ""),
        codec_audio=fluxo_audio.get("codec_name") if fluxo_audio else None,
        pix_fmt=fluxo_video.get("pix_fmt", ""),
        perfil_video=fluxo_video.get("profile"),
        largura=int(fluxo_video.get("width", 0)),
        altura=int(fluxo_video.get("height", 0)),
        tamanho_bytes=tamanho_bytes,
    )


async def conferir_decodificacao(caminho: Path, ffmpeg: Path, segundos: int = 5) -> None:
    """Roda uma decodificação real dos primeiros `segundos` do arquivo.

    `ffprobe` só lê metadados; isto confirma que o conteúdo decodifica de fato.
    """
    try:
        await executar(
            [
                str(ffmpeg),
                "-v",
                "error",
                "-xerror",
                "-t",
                str(segundos),
                "-i",
                str(caminho),
                "-f",
                "null",
                "-",
            ],
            timeout_s=segundos + 30,
        )
    except FalhaDeFerramenta as excecao:
        raise FonteInvalida(f"arquivo não decodifica ({caminho}): {excecao}") from excecao


def decidir_plano(
    sondagem: SondagemMidia, duracao_esperada_s: int | None = None
) -> PlanoDeEmpacotamento:
    """Decide, por fluxo, se vídeo/áudio podem ser copiados sem recodificar.

    Pura — não roda subprocesso, testável só com uma `SondagemMidia` fabricada.
    """
    if duracao_esperada_s is not None:
        tolerancia_s = max(5, duracao_esperada_s * 0.02)
        if abs(sondagem.duracao_s - duracao_esperada_s) > tolerancia_s:
            raise FonteInvalida(
                f"duração {sondagem.duracao_s:.1f}s fora da tolerância de "
                f"{tolerancia_s:.1f}s em torno do esperado ({duracao_esperada_s}s)"
            )

    h264_copiavel = (
        sondagem.codec_video == "h264"
        and sondagem.pix_fmt == "yuv420p"
        and sondagem.perfil_video in _PERFIS_H264_COMPATIVEIS
    )
    av1_copiavel = (
        sondagem.codec_video == "av1"
        and sondagem.pix_fmt == "yuv420p"
        and sondagem.perfil_video in _PERFIS_AV1_COMPATIVEIS
    )
    video_copia = h264_copiavel or av1_copiavel
    audio_copia = sondagem.codec_audio is None or sondagem.codec_audio == "aac"

    return PlanoDeEmpacotamento(
        video=EstrategiaFluxo.COPIA if video_copia else EstrategiaFluxo.RECODIFICA,
        audio=EstrategiaFluxo.COPIA if audio_copia else EstrategiaFluxo.RECODIFICA,
        rendition=f"{sondagem.altura}p",
        tem_audio=sondagem.codec_audio is not None,
        segmentos_fmp4=av1_copiavel,
    )


def _primeiro_fluxo(dados: dict, tipo: str) -> dict | None:
    for fluxo in dados.get("streams", []):
        if fluxo.get("codec_type") == tipo:
            return fluxo
    return None


def _extrair_duracao_s(formato: dict, fluxo_video: dict) -> float:
    bruta = formato.get("duration") or fluxo_video.get("duration")
    if bruta is None:
        raise FonteInvalida("não foi possível determinar a duração do arquivo")
    return float(bruta)

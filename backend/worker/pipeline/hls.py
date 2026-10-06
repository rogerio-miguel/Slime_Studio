"""Etapa `empacotando_hls` do pipeline (ESPECIFICACAO.md §3D).

Roda uma única invocação de `ffmpeg` que produz a variante e o master manifest
juntos. Escreve em `<destino>.tmp/` e promove com `os.replace()` (rename
atômico) só ao concluir com sucesso.
"""

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from core.erros import FalhaDeFerramenta
from worker.pipeline.ferramentas import executar
from worker.pipeline.validacao import EstrategiaFluxo, PlanoDeEmpacotamento, SondagemMidia

_NOME_MASTER = "master.m3u8"
_MARCADOR_STREAM_INF = "#EXT-X-STREAM-INF"
# Reserva fixa pro hint de áudio (AAC estéreo padrão) quando `plano.tem_audio` —
# ver `_hints_de_bitrate`.
_BITRATE_AUDIO_HINT_BPS = 128_000
_BITRATE_VIDEO_HINT_MINIMO_BPS = 100_000


@dataclass(frozen=True, slots=True)
class ResultadoEmpacotamento:
    master_absoluto: Path
    master_relativo: Path  # relativo a media_root — é o que vai para Episodio.hls_path
    renditions: list[str]
    tamanho_bytes: int


async def empacotar(
    fonte: Path,
    destino: Path,
    plano: PlanoDeEmpacotamento,
    sondagem: SondagemMidia,
    ffmpeg: Path,
    media_root: Path,
    duracao_segmento_s: int = 8,
) -> ResultadoEmpacotamento:
    """Empacota `fonte` em HLS (variante única + master manifest) dentro de `destino`.

    Nota: `media_root` foi acrescentado à assinatura descrita no plano original
    porque, sem ele, não há como calcular `master_relativo` (relativo a
    `media_root`, conforme `ResultadoEmpacotamento` documenta) — ver desvio no
    relatório final.
    """
    destino_tmp = destino.with_name(destino.name + ".tmp")

    try:
        if destino_tmp.exists():
            shutil.rmtree(destino_tmp)
        destino_tmp.mkdir(parents=True, exist_ok=True)

        argumentos = _montar_comando_ffmpeg(
            ffmpeg, fonte, destino_tmp, plano, sondagem, duracao_segmento_s
        )
        await executar(argumentos, timeout_s=None)

        master_tmp = destino_tmp / _NOME_MASTER
        if not master_tmp.exists():
            raise FalhaDeFerramenta(
                f"ffmpeg concluiu sem erro mas não gerou {_NOME_MASTER} em {destino_tmp}"
            )
        # Sem hint de bitrate (`-b:v`/`-b:a`, ver `_hints_de_bitrate`), o ffmpeg em
        # modo `copy` já foi observado gerando um master.m3u8 truncado — só
        # `#EXTM3U`/`#EXT-X-VERSION`, sem `#EXT-X-STREAM-INF` apontando pra
        # variante. O arquivo existe mas o hls.js não tem o que tocar. Confirma
        # o conteúdo, não só a existência, pra pegar isso aqui em vez de deixar
        # o job ser marcado `pronto` com um vídeo quebrado.
        conteudo_master = master_tmp.read_text(encoding="utf-8")
        if _MARCADOR_STREAM_INF not in conteudo_master:
            raise FalhaDeFerramenta(
                f"master manifest sem {_MARCADOR_STREAM_INF} (sem variante referenciada) "
                f"em {master_tmp}"
            )

        _promover(destino_tmp, destino)
    except BaseException:
        if destino_tmp.exists():
            shutil.rmtree(destino_tmp, ignore_errors=True)
        raise

    tamanho_bytes = sum(
        arquivo.stat().st_size for arquivo in destino.rglob("*") if arquivo.is_file()
    )
    master_absoluto = destino / _NOME_MASTER

    return ResultadoEmpacotamento(
        master_absoluto=master_absoluto,
        master_relativo=master_absoluto.relative_to(media_root),
        renditions=[plano.rendition],
        tamanho_bytes=tamanho_bytes,
    )


def _promover(destino_tmp: Path, destino: Path) -> None:
    """Promove `destino_tmp` para `destino` com a menor janela possível sem `destino`.

    Reprocessamento (`destino` já existe): em vez de `rmtree(destino)` seguido de
    `os.replace()` — que deixa uma janela em que `destino` não existe em disco se o
    processo morrer entre as duas chamadas —, o diretório antigo é primeiro renomeado
    para `<destino>.old` (rename, não cópia). Só depois que o `os.replace()` do novo
    diretório tiver sucesso é que o `.old` é removido; se o `os.replace()` falhar, o
    `.old` é restaurado no lugar de `destino`.
    """
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino_antigo = destino.with_name(destino.name + ".old")
    if destino_antigo.exists():
        shutil.rmtree(destino_antigo, ignore_errors=True)

    havia_antigo = destino.exists()
    if havia_antigo:
        os.replace(destino, destino_antigo)

    try:
        os.replace(destino_tmp, destino)
    except BaseException:
        if havia_antigo:
            os.replace(destino_antigo, destino)
        raise
    else:
        if havia_antigo:
            shutil.rmtree(destino_antigo, ignore_errors=True)


def _montar_comando_ffmpeg(
    ffmpeg: Path,
    fonte: Path,
    destino_tmp: Path,
    plano: PlanoDeEmpacotamento,
    sondagem: SondagemMidia,
    duracao_segmento_s: int,
) -> list[str]:
    mapas = ["-map", "0:v:0"]
    grupo_stream_map = f"v:0,name:{plano.rendition}"
    if plano.tem_audio:
        mapas += ["-map", "0:a:0?"]
        grupo_stream_map = f"v:0,a:0,name:{plano.rendition}"

    hint_video_bps, hint_audio_bps = _hints_de_bitrate(sondagem, plano)

    return [
        str(ffmpeg),
        "-nostdin",
        "-hide_banner",
        "-y",
        "-i",
        str(fonte),
        *mapas,
        "-sn",
        "-dn",
        "-map_metadata",
        "-1",
        *_flags_codec_video(plano.video, hint_video_bps),
        *(_flags_codec_audio(plano.audio, hint_audio_bps) if plano.tem_audio else []),
        "-f",
        "hls",
        "-hls_time",
        str(duracao_segmento_s),
        "-hls_playlist_type",
        "vod",
        *(["-hls_segment_type", "fmp4"] if plano.segmentos_fmp4 else []),
        "-hls_flags",
        "independent_segments",
        "-hls_segment_filename",
        str(destino_tmp / "%v" / f"seg_%05d.{'m4s' if plano.segmentos_fmp4 else 'ts'}"),
        "-master_pl_name",
        _NOME_MASTER,
        "-var_stream_map",
        grupo_stream_map,
        str(destino_tmp / "%v" / "index.m3u8"),
    ]


def _flags_codec_video(estrategia: EstrategiaFluxo, hint_bps: int | None) -> list[str]:
    if estrategia is EstrategiaFluxo.COPIA:
        # `-b:v` aqui não recodifica nada (stream copiado byte a byte) — é só o
        # hint de bitrate que o muxer HLS usa pra calcular o `BANDWIDTH` do
        # master manifest. Sem ele, ffmpeg loga "Bandwidth info not available,
        # set audio and video bitrates" e o master sai sem `#EXT-X-STREAM-INF`
        # (bug reproduzido manualmente, ver checagem de conteúdo em `empacotar`).
        flags = ["-c:v", "copy"]
        if hint_bps is not None:
            flags += ["-b:v", str(hint_bps)]
        return flags
    # RECODIFICA usa `-crf` (qualidade variável) — combinar com `-b:v` mudaria
    # pro modo restringido por bitrate do encoder, uma mudança de comportamento
    # não confirmada como necessária (o bug só foi reproduzido em modo COPIA).
    # Se `-crf` também deixar o muxer sem bitrate pra calcular o master, a
    # checagem de conteúdo em `empacotar` já pega isso como falha explícita.
    return ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p"]


def _flags_codec_audio(estrategia: EstrategiaFluxo, hint_bps: int | None) -> list[str]:
    if estrategia is EstrategiaFluxo.COPIA:
        flags = ["-c:a", "copy"]
        if hint_bps is not None:
            flags += ["-b:a", str(hint_bps)]
        return flags
    return ["-c:a", "aac", "-b:a", "192k"]


def _hints_de_bitrate(
    sondagem: SondagemMidia, plano: PlanoDeEmpacotamento
) -> tuple[int | None, int | None]:
    """Bitrate hint (bps) pro muxer HLS calcular `BANDWIDTH` em modo `copy`.

    Só relevante quando o fluxo correspondente está em `EstrategiaFluxo.COPIA`
    (RECODIFICA já define bitrate próprio via seus próprios flags de codec).
    Estimado a partir do bitrate médio do container-fonte
    (`tamanho_bytes * 8 / duracao_s`), reservando um valor fixo de áudio quando
    há áudio e atribuindo o restante ao vídeo (com piso mínimo pra nunca gerar
    um hint absurdo/negativo em fontes muito pequenas ou de bitrate atípico).
    """
    if plano.video is not EstrategiaFluxo.COPIA and (
        not plano.tem_audio or plano.audio is not EstrategiaFluxo.COPIA
    ):
        return None, None

    # `sondar()`/`decidir_plano()` não garantem `duracao_s > 0` (só validam
    # tolerância quando `duracao_esperada_s` é informado) — sem essa guarda,
    # uma sondagem com duração zerada estoura `ZeroDivisionError` não tratado
    # em vez de uma falha de domínio clara.
    if sondagem.duracao_s <= 0:
        raise FalhaDeFerramenta(
            f"duração sondada inválida ({sondagem.duracao_s}s) — não é possível "
            "estimar bitrate pro master manifest"
        )

    bitrate_total_bps = int(sondagem.tamanho_bytes * 8 / sondagem.duracao_s)
    reserva_audio_bps = _BITRATE_AUDIO_HINT_BPS if plano.tem_audio else 0

    hint_video_bps = None
    if plano.video is EstrategiaFluxo.COPIA:
        hint_video_bps = max(bitrate_total_bps - reserva_audio_bps, _BITRATE_VIDEO_HINT_MINIMO_BPS)

    hint_audio_bps = None
    if plano.tem_audio and plano.audio is EstrategiaFluxo.COPIA:
        hint_audio_bps = _BITRATE_AUDIO_HINT_BPS

    return hint_video_bps, hint_audio_bps

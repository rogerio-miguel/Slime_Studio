"""Etapa `empacotando_hls` do pipeline (ESPECIFICACAO.md §3D).

Roda uma única invocação de `ffmpeg` que produz a variante e o master manifest
juntos. Escreve em `<destino>.tmp/` e promove com `os.replace()` (rename
atômico) só ao concluir com sucesso.
"""

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from core.enums import TipoEpisodio, VersaoEpisodio
from core.erros import FalhaDeFerramenta
from worker.pipeline.ferramentas import executar
from worker.pipeline.validacao import EstrategiaFluxo, PlanoDeEmpacotamento

_NOME_MASTER = "master.m3u8"


@dataclass(frozen=True, slots=True)
class ResultadoEmpacotamento:
    master_absoluto: Path
    master_relativo: Path  # relativo a media_root — é o que vai para Episodio.hls_path
    renditions: list[str]
    tamanho_bytes: int


def diretorio_do_episodio(
    media_root: Path,
    anime_slug: str,
    numero: int,
    tipo: TipoEpisodio,
    versao: VersaoEpisodio,
) -> Path:
    nome_pasta = f"{numero:03d}-{tipo.value}-{versao.value}"
    return media_root / "hls" / anime_slug / nome_pasta


async def empacotar(
    fonte: Path,
    destino: Path,
    plano: PlanoDeEmpacotamento,
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

        argumentos = _montar_comando_ffmpeg(ffmpeg, fonte, destino_tmp, plano, duracao_segmento_s)
        await executar(argumentos, timeout_s=None)

        master_tmp = destino_tmp / _NOME_MASTER
        if not master_tmp.exists():
            raise FalhaDeFerramenta(
                f"ffmpeg concluiu sem erro mas não gerou {_NOME_MASTER} em {destino_tmp}"
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
    duracao_segmento_s: int,
) -> list[str]:
    mapas = ["-map", "0:v:0"]
    grupo_stream_map = f"v:0,name:{plano.rendition}"
    if plano.tem_audio:
        mapas += ["-map", "0:a:0?"]
        grupo_stream_map = f"v:0,a:0,name:{plano.rendition}"

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
        *_flags_codec_video(plano.video),
        *(_flags_codec_audio(plano.audio) if plano.tem_audio else []),
        "-f",
        "hls",
        "-hls_time",
        str(duracao_segmento_s),
        "-hls_playlist_type",
        "vod",
        "-hls_flags",
        "independent_segments",
        "-hls_segment_filename",
        str(destino_tmp / "%v" / "seg_%05d.ts"),
        "-master_pl_name",
        _NOME_MASTER,
        "-var_stream_map",
        grupo_stream_map,
        str(destino_tmp / "%v" / "index.m3u8"),
    ]


def _flags_codec_video(estrategia: EstrategiaFluxo) -> list[str]:
    if estrategia is EstrategiaFluxo.COPIA:
        return ["-c:v", "copy"]
    return ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p"]


def _flags_codec_audio(estrategia: EstrategiaFluxo) -> list[str]:
    if estrategia is EstrategiaFluxo.COPIA:
        return ["-c:a", "copy"]
    return ["-c:a", "aac", "-b:a", "192k"]

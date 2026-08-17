"""Download de mídia (ESPECIFICACAO.md §3A/§3D) — agnóstico de site (D4 do plano).

Só entra em cena depois que `extractors/resiliencia.py::chamar` já resolveu a
`LinkDeMidia` (URL + cabeçalhos de hotlink protection) via o adapter do site;
daqui pra frente não há mais `ClienteDeSite` nem sessão de bypass envolvidos —
é uma checagem HTTP curta seguida de um `ffmpeg -c copy` genérico.

Desvio do plano: `conferir_link_de_midia` não recebe um `ClienteDeSite` — por
esta função rodar depois que `resiliencia.chamar` já devolveu (o `ClienteDeSite`
usado para resolver o link não sobrevive a essa fronteira, D4: downloader é
agnóstico de site), a checagem faz sua própria requisição HTTP curta com
`requests`, isolada em `_baixar_amostra` para ser substituível em teste.
"""

import os
from pathlib import Path

import requests

from core.enums import TipoEpisodio, VersaoEpisodio
from core.erros import FalhaDeExtracao, FalhaDeFerramenta
from extractors.base import LinkDeMidia
from worker.pipeline.ferramentas import executar

_TIMEOUT_S = 15
# Teto do próprio download (não da checagem prévia `conferir_link_de_midia`,
# que usa `_TIMEOUT_S` acima): episódios legítimos levam minutos, não horas —
# este teto é rede de segurança para o heartbeat do worker
# (`worker/__main__.py::_bater_heartbeat`) e `reciclar_jobs_orfaos` conseguirem
# detectar um download travado, não um limite operacional.
_TIMEOUT_DOWNLOAD_S = 2 * 60 * 60
_TAMANHO_AMOSTRA_BYTES = 4096
# Abaixo disso, quase certo que é isca (PNG/HTML de erro) em vez de mídia real.
_TAMANHO_MINIMO_BYTES = 1024
_ASSINATURA_PLAYLIST = "#extm3u"
_MARCADORES_ISCA_HTML = ("<html", "<!doctype html")


def caminho_raw(
    media_root: Path, anime_slug: str, numero: int, tipo: TipoEpisodio, versao: VersaoEpisodio
) -> Path:
    nome_arquivo = f"{numero:03d}-{tipo.value}-{versao.value}.mkv"
    return media_root / "raw" / anime_slug / nome_arquivo


def conferir_link_de_midia(link: LinkDeMidia, *, timeout_s: int = _TIMEOUT_S) -> None:
    """Confere, com uma amostra curta do corpo, que `link.url` aponta para mídia de
    verdade — não uma isca anti-scraping (página HTML de erro ou imagem no lugar
    do vídeo/playlist esperado). Levanta `FalhaDeExtracao` (retentável) se a
    amostra parecer uma isca."""
    content_type, amostra = _baixar_amostra(link.url, link.cabecalhos, timeout_s)
    corpo_como_texto = amostra.decode("utf-8", errors="replace").lower()

    if any(marcador in corpo_como_texto for marcador in _MARCADORES_ISCA_HTML):
        raise FalhaDeExtracao(
            f"link de mídia devolveu HTML no lugar de mídia: {link.url}", permite_retentativa=True
        )
    if "image/" in content_type:
        raise FalhaDeExtracao(
            f"link de mídia devolveu imagem no lugar de mídia: {link.url}", permite_retentativa=True
        )
    if link.url.endswith(".m3u8"):
        if not corpo_como_texto.lstrip().startswith(_ASSINATURA_PLAYLIST):
            raise FalhaDeExtracao(
                f"playlist .m3u8 não começa com #EXTM3U: {link.url}", permite_retentativa=True
            )
    elif len(amostra) < _TAMANHO_MINIMO_BYTES:
        raise FalhaDeExtracao(
            f"link de mídia devolveu corpo suspeito pequeno ({len(amostra)} bytes): {link.url}",
            permite_retentativa=True,
        )


def _baixar_amostra(url: str, cabecalhos: dict[str, str], timeout_s: int) -> tuple[str, bytes]:
    """Isolado do resto de `conferir_link_de_midia` para ser substituído por
    `monkeypatch` em teste, sem tocar rede real."""
    try:
        with requests.get(url, headers=cabecalhos, timeout=timeout_s, stream=True) as resposta:
            resposta.raise_for_status()
            content_type = resposta.headers.get("Content-Type", "")
            amostra = next(resposta.iter_content(chunk_size=_TAMANHO_AMOSTRA_BYTES), b"")
            return content_type, amostra
    except requests.RequestException as excecao:
        raise FalhaDeExtracao(
            f"falha ao conferir link de mídia {url}: {excecao}", permite_retentativa=True
        ) from excecao


async def baixar(link: LinkDeMidia, destino: Path, ffmpeg_bin: str) -> Path:
    """Baixa `link` via `ffmpeg -c copy` para `destino` (`.mkv`), escrevendo em
    `<destino>.part` e promovendo com `os.replace()` (rename atômico) só ao
    concluir com sucesso. Remove o `.part` em qualquer `BaseException` — nunca
    deixa lixo parcial em `MEDIA_ROOT/raw/`."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    parcial = destino.with_name(destino.name + ".part")

    try:
        argumentos = _montar_comando(ffmpeg_bin, link, parcial)
        await executar(argumentos, timeout_s=_TIMEOUT_DOWNLOAD_S)
        if not parcial.exists():
            raise FalhaDeFerramenta(f"ffmpeg concluiu sem erro mas não gerou {parcial}")
        os.replace(parcial, destino)
    except BaseException:
        if parcial.exists():
            parcial.unlink(missing_ok=True)
        raise

    return destino


def _montar_comando(ffmpeg_bin: str, link: LinkDeMidia, destino_parcial: Path) -> list[str]:
    """`-headers` só entra quando há cabeçalhos (protocolo HTTP) — passá-lo junto de
    uma entrada não-HTTP (ex. arquivo local em teste de integração) é rejeitado
    pelo `ffmpeg`. Cada cabeçalho termina em `\\r\\n`, **incluindo o último** — sem
    isso o `ffmpeg` ignora o cabeçalho silenciosamente e o download volta 403.

    `-f matroska` é explícito porque `destino_parcial` termina em `.mkv.part`: o
    `ffmpeg` infere o muxer pela extensão do arquivo de saída, e `.part` não é
    reconhecida (`Unable to choose an output format for '...part'`)."""
    argumentos = [ffmpeg_bin, "-nostdin", "-hide_banner", "-y"]
    if link.cabecalhos:
        cabecalhos = "".join(f"{chave}: {valor}\r\n" for chave, valor in link.cabecalhos.items())
        argumentos += ["-headers", cabecalhos]
    argumentos += ["-i", link.url, "-c", "copy", "-f", "matroska", str(destino_parcial)]
    return argumentos

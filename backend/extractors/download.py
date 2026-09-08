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

import asyncio
import os
import re
import sys
import tempfile
import time
import urllib.parse
from pathlib import Path

import requests

from core.enums import TipoEpisodio, VersaoEpisodio
from core.erros import FalhaDeExtracao, FalhaDeFerramenta
from extractors.base import FormatoDeMidia, LinkDeMidia
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
_ASSINATURA_MPD = "<mpd"
_MARCADORES_ISCA_HTML = ("<html", "<!doctype html")

# Download em blocos (Range requests) para `*.googlevideo.com`: o Google throttla
# conexão única, então baixamos em blocos sequenciais como o yt-dlp faz.
# 10 MiB por bloco é o default do yt-dlp; 60 s de teto por requisição de bloco;
# até 4 tentativas do mesmo bloco em erro de rede, com backoff `2 ** tentativa`.
_TAMANHO_BLOCO_BYTES = 10 * 1024 * 1024
_TIMEOUT_BLOCO_S = 60
_MAX_TENTATIVAS_BLOCO = 4
_CONTENT_RANGE_RE = re.compile(r"\s*bytes\s+(\d+)-(\d+)/(\d+|\*)\s*", re.IGNORECASE)

# Download DASH via `yt-dlp` em vez de `ffmpeg -f dash -i` (confirmado ao vivo
# em 2026-09-08): o CDN do AnimeFire (`akumast.net`) serve ~1 a cada N segmentos
# DASH como fragmento MP4 vazio (200 OK, `mdat` de 8 bytes) — armadilha
# anti-download. O demuxer `dash` do ffmpeg PARA no 1º segmento vazio
# ("No longer receiving stream_index") e SAI 0, gerando um arquivo truncado
# (~44s) que o pipeline aceita como pronto. O `yt-dlp` retenta o fragmento e
# segue (`--fragment-retries` + `--skip-unavailable-fragments`), montando o
# episódio inteiro. É por isso que `_montar_comando`/`FormatoDeMidia.DASH` só
# tem valor pra `conferir_link_de_midia` agora — `baixar` desvia DASH pra cá.
_MAX_TENTATIVAS_FRAGMENTO = 10
# Piso de duração do arquivo baixado vs. o `mediaPresentationDuration` do
# manifesto. Abaixo disso o download veio truncado (CDN dropou uma faixa
# inteira de segmentos, não só os fragmentos-isca esparsos que o yt-dlp já
# cobre) — `FalhaDeExtracao` retentável em vez de aceitar um episódio pela
# metade. Folga de 15% cobre o desconto real dos fragmentos-isca vazios e
# imprecisão de `mediaPresentationDuration`.
_FRACAO_MINIMA_DASH = 0.85
_RE_MPD_DURACAO = re.compile(r'mediaPresentationDuration="([^"]+)"')
# ISO 8601 de duração, só a parte de tempo (`PT…`) — dias/meses não aparecem
# em manifesto de episódio. Grupos: horas, minutos, segundos (com decimais).
_RE_DURACAO_ISO8601 = re.compile(
    r"PT(?:(\d+(?:\.\d+)?)H)?(?:(\d+(?:\.\d+)?)M)?(?:(\d+(?:\.\d+)?)S)?", re.IGNORECASE
)


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

    if link.formato is FormatoDeMidia.DASH:
        # Manifesto DASH disfarçado de imagem (URL `.../m.jpg`, corpo XML de MPD):
        # pula tanto o piso de tamanho quanto a guarda de `content_type` abaixo —
        # um manifesto compacto (uma Representation, um SegmentTemplate) cabe em
        # menos de `_TAMANHO_MINIMO_BYTES` e a URL termina em `.jpg` só de fachada.
        if _ASSINATURA_MPD not in corpo_como_texto:
            raise FalhaDeExtracao(
                f"manifesto DASH sem assinatura <MPD: {link.url}", permite_retentativa=True
            )
        return

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


def _eh_googlevideo(url: str) -> bool:
    """`True` se `url` aponta para um CDN de mídia do Google (`*.googlevideo.com`).
    Esses hosts respondem a `Range` e throttlam conexão única — daí o download em
    blocos de `_baixar_em_blocos` no lugar do `ffmpeg` direto."""
    hostname = urllib.parse.urlparse(url).hostname or ""
    return hostname == "googlevideo.com" or hostname.endswith(".googlevideo.com")


async def baixar(
    link: LinkDeMidia, destino: Path, ffmpeg_bin: str, ffprobe_bin: str | None = None
) -> Path:
    """Baixa `link` para `destino` (`.mkv`), escrevendo em `<destino>.part` e
    promovendo com `os.replace()` (rename atômico) só ao concluir com sucesso.
    Remove qualquer parcial (`.part`, `.bruto`) em `BaseException` — nunca deixa
    lixo em `MEDIA_ROOT/raw/`.

    `FormatoDeMidia.DASH` desvia para `yt-dlp` (`_baixar_dash`) — o demuxer `dash`
    do `ffmpeg` trunca silenciosamente diante dos fragmentos-isca vazios que
    alguns CDNs de anime servem (ver `_MAX_TENTATIVAS_FRAGMENTO`). Para URLs
    `*.googlevideo.com` baixa o mp4 cru em blocos (Range requests, para escapar
    do throttle de conexão única do Google) para `<destino>.bruto` e só então
    remuxa localmente com `ffmpeg -c copy`. Para todo o resto, `ffmpeg` baixa e
    remuxa direto da URL remota.

    Falha do `ffmpeg`/`yt-dlp` no download (conexão truncada pelo CDN, timeout de
    rede) e falha de rede no download em blocos são traduzidas para
    `FalhaDeExtracao` retentável — o executor reagenda o job com backoff em vez
    de marcá-lo como falho definitivo. Só o `.part` ausente após sucesso do
    `ffmpeg` continua sendo `FalhaDeFerramenta` (bug interno, não rede)."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    parcial = destino.with_name(destino.name + ".part")

    if link.formato is FormatoDeMidia.DASH:
        return await _baixar_dash(link, destino, ffmpeg_bin, ffprobe_bin)

    if _eh_googlevideo(link.url):
        bruto = destino.with_name(destino.name + ".bruto")
        try:
            await asyncio.to_thread(
                _baixar_em_blocos, link.url, link.cabecalhos, bruto, timeout_s=_TIMEOUT_BLOCO_S
            )
            entrada_local = LinkDeMidia(url=str(bruto), cabecalhos={})
            await _remuxar_e_promover(ffmpeg_bin, entrada_local, parcial, destino)
        except BaseException:
            bruto.unlink(missing_ok=True)
            parcial.unlink(missing_ok=True)
            raise
        bruto.unlink(missing_ok=True)
        return destino

    try:
        await _remuxar_e_promover(ffmpeg_bin, link, parcial, destino)
    except BaseException:
        parcial.unlink(missing_ok=True)
        raise

    return destino


async def _baixar_dash(
    link: LinkDeMidia, destino: Path, ffmpeg_bin: str, ffprobe_bin: str | None
) -> Path:
    """Baixa um manifesto DASH via `yt-dlp` (fragmento a fragmento, com retry por
    fragmento) para um diretório temporário no mesmo filesystem de `destino`, e
    promove com `os.replace()` atômico. `yt-dlp` cuida da fusão vídeo+áudio
    (`--merge-output-format mkv`, usando o `ffmpeg` que passamos).

    Falha do `yt-dlp` (rede, CDN) vira `FalhaDeExtracao` retentável. Arquivo
    ausente após saída 0 é `FalhaDeFerramenta` (bug interno). Download que passou
    mas veio curto demais vs. o `mediaPresentationDuration` do manifesto
    (`_conferir_duracao_dash`) também é `FalhaDeExtracao` retentável — uma faixa
    inteira de segmentos caiu, não só os fragmentos-isca esparsos."""
    with tempfile.TemporaryDirectory(dir=destino.parent, prefix=".ytdl-") as tmp:
        saida_modelo = str(Path(tmp) / "video.%(ext)s")
        argumentos = _montar_comando_ytdl(link, saida_modelo, ffmpeg_bin)
        try:
            await executar(argumentos, timeout_s=_TIMEOUT_DOWNLOAD_S)
        except FalhaDeFerramenta as excecao:
            sufixo_stderr = f" — stderr: {excecao.cauda_stderr}" if excecao.cauda_stderr else ""
            raise FalhaDeExtracao(
                f"yt-dlp falhou no download DASH ({excecao}){sufixo_stderr}",
                permite_retentativa=True,
            ) from excecao

        produzidos = [
            caminho
            for caminho in Path(tmp).glob("video.*")
            if caminho.suffix.lower() in (".mkv", ".webm", ".mp4")
        ]
        if not produzidos:
            raise FalhaDeFerramenta(
                f"yt-dlp concluiu sem erro mas não gerou arquivo de vídeo em {tmp}"
            )
        arquivo = produzidos[0]
        await _conferir_duracao_dash(link, arquivo, ffprobe_bin)
        os.replace(arquivo, destino)

    return destino


def _montar_comando_ytdl(link: LinkDeMidia, saida_modelo: str, ffmpeg_bin: str) -> list[str]:
    """`yt-dlp` como módulo do próprio interpretador (`sys.executable -m yt_dlp`)
    — mesmo venv, sem depender de um console-script no PATH. `--skip-unavailable-
    fragments` + `--fragment-retries` cobrem os fragmentos-isca vazios; `--no-part`
    escreve direto (o diretório temporário já isola parciais); `--no-progress`
    mantém o stdout enxuto pro `communicate()` de `executar`."""
    argumentos = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--no-warnings",
        "--no-progress",
        "--no-playlist",
        "--no-part",
        "--fragment-retries",
        str(_MAX_TENTATIVAS_FRAGMENTO),
        "--retries",
        str(_MAX_TENTATIVAS_FRAGMENTO),
        "--skip-unavailable-fragments",
        "--ffmpeg-location",
        ffmpeg_bin,
        "-f",
        "bv*+ba/b",
        "--merge-output-format",
        "mkv",
        "--remux-video",
        "mkv",
        "-o",
        saida_modelo,
    ]
    for chave, valor in link.cabecalhos.items():
        argumentos += ["--add-header", f"{chave}:{valor}"]
    argumentos += ["--", link.url]
    return argumentos


async def _conferir_duracao_dash(
    link: LinkDeMidia, arquivo: Path, ffprobe_bin: str | None
) -> None:
    """Rede de segurança contra download truncado: compara a duração real do
    arquivo com o `mediaPresentationDuration` do manifesto. Manifesto sem
    duração declarada, ou inacessível agora, não bloqueia (não dá pra conferir —
    o arquivo já está baixado). Sem `ffprobe_bin` (chamador de teste), pula a
    checagem."""
    if ffprobe_bin is None:
        return
    duracao_manifesto = await asyncio.to_thread(_duracao_do_manifesto_dash, link)
    if duracao_manifesto is None:
        return
    duracao_real = await _sondar_duracao_s(arquivo, ffprobe_bin)
    if duracao_real < duracao_manifesto * _FRACAO_MINIMA_DASH:
        arquivo.unlink(missing_ok=True)
        raise FalhaDeExtracao(
            f"download DASH truncado: {duracao_real:.0f}s de ~{duracao_manifesto:.0f}s "
            f"do manifesto",
            permite_retentativa=True,
        )


def _duracao_do_manifesto_dash(link: LinkDeMidia) -> float | None:
    """`mediaPresentationDuration` do MPD em segundos, ou `None` se o manifesto
    não declara duração ou não pôde ser rebaixado. Isolado (como `_baixar_amostra`)
    para `monkeypatch` em teste."""
    try:
        with requests.get(link.url, headers=link.cabecalhos, timeout=_TIMEOUT_S) as resposta:
            resposta.raise_for_status()
            corpo = resposta.text
    except requests.RequestException:
        return None
    correspondencia = _RE_MPD_DURACAO.search(corpo)
    if correspondencia is None:
        return None
    return _iso8601_duracao_para_segundos(correspondencia.group(1))


def _iso8601_duracao_para_segundos(texto: str) -> float | None:
    """`"PT1H23M40.044S"` -> `5020.044`. `None` quando não casa nenhum campo de
    tempo (formato inesperado)."""
    correspondencia = _RE_DURACAO_ISO8601.fullmatch(texto.strip())
    if correspondencia is None or not any(correspondencia.groups()):
        return None
    horas, minutos, segundos = (
        float(valor) if valor else 0.0 for valor in correspondencia.groups()
    )
    return horas * 3600 + minutos * 60 + segundos


async def _sondar_duracao_s(arquivo: Path, ffprobe_bin: str) -> float:
    """Duração do arquivo em segundos via `ffprobe`. `0.0` quando o `ffprobe` não
    devolve um número (arquivo sem container de duração conhecida) — o chamador
    trata como "curto demais"."""
    resultado = await executar(
        [
            ffprobe_bin,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nw=1:nk=1",
            str(arquivo),
        ],
        timeout_s=_TIMEOUT_S,
    )
    try:
        return float(resultado.stdout.strip())
    except ValueError:
        return 0.0


async def _remuxar_e_promover(
    ffmpeg_bin: str, entrada: LinkDeMidia, parcial: Path, destino: Path
) -> None:
    """`ffmpeg -c copy` de `entrada` para `parcial`, promovendo para `destino` com
    `os.replace()` (rename atômico) só no sucesso. Falha de rede/CDN do `ffmpeg`
    (conexão truncada, timeout) vira `FalhaDeExtracao` retentável; `.part` ausente
    após o `ffmpeg` sair 0 continua `FalhaDeFerramenta` (bug interno, não rede)."""
    argumentos = _montar_comando(ffmpeg_bin, entrada, parcial)
    try:
        await executar(argumentos, timeout_s=_TIMEOUT_DOWNLOAD_S)
    except FalhaDeFerramenta as excecao:
        sufixo_stderr = f" — stderr: {excecao.cauda_stderr}" if excecao.cauda_stderr else ""
        raise FalhaDeExtracao(
            f"ffmpeg falhou no download ({excecao}){sufixo_stderr}",
            permite_retentativa=True,
        ) from excecao
    if not parcial.exists():
        raise FalhaDeFerramenta(f"ffmpeg concluiu sem erro mas não gerou {parcial}")
    os.replace(parcial, destino)


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
        # CDN de anime derruba conexões HTTP longas no meio do download; sem estas
        # flags um drop truncado faz o ffmpeg sair com AVERROR_EOF e o job inteiro
        # se perde. São opções de input (valem pra http/https) — vêm antes do `-i`.
        argumentos += [
            "-reconnect", "1",
            "-reconnect_streamed", "1",
            "-reconnect_on_network_error", "1",
            "-reconnect_delay_max", "30",
        ]
    if link.formato is FormatoDeMidia.DASH:
        # Formato de *entrada* explícito: sem isso o ffmpeg tentaria inferir pelo
        # probe automático, que usaria a extensão `.jpg` mascarada e poderia falhar.
        argumentos += ["-f", "dash"]
    argumentos += ["-i", link.url, "-c", "copy", "-f", "matroska", str(destino_parcial)]
    return argumentos


def _baixar_em_blocos(
    url: str, cabecalhos: dict[str, str], destino: Path, *, timeout_s: int
) -> None:
    """Baixa `url` inteira para `destino` (arquivo cru, tipicamente mp4 progressivo)
    em blocos sequenciais de `_TAMANHO_BLOCO_BYTES` via header `Range`. Função
    bloqueante — o chamador (`baixar`) a roda em `asyncio.to_thread`, fora do
    event loop.

    Se o servidor ignorar o `Range` e responder 200 no primeiro bloco, cai para
    download de conexão única em streaming (sai throttled, mas funciona). 200 fora
    de hora, `Content-Range` incoerente ou bloco vazio viram `FalhaDeExtracao`
    retentável — nunca corrompe o arquivo em silêncio.

    Teto de tempo total igual ao do `ffmpeg` (`_TIMEOUT_DOWNLOAD_S`): sem ele, um
    servidor que devolvesse 206 sem fim manteria a thread presa para sempre e o
    heartbeat do worker seguiria batendo (o event loop está livre), sem
    `reciclar_jobs_orfaos` nunca detectar o job travado."""
    prazo_final = time.monotonic() + _TIMEOUT_DOWNLOAD_S
    inicio = 0
    with open(destino, "wb") as arquivo:
        while True:
            if time.monotonic() > prazo_final:
                raise FalhaDeExtracao(
                    f"download em blocos excedeu {_TIMEOUT_DOWNLOAD_S}s: {url}",
                    permite_retentativa=True,
                )
            faixa_pedida = f"bytes={inicio}-{inicio + _TAMANHO_BLOCO_BYTES - 1}"
            cabecalhos_bloco = {**cabecalhos, "Range": faixa_pedida}
            with _get_bloco_com_retry(url, cabecalhos_bloco, timeout_s=timeout_s) as resposta:
                if resposta.status_code == 200:
                    if inicio != 0:
                        raise FalhaDeExtracao(
                            f"servidor respondeu 200 no meio do download em blocos: {url}",
                            permite_retentativa=True,
                        )
                    for pedaco in resposta.iter_content(chunk_size=_TAMANHO_BLOCO_BYTES):
                        arquivo.write(pedaco)
                    return

                if resposta.status_code == 416:
                    if inicio == 0:
                        raise FalhaDeExtracao(
                            f"servidor respondeu 416 no primeiro bloco: {url}",
                            permite_retentativa=True,
                        )
                    return

                corpo = resposta.content
                if not corpo:
                    raise FalhaDeExtracao(
                        f"bloco 206 sem corpo — abortado para não entrar em laço: {url}",
                        permite_retentativa=True,
                    )
                faixa_inicio, faixa_fim, total = _parse_content_range(
                    resposta.headers.get("Content-Range", ""), url
                )
                if faixa_inicio != inicio or len(corpo) != faixa_fim - faixa_inicio + 1:
                    raise FalhaDeExtracao(
                        f"bloco incoerente com o Content-Range "
                        f"(faixa {faixa_inicio}-{faixa_fim}, {len(corpo)} bytes) em {url}",
                        permite_retentativa=True,
                    )
                arquivo.write(corpo)
                inicio = faixa_fim + 1
                if total is not None and inicio >= total:
                    return


def _get_bloco_com_retry(
    url: str, cabecalhos: dict[str, str], *, timeout_s: int
) -> requests.Response:
    """`_get_bloco` com até `_MAX_TENTATIVAS_BLOCO` tentativas do mesmo bloco em
    erro de rede (timeout, conexão truncada, 5xx), backoff `2 ** tentativa`. O
    corpo de um 206 é lido aqui dentro, então uma conexão truncada durante a
    transferência do bloco também dispara a retentativa. Esgotadas as tentativas,
    `FalhaDeExtracao` retentável — o executor reagenda o job."""
    ultimo_erro: Exception | None = None
    for tentativa in range(_MAX_TENTATIVAS_BLOCO):
        resposta = None
        try:
            resposta = _get_bloco(url, cabecalhos, timeout_s)
            if resposta.status_code == 206:
                _ = resposta.content  # puxa o corpo agora: truncação vira RequestException aqui
            elif resposta.status_code not in (200, 416):
                resposta.raise_for_status()
                raise FalhaDeExtracao(
                    f"HTTP {resposta.status_code} inesperado ao baixar bloco de {url}",
                    permite_retentativa=True,
                )
            return resposta
        except requests.RequestException as excecao:
            if resposta is not None:
                resposta.close()
            ultimo_erro = excecao
            if tentativa + 1 < _MAX_TENTATIVAS_BLOCO:
                time.sleep(2**tentativa)
        except BaseException:
            if resposta is not None:
                resposta.close()
            raise
    raise FalhaDeExtracao(
        f"falha de rede ao baixar bloco de {url} após {_MAX_TENTATIVAS_BLOCO} "
        f"tentativas: {ultimo_erro}",
        permite_retentativa=True,
    ) from ultimo_erro


def _get_bloco(url: str, cabecalhos: dict[str, str], timeout_s: int) -> requests.Response:
    """Isolado (como `_baixar_amostra`) para ser substituído por `monkeypatch` em
    teste, sem tocar rede real. `stream=True` para não puxar o corpo antes de o
    chamador checar o status."""
    return requests.get(url, headers=cabecalhos, timeout=timeout_s, stream=True)


def _parse_content_range(cabecalho: str, url: str) -> tuple[int, int, int | None]:
    """`bytes <ini>-<fim>/<total>` → `(ini, fim, total)`, com `total` `None` quando
    o servidor manda `*`. Cabeçalho ausente, malformado ou com faixa impossível
    (`fim < ini`, `fim >= total`) vira `FalhaDeExtracao` retentável."""
    correspondencia = _CONTENT_RANGE_RE.fullmatch(cabecalho)
    if correspondencia is None:
        raise FalhaDeExtracao(
            f"Content-Range ausente ou malformado ({cabecalho!r}) no download de {url}",
            permite_retentativa=True,
        )
    inicio_bruto, fim_bruto, total_bruto = correspondencia.groups()
    inicio, fim = int(inicio_bruto), int(fim_bruto)
    total = None if total_bruto == "*" else int(total_bruto)
    if fim < inicio or (total is not None and fim >= total):
        raise FalhaDeExtracao(
            f"Content-Range com faixa impossível ({cabecalho!r}) no download de {url}",
            permite_retentativa=True,
        )
    return inicio, fim, total

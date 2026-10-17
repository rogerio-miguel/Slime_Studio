"""Testes de `captura/download.py`. `conferir_link_de_midia`/`_montar_comando`
não tocam rede (monkeypatch/função pura); o download real é `@pytest.mark.integracao`
contra um arquivo **local** de teste, nunca contra rede."""

import shutil
from pathlib import Path

import pytest

from captura import download
from core.enums import TipoEpisodio, VersaoEpisodio
from core.erros import FalhaDeExtracao, FalhaDeFerramenta
from fontes.adaptadores.base import FormatoDeMidia, LinkDeMidia
from worker.pipeline.ferramentas import executar

_FFMPEG = shutil.which("ffmpeg")


def test_caminho_raw_segue_padrao_de_hls():
    caminho = download.caminho_raw(
        Path("/media"), "slime-datta-ken", 5, TipoEpisodio.REGULAR, VersaoEpisodio.LEGENDADO
    )
    assert caminho == Path("/media/raw/slime-datta-ken/005-regular-legendado.mkv")


def test_montar_comando_inclui_headers_com_cr_lf_no_ultimo():
    link = LinkDeMidia(
        url="https://cdn.exemplo/video.mp4",
        cabecalhos={"Referer": "https://site.exemplo/ep1", "User-Agent": "ua-teste"},
    )

    argumentos = download._montar_comando("ffmpeg", link, Path("/tmp/destino.mkv.part"))

    indice_headers = argumentos.index("-headers")
    valor_headers = argumentos[indice_headers + 1]
    assert valor_headers == "Referer: https://site.exemplo/ep1\r\nUser-Agent: ua-teste\r\n"
    assert valor_headers.endswith("\r\n")


def test_montar_comando_ordem_dos_argumentos():
    link = LinkDeMidia(url="https://cdn.exemplo/video.mp4", cabecalhos={"Referer": "r"})
    destino = Path("/tmp/destino.mkv.part")

    argumentos = download._montar_comando("ffmpeg", link, destino)

    assert argumentos == [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-y",
        "-protocol_whitelist",
        "http,https,tcp,tls,crypto",
        "-headers",
        "Referer: r\r\n",
        "-reconnect",
        "1",
        "-reconnect_streamed",
        "1",
        "-reconnect_on_network_error",
        "1",
        "-reconnect_delay_max",
        "30",
        "-i",
        "https://cdn.exemplo/video.mp4",
        "-c",
        "copy",
        "-f",
        "matroska",
        str(destino),
    ]


def test_montar_comando_remoto_restringe_protocolos_antes_do_input():
    link = LinkDeMidia(url="https://cdn.exemplo/video.mp4", cabecalhos={})

    argumentos = download._montar_comando("ffmpeg", link, Path("/tmp/destino.mkv.part"))

    indice = argumentos.index("-protocol_whitelist")
    assert argumentos[indice + 1] == "http,https,tcp,tls,crypto"
    assert indice < argumentos.index("-i")


def test_montar_comando_local_nao_restringe_protocolos():
    link = LinkDeMidia(url="/caminho/local.mp4", cabecalhos={})

    argumentos = download._montar_comando("ffmpeg", link, Path("/tmp/destino.mkv.part"))

    assert "-protocol_whitelist" not in argumentos


def test_montar_comando_ytdl_ignora_config_e_plugins_do_ambiente():
    link = LinkDeMidia(url="https://cdn.exemplo/m.jpg", cabecalhos={}, formato=FormatoDeMidia.HLS)

    argumentos = download._montar_comando_ytdl(link, "/tmp/video.%(ext)s", "ffmpeg")

    assert "--ignore-config" in argumentos
    assert "--no-plugin-dirs" in argumentos
    assert argumentos[-2:] == ["--", link.url]


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "/etc/passwd",
        "gopher://cdn.exemplo/x",
        "https:///sem-host",
        "http://localhost:8000/x",
        "http://api.localhost/x",
        "http://127.0.0.1/x",
        "http://[::1]/x",
        "http://[::ffff:127.0.0.1]/x",
        "http://10.0.0.5/x",
        "http://192.168.1.10/x",
        "http://169.254.169.254/latest/meta-data",
    ],
)
def test_exigir_url_de_midia_segura_rejeita_destino_nao_externo(url: str):
    with pytest.raises(FalhaDeExtracao) as erro:
        download.exigir_url_de_midia_segura(url)

    assert erro.value.permite_retentativa is False


@pytest.mark.parametrize(
    "url", ["https://cdn.exemplo/video.mp4", "http://cdn.exemplo:8080/m.m3u8", "https://93.184.216.34/x"]
)
def test_exigir_url_de_midia_segura_aceita_destino_externo(url: str):
    download.exigir_url_de_midia_segura(url)


def test_montar_comando_sem_cabecalhos_omite_flag_headers():
    link = LinkDeMidia(url="/caminho/local.mp4", cabecalhos={})
    destino = Path("/tmp/destino.mkv.part")

    argumentos = download._montar_comando("ffmpeg", link, destino)

    assert "-headers" not in argumentos
    assert argumentos == [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-y",
        "-i",
        "/caminho/local.mp4",
        "-c",
        "copy",
        "-f",
        "matroska",
        str(destino),
    ]


def test_montar_comando_dash_inclui_flag_de_formato_de_entrada():
    link = LinkDeMidia(
        url="https://akumast.net/i/token/m.jpg", cabecalhos={}, formato=FormatoDeMidia.DASH
    )
    destino = Path("/tmp/destino.mkv.part")

    argumentos = download._montar_comando("ffmpeg", link, destino)

    indice_f_dash = argumentos.index("-f")
    assert argumentos[indice_f_dash + 1] == "dash"
    indice_i = argumentos.index("-i")
    assert indice_f_dash < indice_i
    assert argumentos[indice_i + 1] == link.url


def test_conferir_link_de_midia_aceita_playlist_valida(monkeypatch):
    monkeypatch.setattr(
        download, "_baixar_amostra", lambda url, cabecalhos, timeout_s: ("", b"#EXTM3U\n...")
    )
    link = LinkDeMidia(url="https://cdn.exemplo/master.m3u8", cabecalhos={})

    download.conferir_link_de_midia(link)  # não levanta


def test_conferir_link_de_midia_detecta_isca_html():
    monkeypatch_valor = b"<!DOCTYPE html><html><body>Bloqueado</body></html>"

    def _amostra_falsa(url, cabecalhos, timeout_s):
        return "text/html", monkeypatch_valor

    original = download._baixar_amostra
    download._baixar_amostra = _amostra_falsa
    try:
        link = LinkDeMidia(url="https://cdn.exemplo/video.mp4", cabecalhos={})
        with pytest.raises(FalhaDeExtracao):
            download.conferir_link_de_midia(link)
    finally:
        download._baixar_amostra = original


def test_conferir_link_de_midia_detecta_content_type_imagem(monkeypatch):
    monkeypatch.setattr(
        download, "_baixar_amostra", lambda url, cabecalhos, timeout_s: ("image/png", b"\x89PNG...")
    )
    link = LinkDeMidia(url="https://cdn.exemplo/video.mp4", cabecalhos={})

    with pytest.raises(FalhaDeExtracao):
        download.conferir_link_de_midia(link)


def test_conferir_link_de_midia_detecta_playlist_sem_assinatura(monkeypatch):
    monkeypatch.setattr(
        download, "_baixar_amostra", lambda url, cabecalhos, timeout_s: ("", b"nao e um m3u8")
    )
    link = LinkDeMidia(url="https://cdn.exemplo/master.m3u8", cabecalhos={})

    with pytest.raises(FalhaDeExtracao):
        download.conferir_link_de_midia(link)


def test_conferir_link_de_midia_detecta_corpo_pequeno_demais(monkeypatch):
    monkeypatch.setattr(
        download, "_baixar_amostra", lambda url, cabecalhos, timeout_s: ("video/mp4", b"x")
    )
    link = LinkDeMidia(url="https://cdn.exemplo/video.mp4", cabecalhos={})

    with pytest.raises(FalhaDeExtracao):
        download.conferir_link_de_midia(link)


def test_conferir_link_de_midia_dash_aceita_manifesto_compacto(monkeypatch):
    """Regressão: um manifesto DASH compacto (uma Representation, um
    SegmentTemplate) cabe em menos de `_TAMANHO_MINIMO_BYTES` — o piso de tamanho
    não pode rejeitá-lo, nem a guarda de content-type de imagem (a URL termina em
    `.jpg` só de fachada)."""
    corpo = b'<?xml version="1.0"?><MPD><Period><AdaptationSet></AdaptationSet></Period></MPD>'
    assert len(corpo) < download._TAMANHO_MINIMO_BYTES
    monkeypatch.setattr(
        download, "_baixar_amostra", lambda url, cabecalhos, timeout_s: ("image/jpeg", corpo)
    )
    link = LinkDeMidia(
        url="https://akumast.net/i/token/m.jpg", cabecalhos={}, formato=FormatoDeMidia.DASH
    )

    download.conferir_link_de_midia(link)  # não levanta


def test_conferir_link_de_midia_dash_sem_assinatura_falha(monkeypatch):
    monkeypatch.setattr(
        download, "_baixar_amostra", lambda url, cabecalhos, timeout_s: ("image/jpeg", b"lixo")
    )
    link = LinkDeMidia(
        url="https://akumast.net/i/token/m.jpg", cabecalhos={}, formato=FormatoDeMidia.DASH
    )

    with pytest.raises(FalhaDeExtracao):
        download.conferir_link_de_midia(link)


def test_conferir_link_de_midia_hls_aceita_playlist_mascarada_de_jpg(monkeypatch):
    """Regressão: AnimeFire passou a servir HLS mascarado de `.jpg` (confirmado
    ao vivo em 2026-09-14) em vez de DASH — mesma fachada, corpo `#EXTM3U`."""
    monkeypatch.setattr(
        download,
        "_baixar_amostra",
        lambda url, cabecalhos, timeout_s: ("image/jpeg", b"#EXTM3U\n#EXT-X-STREAM-INF:...\n"),
    )
    link = LinkDeMidia(
        url="https://akumast.net/i/token/h.jpg", cabecalhos={}, formato=FormatoDeMidia.HLS
    )

    download.conferir_link_de_midia(link)  # não levanta


def test_conferir_link_de_midia_hls_sem_assinatura_falha(monkeypatch):
    monkeypatch.setattr(
        download, "_baixar_amostra", lambda url, cabecalhos, timeout_s: ("image/jpeg", b"lixo")
    )
    link = LinkDeMidia(
        url="https://akumast.net/i/token/h.jpg", cabecalhos={}, formato=FormatoDeMidia.HLS
    )

    with pytest.raises(FalhaDeExtracao):
        download.conferir_link_de_midia(link)


async def test_baixar_traduz_falha_do_ffmpeg_em_falha_de_extracao_retentavel(tmp_path, monkeypatch):
    """Download truncado pelo CDN (ffmpeg sai != 0) vira `FalhaDeExtracao`
    retentável — o executor reagenda com backoff em vez de falha definitiva — e
    preserva a cauda do stderr na mensagem. O `.part` parcial é removido."""
    destino = tmp_path / "raw" / "anime-teste" / "001-regular-legendado.mkv"
    parcial = destino.with_name(destino.name + ".part")

    async def _executar_falho(argumentos, *, timeout_s):
        destino.parent.mkdir(parents=True, exist_ok=True)
        parcial.write_bytes(b"parcial truncado")
        raise FalhaDeFerramenta(
            "comando falhou (código 187)", cauda_stderr="video.mp4: End of file"
        )

    monkeypatch.setattr(download, "executar", _executar_falho)
    link = LinkDeMidia(url="https://cdn.exemplo/video.mp4", cabecalhos={"Referer": "r"})

    with pytest.raises(FalhaDeExtracao) as info:
        await download.baixar(link, destino, "ffmpeg")

    assert info.value.permite_retentativa is True
    assert "187" in str(info.value)
    assert "End of file" in str(info.value)
    assert not parcial.exists()


@pytest.mark.parametrize("formato", [FormatoDeMidia.DASH, FormatoDeMidia.HLS])
async def test_baixar_desvia_manifesto_mascarado_para_ytdlp(tmp_path, monkeypatch, formato):
    """DASH e HLS mascarados (ver `FormatoDeMidia`) vão os dois para `_baixar_dash`
    (yt-dlp) — nunca para o `ffmpeg` direto, que trunca nos fragmentos-isca."""
    chamadas = []

    async def _baixar_dash_falso(link, destino, ffmpeg_bin, ffprobe_bin):
        chamadas.append(link)
        return destino

    monkeypatch.setattr(download, "_baixar_dash", _baixar_dash_falso)
    link = LinkDeMidia(url="https://akumast.net/i/token/m.jpg", cabecalhos={}, formato=formato)
    destino = tmp_path / "raw" / "anime-teste" / "001-regular-legendado.mkv"

    resultado = await download.baixar(link, destino, "ffmpeg", "ffprobe")

    assert resultado == destino
    assert chamadas == [link]


async def test_baixar_nao_traduz_part_ausente_apos_ffmpeg_ok(tmp_path, monkeypatch):
    """`.part` ausente depois do ffmpeg sair 0 é bug interno, não falha de rede —
    continua `FalhaDeFerramenta` (falha definitiva do job)."""
    destino = tmp_path / "raw" / "anime-teste" / "001-regular-legendado.mkv"

    async def _executar_ok(argumentos, *, timeout_s):
        return None

    monkeypatch.setattr(download, "executar", _executar_ok)
    link = LinkDeMidia(url="https://cdn.exemplo/video.mp4", cabecalhos={})

    with pytest.raises(FalhaDeFerramenta):
        await download.baixar(link, destino, "ffmpeg")


async def _gerar_clipe_sintetico(ffmpeg: Path, destino: Path) -> None:
    await executar(
        [
            str(ffmpeg),
            "-nostdin",
            "-hide_banner",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=1:size=160x120:rate=24",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(destino),
        ],
        timeout_s=60,
    )


@pytest.mark.integracao
@pytest.mark.skipif(_FFMPEG is None, reason="ffmpeg não está no PATH")
async def test_baixar_promove_part_para_destino_com_ffmpeg_real(tmp_path):
    fonte = tmp_path / "fonte.mp4"
    await _gerar_clipe_sintetico(Path(_FFMPEG), fonte)

    destino = tmp_path / "raw" / "anime-teste" / "001-regular-legendado.mkv"
    link = LinkDeMidia(url=str(fonte), cabecalhos={})

    resultado = await download.baixar(link, destino, _FFMPEG)

    assert resultado == destino
    assert destino.exists()
    assert not destino.with_name(destino.name + ".part").exists()

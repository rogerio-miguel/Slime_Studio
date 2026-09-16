"""Testes do download em blocos (Range requests) para `*.googlevideo.com` de
`extractors/download.py`. Sem rede real: `_get_bloco` (a única chamada HTTP, isolada
como `_baixar_amostra`) é substituída por `monkeypatch` e devolve um dublê de
`requests.Response`."""

from pathlib import Path

import pytest
import requests

from core.erros import FalhaDeExtracao, FalhaDeFerramenta
from extractors import download
from extractors.base import LinkDeMidia


class RespostaFalsa:
    """Dublê mínimo de `requests.Response` para os testes de bloco."""

    def __init__(
        self, status_code: int, *, headers: dict[str, str] | None = None, content: bytes = b""
    ) -> None:
        self.status_code = status_code
        self.headers = headers or {}
        self.content = content

    def iter_content(self, chunk_size: int = 1):
        passo = max(chunk_size, 1)
        for inicio in range(0, len(self.content), passo):
            yield self.content[inicio:inicio + passo]

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def _sequencia_de_blocos(itens, registro: list | None = None):
    """Fábrica de `_get_bloco` falso: devolve `itens` em ordem; um item que seja
    exceção é levantado. Se `registro` for passado, cada chamada anexa uma cópia
    dos cabeçalhos recebidos."""
    iterador = iter(itens)

    def _fake(url, cabecalhos, timeout_s):
        if registro is not None:
            registro.append(dict(cabecalhos))
        item = next(iterador)
        if isinstance(item, BaseException):
            raise item
        return item

    return _fake


# --- _eh_googlevideo -------------------------------------------------------------

@pytest.mark.parametrize(
    "url",
    [
        "https://rr2---sn-x.googlevideo.com/videoplayback?itag=18",
        "https://googlevideo.com/videoplayback",
        "http://GoogleVideo.com/x",
    ],
)
def test_eh_googlevideo_aceita_hosts_do_google(url):
    assert download._eh_googlevideo(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "https://animefire.one/video/123.mp4",
        "https://evil-googlevideo.com.br/x",
        "https://googlevideo.com.attacker.net/x",
        "https://cdn.exemplo/master.m3u8",
    ],
)
def test_eh_googlevideo_rejeita_hosts_parecidos(url):
    assert download._eh_googlevideo(url) is False


# --- _baixar_em_blocos: caminho feliz -----------------------------------------

def test_baixar_em_blocos_concatena_blocos_206_e_para_no_total(tmp_path, monkeypatch):
    monkeypatch.setattr(download, "_TAMANHO_BLOCO_BYTES", 10)
    dados = bytes(range(25))  # 2,5 blocos de 10
    respostas = [
        RespostaFalsa(206, headers={"Content-Range": "bytes 0-9/25"}, content=dados[0:10]),
        RespostaFalsa(206, headers={"Content-Range": "bytes 10-19/25"}, content=dados[10:20]),
        RespostaFalsa(206, headers={"Content-Range": "bytes 20-24/25"}, content=dados[20:25]),
    ]
    monkeypatch.setattr(download, "_get_bloco", _sequencia_de_blocos(respostas))

    destino = tmp_path / "video.bruto"
    download._baixar_em_blocos("https://x.googlevideo.com/v", {}, destino, timeout_s=60)

    assert destino.read_bytes() == dados


def test_baixar_em_blocos_envia_range_por_iteracao_e_propaga_user_agent(tmp_path, monkeypatch):
    monkeypatch.setattr(download, "_TAMANHO_BLOCO_BYTES", 10)
    dados = bytes(range(25))
    registro: list[dict[str, str]] = []
    respostas = [
        RespostaFalsa(206, headers={"Content-Range": "bytes 0-9/25"}, content=dados[0:10]),
        RespostaFalsa(206, headers={"Content-Range": "bytes 10-19/25"}, content=dados[10:20]),
        RespostaFalsa(206, headers={"Content-Range": "bytes 20-24/25"}, content=dados[20:25]),
    ]
    monkeypatch.setattr(download, "_get_bloco", _sequencia_de_blocos(respostas, registro))

    destino = tmp_path / "video.bruto"
    download._baixar_em_blocos(
        "https://x.googlevideo.com/v", {"User-Agent": "ua-x"}, destino, timeout_s=60
    )

    assert [h["Range"] for h in registro] == ["bytes=0-9", "bytes=10-19", "bytes=20-29"]
    assert all(h["User-Agent"] == "ua-x" for h in registro)


def test_baixar_em_blocos_conclui_com_416_apos_ter_escrito(tmp_path, monkeypatch):
    monkeypatch.setattr(download, "_TAMANHO_BLOCO_BYTES", 10)
    dados = b"0123456789"
    respostas = [
        RespostaFalsa(206, headers={"Content-Range": "bytes 0-9/*"}, content=dados),
        RespostaFalsa(416),
    ]
    monkeypatch.setattr(download, "_get_bloco", _sequencia_de_blocos(respostas))

    destino = tmp_path / "video.bruto"
    download._baixar_em_blocos("https://x.googlevideo.com/v", {}, destino, timeout_s=60)

    assert destino.read_bytes() == dados


# --- _baixar_em_blocos: fallback 200 ----------------------------------------------

def test_baixar_em_blocos_fallback_200_na_primeira_iteracao(tmp_path, monkeypatch):
    monkeypatch.setattr(download, "_TAMANHO_BLOCO_BYTES", 8)
    registro: list[dict[str, str]] = []
    corpo = b"corpo inteiro streamado sem range"
    monkeypatch.setattr(
        download, "_get_bloco",
        _sequencia_de_blocos([RespostaFalsa(200, content=corpo)], registro),
    )

    destino = tmp_path / "video.bruto"
    download._baixar_em_blocos("https://x.googlevideo.com/v", {}, destino, timeout_s=60)

    assert destino.read_bytes() == corpo
    assert len(registro) == 1  # uma requisição só


def test_baixar_em_blocos_200_em_iteracao_posterior_e_erro_retentavel(tmp_path, monkeypatch):
    monkeypatch.setattr(download, "_TAMANHO_BLOCO_BYTES", 10)
    respostas = [
        RespostaFalsa(206, headers={"Content-Range": "bytes 0-9/100"}, content=b"0123456789"),
        RespostaFalsa(200, content=b"agora ignorou o range"),
    ]
    monkeypatch.setattr(download, "_get_bloco", _sequencia_de_blocos(respostas))

    destino = tmp_path / "video.bruto"
    with pytest.raises(FalhaDeExtracao) as info:
        download._baixar_em_blocos("https://x.googlevideo.com/v", {}, destino, timeout_s=60)

    assert info.value.permite_retentativa is True


# --- _baixar_em_blocos: guardas de corrupção ------------------------------------

def test_baixar_em_blocos_bloco_206_vazio_aborta_retentavel(tmp_path, monkeypatch):
    monkeypatch.setattr(download, "_TAMANHO_BLOCO_BYTES", 10)
    respostas = [RespostaFalsa(206, headers={"Content-Range": "bytes 0-9/100"}, content=b"")]
    monkeypatch.setattr(download, "_get_bloco", _sequencia_de_blocos(respostas))

    destino = tmp_path / "video.bruto"
    with pytest.raises(FalhaDeExtracao) as info:
        download._baixar_em_blocos("https://x.googlevideo.com/v", {}, destino, timeout_s=60)

    assert info.value.permite_retentativa is True


def test_baixar_em_blocos_content_range_ausente_e_erro_retentavel(tmp_path, monkeypatch):
    monkeypatch.setattr(download, "_TAMANHO_BLOCO_BYTES", 10)
    respostas = [RespostaFalsa(206, headers={}, content=b"0123456789")]
    monkeypatch.setattr(download, "_get_bloco", _sequencia_de_blocos(respostas))

    destino = tmp_path / "video.bruto"
    with pytest.raises(FalhaDeExtracao) as info:
        download._baixar_em_blocos("https://x.googlevideo.com/v", {}, destino, timeout_s=60)

    assert info.value.permite_retentativa is True


def test_baixar_em_blocos_corpo_menor_que_o_content_range_e_erro_retentavel(tmp_path, monkeypatch):
    monkeypatch.setattr(download, "_TAMANHO_BLOCO_BYTES", 10)
    respostas = [RespostaFalsa(206, headers={"Content-Range": "bytes 0-9/100"}, content=b"012")]
    monkeypatch.setattr(download, "_get_bloco", _sequencia_de_blocos(respostas))

    destino = tmp_path / "video.bruto"
    with pytest.raises(FalhaDeExtracao) as info:
        download._baixar_em_blocos("https://x.googlevideo.com/v", {}, destino, timeout_s=60)

    assert info.value.permite_retentativa is True


# --- retry por bloco -----------------------------------------------------------

def test_baixar_em_blocos_retenta_bloco_em_erro_de_rede_e_conclui(tmp_path, monkeypatch):
    monkeypatch.setattr(download, "_TAMANHO_BLOCO_BYTES", 1000)
    dados = b"conteudo completo do video"
    sleeps: list[int] = []
    monkeypatch.setattr(download.time, "sleep", sleeps.append)
    respostas = [
        requests.ConnectionError("conexao caiu"),
        requests.ConnectionError("de novo"),
        RespostaFalsa(
            206,
            headers={"Content-Range": f"bytes 0-{len(dados) - 1}/{len(dados)}"},
            content=dados,
        ),
    ]
    monkeypatch.setattr(download, "_get_bloco", _sequencia_de_blocos(respostas))

    destino = tmp_path / "video.bruto"
    download._baixar_em_blocos("https://x.googlevideo.com/v", {}, destino, timeout_s=60)

    assert destino.read_bytes() == dados
    assert sleeps == [1, 2]


def test_baixar_em_blocos_esgota_retentativas_do_bloco_e_falha_retentavel(tmp_path, monkeypatch):
    monkeypatch.setattr(download, "_TAMANHO_BLOCO_BYTES", 1000)
    sleeps: list[int] = []
    monkeypatch.setattr(download.time, "sleep", sleeps.append)
    respostas = [requests.ConnectionError("caiu") for _ in range(download._MAX_TENTATIVAS_BLOCO)]
    monkeypatch.setattr(download, "_get_bloco", _sequencia_de_blocos(respostas))

    destino = tmp_path / "video.bruto"
    with pytest.raises(FalhaDeExtracao) as info:
        download._baixar_em_blocos("https://x.googlevideo.com/v", {}, destino, timeout_s=60)

    assert info.value.permite_retentativa is True
    assert sleeps == [1, 2, 4]


def test_baixar_em_blocos_status_5xx_retenta_e_falha_retentavel(tmp_path, monkeypatch):
    monkeypatch.setattr(download, "_TAMANHO_BLOCO_BYTES", 1000)
    monkeypatch.setattr(download.time, "sleep", lambda _s: None)
    respostas = [RespostaFalsa(503) for _ in range(download._MAX_TENTATIVAS_BLOCO)]
    monkeypatch.setattr(download, "_get_bloco", _sequencia_de_blocos(respostas))

    destino = tmp_path / "video.bruto"
    with pytest.raises(FalhaDeExtracao) as info:
        download._baixar_em_blocos("https://x.googlevideo.com/v", {}, destino, timeout_s=60)

    assert info.value.permite_retentativa is True


# --- baixar(): roteamento googlevideo ----------------------------------------

async def test_baixar_googlevideo_baixa_em_blocos_remuxa_e_promove(tmp_path, monkeypatch):
    destino = tmp_path / "raw" / "anime-teste" / "001-regular-legendado.mkv"
    bruto = destino.with_name(destino.name + ".bruto")
    parcial = destino.with_name(destino.name + ".part")

    visto: dict[str, object] = {}

    def _blocos_falso(url, cabecalhos, destino_bruto, *, timeout_s):
        visto["url"] = url
        visto["cabecalhos"] = dict(cabecalhos)
        destino_bruto.write_bytes(b"mp4 falso progressivo itag 18")

    async def _executar_ok(argumentos, *, timeout_s):
        Path(argumentos[-1]).write_bytes(b"mkv remuxado")

    monkeypatch.setattr(download, "_baixar_em_blocos", _blocos_falso)
    monkeypatch.setattr(download, "executar", _executar_ok)

    link = LinkDeMidia(
        url="https://rr3---sn-abc.googlevideo.com/videoplayback?itag=18",
        cabecalhos={"User-Agent": "ua-teste"},
    )
    resultado = await download.baixar(link, destino, "ffmpeg")

    assert resultado == destino
    assert destino.read_bytes() == b"mkv remuxado"
    assert not bruto.exists()
    assert not parcial.exists()
    assert visto["url"] == link.url
    assert visto["cabecalhos"] == {"User-Agent": "ua-teste"}


async def test_baixar_googlevideo_falha_no_remux_limpa_bruto_e_part(tmp_path, monkeypatch):
    destino = tmp_path / "raw" / "anime-teste" / "001-regular-legendado.mkv"
    bruto = destino.with_name(destino.name + ".bruto")
    parcial = destino.with_name(destino.name + ".part")

    def _blocos_falso(url, cabecalhos, destino_bruto, *, timeout_s):
        destino_bruto.write_bytes(b"mp4 falso")

    async def _executar_falho(argumentos, *, timeout_s):
        Path(argumentos[-1]).write_bytes(b"parcial truncado")
        raise FalhaDeFerramenta(
            "comando falhou (código 1)", cauda_stderr="bruto: Invalid data found"
        )

    monkeypatch.setattr(download, "_baixar_em_blocos", _blocos_falso)
    monkeypatch.setattr(download, "executar", _executar_falho)

    link = LinkDeMidia(
        url="https://x.googlevideo.com/videoplayback", cabecalhos={"User-Agent": "u"}
    )
    with pytest.raises(FalhaDeExtracao) as info:
        await download.baixar(link, destino, "ffmpeg")

    assert info.value.permite_retentativa is True
    assert "Invalid data found" in str(info.value)
    assert not bruto.exists()
    assert not parcial.exists()
    assert not destino.exists()


async def test_baixar_googlevideo_falha_no_download_em_blocos_limpa_bruto(tmp_path, monkeypatch):
    destino = tmp_path / "raw" / "anime-teste" / "001-regular-legendado.mkv"
    bruto = destino.with_name(destino.name + ".bruto")

    def _blocos_falho(url, cabecalhos, destino_bruto, *, timeout_s):
        destino_bruto.write_bytes(b"parcial")
        raise FalhaDeExtracao("rede caiu no bloco 3", permite_retentativa=True)

    async def _executar_nunca(argumentos, *, timeout_s):
        raise AssertionError("ffmpeg não deveria ser chamado se o download em blocos falhou")

    monkeypatch.setattr(download, "_baixar_em_blocos", _blocos_falho)
    monkeypatch.setattr(download, "executar", _executar_nunca)

    link = LinkDeMidia(url="https://x.googlevideo.com/v", cabecalhos={"User-Agent": "u"})
    with pytest.raises(FalhaDeExtracao):
        await download.baixar(link, destino, "ffmpeg")

    assert not bruto.exists()


async def test_baixar_url_nao_googlevideo_usa_ffmpeg_direto(tmp_path, monkeypatch):
    destino = tmp_path / "raw" / "anime-teste" / "001-regular-legendado.mkv"

    def _blocos_nunca(*_args, **_kwargs):
        raise AssertionError("_baixar_em_blocos não deveria rodar para URL não-googlevideo")

    argumentos_vistos: dict[str, object] = {}

    async def _executar_ok(argumentos, *, timeout_s):
        argumentos_vistos["args"] = list(argumentos)
        Path(argumentos[-1]).write_bytes(b"mkv")

    monkeypatch.setattr(download, "_baixar_em_blocos", _blocos_nunca)
    monkeypatch.setattr(download, "executar", _executar_ok)

    link = LinkDeMidia(url="https://cdn.animefire.plus/video/123.mp4", cabecalhos={"Referer": "r"})
    resultado = await download.baixar(link, destino, "ffmpeg")

    assert resultado == destino
    assert destino.read_bytes() == b"mkv"
    assert "-i" in argumentos_vistos["args"]
    assert "https://cdn.animefire.plus/video/123.mp4" in argumentos_vistos["args"]

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


def _respostas_por_faixa(mapa: dict[str, object], registro: list | None = None):
    """Fábrica de `_get_bloco` falso: escolhe a resposta pela `Range` pedida, não
    pela ordem de chamada — necessário porque os blocos restantes (depois do
    primeiro) saem em paralelo, então a ordem de chamada não é determinística.
    Valor no mapa é uma resposta única (sempre a mesma) ou uma lista/fila
    (cada chamada consome o próximo item — simula retry-então-sucesso na mesma
    faixa). Item que seja exceção é levantado. Se `registro` for passado, cada
    chamada anexa uma cópia dos cabeçalhos recebidos."""
    filas = {
        chave: (list(valor) if isinstance(valor, list) else None) for chave, valor in mapa.items()
    }

    def _fake(url, cabecalhos, timeout_s):
        if registro is not None:
            registro.append(dict(cabecalhos))
        faixa = cabecalhos["Range"]
        fila = filas.get(faixa)
        item = fila.pop(0) if fila is not None else mapa[faixa]
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
    dados = bytes(range(25))  # 2,5 blocos de 10: 1 sequencial + 2 em paralelo
    mapa = {
        "bytes=0-9": RespostaFalsa(
            206, headers={"Content-Range": "bytes 0-9/25"}, content=dados[0:10]
        ),
        "bytes=10-19": RespostaFalsa(
            206, headers={"Content-Range": "bytes 10-19/25"}, content=dados[10:20]
        ),
        "bytes=20-29": RespostaFalsa(
            206, headers={"Content-Range": "bytes 20-24/25"}, content=dados[20:25]
        ),
    }
    monkeypatch.setattr(download, "_get_bloco", _respostas_por_faixa(mapa))

    destino = tmp_path / "video.bruto"
    download._baixar_em_blocos("https://x.googlevideo.com/v", {}, destino, timeout_s=60)

    assert destino.read_bytes() == dados


def test_baixar_em_blocos_envia_range_por_iteracao_e_propaga_user_agent(tmp_path, monkeypatch):
    monkeypatch.setattr(download, "_TAMANHO_BLOCO_BYTES", 10)
    dados = bytes(range(25))
    registro: list[dict[str, str]] = []
    mapa = {
        "bytes=0-9": RespostaFalsa(
            206, headers={"Content-Range": "bytes 0-9/25"}, content=dados[0:10]
        ),
        "bytes=10-19": RespostaFalsa(
            206, headers={"Content-Range": "bytes 10-19/25"}, content=dados[10:20]
        ),
        "bytes=20-29": RespostaFalsa(
            206, headers={"Content-Range": "bytes 20-24/25"}, content=dados[20:25]
        ),
    }
    monkeypatch.setattr(download, "_get_bloco", _respostas_por_faixa(mapa, registro))

    destino = tmp_path / "video.bruto"
    download._baixar_em_blocos(
        "https://x.googlevideo.com/v", {"User-Agent": "ua-x"}, destino, timeout_s=60
    )

    # 1º bloco sempre sai sozinho, sequencial; os 2 seguintes saem em paralelo
    # (ordem entre eles não é determinística).
    assert registro[0]["Range"] == "bytes=0-9"
    assert sorted(h["Range"] for h in registro[1:]) == ["bytes=10-19", "bytes=20-29"]
    assert all(h["User-Agent"] == "ua-x" for h in registro)


def test_baixar_em_blocos_conclui_com_416_apos_ter_escrito(tmp_path, monkeypatch):
    """Sem total conhecido (`Content-Range` com `*`), cai pro caminho
    sequencial original — 416 depois de já ter escrito algo é fim legítimo."""
    monkeypatch.setattr(download, "_TAMANHO_BLOCO_BYTES", 10)
    dados = b"0123456789"
    mapa = {
        "bytes=0-9": RespostaFalsa(206, headers={"Content-Range": "bytes 0-9/*"}, content=dados),
        "bytes=10-19": RespostaFalsa(416),
    }
    monkeypatch.setattr(download, "_get_bloco", _respostas_por_faixa(mapa))

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
        _respostas_por_faixa({"bytes=0-7": RespostaFalsa(200, content=corpo)}, registro),
    )

    destino = tmp_path / "video.bruto"
    download._baixar_em_blocos("https://x.googlevideo.com/v", {}, destino, timeout_s=60)

    assert destino.read_bytes() == corpo
    assert len(registro) == 1  # uma requisição só


def test_baixar_em_blocos_200_em_bloco_paralelo_e_erro_retentavel(tmp_path, monkeypatch):
    """Total conhecido (20) e um só bloco restante (10-19) — 200 nele é erro:
    com total conhecido, um bloco dentro dele só pode vir como 206."""
    monkeypatch.setattr(download, "_TAMANHO_BLOCO_BYTES", 10)
    mapa = {
        "bytes=0-9": RespostaFalsa(
            206, headers={"Content-Range": "bytes 0-9/20"}, content=b"0123456789"
        ),
        "bytes=10-19": RespostaFalsa(200, content=b"agora ignorou o range"),
    }
    monkeypatch.setattr(download, "_get_bloco", _respostas_por_faixa(mapa))

    destino = tmp_path / "video.bruto"
    with pytest.raises(FalhaDeExtracao) as info:
        download._baixar_em_blocos("https://x.googlevideo.com/v", {}, destino, timeout_s=60)

    assert info.value.permite_retentativa is True


# --- _baixar_em_blocos: guardas de corrupção ------------------------------------

def test_baixar_em_blocos_bloco_206_vazio_aborta_retentavel(tmp_path, monkeypatch):
    monkeypatch.setattr(download, "_TAMANHO_BLOCO_BYTES", 10)
    mapa = {
        "bytes=0-9": RespostaFalsa(206, headers={"Content-Range": "bytes 0-9/100"}, content=b"")
    }
    monkeypatch.setattr(download, "_get_bloco", _respostas_por_faixa(mapa))

    destino = tmp_path / "video.bruto"
    with pytest.raises(FalhaDeExtracao) as info:
        download._baixar_em_blocos("https://x.googlevideo.com/v", {}, destino, timeout_s=60)

    assert info.value.permite_retentativa is True


def test_baixar_em_blocos_content_range_ausente_e_erro_retentavel(tmp_path, monkeypatch):
    monkeypatch.setattr(download, "_TAMANHO_BLOCO_BYTES", 10)
    mapa = {"bytes=0-9": RespostaFalsa(206, headers={}, content=b"0123456789")}
    monkeypatch.setattr(download, "_get_bloco", _respostas_por_faixa(mapa))

    destino = tmp_path / "video.bruto"
    with pytest.raises(FalhaDeExtracao) as info:
        download._baixar_em_blocos("https://x.googlevideo.com/v", {}, destino, timeout_s=60)

    assert info.value.permite_retentativa is True


def test_baixar_em_blocos_corpo_menor_que_o_content_range_e_erro_retentavel(tmp_path, monkeypatch):
    monkeypatch.setattr(download, "_TAMANHO_BLOCO_BYTES", 10)
    mapa = {
        "bytes=0-9": RespostaFalsa(
            206, headers={"Content-Range": "bytes 0-9/100"}, content=b"012"
        )
    }
    monkeypatch.setattr(download, "_get_bloco", _respostas_por_faixa(mapa))

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
    mapa = {
        "bytes=0-999": [
            requests.ConnectionError("conexao caiu"),
            requests.ConnectionError("de novo"),
            RespostaFalsa(
                206,
                headers={"Content-Range": f"bytes 0-{len(dados) - 1}/{len(dados)}"},
                content=dados,
            ),
        ]
    }
    monkeypatch.setattr(download, "_get_bloco", _respostas_por_faixa(mapa))

    destino = tmp_path / "video.bruto"
    download._baixar_em_blocos("https://x.googlevideo.com/v", {}, destino, timeout_s=60)

    assert destino.read_bytes() == dados
    assert sleeps == [1, 2]


def test_baixar_em_blocos_esgota_retentativas_do_bloco_e_falha_retentavel(tmp_path, monkeypatch):
    monkeypatch.setattr(download, "_TAMANHO_BLOCO_BYTES", 1000)
    sleeps: list[int] = []
    monkeypatch.setattr(download.time, "sleep", sleeps.append)
    mapa = {
        "bytes=0-999": [
            requests.ConnectionError("caiu") for _ in range(download._MAX_TENTATIVAS_BLOCO)
        ]
    }
    monkeypatch.setattr(download, "_get_bloco", _respostas_por_faixa(mapa))

    destino = tmp_path / "video.bruto"
    with pytest.raises(FalhaDeExtracao) as info:
        download._baixar_em_blocos("https://x.googlevideo.com/v", {}, destino, timeout_s=60)

    assert info.value.permite_retentativa is True
    assert sleeps == [1, 2, 4]


def test_baixar_em_blocos_status_5xx_retenta_e_falha_retentavel(tmp_path, monkeypatch):
    monkeypatch.setattr(download, "_TAMANHO_BLOCO_BYTES", 1000)
    monkeypatch.setattr(download.time, "sleep", lambda _s: None)
    mapa = {"bytes=0-999": [RespostaFalsa(503) for _ in range(download._MAX_TENTATIVAS_BLOCO)]}
    monkeypatch.setattr(download, "_get_bloco", _respostas_por_faixa(mapa))

    destino = tmp_path / "video.bruto"
    with pytest.raises(FalhaDeExtracao) as info:
        download._baixar_em_blocos("https://x.googlevideo.com/v", {}, destino, timeout_s=60)

    assert info.value.permite_retentativa is True


# --- _baixar_em_blocos: caminho paralelo (blocos restantes) ---------------------

def test_baixar_em_blocos_paralelo_reconstitui_arquivo_fora_de_ordem(tmp_path, monkeypatch):
    """5 blocos restantes; um deles (o do meio) tem latência artificial maior,
    forçando conclusão fora de ordem — o arquivo final tem que sair correto
    mesmo assim (escrita por `seek`, não por ordem de chegada)."""
    import time as time_mod

    monkeypatch.setattr(download, "_TAMANHO_BLOCO_BYTES", 10)
    dados = bytes(range(60))  # 6 blocos de 10
    mapa = {}
    for inicio in range(0, 60, 10):
        fim = min(inicio + 9, 59)
        mapa[f"bytes={inicio}-{inicio + 9}"] = RespostaFalsa(
            206,
            headers={"Content-Range": f"bytes {inicio}-{fim}/60"},
            content=dados[inicio : fim + 1],
        )

    base_fake = _respostas_por_faixa(mapa)

    def _fake_com_atraso(url, cabecalhos, timeout_s):
        if cabecalhos["Range"] == "bytes=30-39":  # bloco do meio, atrasado de propósito
            time_mod.sleep(0.05)
        return base_fake(url, cabecalhos, timeout_s)

    monkeypatch.setattr(download, "_get_bloco", _fake_com_atraso)

    destino = tmp_path / "video.bruto"
    download._baixar_em_blocos("https://x.googlevideo.com/v", {}, destino, timeout_s=60)

    assert destino.read_bytes() == dados


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

"""Testes de `extractors/cliente.py::ClienteNavegador` sem rede e sem Chromium —
a página do DrissionPage é substituída por um dublê que devolve pacotes de rede
pré-programados.

O que roda contra navegador de verdade é o smoke test (`test_smoke_scrapers.py`,
marcador `rede`, desselecionado por padrão): aqui a intenção é travar a lógica de
decisão (o que conta como mídia, o que é descartado), não o driver.
"""

import pytest

from core.erros import FalhaDeExtracao
from extractors import cliente as modulo_cliente
from extractors.cliente import ClienteNavegador


class _RequisicaoFalsa:
    def __init__(self, headers: dict[str, str]) -> None:
        self.headers = headers


class _PacoteFalso:
    def __init__(self, url: str, *, tipo: str = "Media", headers: dict | None = None) -> None:
        self.url = url
        self.resourceType = tipo
        self.request = _RequisicaoFalsa(
            headers
            if headers is not None
            else {"Referer": "https://animesdrive.online/", "User-Agent": "Chrome/150"}
        )


class _EscutaFalsa:
    def __init__(self, pacotes: list[_PacoteFalso]) -> None:
        self._pacotes = list(pacotes)

    def start(self, *args, **kwargs) -> None:
        pass

    def stop(self) -> None:
        pass

    def wait(self, timeout=None, raise_err=None):
        return self._pacotes.pop(0) if self._pacotes else False


class _AcoesFalsas:
    def __init__(self) -> None:
        self.cliques = 0

    def move_to(self, ponto):
        return self

    def click(self) -> None:
        self.cliques += 1


class _PaginaFalsa:
    def __init__(self, pacotes: list[_PacoteFalso]) -> None:
        self.listen = _EscutaFalsa(pacotes)
        self.actions = _AcoesFalsas()
        self.navegou: list[str] = []

    def get(self, url, **kwargs) -> None:
        self.navegou.append(url)

    def run_js(self, script):
        return [640, 360]  # centro do "player"


@pytest.fixture
def navegador_com(monkeypatch):
    """Devolve `(cliente, pagina)` com a página dublada já instalada."""

    def _montar(pacotes: list[_PacoteFalso], *, responde=lambda url, cabecalhos: True):
        pagina = _PaginaFalsa(pacotes)
        cliente = ClienteNavegador()
        monkeypatch.setattr(cliente, "_obter_pagina", lambda: pagina)
        monkeypatch.setattr(modulo_cliente, "_responde", responde)
        return cliente, pagina

    return _montar


def test_capturar_midia_devolve_os_cabecalhos_que_o_navegador_enviou(navegador_com):
    cliente, pagina = navegador_com([_PacoteFalso("https://cdn.exemplo/01.mp4")])

    capturada = cliente.capturar_midia("https://animesdrive.online/episodio/x", timeout_s=5)

    assert capturada.url == "https://cdn.exemplo/01.mp4"
    assert capturada.cabecalhos == {
        "User-Agent": "Chrome/150",
        "Referer": "https://animesdrive.online/",
    }
    assert pagina.navegou == ["https://animesdrive.online/episodio/x"]


def test_capturar_midia_pula_a_origem_que_nao_responde(navegador_com):
    """Regressão do caso real: o player pede duas origens e a **primeira** devolve
    404 — devolver a primeira vista faria o job baixar lixo (confirmado ao vivo em
    2026-08-17)."""
    cliente, _ = navegador_com(
        [_PacoteFalso("https://morta.exemplo/01.mp4"), _PacoteFalso("https://viva.exemplo/01.mp4")],
        responde=lambda url, cabecalhos: "viva" in url,
    )

    capturada = cliente.capturar_midia("https://animesdrive.online/episodio/x", timeout_s=5)

    assert capturada.url == "https://viva.exemplo/01.mp4"


def test_capturar_midia_sem_origem_viva_falha_dizendo_o_que_descartou(navegador_com):
    cliente, _ = navegador_com(
        [_PacoteFalso("https://morta.exemplo/01.mp4")],
        responde=lambda url, cabecalhos: False,
    )

    with pytest.raises(FalhaDeExtracao) as excinfo:
        cliente.capturar_midia("https://animesdrive.online/episodio/x", timeout_s=1)

    assert excinfo.value.permite_retentativa is True
    assert "morta.exemplo" in str(excinfo.value)


def test_capturar_midia_ignora_segmento_e_host_excluido(navegador_com):
    """Segmento HLS (`.ts`) é pedaço, não índice — o `ffmpeg` não baixa o episódio
    a partir dele. Trailer do YouTube na mesma página também não é a mídia."""
    cliente, _ = navegador_com(
        [
            _PacoteFalso("https://cdn.exemplo/stream/seg-001.ts"),
            _PacoteFalso("https://rr1.googlevideo.youtube.com/videoplayback.mp4"),
            _PacoteFalso("https://cdn.exemplo/master.m3u8", tipo="XHR"),
        ]
    )

    capturada = cliente.capturar_midia(
        "https://animesdrive.online/episodio/x",
        hosts_ignorados=("youtube.com", "youtu.be"),
        timeout_s=5,
    )

    assert capturada.url == "https://cdn.exemplo/master.m3u8"


def test_capturar_midia_clica_no_player_quando_nada_aparece_sozinho(navegador_com):
    """Player que só pede a mídia depois de interação: sem o clique, a captura
    expiraria com a página parada no poster."""
    cliente, pagina = navegador_com([], responde=lambda url, cabecalhos: True)

    with pytest.raises(FalhaDeExtracao):
        cliente.capturar_midia("https://animesdrive.online/episodio/x", timeout_s=1)

    assert pagina.actions.cliques > 0


def test_cabecalhos_caem_no_user_agent_do_cliente_quando_a_requisicao_nao_trouxe(
    navegador_com,
):
    cliente, _ = navegador_com([_PacoteFalso("https://cdn.exemplo/01.mp4", headers={})])

    capturada = cliente.capturar_midia("https://animesdrive.online/episodio/x", timeout_s=5)

    assert capturada.cabecalhos == {"User-Agent": cliente.user_agent()}


def test_binario_de_navegador_respeita_a_variavel_de_ambiente(monkeypatch):
    monkeypatch.setenv("SLIME_NAVEGADOR_BIN", "/opt/navegador/bin")

    assert modulo_cliente._localizar_binario_de_navegador() == "/opt/navegador/bin"


def test_sem_navegador_instalado_falha_sem_retentativa(monkeypatch):
    """Faltar navegador é problema de máquina, não do site — retentar não resolve
    e não pode contar no circuit breaker do domínio."""
    monkeypatch.delenv("SLIME_NAVEGADOR_BIN", raising=False)
    monkeypatch.setattr(modulo_cliente.shutil, "which", lambda nome: None)

    with pytest.raises(FalhaDeExtracao) as excinfo:
        modulo_cliente._localizar_binario_de_navegador()

    assert excinfo.value.permite_retentativa is False


def test_fechar_sem_navegador_aberto_nao_faz_nada(monkeypatch):
    """`resiliencia` fecha o cliente sempre, inclusive quando a operação falhou
    antes de qualquer navegação — não pode explodir por causa disso."""
    ClienteNavegador().fechar()

"""Testes de `extractors/cliente.py::ClienteNavegador` sem rede e sem Chromium —
a página do DrissionPage é substituída por um dublê que devolve pacotes de rede
pré-programados.

O que roda contra navegador de verdade é o smoke test (`test_smoke_scrapers.py`,
marcador `rede`, desselecionado por padrão): aqui a intenção é travar a lógica de
decisão (o que conta como mídia, o que é descartado), não o driver.
"""

import sys

import pytest
from DrissionPage.errors import BaseError

from core.erros import FalhaDeExtracao, SessaoRejeitada
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
    """Um `start()` avança pro próximo lote de pacotes (capado no último) — é o
    que torna observável o descarte da fila pré-troca de servidor: a escuta é
    parada e rearmada depois do clique de ativação
    (`ClienteNavegador._ativar_servidor`), então o 2º `start()` de uma captura
    com `seletor_para_ativar` deve enxergar só o lote pós-troca."""

    def __init__(self, lotes: list[list[_PacoteFalso]]) -> None:
        self._lotes = lotes
        self._indice = -1
        self._pacotes: list[_PacoteFalso] = []

    def start(self, *args, **kwargs) -> None:
        self._indice = min(self._indice + 1, len(self._lotes) - 1)
        self._pacotes = list(self._lotes[self._indice])

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


class _ElementoFalso:
    """Dublê do botão de troca de servidor (`pagina.ele(seletor)`)."""

    def __init__(self) -> None:
        self.cliques = 0

    def click(self) -> None:
        self.cliques += 1


# UA que `_PaginaFalsa.run_js` devolve para o script de `navigator.userAgent`.
# Em produção (modo visível) é o UA nativo do binário, lido do DOM — não a
# constante `_USER_AGENT_NAVEGADOR`.
_UA_DO_DOM_PADRAO = "Mozilla/5.0 (X11; Linux x86_64) Chrome-nativo-de-teste/151.0 Safari/537.36"


class _PaginaFalsa:
    def __init__(
        self,
        lotes: list[list[_PacoteFalso]],
        *,
        elemento_ausente: bool = False,
        html: str | list[str] = "",
        ua_do_dom: str | BaseException = _UA_DO_DOM_PADRAO,
    ) -> None:
        self.listen = _EscutaFalsa(lotes)
        self.actions = _AcoesFalsas()
        self.navegou: list[str] = []
        self.elemento: _ElementoFalso | None = None if elemento_ausente else _ElementoFalso()
        # `html` é lido por `_aguardar_desafio_cloudflare` / `_ainda_em_desafio` /
        # `obter_html`. `str` → sempre devolvido (o default `""` não tem marcador,
        # então o caminho normal segue direto). Sequência → um item por leitura,
        # repetindo o último indefinidamente: simula o DOM trocando da
        # interstitial de desafio para a página real após o auto-solve do
        # Cloudflare.
        self._html_sequencia: list[str] = [html] if isinstance(html, str) else list(html)
        self._html_cursor = 0
        # `run_js` despacha por script: o de `user_agent()` devolve string (ou
        # levanta, se `ua_do_dom` for uma exceção); qualquer outro é o
        # `_JS_CENTRO_DO_PLAYER`, que espera um par de coordenadas.
        self._ua_do_dom = ua_do_dom
        self.leituras_de_ua = 0

    @property
    def html(self) -> str:
        indice = min(self._html_cursor, len(self._html_sequencia) - 1)
        self._html_cursor += 1
        return self._html_sequencia[indice]

    def get(self, url, **kwargs) -> None:
        self.navegou.append(url)

    def run_js(self, script):
        if "navigator.userAgent" in script:
            self.leituras_de_ua += 1
            if isinstance(self._ua_do_dom, BaseException):
                raise self._ua_do_dom
            return self._ua_do_dom
        return [640, 360]  # centro do "player" (_JS_CENTRO_DO_PLAYER)

    def ele(self, seletor, timeout=None):
        return self.elemento


@pytest.fixture
def navegador_com(monkeypatch):
    """Devolve `(cliente, pagina)` com a página dublada já instalada.

    `pacotes` é o lote único de sempre (compatível com os testes que não
    mexem em troca de servidor); `lotes` (lista de lotes) é pra quem precisa
    simular o descarte de fila pré/pós-troca."""

    def _montar(
        pacotes: list[_PacoteFalso] | None = None,
        *,
        lotes: list[list[_PacoteFalso]] | None = None,
        responde=lambda url, cabecalhos: True,
        elemento_ausente: bool = False,
        html: str | list[str] = "",
    ):
        lotes_reais = lotes if lotes is not None else [pacotes or []]
        pagina = _PaginaFalsa(lotes_reais, elemento_ausente=elemento_ausente, html=html)
        cliente = ClienteNavegador()
        monkeypatch.setattr(cliente, "_obter_pagina", lambda: pagina)
        monkeypatch.setattr(modulo_cliente, "responde", responde)
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


def test_capturar_midia_ativa_o_servidor_antes_de_procurar_midia(navegador_com):
    """Com `seletor_para_ativar`, o pacote do lote PRÉ-troca (o que a aba do
    servidor default já tinha enfileirado) é descartado — só o pacote do lote
    PÓS-troca (depois do clique + rearme da escuta) conta."""
    cliente, pagina = navegador_com(
        lotes=[
            [_PacoteFalso("https://cdn.exemplo/default.mp4")],
            [_PacoteFalso("https://cdn.exemplo/pos-troca.mp4")],
        ]
    )

    capturada = cliente.capturar_midia(
        "https://animesdrive.online/episodio/x",
        seletor_para_ativar='[data-animeq-switch="1"]',
        timeout_s=5,
    )

    assert capturada.url == "https://cdn.exemplo/pos-troca.mp4"
    assert pagina.elemento.cliques == 1


def test_capturar_midia_com_seletor_inexistente_falha_em_vez_de_pegar_o_player_default(
    navegador_com,
):
    """Elemento não encontrado falha o candidato — não pode seguir e devolver a
    mídia do servidor default, que seria a qualidade errada silenciosa."""
    cliente, _ = navegador_com(
        lotes=[[_PacoteFalso("https://cdn.exemplo/default.mp4")]],
        elemento_ausente=True,
    )

    with pytest.raises(FalhaDeExtracao) as excinfo:
        cliente.capturar_midia(
            "https://animesdrive.online/episodio/x",
            seletor_para_ativar='[data-animeq-switch="1"]',
            timeout_s=5,
        )

    assert '[data-animeq-switch="1"]' in str(excinfo.value)


def test_capturar_midia_sem_seletor_nao_rearma_a_escuta(navegador_com):
    """Regressão do caminho legado: sem `seletor_para_ativar`, `listen.start` é
    chamado uma vez só (o rearme extra é exclusivo do fluxo de troca)."""
    cliente, pagina = navegador_com([_PacoteFalso("https://cdn.exemplo/01.mp4")])
    chamadas_de_start = []
    start_original = pagina.listen.start

    def start_contando(*args, **kwargs):
        chamadas_de_start.append(1)
        start_original(*args, **kwargs)

    pagina.listen.start = start_contando

    cliente.capturar_midia("https://animesdrive.online/episodio/x", timeout_s=5)

    assert len(chamadas_de_start) == 1


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


# ===========================================================================
# Fatia D — bypass de desafio Cloudflare (modo de exibição, marcadores, espera)
# ===========================================================================


class _ErroDrissionFalso(BaseError):
    """Exceção trivial no lugar de uma real do DrissionPage — o caminho de erro
    de `user_agent()` só captura `BaseError`."""


class _RespostaHttpFalsa:
    """Mínimo de `requests.Response` que `_eh_desafio_cloudflare` inspeciona."""

    def __init__(self, *, headers: dict[str, str] | None = None, text: str = "") -> None:
        self.headers = headers or {}
        self.text = text


class _RespostaDocumentoFalsa:
    def __init__(self, status: int) -> None:
        self.status = status


class _PacoteDeNavegacaoFalso:
    """Pacote que `pagina.listen.wait` devolve dentro de `_navegar` — só carrega
    o status HTTP do documento, o único campo que `_navegar` lê."""

    def __init__(self, status: int) -> None:
        self.response = _RespostaDocumentoFalsa(status)


class _OpcoesDeNavegadorFalsas:
    """Dublê de `ChromiumOptions` — registra o que `_obter_pagina` configurou,
    sem subir Chromium."""

    instancias: list["_OpcoesDeNavegadorFalsas"] = []

    def __init__(self) -> None:
        self.user_agent_definido: str | None = None
        self.headless_definido: bool | None = None
        self.argumentos: list[str] = []
        _OpcoesDeNavegadorFalsas.instancias.append(self)

    def set_browser_path(self, caminho):
        return self

    def auto_port(self, *args, **kwargs):
        return self

    def headless(self, valor):
        self.headless_definido = valor
        return self

    def incognito(self, valor):
        return self

    def mute(self, valor):
        return self

    def set_user_agent(self, ua):
        self.user_agent_definido = ua
        return self

    def set_argument(self, argumento):
        self.argumentos.append(argumento)
        return self


# --- sanidade do dublê _PaginaFalsa (ajustes de dublê da Fatia D) -----------


def test_pagina_falsa_run_js_despacha_por_script():
    """O script de `user_agent()` devolve string; qualquer outro é o
    `_JS_CENTRO_DO_PLAYER` e devolve o par de coordenadas."""
    pagina = _PaginaFalsa([[]], ua_do_dom="UA-do-DOM/9.0")

    assert pagina.run_js("return navigator.userAgent") == "UA-do-DOM/9.0"
    assert pagina.run_js(modulo_cliente._JS_CENTRO_DO_PLAYER) == [640, 360]


def test_pagina_falsa_html_str_sempre_devolve_o_mesmo():
    pagina = _PaginaFalsa([[]], html="fixo")

    assert [pagina.html, pagina.html, pagina.html] == ["fixo", "fixo", "fixo"]


def test_pagina_falsa_html_sequencia_avanca_e_repete_o_ultimo():
    pagina = _PaginaFalsa([[]], html=["a", "b"])

    assert [pagina.html, pagina.html, pagina.html] == ["a", "b", "b"]


# --- _modo_headless -------------------------------------------------------------


@pytest.mark.parametrize(
    "valor, esperado",
    [
        ("1", True),
        ("headless", True),
        ("sim", True),
        ("0", False),
        ("false", False),
        ("FALSE", False),
        ("nao", False),
        ("não", False),
        ("  0  ", False),
    ],
)
def test_modo_headless_respeita_a_variavel_forcada(monkeypatch, valor, esperado):
    monkeypatch.setenv("SLIME_NAVEGADOR_HEADLESS", valor)

    assert modulo_cliente._modo_headless() is esperado


def test_modo_headless_sem_env_em_linux_sem_display_e_headless_com_aviso(monkeypatch, caplog):
    monkeypatch.delenv("SLIME_NAVEGADOR_HEADLESS", raising=False)
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setattr(sys, "platform", "linux")

    with caplog.at_level("WARNING", logger="extractors.cliente"):
        assert modulo_cliente._modo_headless() is True

    assert "sem servidor de display" in caplog.text


def test_modo_headless_sem_env_com_display_roda_visivel(monkeypatch):
    monkeypatch.delenv("SLIME_NAVEGADOR_HEADLESS", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setattr(sys, "platform", "linux")

    assert modulo_cliente._modo_headless() is False


def test_modo_headless_sem_env_fora_do_linux_roda_visivel(monkeypatch):
    monkeypatch.delenv("SLIME_NAVEGADOR_HEADLESS", raising=False)
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setattr(sys, "platform", "win32")

    assert modulo_cliente._modo_headless() is False


# --- _user_agent_override / ClienteNavegador.__init__ ----------------------


def test_user_agent_override_so_forca_no_headless():
    assert modulo_cliente._user_agent_override(True) == modulo_cliente._USER_AGENT_NAVEGADOR
    assert modulo_cliente._user_agent_override(False) is None


def test_cliente_navegador_respeita_headless_explicito(monkeypatch):
    def _nao_deve_chamar():
        raise AssertionError("_modo_headless não deve ser consultado com headless explícito")

    monkeypatch.setattr(modulo_cliente, "_modo_headless", _nao_deve_chamar)

    assert ClienteNavegador(headless=True)._headless is True
    assert ClienteNavegador(headless=False)._headless is False


def test_cliente_navegador_sem_argumento_consulta_o_ambiente(monkeypatch):
    sentinela = object()
    monkeypatch.setattr(modulo_cliente, "_modo_headless", lambda: sentinela)

    assert ClienteNavegador()._headless is sentinela


# --- user_agent() ---------------------------------------------------------------


def test_user_agent_sem_pagina_devolve_a_constante():
    cliente = ClienteNavegador(headless=True)

    assert cliente._pagina is None
    assert cliente.user_agent() == modulo_cliente._USER_AGENT_NAVEGADOR


def test_user_agent_le_do_dom_uma_vez_e_cacheia():
    cliente = ClienteNavegador(headless=True)
    pagina = _PaginaFalsa([[]], ua_do_dom="UA-de-teste/1.0")
    cliente._pagina = pagina

    assert cliente.user_agent() == "UA-de-teste/1.0"
    assert cliente.user_agent() == "UA-de-teste/1.0"
    assert pagina.leituras_de_ua == 1  # 2ª chamada veio do cache, sem reler o DOM


def test_user_agent_com_erro_de_dom_cai_na_constante_e_loga(caplog):
    cliente = ClienteNavegador(headless=True)
    pagina = _PaginaFalsa([[]], ua_do_dom=_ErroDrissionFalso("falha simulada ao ler o DOM"))
    cliente._pagina = pagina

    with caplog.at_level("WARNING", logger="extractors.cliente"):
        assert cliente.user_agent() == modulo_cliente._USER_AGENT_NAVEGADOR

    assert "UA real do DOM" in caplog.text
    assert cliente.user_agent() == modulo_cliente._USER_AGENT_NAVEGADOR  # cacheado
    assert pagina.leituras_de_ua == 1


# --- _obter_pagina: UA override só em headless -----------------------------


@pytest.mark.parametrize(
    "headless, ua_esperado",
    [(True, modulo_cliente._USER_AGENT_NAVEGADOR), (False, None)],
    ids=["headless", "visivel"],
)
def test_obter_pagina_forca_user_agent_apenas_no_modo_headless(monkeypatch, headless, ua_esperado):
    monkeypatch.setenv("SLIME_NAVEGADOR_BIN", "/usr/bin/navegador-de-teste")
    monkeypatch.setattr("DrissionPage.ChromiumOptions", _OpcoesDeNavegadorFalsas)
    monkeypatch.setattr("DrissionPage.ChromiumPage", lambda opcoes: opcoes)
    _OpcoesDeNavegadorFalsas.instancias = []

    ClienteNavegador(headless=headless)._obter_pagina()

    opcoes = _OpcoesDeNavegadorFalsas.instancias[-1]
    assert opcoes.headless_definido is headless
    assert opcoes.user_agent_definido == ua_esperado
    assert "--disable-blink-features=AutomationControlled" in opcoes.argumentos


# --- _tem_marcador_de_desafio (decisão D5) ---------------------------------


@pytest.mark.parametrize(
    "corpo",
    [
        "<title>Just a moment...</title>",
        "window._cf_chl_opt = {cvId: '3'};",
        '<script src="/cdn-cgi/challenge-platform/h/b/orchestrate/chl_page/v1"></script>',
    ],
)
def test_tem_marcador_de_desafio_reconhece_cada_marcador(corpo):
    assert modulo_cliente._tem_marcador_de_desafio(corpo) is True


def test_tem_marcador_de_desafio_ignora_o_titulo_localizado_sozinho():
    """D5: o título traduzido ("Um momento…") NÃO é marcador — só o caminho
    estrutural `/cdn-cgi/challenge-platform/` conta. Sem isso, qualquer página
    pt-BR com esse texto viraria falso positivo de desafio."""
    assert modulo_cliente._tem_marcador_de_desafio("<title>Um momento…</title>") is False
    assert (
        modulo_cliente._tem_marcador_de_desafio(
            "<title>Um momento…</title>"
            '<script src="/cdn-cgi/challenge-platform/h/b/orchestrate/chl_page/v1"></script>'
        )
        is True
    )


# --- _eh_desafio_cloudflare ----------------------------------------------------


def test_eh_desafio_cloudflare_reconhece_corpo_localizado_sem_just_a_moment():
    resposta = _RespostaHttpFalsa(
        text=(
            "<html><head>"
            '<script src="/cdn-cgi/challenge-platform/h/g/orchestrate/chl_page/v1"></script>'
            "</head><body>Um momento…</body></html>"
        )
    )

    assert modulo_cliente._eh_desafio_cloudflare(resposta) is True


def test_eh_desafio_cloudflare_reconhece_so_o_header_com_corpo_limpo():
    resposta = _RespostaHttpFalsa(
        headers={"cf-mitigated": "challenge"}, text="<html>conteúdo real</html>"
    )

    assert modulo_cliente._eh_desafio_cloudflare(resposta) is True


# --- _aguardar_desafio_cloudflare -----------------------------------------------


def test_aguardar_desafio_sem_marcador_retorna_false_sem_dormir(monkeypatch):
    dormidas: list[float] = []
    monkeypatch.setattr(modulo_cliente.time, "sleep", lambda s: dormidas.append(s))
    cliente = ClienteNavegador(headless=True)
    pagina = _PaginaFalsa([[]], html="<html>página comum, sem desafio</html>")

    resultado = cliente._aguardar_desafio_cloudflare(
        pagina, limite=modulo_cliente.time.monotonic() + 5
    )

    assert resultado is False
    assert dormidas == []


def test_aguardar_desafio_que_limpa_retorna_true_e_deixa_o_corpo_limpo(monkeypatch):
    monkeypatch.setattr(modulo_cliente, "_ESPERA_DESAFIO_S", 0.2)
    monkeypatch.setattr(modulo_cliente, "_INTERVALO_DESAFIO_S", 0.01)
    cliente = ClienteNavegador(headless=True)
    pagina = _PaginaFalsa(
        [[]],
        html=[
            '<script src="/cdn-cgi/challenge-platform/x"></script>',
            "<html>episódio real</html>",
        ],
    )

    resultado = cliente._aguardar_desafio_cloudflare(
        pagina, limite=modulo_cliente.time.monotonic() + modulo_cliente._ESPERA_DESAFIO_S
    )

    assert resultado is True
    assert "challenge-platform" not in pagina.html


def test_aguardar_desafio_que_nunca_limpa_retorna_true_com_warning(monkeypatch, caplog):
    monkeypatch.setattr(modulo_cliente, "_ESPERA_DESAFIO_S", 0.15)
    monkeypatch.setattr(modulo_cliente, "_INTERVALO_DESAFIO_S", 0.01)
    cliente = ClienteNavegador(headless=True)
    pagina = _PaginaFalsa([[]], html="<html>window._cf_chl_opt = {};</html>")

    with caplog.at_level("WARNING", logger="extractors.cliente"):
        resultado = cliente._aguardar_desafio_cloudflare(
            pagina, limite=modulo_cliente.time.monotonic() + modulo_cliente._ESPERA_DESAFIO_S
        )

    assert resultado is True
    assert "ainda presente" in caplog.text


# --- obter_html: armadilha D4 + desafio que não limpa ----------------------


def test_obter_html_sem_desafio_devolve_o_corpo(navegador_com):
    cliente, pagina = navegador_com(
        lotes=[[_PacoteDeNavegacaoFalso(200)]],
        html="<html><body>episódio</body></html>",
    )

    resultado = cliente.obter_html("https://animesdrive.online/episodio/x", timeout_s=5)

    assert resultado == "<html><body>episódio</body></html>"
    assert pagina.navegou == ["https://animesdrive.online/episodio/x"]


def test_obter_html_com_desafio_que_limpa_nao_rejeita(navegador_com, monkeypatch):
    """Regressão D4: `_navegar` observou 403 na interstitial, mas o auto-solve do
    Turnstile recarregou a página real. A decisão tem de cair no corpo já limpo,
    não no status 403 da tela de desafio."""
    monkeypatch.setattr(modulo_cliente, "_ESPERA_DESAFIO_S", 0.2)
    monkeypatch.setattr(modulo_cliente, "_INTERVALO_DESAFIO_S", 0.01)
    cliente, _ = navegador_com(
        lotes=[[_PacoteDeNavegacaoFalso(403)]],
        html=[
            '<html><script src="/cdn-cgi/challenge-platform/x"></script>Um momento…</html>',
            "<html><body>conteúdo do episódio</body></html>",
        ],
    )

    resultado = cliente.obter_html("https://animesdrive.online/episodio/x", timeout_s=5)

    assert resultado == "<html><body>conteúdo do episódio</body></html>"


def test_obter_html_com_desafio_que_nunca_limpa_levanta_sessao_rejeitada(
    navegador_com, monkeypatch
):
    monkeypatch.setattr(modulo_cliente, "_ESPERA_DESAFIO_S", 0.15)
    monkeypatch.setattr(modulo_cliente, "_INTERVALO_DESAFIO_S", 0.01)
    cliente, _ = navegador_com(
        lotes=[[_PacoteDeNavegacaoFalso(403)]],
        html="<html><script src='/cdn-cgi/challenge-platform/x'></script>bloqueado</html>",
    )

    with pytest.raises(SessaoRejeitada) as excinfo:
        cliente.obter_html("https://animesdrive.online/episodio/x", timeout_s=5)

    assert "animesdrive.online/episodio/x" in str(excinfo.value)


# --- capturar_midia: desafio que não limpa + caminho feliz preservado -----


def test_capturar_midia_com_desafio_que_nao_limpa_levanta_sessao_rejeitada(
    navegador_com, monkeypatch
):
    """Sem o corte, a captura gastaria a janela inteira clicando na interstitial
    e terminaria com 'nenhuma URL de mídia utilizável' — mensagem enganosa pro
    que aconteceu de fato."""
    monkeypatch.setattr(modulo_cliente, "_ESPERA_DESAFIO_S", 0.15)
    monkeypatch.setattr(modulo_cliente, "_INTERVALO_DESAFIO_S", 0.01)
    cliente, _ = navegador_com(
        [_PacoteFalso("https://cdn.exemplo/01.mp4")],
        html="<html><script src='/cdn-cgi/challenge-platform/x'></script>bloqueado</html>",
    )

    with pytest.raises(SessaoRejeitada) as excinfo:
        cliente.capturar_midia("https://animesdrive.online/episodio/x", timeout_s=5)

    assert "animesdrive.online/episodio/x" in str(excinfo.value)


def test_capturar_midia_sem_desafio_segue_o_fluxo_normal(navegador_com):
    """A espera de desafio da Fatia B devolve na hora quando o corpo não tem
    marcador (default do dublê) — a captura procede como antes."""
    cliente, pagina = navegador_com([_PacoteFalso("https://cdn.exemplo/01.mp4")])

    capturada = cliente.capturar_midia("https://animesdrive.online/episodio/x", timeout_s=5)

    assert capturada.url == "https://cdn.exemplo/01.mp4"
    assert pagina.navegou == ["https://animesdrive.online/episodio/x"]

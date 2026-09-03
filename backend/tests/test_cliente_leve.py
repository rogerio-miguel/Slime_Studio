"""Testes de `extractors/cliente.py::ClienteLeve` sem rede — a sessão
`cloudscraper` é trocada por um dublê que devolve uma resposta (ou levanta uma
exceção de `requests`) pré-programada.

O foco é a tradução de erro compartilhada por GET e POST (`_requisitar`): 404,
desafio Cloudflare e falha de transporte têm de virar a mesma exceção de domínio
seja qual for o método. O que toca rede real é o smoke test
(`test_smoke_scrapers.py`, marcador `rede`)."""

import pytest
import requests

from core.erros import FalhaDeExtracao, FonteNaoEncontrada, SessaoRejeitada
from extractors.cliente import ClienteComPost, ClienteLeve, ClienteNavegador


class _RespostaFalsa:
    def __init__(
        self, *, status_code: int = 200, text: str = "", headers: dict[str, str] | None = None
    ) -> None:
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}

    @property
    def ok(self) -> bool:
        return self.status_code < 400


class _SessaoFalsa:
    """`get`/`post` devolvem `resultado` (ou o levantam, se for exceção) e
    registram a chamada em `self.chamadas` para inspeção."""

    def __init__(self, resultado: _RespostaFalsa | BaseException) -> None:
        self._resultado = resultado
        self.chamadas: list[tuple[str, str, dict]] = []

    def get(self, url: str, **kwargs) -> _RespostaFalsa:
        return self._responder("GET", url, kwargs)

    def post(self, url: str, **kwargs) -> _RespostaFalsa:
        return self._responder("POST", url, kwargs)

    def _responder(self, metodo: str, url: str, kwargs: dict) -> _RespostaFalsa:
        self.chamadas.append((metodo, url, kwargs))
        if isinstance(self._resultado, BaseException):
            raise self._resultado
        return self._resultado


@pytest.fixture
def cliente_leve_com(monkeypatch):
    """Fábrica de `(ClienteLeve, _SessaoFalsa)` — `cloudscraper.create_scraper` é
    trocado por uma fábrica do dublê, então nenhuma sessão real sobe (mesmo
    motivo de `test_resolucao.py` não tocar `cloudscraper`)."""

    def _montar(
        resultado: _RespostaFalsa | BaseException,
    ) -> tuple[ClienteLeve, _SessaoFalsa]:
        sessao = _SessaoFalsa(resultado)
        monkeypatch.setattr(
            "extractors.cliente.cloudscraper.create_scraper", lambda **_: sessao
        )
        return ClienteLeve(), sessao

    return _montar


def test_postar_formulario_faz_post_com_data_e_devolve_o_texto(cliente_leve_com):
    cli, sessao = cliente_leve_com(_RespostaFalsa(text="RESPOSTA-RPC"))

    resultado = cli.postar_formulario(
        "https://blogger/rpc", {"f.req": "[[[x]]]"}, timeout_s=7
    )

    assert resultado == "RESPOSTA-RPC"
    metodo, url, kwargs = sessao.chamadas[0]
    assert (metodo, url) == ("POST", "https://blogger/rpc")
    assert kwargs["data"] == {"f.req": "[[[x]]]"}
    assert kwargs["timeout"] == 7


def test_obter_html_continua_indo_por_get(cliente_leve_com):
    cli, sessao = cliente_leve_com(_RespostaFalsa(text="<html>ok</html>"))

    assert cli.obter_html("https://x", timeout_s=5) == "<html>ok</html>"
    assert sessao.chamadas[0][0] == "GET"


@pytest.mark.parametrize("operacao", ["get", "post"])
@pytest.mark.parametrize(
    ("resultado", "excecao"),
    [
        (_RespostaFalsa(status_code=404), FonteNaoEncontrada),
        (_RespostaFalsa(status_code=403, text="Just a moment"), SessaoRejeitada),
        (_RespostaFalsa(status_code=503, text="cf_chl_opt"), SessaoRejeitada),
        (_RespostaFalsa(status_code=500), FalhaDeExtracao),
        (requests.Timeout("estourou"), FalhaDeExtracao),
        (requests.ConnectionError("recusada"), FalhaDeExtracao),
    ],
)
def test_get_e_post_traduzem_erro_pela_mesma_regra(cliente_leve_com, operacao, resultado, excecao):
    cli, _ = cliente_leve_com(resultado)

    with pytest.raises(excecao):
        if operacao == "get":
            cli.obter_html("https://x/y", timeout_s=5)
        else:
            cli.postar_formulario("https://x/y", {"a": "b"}, timeout_s=5)


def test_403_sem_marcador_de_desafio_nao_e_sessao_rejeitada(cliente_leve_com):
    cli, _ = cliente_leve_com(_RespostaFalsa(status_code=403, text="forbidden"))

    with pytest.raises(FalhaDeExtracao) as info:
        cli.postar_formulario("https://x/y", {"a": "b"}, timeout_s=5)
    assert not isinstance(info.value, SessaoRejeitada)


def test_capacidade_de_post_e_exclusiva_do_cliente_leve(monkeypatch):
    monkeypatch.setattr(
        "extractors.cliente.cloudscraper.create_scraper", lambda **_: object()
    )
    assert isinstance(ClienteLeve(), ClienteComPost)
    assert not isinstance(ClienteNavegador(), ClienteComPost)

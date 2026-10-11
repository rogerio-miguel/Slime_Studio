"""Testes de `fontes/rede/rede_segura.py` — sem rede: `resolver_dns` e `requests.get` são
substituídos."""

import pytest
import requests

from fontes.rede import rede_segura
from fontes.rede.rede_segura import DestinoNaoPermitido, get_validando_redirects, validar_destino


def _dns(monkeypatch, ips_por_host: dict[str, list[str]]):
    monkeypatch.setattr(rede_segura, "resolver_dns", lambda host: ips_por_host.get(host, []))


class _Resposta:
    def __init__(self, status_code: int, location: str | None = None):
        self.status_code = status_code
        self.headers = {"Location": location} if location else {}
        self.fechada = False

    def close(self):
        self.fechada = True


# --- validar_destino: DNS ---------------------------------------------------


@pytest.mark.parametrize("ip", ["127.0.0.1", "10.0.0.5", "169.254.169.254", "192.168.0.9", "::1"])
def test_nome_que_resolve_para_ip_interno_e_rejeitado(monkeypatch, ip: str):
    _dns(monkeypatch, {"cdn.exemplo": [ip]})

    with pytest.raises(DestinoNaoPermitido) as erro:
        validar_destino("https://cdn.exemplo/v.mp4")

    assert erro.value.permite_retentativa is False


def test_nome_com_um_ip_publico_e_um_interno_e_rejeitado(monkeypatch):
    _dns(monkeypatch, {"cdn.exemplo": ["93.184.216.34", "127.0.0.1"]})

    with pytest.raises(DestinoNaoPermitido):
        validar_destino("https://cdn.exemplo/v.mp4")


def test_nome_que_resolve_para_ip_publico_passa(monkeypatch):
    _dns(monkeypatch, {"cdn.exemplo": ["93.184.216.34"]})

    validar_destino("https://cdn.exemplo/v.mp4")


def test_nome_que_nao_resolve_passa_e_falha_na_requisicao(monkeypatch):
    _dns(monkeypatch, {})

    validar_destino("https://nao-existe.exemplo/v.mp4")


def test_ip_literal_nao_consulta_dns(monkeypatch):
    def _nao_deveria_ser_chamado(host):
        raise AssertionError("DNS consultado para IP literal")

    monkeypatch.setattr(rede_segura, "resolver_dns", _nao_deveria_ser_chamado)

    with pytest.raises(DestinoNaoPermitido):
        validar_destino("http://127.0.0.1/x")
    validar_destino("http://93.184.216.34/x")


# --- get_validando_redirects -------------------------------------------------


def _get_falso(monkeypatch, respostas: dict[str, _Resposta]):
    chamadas: list[dict] = []

    def _get(url, **kwargs):
        chamadas.append({"url": url, **kwargs})
        return respostas[url]

    monkeypatch.setattr(rede_segura.requests, "get", _get)
    return chamadas


def test_sem_redirect_devolve_a_resposta_e_nao_segue_sozinho(monkeypatch):
    final = _Resposta(200)
    chamadas = _get_falso(monkeypatch, {"https://cdn.exemplo/v.mp4": final})

    resposta = get_validando_redirects(
        "https://cdn.exemplo/v.mp4", headers={"Referer": "r"}, timeout=5, stream=True
    )

    assert resposta is final
    assert chamadas == [
        {
            "url": "https://cdn.exemplo/v.mp4",
            "headers": {"Referer": "r"},
            "timeout": 5,
            "stream": True,
            "allow_redirects": False,
        }
    ]


def test_segue_redirect_relativo_e_repassa_cabecalhos_em_cada_salto(monkeypatch):
    final = _Resposta(200)
    salto = _Resposta(302, "/outro/v.mp4")
    chamadas = _get_falso(
        monkeypatch,
        {"https://cdn.exemplo/v.mp4": salto, "https://cdn.exemplo/outro/v.mp4": final},
    )

    resposta = get_validando_redirects(
        "https://cdn.exemplo/v.mp4", headers={"Referer": "r"}, timeout=5
    )

    assert resposta is final
    assert salto.fechada is True
    assert [c["headers"] for c in chamadas] == [{"Referer": "r"}, {"Referer": "r"}]


def test_redirect_para_ip_interno_e_barrado_antes_da_requisicao(monkeypatch):
    chamadas = _get_falso(
        monkeypatch, {"https://cdn.exemplo/v.mp4": _Resposta(302, "http://127.0.0.1:8000/admin")}
    )

    with pytest.raises(DestinoNaoPermitido):
        get_validando_redirects("https://cdn.exemplo/v.mp4", headers={}, timeout=5)

    assert [c["url"] for c in chamadas] == ["https://cdn.exemplo/v.mp4"]


def test_redirect_para_nome_que_resolve_para_ip_interno_e_barrado(monkeypatch):
    _dns(monkeypatch, {"cdn.exemplo": ["93.184.216.34"], "interno.exemplo": ["10.0.0.5"]})
    _get_falso(
        monkeypatch, {"https://cdn.exemplo/v.mp4": _Resposta(301, "https://interno.exemplo/x")}
    )

    with pytest.raises(DestinoNaoPermitido):
        get_validando_redirects("https://cdn.exemplo/v.mp4", headers={}, timeout=5)


def test_redirect_para_esquema_file_e_barrado(monkeypatch):
    _get_falso(monkeypatch, {"https://cdn.exemplo/v.mp4": _Resposta(302, "file:///etc/passwd")})

    with pytest.raises(DestinoNaoPermitido):
        get_validando_redirects("https://cdn.exemplo/v.mp4", headers={}, timeout=5)


def test_redirect_sem_location_levanta_erro_de_requests(monkeypatch):
    _get_falso(monkeypatch, {"https://cdn.exemplo/v.mp4": _Resposta(302)})

    with pytest.raises(requests.RequestException):
        get_validando_redirects("https://cdn.exemplo/v.mp4", headers={}, timeout=5)


def test_redirects_demais_levantam_too_many_redirects(monkeypatch):
    _get_falso(monkeypatch, {"https://cdn.exemplo/v.mp4": _Resposta(302, "/v.mp4")})

    with pytest.raises(requests.TooManyRedirects):
        get_validando_redirects("https://cdn.exemplo/v.mp4", headers={}, timeout=5)

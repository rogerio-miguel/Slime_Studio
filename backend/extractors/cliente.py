"""Cliente HTTP para extratores de site (ESPECIFICACAO.md §3A).

`ClienteDeSite` é `Protocol` (colaborador estrutural que os adapters recebem
por injeção, não hierarquia — D2/D3 do plano) — `ClienteLeve` e
`ClienteNavegador` implementam o mesmo contrato sem herdar nada em comum.

Este módulo é a **única** fronteira onde exceção de `requests`/`cloudscraper`
pode existir: tudo que sai daqui já é `FalhaDeExtracao` (ou subclasse) —
nenhum chamador precisa saber o que é `requests.Timeout`.
"""

from typing import Protocol

import cloudscraper
import requests

from core.erros import FalhaDeExtracao, FonteNaoEncontrada, SessaoRejeitada

# Marcadores de desafio Cloudflare ainda em curso (ESPECIFICACAO.md §9, linha do
# risco "sessão de bypass expirada"): header `cf-mitigated`, `<title>Just a
# moment` e o parâmetro `cf_chl_opt` do script de verificação.
_MARCADOR_HEADER_CLOUDFLARE = "cf-mitigated"
_MARCADORES_CORPO_CLOUDFLARE = ("Just a moment", "cf_chl_opt")


class ClienteDeSite(Protocol):
    """Contrato estrutural que os adapters (`ExtratorDeSite`) recebem por injeção."""

    def obter_html(self, url: str, *, timeout_s: int) -> str: ...
    def obter_json(self, url: str, *, timeout_s: int) -> dict | list: ...
    def cookies(self) -> dict[str, str]: ...
    def user_agent(self) -> str: ...


class ClienteLeve:
    """Sessão `cloudscraper` pré-carregada com cookies de `SessaoBypass`, se houver."""

    def __init__(
        self, *, cookies: dict[str, str] | None = None, user_agent: str | None = None
    ) -> None:
        self._sessao = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "windows", "desktop": True}
        )
        if cookies:
            self._sessao.cookies.update(cookies)
        if user_agent:
            self._sessao.headers["User-Agent"] = user_agent

    def obter_html(self, url: str, *, timeout_s: int) -> str:
        resposta = self._requisitar(url, timeout_s=timeout_s)
        return resposta.text

    def obter_json(self, url: str, *, timeout_s: int) -> dict | list:
        resposta = self._requisitar(url, timeout_s=timeout_s)
        try:
            return resposta.json()
        except requests.JSONDecodeError as excecao:
            raise FalhaDeExtracao(
                f"resposta de {url} não é JSON válido", permite_retentativa=True
            ) from excecao

    def cookies(self) -> dict[str, str]:
        return self._sessao.cookies.get_dict()

    def user_agent(self) -> str:
        return self._sessao.headers.get("User-Agent", "")

    def _requisitar(self, url: str, *, timeout_s: int) -> requests.Response:
        try:
            resposta = self._sessao.get(url, timeout=timeout_s)
        except (requests.ConnectionError, requests.Timeout) as excecao:
            raise FalhaDeExtracao(
                f"falha de rede ao acessar {url}: {excecao}", permite_retentativa=True
            ) from excecao
        except requests.RequestException as excecao:
            raise FalhaDeExtracao(
                f"falha ao acessar {url}: {excecao}", permite_retentativa=True
            ) from excecao

        if resposta.status_code == 404:
            raise FonteNaoEncontrada(f"não encontrado: {url}")
        if resposta.status_code in (403, 503) and _eh_desafio_cloudflare(resposta):
            raise SessaoRejeitada(f"sessão rejeitada (desafio Cloudflare) em {url}")
        if not resposta.ok:
            raise FalhaDeExtracao(
                f"HTTP {resposta.status_code} em {url}", permite_retentativa=True
            )
        return resposta


class ClienteNavegador:
    """Stub — a implementação via navegador completo (DrissionPage) chega na etapa 2B.

    A interface nasce completa para que `resiliencia.chamar` já saiba escalar
    para cá quando `SessaoRejeitada` acontece; hoje qualquer chamada falha de
    propósito, sem retentativa.
    """

    _MENSAGEM = "cliente de navegador indisponível até a etapa 2B"

    def obter_html(self, url: str, *, timeout_s: int) -> str:
        raise FalhaDeExtracao(self._MENSAGEM, permite_retentativa=False)

    def obter_json(self, url: str, *, timeout_s: int) -> dict | list:
        raise FalhaDeExtracao(self._MENSAGEM, permite_retentativa=False)

    def cookies(self) -> dict[str, str]:
        raise FalhaDeExtracao(self._MENSAGEM, permite_retentativa=False)

    def user_agent(self) -> str:
        raise FalhaDeExtracao(self._MENSAGEM, permite_retentativa=False)


def _eh_desafio_cloudflare(resposta: requests.Response) -> bool:
    if _MARCADOR_HEADER_CLOUDFLARE in resposta.headers:
        return True
    corpo = resposta.text
    return any(marcador in corpo for marcador in _MARCADORES_CORPO_CLOUDFLARE)

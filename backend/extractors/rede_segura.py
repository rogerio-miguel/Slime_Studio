"""Validação de destino para URL de mídia vinda de scraping (SSRF): esquema http(s), host
que não seja `localhost`/IP não público, e nome DNS que não resolva pra IP não público.
`get_validando_redirects` faz o GET revalidando cada salto — `requests` seguiria o
redirect sozinho, sem olhar pra onde ele aponta.

Limite conhecido: a checagem de DNS é "verifica e depois usa" — o `requests` (e, mais
ainda, o `ffmpeg`/`yt-dlp`, que resolvem por conta própria) faz outro lookup depois.
Fixar o IP validado na conexão fecharia a janela de DNS rebinding, mas só cobriria as
chamadas `requests`; por isso não foi feito.

Depende só de `core.erros` (não importa `extractors.download`/`cliente`), pra os dois
poderem usá-lo sem import circular.
"""

import ipaddress
import socket
import urllib.parse

import requests

from core.erros import FalhaDeExtracao

_MAX_SALTOS = 5
_STATUS_DE_REDIRECT = frozenset({301, 302, 303, 307, 308})


class DestinoNaoPermitido(FalhaDeExtracao):
    """Definitivo (`permite_retentativa=False`): repetir não muda pra onde a URL aponta."""

    def __init__(self, mensagem: str) -> None:
        super().__init__(mensagem, permite_retentativa=False)


def resolver_dns(hostname: str) -> list[str]:
    """IPs de `hostname`, ou `[]` se não resolve (aí a requisição falha sozinha, com o
    erro de rede de sempre). Ponto único de DNS, substituível em teste."""
    try:
        informacoes = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return []
    return sorted({informacao[4][0].split("%")[0] for informacao in informacoes})


def _ip_nao_publico(texto: str) -> bool:
    endereco = ipaddress.ip_address(texto)
    if isinstance(endereco, ipaddress.IPv6Address) and endereco.ipv4_mapped is not None:
        endereco = endereco.ipv4_mapped
    return not endereco.is_global


def validar_destino(url: str) -> None:
    """Levanta `DestinoNaoPermitido` se `url` não é um destino externo. Faz DNS bloqueante:
    de código `async`, chame via `asyncio.to_thread`."""
    partes = urllib.parse.urlparse(url)
    hostname = partes.hostname
    if partes.scheme not in ("http", "https") or not hostname:
        raise DestinoNaoPermitido(f"URL de mídia com esquema ou host inválido: {url}")
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise DestinoNaoPermitido(f"URL de mídia aponta para host interno: {url}")
    try:
        ipaddress.ip_address(hostname)
        enderecos = [hostname]
    except ValueError:
        enderecos = resolver_dns(hostname)
    if any(_ip_nao_publico(endereco) for endereco in enderecos):
        raise DestinoNaoPermitido(f"URL de mídia aponta para host interno: {url}")


def get_validando_redirects(
    url: str, *, headers: dict[str, str], timeout: float, stream: bool = False
) -> requests.Response:
    """GET que valida `url` e cada `Location` (até `_MAX_SALTOS`) antes de segui-los.
    Os cabeçalhos (incluindo `Cookie`, se houver) vão em todos os saltos, como o
    `requests` já fazia. Levanta `DestinoNaoPermitido` num destino interno e
    `requests.TooManyRedirects` no excesso."""
    atual = url
    for _ in range(_MAX_SALTOS + 1):
        validar_destino(atual)
        resposta = requests.get(
            atual, headers=headers, timeout=timeout, stream=stream, allow_redirects=False
        )
        if resposta.status_code not in _STATUS_DE_REDIRECT:
            return resposta
        destino = resposta.headers.get("Location")
        resposta.close()
        if not destino:
            raise requests.RequestException(f"redirect sem Location em {atual}")
        atual = urllib.parse.urljoin(atual, destino)
    raise requests.TooManyRedirects(f"mais de {_MAX_SALTOS} redirects a partir de {url}")

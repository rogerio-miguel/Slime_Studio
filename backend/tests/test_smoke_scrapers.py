"""Smoke test por scraper (ESPECIFICACAO.md §7) — verifica periodicamente se cada
extrator ainda consegue localizar o link de um episódio real, sem esperar até um
job falhar em produção pra descobrir que o site mudou.

`@pytest.mark.rede`: toca rede real de propósito — desselecionado por padrão
(`addopts = ["-m", "not rede"]`, `pyproject.toml`). É diagnóstico manual, não gate
de CI. O smoke do AnimesDrive vai além e sobe um Chromium de verdade
(`ClienteNavegador`): `resolver_midia` de lá não existe sem navegador
(`exige_navegador_para_midia`), então não há como cobrir essa ponta sem um. Segue
sob o mesmo marcador porque a distinção que importa é a mesma — diagnóstico
manual, nunca CI.

Título de referência do AnimeFire: "One Piece" (`one-piece`) — série longa em
exibição, baixo risco de sumir do catálogo e virar fixture instável. Mesmo
título usado como referência do AnimesDrive, pelo mesmo motivo.

Desde a Fatia D do bypass de Cloudflare, `ClienteNavegador()` sobe o Chromium em
**janela visível** por padrão (só GUI + UA nativo limpa o Turnstile) — rode este
diagnóstico num ambiente gráfico, ou force `SLIME_NAVEGADOR_HEADLESS=1` (ciente
de que headless não resolve o desafio).
"""

import pytest

from extractors.animefire import AnimeFireProvider
from extractors.animesdrive import AnimesDriveProvider
from extractors.cliente import ClienteLeve, ClienteNavegador

pytestmark = pytest.mark.rede

_IDENTIFICADOR_REFERENCIA = "one-piece"
# Identificador cujo slug de episódio **não** é derivável dele
# (`/episodio/one-piece-dublado-episodio-N`) — o caso que o filtro por prefixo
# do adapter quebrava.
_IDENTIFICADOR_SLUG_DIVERGENTE = "one-piece-dublado-todos-os-episodios"
_EPISODIO_REFERENCIA_COM_PLAYER = (
    "https://animesdrive.cloud/episodio/solo-leveling-dublado-episodio-01"
)


def test_animefire_localiza_link_de_um_episodio_real():
    provider = AnimeFireProvider()
    cliente = ClienteLeve()

    resultados = provider.buscar(cliente, "One Piece")
    assert any(r.identificador == _IDENTIFICADOR_REFERENCIA for r in resultados)

    episodios = provider.listar_episodios(cliente, _IDENTIFICADOR_REFERENCIA)
    assert len(episodios) > 1000
    assert episodios[0].numero == 1  # mais antigo primeiro

    midia = provider.resolver_midia(cliente, episodios[0].url)
    assert midia.url
    assert "Referer" in midia.cabecalhos


def test_animesdrive_localiza_link_de_um_episodio_real():
    provider = AnimesDriveProvider()
    cliente = ClienteLeve()
    try:
        resultados = provider.buscar(cliente, "One Piece")
        assert any(r.identificador == _IDENTIFICADOR_REFERENCIA for r in resultados)

        episodios = provider.listar_episodios(cliente, _IDENTIFICADOR_REFERENCIA)
        assert episodios[0].numero == 1  # trava a ordem real
    finally:
        cliente.fechar()


def test_animesdrive_resolve_midia_com_navegador():
    """Episódio fixo, não `episodios[0]` do teste acima: nem todo episódio do
    AnimesDrive é resolvível hoje — tem página sem iframe nenhum
    (`one-piece-episodio-01`) e tem página cujas origens de mídia respondem 404
    (`tensei-shitara-slime-datta-ken-3-episodio-01`, as duas mortas). Cair num
    desses testaria o caminho de erro achando que testa o de sucesso. Este aqui
    foi conferido resolvendo de ponta a ponta (2026-08-17), temporada encerrada,
    baixo risco de mudar."""
    provider = AnimesDriveProvider()
    navegador = ClienteNavegador()
    try:
        midia = provider.resolver_midia(navegador, _EPISODIO_REFERENCIA_COM_PLAYER)
    finally:
        navegador.fechar()

    assert midia.url.startswith("http")
    assert midia.cabecalhos["User-Agent"]


def test_animesdrive_lista_episodios_com_slug_divergente_do_identificador():
    """Regressão ao vivo do filtro por prefixo: este anime lista episódios com
    slug `one-piece-dublado`, que não começa com o identificador dele — o filtro
    antigo descartava todos e a listagem inteira quebrava."""
    provider = AnimesDriveProvider()
    cliente = ClienteLeve()
    try:
        episodios = provider.listar_episodios(cliente, _IDENTIFICADOR_SLUG_DIVERGENTE)
    finally:
        cliente.fechar()

    assert len(episodios) > 100
    assert all("/episodio/one-piece-dublado-episodio-" in ep.url for ep in episodios)

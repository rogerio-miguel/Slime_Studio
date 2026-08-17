"""Testes de parsing de `extractors/animefire.py`, sem rede — `ClienteFalso`
devolve fixtures HTML/JSON escritas à mão em `tests/fixtures/animefire/`."""

import json
from pathlib import Path

import pytest
from conftest import ClienteFalso

from core.erros import EstruturaDoSiteMudou, FonteNaoEncontrada
from extractors.animefire import AnimeFireProvider
from extractors.base import EpisodioRemoto, LinkDeMidia, ResultadoBusca

_FIXTURES = Path(__file__).parent / "fixtures" / "animefire"


def _ler_fixture(nome: str) -> str:
    return (_FIXTURES / nome).read_text(encoding="utf-8")


@pytest.fixture
def extrator() -> AnimeFireProvider:
    return AnimeFireProvider()


class _ClienteQueDevolve404:
    """Fake mínimo de `ClienteDeSite` que simula HTTP 404 (`FonteNaoEncontrada`)
    — `ClienteFalso` (conftest.py) só devolve HTML pré-programado, nunca
    levanta exceção, então não serve pra este caso."""

    def obter_html(self, url: str, *, timeout_s: int) -> str:
        raise FonteNaoEncontrada(f"não encontrado: {url}")

    def obter_json(self, url: str, *, timeout_s: int) -> dict | list:
        raise AssertionError("não deveria ser chamado")

    def cookies(self) -> dict[str, str]:
        return {}

    def user_agent(self) -> str:
        return "ClienteFalso/1.0"


def test_buscar_com_resultado_devolve_candidatos(extrator):
    url_busca = f"{extrator.BASE_URL}/pesquisar/tensei-shitara-slime-datta-ken"
    cliente = ClienteFalso(html_por_url={url_busca: _ler_fixture("busca.html")})

    resultados = extrator.buscar(cliente, "Tensei Shitara Slime Datta Ken")

    assert resultados == [
        ResultadoBusca(
            titulo_exibicao="Tensei Shitara Slime Datta Ken",
            identificador="tensei-shitara-slime-datta-ken",
            url=f"{extrator.BASE_URL}/animes/tensei-shitara-slime-datta-ken-todos-os-episodios",
        ),
        ResultadoBusca(
            titulo_exibicao="Tensei Shitara Slime Datta Ken 2",
            identificador="tensei-shitara-slime-datta-ken-2",
            url=f"{extrator.BASE_URL}/animes/tensei-shitara-slime-datta-ken-2-todos-os-episodios",
        ),
    ]


def test_buscar_resultados_nao_tem_capa_url(extrator):
    """AnimeFire não expõe imagem nenhuma na página de busca (confirmado ao
    vivo e no código de referência Slime_Shell_Web) — documenta que
    `capa_url` sai `None` de propósito, não por parsing esquecido.
    Enriquecimento por metadado de provedor externo mora em
    `api/servicos/busca.py::enriquecer_capas`."""
    url_busca = f"{extrator.BASE_URL}/pesquisar/tensei-shitara-slime-datta-ken"
    cliente = ClienteFalso(html_por_url={url_busca: _ler_fixture("busca.html")})

    resultados = extrator.buscar(cliente, "Tensei Shitara Slime Datta Ken")

    assert resultados
    assert all(resultado.capa_url is None for resultado in resultados)


def test_buscar_sem_resultado_devolve_lista_vazia(extrator):
    url_busca = f"{extrator.BASE_URL}/pesquisar/anime-inexistente"
    cliente = ClienteFalso(html_por_url={url_busca: _ler_fixture("busca_vazia.html")})

    assert extrator.buscar(cliente, "Anime Inexistente") == []


def test_buscar_404_devolve_lista_vazia_sem_levantar_excecao(extrator):
    resultados = extrator.buscar(_ClienteQueDevolve404(), "Anime Inexistente")

    assert resultados == []


def test_listar_episodios_deduplica_ordena_e_ignora_nao_numerico(extrator):
    identificador = "tensei-shitara-slime-datta-ken"
    url_anime = f"{extrator.BASE_URL}/animes/{identificador}-todos-os-episodios"
    cliente = ClienteFalso(html_por_url={url_anime: _ler_fixture("episodios.html")})

    episodios = extrator.listar_episodios(cliente, identificador)

    assert episodios == [
        EpisodioRemoto(numero=1, url=f"{extrator.BASE_URL}/animes/{identificador}/1"),
        EpisodioRemoto(numero=2, url=f"{extrator.BASE_URL}/animes/{identificador}/2"),
        EpisodioRemoto(numero=3, url=f"{extrator.BASE_URL}/animes/{identificador}/3"),
    ]


def test_listar_episodios_vazio_levanta_estrutura_do_site_mudou(extrator):
    identificador = "anime-sem-episodios"
    url_anime = f"{extrator.BASE_URL}/animes/{identificador}-todos-os-episodios"
    cliente = ClienteFalso(html_por_url={url_anime: "<html><body></body></html>"})

    with pytest.raises(EstruturaDoSiteMudou):
        extrator.listar_episodios(cliente, identificador)


def test_resolver_midia_pega_ultimo_item_da_lista(extrator):
    url_episodio = f"{extrator.BASE_URL}/animes/tensei-shitara-slime-datta-ken/1"
    url_json = "https://animefire.io/video/abc123/data.json"
    cliente = ClienteFalso(
        html_por_url={url_episodio: _ler_fixture("episodio.html")},
        json_por_url={url_json: json.loads(_ler_fixture("midia.json"))},
    )

    link = extrator.resolver_midia(cliente, url_episodio)

    assert link == LinkDeMidia(
        url="https://cdn.animefire.io/videos/abc123-hd.mp4",
        cabecalhos={"Referer": url_episodio, "User-Agent": "ClienteFalso/1.0"},
    )


def test_resolver_midia_sem_video_tag_levanta_estrutura_do_site_mudou(extrator):
    url_episodio = f"{extrator.BASE_URL}/animes/tensei-shitara-slime-datta-ken/1"
    cliente = ClienteFalso(html_por_url={url_episodio: _ler_fixture("episodio_sem_video.html")})

    with pytest.raises(EstruturaDoSiteMudou):
        extrator.resolver_midia(cliente, url_episodio)


def test_resolver_midia_com_data_nao_lista_levanta_estrutura_do_site_mudou(extrator):
    url_episodio = f"{extrator.BASE_URL}/animes/tensei-shitara-slime-datta-ken/1"
    url_json = "https://animefire.io/video/abc123/data.json"
    cliente = ClienteFalso(
        html_por_url={url_episodio: _ler_fixture("episodio.html")},
        json_por_url={url_json: {"data": {"src": "https://cdn.animefire.io/videos/abc123-hd.mp4"}}},
    )

    with pytest.raises(EstruturaDoSiteMudou):
        extrator.resolver_midia(cliente, url_episodio)

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


class _ClienteComExcecoes404:
    """Fake de `ClienteDeSite`: URLs em `html_por_url` respondem com o HTML
    programado, qualquer outra URL simula HTTP 404 (`FonteNaoEncontrada`) —
    `ClienteFalso` (conftest.py) não serve pra isso porque levanta
    `AssertionError` em vez de simular 404 numa URL não mapeada."""

    def __init__(self, html_por_url: dict[str, str] | None = None) -> None:
        self._html_por_url = html_por_url or {}

    def obter_html(self, url: str, *, timeout_s: int) -> str:
        if url in self._html_por_url:
            return self._html_por_url[url]
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
    resultados = extrator.buscar(_ClienteComExcecoes404(), "Anime Inexistente")

    assert resultados == []


def test_buscar_titulo_com_subtitulo_cai_para_principal_quando_completo_vazio(extrator):
    """AnimeFire casa busca por prefixo do título principal — um subtítulo
    depois de ':' zera o resultado mesmo pra um anime que existe no site
    (confirmado ao vivo contra animefire.io). `buscar` cai pro título truncado
    antes do separador como 2º candidato."""
    titulo = "Anime Principal: Subtitulo Aqui"
    url_completo = f"{extrator.BASE_URL}/pesquisar/anime-principal-subtitulo-aqui"
    url_truncado = f"{extrator.BASE_URL}/pesquisar/anime-principal"
    cliente = ClienteFalso(
        html_por_url={
            url_completo: _ler_fixture("busca_vazia.html"),
            url_truncado: _ler_fixture("busca.html"),
        }
    )

    resultados = extrator.buscar(cliente, titulo)

    assert resultados
    assert resultados[0].identificador == "tensei-shitara-slime-datta-ken"


def test_buscar_titulo_com_subtitulo_e_404_no_completo_tambem_cai_para_truncado(extrator):
    """Mesmo fallback quando o candidato completo dá HTTP 404 em vez de 200
    vazio — os dois comportamentos foram observados ao vivo pro AnimeFire
    dependendo do título (ex: presença literal de ':' na URL)."""
    titulo = "Anime Principal: Subtitulo Aqui"
    url_truncado = f"{extrator.BASE_URL}/pesquisar/anime-principal"
    cliente = _ClienteComExcecoes404({url_truncado: _ler_fixture("busca.html")})

    resultados = extrator.buscar(cliente, titulo)

    assert resultados
    assert resultados[0].identificador == "tensei-shitara-slime-datta-ken"


def test_buscar_titulo_com_subtitulo_nao_tenta_truncado_quando_completo_ja_acha(extrator):
    """Quando o candidato completo já acha resultado, não desperdiça uma 2ª
    requisição — `ClienteFalso` levanta `AssertionError` numa URL não mapeada,
    então isso também prova que o candidato truncado não chegou a ser chamado."""
    titulo = "Anime Principal: Subtitulo Aqui"
    url_completo = f"{extrator.BASE_URL}/pesquisar/anime-principal-subtitulo-aqui"
    cliente = ClienteFalso(html_por_url={url_completo: _ler_fixture("busca.html")})

    resultados = extrator.buscar(cliente, titulo)

    assert resultados
    assert resultados[0].identificador == "tensei-shitara-slime-datta-ken"


def test_buscar_dois_pontos_colado_ao_texto_nao_e_tratado_como_subtitulo(extrator):
    """":" sem espaço nenhum ao redor é parte do título (ex: "Re:Zero"), não
    separador de subtítulo — tratar como separador truncaria pra um prefixo
    curto demais ("Re") e arriscaria casar o card de outro anime por
    prefix-match do AnimeFire, trocando silenciosamente "não encontrei" por
    "encontrei o errado". Só 1 candidato tentado — `ClienteFalso` levantaria
    `AssertionError` numa 2ª URL não mapeada se o código tentasse truncar."""
    titulo = "Re:Zero kara Hajimeru Isekai Seikatsu"
    url_busca = f"{extrator.BASE_URL}/pesquisar/re-zero-kara-hajimeru-isekai-seikatsu"
    cliente = ClienteFalso(html_por_url={url_busca: _ler_fixture("busca_vazia.html")})

    assert extrator.buscar(cliente, titulo) == []


def test_buscar_titulo_com_virgula_formata_termo_via_slugificar(extrator):
    """Regressão: `.replace(" ", "-")` sozinho preservava vírgula literal na
    URL de busca (`.../kimi-to,-me-ni-...`), que nunca casava com o slug real
    do card (`.../kimi-to-me-ni-...`, vírgula colapsada junto do espaço num
    único hífen — confirmado ao vivo contra animefire.io)."""
    titulo = "Toumei na Yoru ni Kakeru Kimi to, Me ni Mienai Koi wo Shita"
    url_busca = (
        f"{extrator.BASE_URL}/pesquisar/"
        "toumei-na-yoru-ni-kakeru-kimi-to-me-ni-mienai-koi-wo-shita"
    )
    cliente = ClienteFalso(html_por_url={url_busca: _ler_fixture("busca.html")})

    resultados = extrator.buscar(cliente, titulo)

    assert resultados


def test_listar_episodios_deduplica_e_inclui_rotulo_nao_numerico_sem_numero(extrator):
    """`episodios.html` tem um episódio "2" duplicado (mesmo href, dedup por
    href) e um rótulo não numérico ("especial") — que não é mais descartado:
    entra na lista com `numero=None` (decisão do produto: sem seção
    "especial" separada, só não capturável ainda)."""
    identificador = "tensei-shitara-slime-datta-ken"
    url_anime = f"{extrator.BASE_URL}/animes/{identificador}-todos-os-episodios"
    cliente = ClienteFalso(html_por_url={url_anime: _ler_fixture("episodios.html")})

    episodios = extrator.listar_episodios(cliente, identificador)

    assert episodios == [
        EpisodioRemoto(
            rotulo="1", numero=1, url=f"{extrator.BASE_URL}/animes/{identificador}/1"
        ),
        EpisodioRemoto(
            rotulo="2", numero=2, url=f"{extrator.BASE_URL}/animes/{identificador}/2"
        ),
        EpisodioRemoto(
            rotulo="especial",
            numero=None,
            url=f"{extrator.BASE_URL}/animes/{identificador}/especial",
        ),
        EpisodioRemoto(
            rotulo="3", numero=3, url=f"{extrator.BASE_URL}/animes/{identificador}/3"
        ),
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

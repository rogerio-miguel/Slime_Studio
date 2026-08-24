"""Testes de parsing de `extractors/animefire.py`, sem rede — `ClienteFalso`
devolve fixtures HTML/JSON escritas à mão em `tests/fixtures/animefire/`."""

import json
from pathlib import Path

import pytest
from conftest import ClienteFalso

from core.enums import VersaoEpisodio
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
            versao=VersaoEpisodio.LEGENDADO,
        ),
        ResultadoBusca(
            titulo_exibicao="Tensei Shitara Slime Datta Ken 2",
            identificador="tensei-shitara-slime-datta-ken-2",
            url=f"{extrator.BASE_URL}/animes/tensei-shitara-slime-datta-ken-2-todos-os-episodios",
            versao=VersaoEpisodio.LEGENDADO,
        ),
    ]


def test_diferencia_versao(extrator):
    """Confirmado ao vivo em 2026-08-18 (busca por "One Piece"): AnimeFire
    também separa legendado de dublado no próprio slug/título, mesmo padrão do
    AnimesDrive — ex. "One Piece (Dublado)" / slug `one-piece-dublado` como
    entrada de catálogo própria."""
    assert extrator.diferencia_versao is True


def test_buscar_marca_versao_dublado_via_marcador_no_slug(extrator):
    """`busca_dublado.html` tem um card "(Dublado)" ao lado do card sem
    marcador — mesma convenção do AnimesDrive: dublado sempre marcado,
    ausência de marcador nunca é indeterminado, é `LEGENDADO`."""
    url_busca = f"{extrator.BASE_URL}/pesquisar/one-piece"
    cliente = ClienteFalso(html_por_url={url_busca: _ler_fixture("busca_dublado.html")})

    resultados = extrator.buscar(cliente, "One Piece")

    assert resultados == [
        ResultadoBusca(
            titulo_exibicao="One Piece",
            identificador="one-piece",
            url=f"{extrator.BASE_URL}/animes/one-piece-todos-os-episodios",
            versao=VersaoEpisodio.LEGENDADO,
        ),
        ResultadoBusca(
            titulo_exibicao="One Piece (Dublado)",
            identificador="one-piece-dublado",
            url=f"{extrator.BASE_URL}/animes/one-piece-dublado-todos-os-episodios",
            versao=VersaoEpisodio.DUBLADO,
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


def test_buscar_chama_buscar_termo_uma_unica_vez_com_termo_exato(extrator):
    """`buscar` não itera mais variantes internamente (responsabilidade que
    saiu do adapter — mora em `extractors/nomes.py::variantes_de_busca` e,
    numa camada de orquestração futura, em quem itera essas variantes).
    Chama `_buscar_termo` uma única vez, com o título recebido tal como veio,
    sem truncar subtítulo."""
    titulo = "Anime Principal: Subtitulo Aqui"
    url_completo = f"{extrator.BASE_URL}/pesquisar/anime-principal-subtitulo-aqui"
    cliente = ClienteFalso(html_por_url={url_completo: _ler_fixture("busca.html")})

    resultados = extrator.buscar(cliente, titulo)

    assert resultados
    assert resultados[0].identificador == "tensei-shitara-slime-datta-ken"


def test_buscar_nao_trunca_mais_internamente_quando_termo_completo_nao_acha(extrator):
    """Antes, um título com subtítulo caía para um 2º candidato truncado
    quando o completo não achava nada (`_candidatos_de_busca`, removido daqui
    — a lógica de gerar variantes agora mora em `extractors/nomes.py`). Agora
    `buscar` faz uma única tentativa — `ClienteFalso` levantaria
    `AssertionError` numa URL truncada não mapeada se o código ainda
    tentasse um 2º candidato."""
    titulo = "Anime Principal: Subtitulo Aqui"
    url_completo = f"{extrator.BASE_URL}/pesquisar/anime-principal-subtitulo-aqui"
    cliente = ClienteFalso(html_por_url={url_completo: _ler_fixture("busca_vazia.html")})

    assert extrator.buscar(cliente, titulo) == []


def test_buscar_termo_nao_recebe_mais_e_ultimo(extrator):
    """`_buscar_termo` perdeu o parâmetro `e_ultimo` — saber se é a última
    variante tentada não é mais responsabilidade do adapter (o `warning` de
    "esgotou todas as variantes" passa a ser de quem itera, fatia futura).
    Chamar só com `cliente` e `termo` prova que a assinatura não exige mais
    esse parâmetro."""
    url_busca = f"{extrator.BASE_URL}/pesquisar/tensei-shitara-slime-datta-ken"
    cliente = ClienteFalso(html_por_url={url_busca: _ler_fixture("busca.html")})

    resultados = extrator._buscar_termo(cliente, "Tensei Shitara Slime Datta Ken")

    assert resultados


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


def test_resolver_midia_escolhe_a_qualidade_mais_alta_por_rotulo(extrator):
    """`midia.json` tem SD antes de HD — a escolha vem da classificação do
    `label` (`extractors/qualidade.py`), não da posição no array."""
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


def test_resolver_midia_com_data_em_ordem_decrescente_ainda_escolhe_a_melhor(extrator):
    """`data[]` com HD antes de SD (ordem invertida em relação à fixture padrão)
    — prova que a escolha não depende mais da posição do array."""
    url_episodio = f"{extrator.BASE_URL}/animes/tensei-shitara-slime-datta-ken/1"
    url_json = "https://animefire.io/video/abc123/data.json"
    cliente = ClienteFalso(
        html_por_url={url_episodio: _ler_fixture("episodio.html")},
        json_por_url={
            url_json: {
                "data": [
                    {"label": "HD", "src": "https://cdn.animefire.io/videos/abc123-hd.mp4"},
                    {"label": "SD", "src": "https://cdn.animefire.io/videos/abc123-sd.mp4"},
                ]
            }
        },
    )

    link = extrator.resolver_midia(cliente, url_episodio)

    assert link.url == "https://cdn.animefire.io/videos/abc123-hd.mp4"


def test_resolver_midia_so_com_sd_nao_falha_e_usa_o_disponivel(extrator):
    """Sem piso mínimo no AnimeFire (diverge do AnimesDrive de propósito): se só
    SD estiver disponível, o episódio continua capturável — recusar seria
    regressão de produto (catálogo antigo frequentemente só tem SD)."""
    url_episodio = f"{extrator.BASE_URL}/animes/tensei-shitara-slime-datta-ken/1"
    url_json = "https://animefire.io/video/abc123/data.json"
    cliente = ClienteFalso(
        html_por_url={url_episodio: _ler_fixture("episodio.html")},
        json_por_url={
            url_json: {
                "data": [{"label": "SD", "src": "https://cdn.animefire.io/videos/abc123-sd.mp4"}]
            }
        },
    )

    link = extrator.resolver_midia(cliente, url_episodio)

    assert link.url == "https://cdn.animefire.io/videos/abc123-sd.mp4"


def test_resolver_midia_com_label_ausente_ou_vazio_nao_e_tratado_como_pior_que_sd(extrator):
    """`label` ausente/vazio classifica como `DESCONHECIDA`, nunca
    `ABAIXO_DO_PISO` — entra no desempate por posição normalmente e pode vencer
    sobre um SD explícito, já que `DESCONHECIDA > ABAIXO_DO_PISO`."""
    url_episodio = f"{extrator.BASE_URL}/animes/tensei-shitara-slime-datta-ken/1"
    url_json = "https://animefire.io/video/abc123/data.json"
    cliente = ClienteFalso(
        html_por_url={url_episodio: _ler_fixture("episodio.html")},
        json_por_url={
            url_json: {
                "data": [
                    {"label": "SD", "src": "https://cdn.animefire.io/videos/abc123-sd.mp4"},
                    {"src": "https://cdn.animefire.io/videos/abc123-sem-label.mp4"},
                ]
            }
        },
    )

    link = extrator.resolver_midia(cliente, url_episodio)

    assert link.url == "https://cdn.animefire.io/videos/abc123-sem-label.mp4"


def test_resolver_midia_com_todos_os_rotulos_desconhecidos_mantem_o_ultimo(extrator):
    """Todos os rótulos desconhecidos (nenhum vocabulário de qualidade) —
    trava de não-regressão: mantém o comportamento de hoje, o último item."""
    url_episodio = f"{extrator.BASE_URL}/animes/tensei-shitara-slime-datta-ken/1"
    url_json = "https://animefire.io/video/abc123/data.json"
    cliente = ClienteFalso(
        html_por_url={url_episodio: _ler_fixture("episodio.html")},
        json_por_url={
            url_json: {
                "data": [
                    {"label": "Servidor 1", "src": "https://cdn.animefire.io/videos/abc123-s1.mp4"},
                    {"label": "Servidor 2", "src": "https://cdn.animefire.io/videos/abc123-s2.mp4"},
                ]
            }
        },
    )

    link = extrator.resolver_midia(cliente, url_episodio)

    assert link.url == "https://cdn.animefire.io/videos/abc123-s2.mp4"


def test_resolver_midia_normaliza_rotulo_f_hd_e_fullhd(extrator):
    """`"F-HD"`/`"Fullhd"` normalizam pro mesmo tier FHD — regressão da
    normalização de `qualidade_do_rotulo` (hífen colapsado, sem exigir
    espaço)."""
    url_episodio = f"{extrator.BASE_URL}/animes/tensei-shitara-slime-datta-ken/1"
    url_json = "https://animefire.io/video/abc123/data.json"
    cliente = ClienteFalso(
        html_por_url={url_episodio: _ler_fixture("episodio.html")},
        json_por_url={
            url_json: {
                "data": [
                    {"label": "HD", "src": "https://cdn.animefire.io/videos/abc123-hd.mp4"},
                    {"label": "F-HD", "src": "https://cdn.animefire.io/videos/abc123-fhd.mp4"},
                ]
            }
        },
    )

    link = extrator.resolver_midia(cliente, url_episodio)

    assert link.url == "https://cdn.animefire.io/videos/abc123-fhd.mp4"

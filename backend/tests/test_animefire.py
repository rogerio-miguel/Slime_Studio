"""Testes de parsing de `extractors/animefire.py`, sem rede — `ClienteFalso`
devolve fixtures HTML/JSON escritas à mão em `tests/fixtures/animefire/`."""

import json
from pathlib import Path

import pytest
from conftest import ClienteFalso

from core.enums import VersaoEpisodio
from core.erros import EstruturaDoSiteMudou, FonteNaoEncontrada
from extractors.animefire import AnimeFireProvider
from extractors.base import EpisodioRemoto, FormatoDeMidia, LinkDeMidia, ResultadoBusca

_FIXTURES = Path(__file__).parent / "fixtures" / "animefire"


def _ler_fixture(nome: str) -> str:
    return (_FIXTURES / nome).read_text(encoding="utf-8")


def _ler_fixture_json(nome: str) -> dict:
    return json.loads(_ler_fixture(nome))


@pytest.fixture
def extrator() -> AnimeFireProvider:
    return AnimeFireProvider()


_API_URL = "https://api.animefire.one"


class _ClienteComExcecao404:
    """Fake de `ClienteDeSite`: `obter_json` sempre levanta `FonteNaoEncontrada`
    (simula HTTP 404) — usado só pra provar que `buscar` trata isso como zero
    resultados, não falha. `ClienteFalso` (conftest.py) não serve pra isso
    porque levanta `AssertionError` em vez de simular 404."""

    def obter_html(self, url: str, *, timeout_s: int) -> str:
        raise AssertionError("não deveria ser chamado")

    def obter_json(self, url: str, *, timeout_s: int) -> dict | list:
        raise FonteNaoEncontrada(f"não encontrado: {url}")

    def cookies(self) -> dict[str, str]:
        return {}

    def user_agent(self) -> str:
        return "ClienteFalso/1.0"


def test_buscar_com_resultado_devolve_candidatos(extrator):
    url_busca = f"{_API_URL}/animes/pesquisar?q=tensei-shitara-slime-datta-ken"
    cliente = ClienteFalso(json_por_url={url_busca: _ler_fixture_json("busca.json")})

    resultados = extrator.buscar(cliente, "Tensei Shitara Slime Datta Ken")

    assert resultados == [
        ResultadoBusca(
            titulo_exibicao="Tensei Shitara Slime Datta Ken",
            identificador="tensei-shitara-slime-datta-ken",
            url=f"{extrator.BASE_URL}/anime/tensei-shitara-slime-datta-ken",
            versao=VersaoEpisodio.LEGENDADO,
        ),
        ResultadoBusca(
            titulo_exibicao="Tensei Shitara Slime Datta Ken 2",
            identificador="tensei-shitara-slime-datta-ken-2",
            url=f"{extrator.BASE_URL}/anime/tensei-shitara-slime-datta-ken-2",
            versao=VersaoEpisodio.LEGENDADO,
        ),
    ]


def test_diferencia_versao(extrator):
    """Confirmado ao vivo em 2026-08-18 (busca por "One Piece"): AnimeFire
    também separa legendado de dublado no próprio slug/título, mesmo padrão do
    AnimesDrive — ex. "One Piece (Dublado)" / slug `one-piece-dublado` como
    entrada de catálogo própria."""
    assert extrator.diferencia_versao is True


def test_buscar_com_audio_dublado_e_legendado_gera_duas_entradas(extrator):
    """`audio: "Dublado &amp; Legendado"` (entity HTML confirmada ao vivo na
    resposta da API) vira duas entradas de `ResultadoBusca` com o mesmo
    `identificador`, uma por versão — não uma versão indeterminada."""
    url_busca = f"{_API_URL}/animes/pesquisar?q=naruto"
    cliente = ClienteFalso(
        json_por_url={url_busca: _ler_fixture_json("busca_ambas_versoes.json")}
    )

    resultados = extrator.buscar(cliente, "Naruto")

    assert resultados == [
        ResultadoBusca(
            titulo_exibicao="Naruto",
            identificador="eU7t5IvcNKU",
            url=f"{extrator.BASE_URL}/anime/eU7t5IvcNKU",
            versao=VersaoEpisodio.DUBLADO,
        ),
        ResultadoBusca(
            titulo_exibicao="Naruto",
            identificador="eU7t5IvcNKU",
            url=f"{extrator.BASE_URL}/anime/eU7t5IvcNKU",
            versao=VersaoEpisodio.LEGENDADO,
        ),
    ]


def test_buscar_com_audio_so_dublado_gera_uma_entrada_sem_duplicar(extrator):
    """`audio` mencionando só um dos dois marcadores não pode gerar fan-out —
    trava de não-regressão para o caso comum (maioria do catálogo é só
    dublado ou só legendado, não os dois)."""
    url_busca = f"{_API_URL}/animes/pesquisar?q=one-piece"
    cliente = ClienteFalso(
        json_por_url={
            url_busca: {
                "data": [
                    {
                        "id": "one-piece",
                        "titles": {"BR": "One Piece"},
                        "audio": "Dublado",
                        "poster_src": "https://image.tmdb.org/t/p/original/op.jpg",
                    }
                ]
            }
        }
    )

    resultados = extrator.buscar(cliente, "One Piece")

    assert resultados == [
        ResultadoBusca(
            titulo_exibicao="One Piece",
            identificador="one-piece",
            url=f"{extrator.BASE_URL}/anime/one-piece",
            versao=VersaoEpisodio.DUBLADO,
        ),
    ]


def test_buscar_ignora_poster_src_extractor_nao_resolve_mais_capa(extrator):
    """Fatia 3 de `PLANO_ARTE_TMDB.md`: `extractors/` deixou de resolver capa
    de anime — `poster_src` (presente na fixture, payload real do site) é
    lido pelo parsing e simplesmente ignorado; `ResultadoBusca` não tem mais
    campo `capa_url` nenhum (enriquecimento é 100% de `api/servicos/capas.py`,
    via metadado de provedor externo)."""
    url_busca = f"{_API_URL}/animes/pesquisar?q=tensei-shitara-slime-datta-ken"
    cliente = ClienteFalso(json_por_url={url_busca: _ler_fixture_json("busca.json")})

    resultados = extrator.buscar(cliente, "Tensei Shitara Slime Datta Ken")

    assert resultados
    assert not hasattr(resultados[0], "capa_url")


def test_buscar_sem_resultado_devolve_lista_vazia(extrator):
    url_busca = f"{_API_URL}/animes/pesquisar?q=anime-inexistente"
    cliente = ClienteFalso(json_por_url={url_busca: _ler_fixture_json("busca_vazia.json")})

    assert extrator.buscar(cliente, "Anime Inexistente") == []


def test_buscar_404_devolve_lista_vazia_sem_levantar_excecao(extrator):
    resultados = extrator.buscar(_ClienteComExcecao404(), "Anime Inexistente")

    assert resultados == []


def test_buscar_com_data_em_formato_invalido_levanta_estrutura_do_site_mudou(extrator):
    url_busca = f"{_API_URL}/animes/pesquisar?q=anime-com-erro"
    cliente = ClienteFalso(json_por_url={url_busca: {"data": {"nao": "e uma lista"}}})

    with pytest.raises(EstruturaDoSiteMudou):
        extrator.buscar(cliente, "Anime Com Erro")


def test_buscar_com_item_sem_id_ou_title_levanta_estrutura_do_site_mudou(extrator):
    url_busca = f"{_API_URL}/animes/pesquisar?q=anime-com-erro"
    cliente = ClienteFalso(
        json_por_url={url_busca: {"data": [{"audio": "Legendado"}]}}
    )

    with pytest.raises(EstruturaDoSiteMudou):
        extrator.buscar(cliente, "Anime Com Erro")


def test_buscar_chama_buscar_termo_uma_unica_vez_com_termo_exato(extrator):
    """`buscar` não itera mais variantes internamente (responsabilidade que
    saiu do adapter — mora em `extractors/busca/termos.py::variantes_de_busca` e,
    numa camada de orquestração futura, em quem itera essas variantes).
    Chama `_buscar_termo` uma única vez, com o título recebido tal como veio,
    sem truncar subtítulo."""
    titulo = "Anime Principal: Subtitulo Aqui"
    url_completo = f"{_API_URL}/animes/pesquisar?q=anime-principal-subtitulo-aqui"
    cliente = ClienteFalso(json_por_url={url_completo: _ler_fixture_json("busca.json")})

    resultados = extrator.buscar(cliente, titulo)

    assert resultados
    assert resultados[0].identificador == "tensei-shitara-slime-datta-ken"


def test_buscar_nao_trunca_mais_internamente_quando_termo_completo_nao_acha(extrator):
    """Antes, um título com subtítulo caía para um 2º candidato truncado
    quando o completo não achava nada (`_candidatos_de_busca`, removido daqui
    — a lógica de gerar variantes agora mora em `extractors/busca/termos.py`). Agora
    `buscar` faz uma única tentativa — `ClienteFalso` levantaria
    `AssertionError` numa URL truncada não mapeada se o código ainda
    tentasse um 2º candidato."""
    titulo = "Anime Principal: Subtitulo Aqui"
    url_completo = f"{_API_URL}/animes/pesquisar?q=anime-principal-subtitulo-aqui"
    cliente = ClienteFalso(json_por_url={url_completo: _ler_fixture_json("busca_vazia.json")})

    assert extrator.buscar(cliente, titulo) == []


def test_buscar_termo_nao_recebe_mais_e_ultimo(extrator):
    """`_buscar_termo` perdeu o parâmetro `e_ultimo` — saber se é a última
    variante tentada não é mais responsabilidade do adapter (o `warning` de
    "esgotou todas as variantes" passa a ser de quem itera, fatia futura).
    Chamar só com `cliente` e `termo` prova que a assinatura não exige mais
    esse parâmetro."""
    url_busca = f"{_API_URL}/animes/pesquisar?q=tensei-shitara-slime-datta-ken"
    cliente = ClienteFalso(json_por_url={url_busca: _ler_fixture_json("busca.json")})

    resultados = extrator._buscar_termo(cliente, "Tensei Shitara Slime Datta Ken")

    assert resultados


def test_buscar_titulo_com_virgula_formata_termo_via_slugificar(extrator):
    """Regressão: `.replace(" ", "-")` sozinho preservava vírgula literal na
    URL de busca (`.../kimi-to,-me-ni-...`), que nunca casava com o slug real
    do card (`.../kimi-to-me-ni-...`, vírgula colapsada junto do espaço num
    único hífen — confirmado ao vivo contra animefire.one). Mesma formatação de
    `q` vale pro endpoint JSON, que aceita hífen ou espaço."""
    titulo = "Toumei na Yoru ni Kakeru Kimi to, Me ni Mienai Koi wo Shita"
    url_busca = (
        f"{_API_URL}/animes/pesquisar?q="
        "toumei-na-yoru-ni-kakeru-kimi-to-me-ni-mienai-koi-wo-shita"
    )
    cliente = ClienteFalso(json_por_url={url_busca: _ler_fixture_json("busca.json")})

    resultados = extrator.buscar(cliente, titulo)

    assert resultados


def test_listar_episodios_calcula_numero_absoluto_e_fan_out_por_audio_com_dedup(extrator):
    """`anime_detalhe.json` tem 2 temporadas (`first_episode_number` 1 e 13,
    provando o cálculo de offset atravessando temporada), um episódio
    duplicado byte a byte (mesmo `id`/`season`/`number`/`audio` — prova dedup
    por `(rotulo, versao)`) e um episódio com `audio: "Dublado &amp;
    Legendado"` (entity HTML) que faz fan-out em duas entradas com o MESMO
    `rotulo`/`numero` e versões diferentes — provando que dedup por
    `(rotulo, versao)` não descarta essas duas como se fossem a mesma."""
    identificador = "tensei-shitara-slime-datta-ken"
    url_anime = f"{_API_URL}/anime/{identificador}"
    cliente = ClienteFalso(
        json_por_url={url_anime: _ler_fixture_json("anime_detalhe.json")}
    )

    episodios = extrator.listar_episodios(cliente, identificador, None)

    assert episodios == [
        EpisodioRemoto(
            rotulo="1",
            numero=1,
            url=f"{extrator.BASE_URL}/anime/{identificador}?ep=ep-s1-1&audio=legendado",
            versao=VersaoEpisodio.LEGENDADO,
            thumb_url="https://image.tmdb.org/t/p/original/ep1.jpg",
        ),
        EpisodioRemoto(
            rotulo="2",
            numero=2,
            url=f"{extrator.BASE_URL}/anime/{identificador}?ep=ep-s1-2&audio=dublado",
            versao=VersaoEpisodio.DUBLADO,
            thumb_url="https://image.tmdb.org/t/p/original/ep2.jpg",
        ),
        EpisodioRemoto(
            rotulo="2",
            numero=2,
            url=f"{extrator.BASE_URL}/anime/{identificador}?ep=ep-s1-2&audio=legendado",
            versao=VersaoEpisodio.LEGENDADO,
            thumb_url="https://image.tmdb.org/t/p/original/ep2.jpg",
        ),
        EpisodioRemoto(
            rotulo="13",
            numero=13,
            url=f"{extrator.BASE_URL}/anime/{identificador}?ep=ep-s2-1&audio=legendado",
            versao=VersaoEpisodio.LEGENDADO,
            thumb_url="https://image.tmdb.org/t/p/original/ep13.jpg",
        ),
    ]


def test_listar_episodios_sem_data_levanta_estrutura_do_site_mudou(extrator):
    """Resposta bem-formada (HTTP 200, JSON válido) mas sem os campos
    esperados — o caso real de "Serviço indisponível" devolvido com 200 em
    vez do JSON de detalhe. Precisa virar `EstruturaDoSiteMudou`, nunca uma
    lista vazia silenciosa (isso seria regressão de catálogo)."""
    identificador = "anime-servico-indisponivel"
    url_anime = f"{_API_URL}/anime/{identificador}"
    cliente = ClienteFalso(json_por_url={url_anime: {"error": "Serviço indisponível"}})

    with pytest.raises(EstruturaDoSiteMudou):
        extrator.listar_episodios(cliente, identificador, None)


def test_listar_episodios_com_episodes_em_formato_invalido_levanta_estrutura_do_site_mudou(
    extrator,
):
    identificador = "anime-com-erro"
    url_anime = f"{_API_URL}/anime/{identificador}"
    cliente = ClienteFalso(
        json_por_url={url_anime: {"data": {"seasons": [], "episodes": "nao-e-uma-lista"}}}
    )

    with pytest.raises(EstruturaDoSiteMudou):
        extrator.listar_episodios(cliente, identificador, None)


def test_listar_episodios_com_lista_vazia_devolve_lista_vazia(extrator):
    """`data.episodes: []` com `seasons` válido é anime ainda não estreado
    (observado ao vivo) — estado legítimo, não erro."""
    identificador = "anime-sem-episodios"
    url_anime = f"{_API_URL}/anime/{identificador}"
    cliente = ClienteFalso(
        json_por_url={
            url_anime: {
                "data": {
                    "seasons": [{"title": None, "number": 1, "first_episode_number": 1}],
                    "episodes": [],
                }
            }
        }
    )

    assert extrator.listar_episodios(cliente, identificador, None) == []
    assert extrator.listar_episodios(cliente, identificador, 1) == []


def test_listar_episodios_com_temporada_ausente_em_seasons_levanta_estrutura_do_site_mudou(
    extrator,
):
    """Episódio referencia `season: 2`, mas `seasons` só mapeia a temporada 1
    — sem como calcular o número absoluto correto, então isto é estrutura
    mudou, não um número calculado errado silenciosamente."""
    identificador = "anime-temporada-orfa"
    url_anime = f"{_API_URL}/anime/{identificador}"
    cliente = ClienteFalso(
        json_por_url={
            url_anime: {
                "data": {
                    "seasons": [{"title": None, "number": 1, "first_episode_number": 1}],
                    "episodes": [
                        {
                            "id": "ep-1",
                            "title": "Episodio 1",
                            "audio": "Legendado",
                            "season": 2,
                            "number": 1,
                            "still_src": None,
                        }
                    ],
                }
            }
        }
    )

    with pytest.raises(EstruturaDoSiteMudou):
        extrator.listar_episodios(cliente, identificador, None)


def _url_sintetica(ep_id: str, audio: str | None = None) -> str:
    identificador = "tensei-shitara-slime-datta-ken"
    base = f"{AnimeFireProvider.BASE_URL}/anime/{identificador}?ep={ep_id}"
    return f"{base}&audio={audio}" if audio else base


def test_resolver_midia_escolhe_o_stream_do_audio_pedido_dublado(extrator):
    ep_id = "ep-s1-1"
    url_episodio = _url_sintetica(ep_id, "dublado")
    url_episode_api = f"{_API_URL}/episode/{ep_id}"
    cliente = ClienteFalso(json_por_url={url_episode_api: _ler_fixture_json("episode.json")})

    link = extrator.resolver_midia(cliente, url_episodio)

    assert link == LinkDeMidia(
        url="https://akumast.net/i/tokendublado/m.jpg",
        cabecalhos={"User-Agent": "ClienteFalso/1.0"},
        formato=FormatoDeMidia.HLS,
    )


def test_resolver_midia_escolhe_o_stream_do_audio_pedido_legendado(extrator):
    ep_id = "ep-s1-1"
    url_episodio = _url_sintetica(ep_id, "legendado")
    url_episode_api = f"{_API_URL}/episode/{ep_id}"
    cliente = ClienteFalso(json_por_url={url_episode_api: _ler_fixture_json("episode.json")})

    link = extrator.resolver_midia(cliente, url_episodio)

    assert link.url == "https://akumast.net/i/tokenlegendado/m.jpg"


def test_resolver_midia_ignora_stream_is_offline(extrator):
    """Um dos dois streams está `is_offline: true` — mesmo pedindo o áudio
    daquele stream, ele é descartado antes da escolha por áudio (não é
    "usável", independente do que `audio` diz)."""
    ep_id = "ep-s1-1"
    url_episodio = _url_sintetica(ep_id, "dublado")
    url_episode_api = f"{_API_URL}/episode/{ep_id}"
    cliente = ClienteFalso(
        json_por_url={
            url_episode_api: {
                "data": {
                    "streams": [
                        {
                            "audio": "dublado",
                            "is_mtl": False,
                            "is_offline": True,
                            "url": "https://akumast.net/i/offline/m.jpg",
                        },
                        {
                            "audio": "legendado",
                            "is_mtl": False,
                            "is_offline": False,
                            "url": "https://akumast.net/i/tokenlegendado/m.jpg",
                        },
                    ]
                }
            }
        }
    )

    with pytest.raises(FonteNaoEncontrada):
        extrator.resolver_midia(cliente, url_episodio)


def test_resolver_midia_sem_audio_na_url_e_um_unico_stream_usa_ele(extrator):
    ep_id = "ep-s1-1"
    url_episodio = _url_sintetica(ep_id)
    url_episode_api = f"{_API_URL}/episode/{ep_id}"
    cliente = ClienteFalso(
        json_por_url={
            url_episode_api: {
                "data": {
                    "streams": [
                        {
                            "audio": "dublado",
                            "is_mtl": False,
                            "is_offline": False,
                            "url": "https://akumast.net/i/tokendublado/m.jpg",
                        }
                    ]
                }
            }
        }
    )

    link = extrator.resolver_midia(cliente, url_episodio)

    assert link.url == "https://akumast.net/i/tokendublado/m.jpg"


def test_resolver_midia_sem_audio_na_url_e_multiplos_streams_prefere_legendado(
    extrator, caplog: pytest.LogCaptureFixture
):
    ep_id = "ep-s1-1"
    url_episodio = _url_sintetica(ep_id)
    url_episode_api = f"{_API_URL}/episode/{ep_id}"
    cliente = ClienteFalso(json_por_url={url_episode_api: _ler_fixture_json("episode.json")})

    with caplog.at_level("WARNING"):
        link = extrator.resolver_midia(cliente, url_episodio)

    assert link.url == "https://akumast.net/i/tokenlegendado/m.jpg"
    assert "legendado" in caplog.text


def test_resolver_midia_audio_pedido_sem_stream_correspondente_levanta_fonte_nao_encontrada(
    extrator,
):
    """`episode.json` só tem streams dublado/legendado — pedir um áudio pedido
    que não bate com nenhum classificado (aqui simulado removendo o stream
    dublado da fixture) precisa cair para o próximo site, não quebrar."""
    ep_id = "ep-s1-1"
    url_episodio = _url_sintetica(ep_id, "dublado")
    url_episode_api = f"{_API_URL}/episode/{ep_id}"
    cliente = ClienteFalso(
        json_por_url={
            url_episode_api: {
                "data": {
                    "streams": [
                        {
                            "audio": "legendado",
                            "is_mtl": False,
                            "is_offline": False,
                            "url": "https://akumast.net/i/tokenlegendado/m.jpg",
                        }
                    ]
                }
            }
        }
    )

    with pytest.raises(FonteNaoEncontrada):
        extrator.resolver_midia(cliente, url_episodio)


def test_resolver_midia_sem_streams_levanta_estrutura_do_site_mudou(extrator):
    ep_id = "ep-s1-1"
    url_episodio = _url_sintetica(ep_id, "legendado")
    url_episode_api = f"{_API_URL}/episode/{ep_id}"
    cliente = ClienteFalso(json_por_url={url_episode_api: {"data": {"streams": []}}})

    with pytest.raises(EstruturaDoSiteMudou):
        extrator.resolver_midia(cliente, url_episodio)


def test_resolver_midia_com_streams_malformado_levanta_estrutura_do_site_mudou(extrator):
    ep_id = "ep-s1-1"
    url_episodio = _url_sintetica(ep_id, "legendado")
    url_episode_api = f"{_API_URL}/episode/{ep_id}"
    cliente = ClienteFalso(
        json_por_url={url_episode_api: {"data": {"streams": "nao-e-uma-lista"}}}
    )

    with pytest.raises(EstruturaDoSiteMudou):
        extrator.resolver_midia(cliente, url_episodio)


def test_resolver_midia_todos_os_streams_offline_levanta_fonte_nao_encontrada(extrator):
    ep_id = "ep-s1-1"
    url_episodio = _url_sintetica(ep_id, "legendado")
    url_episode_api = f"{_API_URL}/episode/{ep_id}"
    cliente = ClienteFalso(
        json_por_url={
            url_episode_api: {
                "data": {
                    "streams": [
                        {
                            "audio": "legendado",
                            "is_mtl": False,
                            "is_offline": True,
                            "url": "https://akumast.net/i/offline/m.jpg",
                        }
                    ]
                }
            }
        }
    )

    with pytest.raises(FonteNaoEncontrada):
        extrator.resolver_midia(cliente, url_episodio)


def test_resolver_midia_sem_ep_na_url_levanta_estrutura_do_site_mudou(extrator):
    url_episodio = f"{AnimeFireProvider.BASE_URL}/anime/tensei-shitara-slime-datta-ken"
    cliente = ClienteFalso()

    with pytest.raises(EstruturaDoSiteMudou):
        extrator.resolver_midia(cliente, url_episodio)


def test_resolver_midia_desempate_por_is_mtl_prefere_nao_mtl(extrator):
    """Dois streams sobrevivem à escolha por áudio (`legendado` pedido, ambos
    classificados como tal) — o desempate nunca filtra a lista, só decide
    qual dos dois usar: o marcado `is_mtl: false` vence."""
    ep_id = "ep-s1-1"
    url_episodio = _url_sintetica(ep_id, "legendado")
    url_episode_api = f"{_API_URL}/episode/{ep_id}"
    cliente = ClienteFalso(
        json_por_url={
            url_episode_api: {
                "data": {
                    "streams": [
                        {
                            "audio": "legendado",
                            "is_mtl": True,
                            "is_offline": False,
                            "url": "https://akumast.net/i/tokenmtl/m.jpg",
                        },
                        {
                            "audio": "legendado",
                            "is_mtl": False,
                            "is_offline": False,
                            "url": "https://akumast.net/i/tokennaomtl/m.jpg",
                        },
                    ]
                }
            }
        }
    )

    link = extrator.resolver_midia(cliente, url_episodio)

    assert link.url == "https://akumast.net/i/tokennaomtl/m.jpg"


def test_resolver_midia_retorno_tem_formato_hls_e_sem_referer(extrator):
    ep_id = "ep-s1-1"
    url_episodio = _url_sintetica(ep_id, "dublado")
    url_episode_api = f"{_API_URL}/episode/{ep_id}"
    cliente = ClienteFalso(json_por_url={url_episode_api: _ler_fixture_json("episode.json")})

    link = extrator.resolver_midia(cliente, url_episodio)

    assert link.formato == FormatoDeMidia.HLS
    assert link.cabecalhos == {"User-Agent": "ClienteFalso/1.0"}
    assert "Referer" not in link.cabecalhos

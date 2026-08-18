"""Testes de parsing de `extractors/animesdrive.py`, sem rede — `ClienteFalso`
(via fixture `cliente_falso` de `conftest.py`) devolve fixtures HTML escritas
à mão em `tests/fixtures/animesdrive/`."""

from pathlib import Path

import pytest

from core.enums import VersaoEpisodio
from core.erros import EstruturaDoSiteMudou, FalhaDeExtracao, FonteNaoEncontrada
from extractors.animesdrive import AnimesDriveProvider
from extractors.base import EpisodioRemoto, ResultadoBusca
from extractors.cliente import MidiaCapturada

_FIXTURES = Path(__file__).parent / "fixtures" / "animesdrive"


def _ler_fixture(nome: str) -> str:
    return (_FIXTURES / nome).read_text(encoding="utf-8")


def _pagina_de_episodios(*hrefs: str) -> str:
    """Envelopa `hrefs` no box `#episodes` do tema DooPlay — é de lá que
    `listar_episodios` lê (`_SELETOR_LISTA_EPISODIOS`), então HTML de teste com
    `<a>` solto no corpo não representaria a página real."""
    links = "\n".join(f'<a href="{href}">Episódio</a>' for href in hrefs)
    return f'<div id="episodes"><div class="episodios-grid">{links}</div></div>'


@pytest.fixture
def extrator() -> AnimesDriveProvider:
    return AnimesDriveProvider()


class _ClienteQueDevolve404:
    """Fake mínimo de `ClienteDeSite` que simula HTTP 404 (`FonteNaoEncontrada`)
    — a fixture `cliente_falso` (conftest.py) só devolve HTML pré-programado,
    nunca levanta exceção, então não serve pra este caso."""

    def obter_html(self, url: str, *, timeout_s: int) -> str:
        raise FonteNaoEncontrada(f"não encontrado: {url}")

    def obter_json(self, url: str, *, timeout_s: int) -> dict | list:
        raise AssertionError("não deveria ser chamado")

    def cookies(self) -> dict[str, str]:
        return {}

    def user_agent(self) -> str:
        return "ClienteFalso/1.0"

    def fechar(self) -> None:
        pass


class _ClienteNavegadorFalso:
    """Fake de `ClienteComCaptura`: devolve HTML pré-programado como o
    `ClienteFalso` e registra o que foi pedido a `capturar_midia`, sem subir
    Chromium nenhum. `capturada=None` simula o navegador não observar mídia."""

    def __init__(self, *, html: str, capturada: MidiaCapturada | None) -> None:
        self._html = html
        self._capturada = capturada
        self.pedidos: list[tuple[str, tuple[str, ...], int]] = []

    def obter_html(self, url: str, *, timeout_s: int) -> str:
        return self._html

    def obter_json(self, url: str, *, timeout_s: int) -> dict | list:
        raise AssertionError("não deveria ser chamado")

    def cookies(self) -> dict[str, str]:
        return {}

    def user_agent(self) -> str:
        return "NavegadorFalso/1.0"

    def fechar(self) -> None:
        pass

    def capturar_midia(
        self, url_pagina: str, *, hosts_ignorados: tuple[str, ...] = (), timeout_s: int
    ) -> MidiaCapturada:
        self.pedidos.append((url_pagina, hosts_ignorados, timeout_s))
        if self._capturada is None:
            raise FalhaDeExtracao(
                f"nenhuma requisição de mídia observada em {url_pagina}",
                permite_retentativa=True,
            )
        return self._capturada


def test_buscar_com_resultado_devolve_candidatos(extrator, cliente_falso):
    url_busca = f"{extrator.BASE_URL}/?s=Tensei+Shitara+Slime+Datta+Ken"
    cliente = cliente_falso(html_por_url={url_busca: _ler_fixture("busca.html")})

    resultados = extrator.buscar(cliente, "Tensei Shitara Slime Datta Ken")

    assert resultados == [
        ResultadoBusca(
            titulo_exibicao="Tensei Shitara Slime Datta Ken",
            identificador="tensei-shitara-slime-datta-ken",
            url="https://animesdrive.online/anime/tensei-shitara-slime-datta-ken",
            capa_url="https://animesdrive.online/capa1.jpg",
            versao=VersaoEpisodio.LEGENDADO,
        ),
        ResultadoBusca(
            titulo_exibicao="Tensei Shitara Slime Datta Ken Dublado",
            identificador="tensei-shitara-slime-datta-ken-dublado",
            url="https://animesdrive.online/anime/tensei-shitara-slime-datta-ken-dublado",
            capa_url="https://animesdrive.online/capa2.jpg",
            versao=VersaoEpisodio.DUBLADO,
        ),
    ]


def test_buscar_absolutiza_capa_nas_3_formas_de_src(extrator, cliente_falso):
    """`busca.html` só cobre path relativo (`/capa1.jpg`) — protocolo-relativo
    (`//host/...`) e URL já absoluta também precisam sair intactos/absolutizados
    de `urljoin`, e `src` só-espaço deve virar `capa_url=None` (não a
    homepage)."""
    html = """
    <div class="result-item"><article>
      <div class="image"><div class="thumbnail">
        <a href="https://animesdrive.online/anime/relativo"><img src="/relativo.jpg"></a>
      </div></div>
      <div class="details"><div class="title">
        <a href="https://animesdrive.online/anime/relativo">Relativo</a>
      </div></div>
    </article></div>
    <div class="result-item"><article>
      <div class="image"><div class="thumbnail">
        <a href="https://animesdrive.online/anime/protocolo-relativo"
           ><img src="//cdn.animesdrive.online/protocolo.jpg"></a>
      </div></div>
      <div class="details"><div class="title">
        <a href="https://animesdrive.online/anime/protocolo-relativo">Protocolo Relativo</a>
      </div></div>
    </article></div>
    <div class="result-item"><article>
      <div class="image"><div class="thumbnail">
        <a href="https://animesdrive.online/anime/absoluto"><img src="https://cdn.outra.com/absoluta.jpg"></a>
      </div></div>
      <div class="details"><div class="title">
        <a href="https://animesdrive.online/anime/absoluto">Absoluto</a>
      </div></div>
    </article></div>
    <div class="result-item"><article>
      <div class="image"><div class="thumbnail">
        <a href="https://animesdrive.online/anime/src-vazio"><img src="   "></a>
      </div></div>
      <div class="details"><div class="title">
        <a href="https://animesdrive.online/anime/src-vazio">Src Vazio</a>
      </div></div>
    </article></div>
    """
    url_busca = f"{extrator.BASE_URL}/?s=teste"
    cliente = cliente_falso(html_por_url={url_busca: html})

    resultados = extrator.buscar(cliente, "teste")

    capas = {resultado.identificador: resultado.capa_url for resultado in resultados}
    assert capas["relativo"] == "https://animesdrive.online/relativo.jpg"
    assert capas["protocolo-relativo"] == "https://cdn.animesdrive.online/protocolo.jpg"
    assert capas["absoluto"] == "https://cdn.outra.com/absoluta.jpg"
    assert capas["src-vazio"] is None


def test_buscar_sem_resultado_devolve_lista_vazia_mesmo_com_widget(extrator, cliente_falso):
    """Regressão do fallback perigoso (`article.w_item_a` é o widget de sidebar
    "mais vistos", presente mesmo quando a busca não acha nada)."""
    url_busca = f"{extrator.BASE_URL}/?s=Anime+Inexistente"
    cliente = cliente_falso(html_por_url={url_busca: _ler_fixture("busca_vazia.html")})

    assert extrator.buscar(cliente, "Anime Inexistente") == []


def test_buscar_404_devolve_lista_vazia_sem_levantar_excecao(extrator):
    resultados = extrator.buscar(_ClienteQueDevolve404(), "Anime Inexistente")

    assert resultados == []


def test_listar_episodios_deduplica_ordena_e_inclui_rotulo_nao_numerico(extrator, cliente_falso):
    """`episodios.html` tem o episódio 3 duplicado (thumbnail + título, mesmo
    href — dedup por rótulo) e um rótulo não numérico ("especial"), que não é
    mais descartado: entra no fim da lista com `numero=None` (decisão do
    produto: sem seção "especial" separada, só não capturável ainda)."""
    identificador = "tensei-shitara-slime-datta-ken"
    url_anime = f"{extrator.BASE_URL}/anime/{identificador}"
    cliente = cliente_falso(html_por_url={url_anime: _ler_fixture("episodios.html")})

    episodios = extrator.listar_episodios(cliente, identificador)

    assert episodios == [
        EpisodioRemoto(
            rotulo="1",
            numero=1,
            url="https://animesdrive.online/episodio/tensei-shitara-slime-datta-ken-episodio-1",
        ),
        EpisodioRemoto(
            rotulo="2",
            numero=2,
            url="https://animesdrive.online/episodio/tensei-shitara-slime-datta-ken-episodio-2",
        ),
        EpisodioRemoto(
            rotulo="3",
            numero=3,
            url="https://animesdrive.online/episodio/tensei-shitara-slime-datta-ken-episodio-3",
        ),
        EpisodioRemoto(
            rotulo="especial",
            numero=None,
            url=(
                "https://animesdrive.online/episodio/"
                "tensei-shitara-slime-datta-ken-episodio-especial"
            ),
        ),
    ]


def test_listar_episodios_rotulos_com_zero_a_esquerda_nao_colapsam(extrator, cliente_falso):
    """Regressão da hipótese de dedup por `int(numero)`: "7" e "07" são rótulos
    distintos na fonte e não podem colapsar num só episódio — a chave de dedup
    é o rótulo cru, não o valor inteiro. Desempate de ordenação entre dois
    rótulos com o mesmo `numero` segue a ordem de aparição na página ("7" antes
    de "07" aqui, porque é assim que o HTML lista), não ordem lexicográfica do
    rótulo — comparar "07" e "7" como string colocaria "07" primeiro
    ('0' < '7' em ASCII), o que seria arbitrário e não a ordem "natural" da
    fonte."""
    identificador = "tensei-shitara-slime-datta-ken"
    html = _pagina_de_episodios(
        "https://animesdrive.online/episodio/tensei-shitara-slime-datta-ken-episodio-7",
        "https://animesdrive.online/episodio/tensei-shitara-slime-datta-ken-episodio-07",
    )
    url_anime = f"{extrator.BASE_URL}/anime/{identificador}"
    cliente = cliente_falso(html_por_url={url_anime: html})

    episodios = extrator.listar_episodios(cliente, identificador)

    assert [(ep.rotulo, ep.numero) for ep in episodios] == [("7", 7), ("07", 7)]


def test_listar_episodios_aceita_url_com_barra_final(extrator, cliente_falso):
    """Regressão da hipótese 2: `_REGEX_EPISODIO` rejeitava indevidamente uma URL
    de episódio terminada em `/`."""
    identificador = "tensei-shitara-slime-datta-ken"
    html = _pagina_de_episodios(
        "https://animesdrive.online/episodio/tensei-shitara-slime-datta-ken-episodio-1/"
    )
    url_anime = f"{extrator.BASE_URL}/anime/{identificador}"
    cliente = cliente_falso(html_por_url={url_anime: html})

    episodios = extrator.listar_episodios(cliente, identificador)

    assert episodios == [
        EpisodioRemoto(
            rotulo="1",
            numero=1,
            url="https://animesdrive.online/episodio/tensei-shitara-slime-datta-ken-episodio-1/",
        ),
    ]


def test_listar_episodios_vazio_levanta_estrutura_do_site_mudou(extrator, cliente_falso):
    identificador = "anime-sem-episodios"
    url_anime = f"{extrator.BASE_URL}/anime/{identificador}"
    cliente = cliente_falso(html_por_url={url_anime: "<html><body></body></html>"})

    with pytest.raises(EstruturaDoSiteMudou):
        extrator.listar_episodios(cliente, identificador)



def test_listar_episodios_aceita_slug_de_episodio_diferente_do_identificador(
    extrator, cliente_falso
):
    """Regressão do filtro por prefixo do `identificador`: o slug do episódio não
    é derivável do identificador do anime. Confirmado ao vivo em 2026-08-17 —
    o anime `one-piece-dublado-todos-os-episodios` lista episódios
    `/episodio/one-piece-dublado-episodio-N`, e o filtro antigo
    (`slug.startswith(identificador)`) descartava todos, quebrando a listagem
    inteira com "nenhum episódio encontrado"."""
    identificador = "one-piece-dublado-todos-os-episodios"
    html = _pagina_de_episodios(
        "https://animesdrive.online/episodio/one-piece-dublado-episodio-1",
        "https://animesdrive.online/episodio/one-piece-dublado-episodio-2",
    )
    url_anime = f"{extrator.BASE_URL}/anime/{identificador}"
    cliente = cliente_falso(html_por_url={url_anime: html})

    episodios = extrator.listar_episodios(cliente, identificador)

    assert [(ep.rotulo, ep.numero) for ep in episodios] == [("1", 1), ("2", 2)]


def test_listar_episodios_ignora_link_de_episodio_fora_do_box(extrator, cliente_falso):
    """`episodios.html` tem um link `/episodio/outro-anime-episodio-5` num widget
    fora de `#episodes` (estrutura real do site) — ele não pode entrar na
    listagem, senão a captura baixaria o episódio de outro anime."""
    identificador = "tensei-shitara-slime-datta-ken"
    url_anime = f"{extrator.BASE_URL}/anime/{identificador}"
    cliente = cliente_falso(html_por_url={url_anime: _ler_fixture("episodios.html")})

    episodios = extrator.listar_episodios(cliente, identificador)

    assert all("outro-anime" not in episodio.url for episodio in episodios)


def test_listar_episodios_com_duas_versoes_relacionadas_devolve_ambas_rotuladas(
    extrator, cliente_falso
):
    """Página que lista legendado e dublado no mesmo box (acontece em página de
    filme/temporada) é a exceção cirúrgica: os dois slugs só divergem pelo
    marcador de versão (`-dublado`), então nenhuma lista é descarte — as duas
    saem juntas, cada episódio rotulado pela versão do próprio slug."""
    identificador = "tensei-shitara-slime-datta-ken-4th-season"
    html = _pagina_de_episodios(
        "https://animesdrive.online/episodio/tensei-shitara-slime-datta-ken-4th-season-episodio-1",
        "https://animesdrive.online/episodio/tensei-shitara-slime-datta-ken-4th-season-episodio-2",
        "https://animesdrive.online/episodio/"
        "tensei-shitara-slime-datta-ken-4th-season-dublado-episodio-1",
    )
    url_anime = f"{extrator.BASE_URL}/anime/{identificador}"
    cliente = cliente_falso(html_por_url={url_anime: html})

    episodios = extrator.listar_episodios(cliente, identificador)

    assert episodios == [
        EpisodioRemoto(
            rotulo="1",
            numero=1,
            url=(
                "https://animesdrive.online/episodio/"
                "tensei-shitara-slime-datta-ken-4th-season-episodio-1"
            ),
            versao=VersaoEpisodio.LEGENDADO,
        ),
        EpisodioRemoto(
            rotulo="1",
            numero=1,
            url=(
                "https://animesdrive.online/episodio/"
                "tensei-shitara-slime-datta-ken-4th-season-dublado-episodio-1"
            ),
            versao=VersaoEpisodio.DUBLADO,
        ),
        EpisodioRemoto(
            rotulo="2",
            numero=2,
            url=(
                "https://animesdrive.online/episodio/"
                "tensei-shitara-slime-datta-ken-4th-season-episodio-2"
            ),
            versao=VersaoEpisodio.LEGENDADO,
        ),
    ]


def test_listar_episodios_com_dois_slugs_nao_relacionados_por_versao_fica_com_a_maior(
    extrator, cliente_falso
):
    """Dois grupos que divergem por outro motivo (não é marcador de versão) não
    disparam a exceção cirúrgica — mantém o comportamento de sempre: fica com
    o maior, descarta o resto com warning."""
    identificador = "tensei-shitara-slime-datta-ken-ova"
    html = _pagina_de_episodios(
        "https://animesdrive.online/episodio/tensei-shitara-slime-datta-ken-ova-episodio-1",
        "https://animesdrive.online/episodio/tensei-shitara-slime-datta-ken-ova-episodio-2",
        "https://animesdrive.online/episodio/tensei-shitara-slime-datta-ken-movie-episodio-1",
    )
    url_anime = f"{extrator.BASE_URL}/anime/{identificador}"
    cliente = cliente_falso(html_por_url={url_anime: html})

    episodios = extrator.listar_episodios(cliente, identificador)

    assert [episodio.url for episodio in episodios] == [
        "https://animesdrive.online/episodio/tensei-shitara-slime-datta-ken-ova-episodio-1",
        "https://animesdrive.online/episodio/tensei-shitara-slime-datta-ken-ova-episodio-2",
    ]


def test_exige_navegador_para_midia_mas_nao_para_o_site_todo(extrator):
    """Busca e listagem seguem no cliente leve (confirmado ao vivo: as duas
    funcionam com `cloudscraper`) — só `resolver_midia` precisa de navegador."""
    assert extrator.exige_navegador_para_midia is True
    assert extrator.exige_navegador is False


def test_diferencia_versao(extrator):
    """AnimesDrive separa legendado de dublado no próprio slug/título — mesma
    capability que o AnimeFire também acabou confirmando (`animefire.py`)."""
    assert extrator.diferencia_versao is True


def test_resolver_midia_devolve_a_url_e_os_cabecalhos_observados(extrator):
    """O `LinkDeMidia` sai da requisição que a própria página fez — inclusive o
    `Referer`, que ao vivo é só a origem (`https://animesdrive.online/`) e não a
    URL do embed nem a do episódio."""
    url_episodio = f"{extrator.BASE_URL}/episodio/tensei-shitara-slime-datta-ken-episodio-1"
    capturada = MidiaCapturada(
        url="https://mangas.cloud/Animes/Letra-T/Tensei/01.mp4",
        cabecalhos={"User-Agent": "Chrome/150", "Referer": "https://animesdrive.online/"},
    )
    cliente = _ClienteNavegadorFalso(
        html=_ler_fixture("episodio_tres_servidores.html"), capturada=capturada
    )

    link = extrator.resolver_midia(cliente, url_episodio)

    assert link.url == capturada.url
    assert link.cabecalhos == capturada.cabecalhos
    assert cliente.pedidos == [(url_episodio, ("youtube.com", "youtu.be"), 90)]


def test_resolver_midia_sem_iframe_nao_gasta_o_navegador(extrator):
    """Página sem player falha em ~1s como `EstruturaDoSiteMudou` (não retentável,
    aciona o fallback pro próximo site) em vez de gastar a janela inteira de
    captura esperando mídia que não vem."""
    url_episodio = f"{extrator.BASE_URL}/episodio/tensei-shitara-slime-datta-ken-episodio-1"
    cliente = _ClienteNavegadorFalso(
        html=_ler_fixture("episodio_sem_iframe.html"), capturada=None
    )

    with pytest.raises(EstruturaDoSiteMudou) as excinfo:
        extrator.resolver_midia(cliente, url_episodio)

    assert "nenhum iframe de player" in str(excinfo.value)
    assert excinfo.value.permite_retentativa is False
    assert excinfo.value.dominio == "animesdrive.online"
    assert cliente.pedidos == []


def test_resolver_midia_com_so_trailer_do_youtube_nao_gasta_o_navegador(extrator):
    url_episodio = f"{extrator.BASE_URL}/episodio/tensei-shitara-slime-datta-ken-episodio-1"
    html = """
    <div class="player-tabs">
      <iframe src="about:blank"></iframe>
      <iframe src="https://www.youtube.com/embed/dQw4w9WgXcQ"></iframe>
    </div>
    """
    cliente = _ClienteNavegadorFalso(html=html, capturada=None)

    with pytest.raises(EstruturaDoSiteMudou):
        extrator.resolver_midia(cliente, url_episodio)

    assert cliente.pedidos == []


def test_resolver_midia_com_cliente_sem_captura_falha_sem_retentativa(extrator, cliente_falso):
    """Contrato quebrado (`resiliencia` entregou o cliente leve apesar de
    `exige_navegador_para_midia`), não falha de site: repetir com o mesmo cliente
    repetiria o erro, então não é retentável e não deve contar no circuit breaker."""
    url_episodio = f"{extrator.BASE_URL}/episodio/tensei-shitara-slime-datta-ken-episodio-1"
    cliente = cliente_falso(
        html_por_url={url_episodio: _ler_fixture("episodio_tres_servidores.html")}
    )

    with pytest.raises(FalhaDeExtracao) as excinfo:
        extrator.resolver_midia(cliente, url_episodio)

    assert "exige cliente de navegador" in str(excinfo.value)
    assert excinfo.value.permite_retentativa is False


def test_resolver_midia_sem_midia_observada_e_retentavel(extrator):
    """Player presente mas nenhuma requisição de mídia observada é transitório
    (anúncio travou, rede lenta) — retentável, diferente de estrutura mudada."""
    url_episodio = f"{extrator.BASE_URL}/episodio/tensei-shitara-slime-datta-ken-episodio-1"
    cliente = _ClienteNavegadorFalso(
        html=_ler_fixture("episodio_um_servidor.html"), capturada=None
    )

    with pytest.raises(FalhaDeExtracao) as excinfo:
        extrator.resolver_midia(cliente, url_episodio)

    assert excinfo.value.permite_retentativa is True
    assert cliente.pedidos == [(url_episodio, ("youtube.com", "youtu.be"), 90)]

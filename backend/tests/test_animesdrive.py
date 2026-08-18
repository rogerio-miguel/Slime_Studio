"""Testes de parsing de `extractors/animesdrive.py`, sem rede — `ClienteFalso`
(via fixture `cliente_falso` de `conftest.py`) devolve fixtures HTML escritas
à mão em `tests/fixtures/animesdrive/`."""

from pathlib import Path

import pytest

from core.erros import EstruturaDoSiteMudou, FonteNaoEncontrada
from extractors.animesdrive import AnimesDriveProvider
from extractors.base import EpisodioRemoto, ResultadoBusca

_FIXTURES = Path(__file__).parent / "fixtures" / "animesdrive"


def _ler_fixture(nome: str) -> str:
    return (_FIXTURES / nome).read_text(encoding="utf-8")


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
        ),
        ResultadoBusca(
            titulo_exibicao="Tensei Shitara Slime Datta Ken Dublado",
            identificador="tensei-shitara-slime-datta-ken-dublado",
            url="https://animesdrive.online/anime/tensei-shitara-slime-datta-ken-dublado",
            capa_url="https://animesdrive.online/capa2.jpg",
        ),
    ]


def test_buscar_absolutiza_capa_nas_3_formas_de_src(extrator, cliente_falso):
    """`busca.html` só cobre path relativo (`/capa1.jpg`) — protocolo-relativo
    (`//host/...`) e URL já absoluta também precisam sair intactos/absolutizados
    de `urljoin`, e `src` só-espaço deve virar `capa_url=None` (não a
    homepage)."""
    html = """
    <div class="result-item"><article>
      <a href="https://animesdrive.online/anime/relativo">
        <div class="thumb"><img src="/relativo.jpg"></div>
        <div class="title">Relativo</div>
      </a>
    </article></div>
    <div class="result-item"><article>
      <a href="https://animesdrive.online/anime/protocolo-relativo">
        <div class="thumb"><img src="//cdn.animesdrive.online/protocolo.jpg"></div>
        <div class="title">Protocolo Relativo</div>
      </a>
    </article></div>
    <div class="result-item"><article>
      <a href="https://animesdrive.online/anime/absoluto">
        <div class="thumb"><img src="https://cdn.outra.com/absoluta.jpg"></div>
        <div class="title">Absoluto</div>
      </a>
    </article></div>
    <div class="result-item"><article>
      <a href="https://animesdrive.online/anime/src-vazio">
        <div class="thumb"><img src="   "></div>
        <div class="title">Src Vazio</div>
      </a>
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
    html = """
    <a href="https://animesdrive.online/episodio/tensei-shitara-slime-datta-ken-episodio-7">
      Episódio 7
    </a>
    <a href="https://animesdrive.online/episodio/tensei-shitara-slime-datta-ken-episodio-07">
      Episódio 07
    </a>
    """
    url_anime = f"{extrator.BASE_URL}/anime/{identificador}"
    cliente = cliente_falso(html_por_url={url_anime: html})

    episodios = extrator.listar_episodios(cliente, identificador)

    assert [(ep.rotulo, ep.numero) for ep in episodios] == [("7", 7), ("07", 7)]


def test_listar_episodios_aceita_url_com_barra_final(extrator, cliente_falso):
    """Regressão da hipótese 2: `_REGEX_EPISODIO` rejeitava indevidamente uma URL
    de episódio terminada em `/`."""
    identificador = "tensei-shitara-slime-datta-ken"
    html = """
    <a href="https://animesdrive.online/episodio/tensei-shitara-slime-datta-ken-episodio-1/">
      Episódio 1
    </a>
    """
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


def test_resolver_midia_tres_servidores_cita_os_tres_hosts(extrator, cliente_falso):
    url_episodio = f"{extrator.BASE_URL}/episodio/tensei-shitara-slime-datta-ken-episodio-1"
    cliente = cliente_falso(
        html_por_url={url_episodio: _ler_fixture("episodio_tres_servidores.html")}
    )

    with pytest.raises(EstruturaDoSiteMudou) as excinfo:
        extrator.resolver_midia(cliente, url_episodio)

    mensagem = str(excinfo.value)
    assert "blogger.com" in mensagem
    assert "animeshd.cloud" in mensagem
    assert "animes.strp2p.com" in mensagem


def test_resolver_midia_um_servidor_cita_o_host(extrator, cliente_falso):
    url_episodio = f"{extrator.BASE_URL}/episodio/tensei-shitara-slime-datta-ken-episodio-1"
    cliente = cliente_falso(
        html_por_url={url_episodio: _ler_fixture("episodio_um_servidor.html")}
    )

    with pytest.raises(EstruturaDoSiteMudou) as excinfo:
        extrator.resolver_midia(cliente, url_episodio)

    assert "blogger.com" in str(excinfo.value)


def test_resolver_midia_sem_iframe_levanta_mensagem_de_estrutura(extrator, cliente_falso):
    url_episodio = f"{extrator.BASE_URL}/episodio/tensei-shitara-slime-datta-ken-episodio-1"
    cliente = cliente_falso(
        html_por_url={url_episodio: _ler_fixture("episodio_sem_iframe.html")}
    )

    with pytest.raises(EstruturaDoSiteMudou) as excinfo:
        extrator.resolver_midia(cliente, url_episodio)

    assert "nenhum iframe de player" in str(excinfo.value)


def test_mensagem_de_estrutura_e_de_capacidade_sao_textos_distintos(extrator, cliente_falso):
    url_episodio = f"{extrator.BASE_URL}/episodio/tensei-shitara-slime-datta-ken-episodio-1"

    cliente_sem_iframe = cliente_falso(
        html_por_url={url_episodio: _ler_fixture("episodio_sem_iframe.html")}
    )
    with pytest.raises(EstruturaDoSiteMudou) as excinfo_estrutura:
        extrator.resolver_midia(cliente_sem_iframe, url_episodio)

    cliente_com_servidor = cliente_falso(
        html_por_url={url_episodio: _ler_fixture("episodio_um_servidor.html")}
    )
    with pytest.raises(EstruturaDoSiteMudou) as excinfo_capacidade:
        extrator.resolver_midia(cliente_com_servidor, url_episodio)

    mensagem_estrutura = str(excinfo_estrutura.value)
    mensagem_capacidade = str(excinfo_capacidade.value)
    assert mensagem_estrutura != mensagem_capacidade
    assert "blogger.com" not in mensagem_estrutura
    assert "blogger.com" in mensagem_capacidade


def test_estrutura_do_site_mudou_nao_permite_retentativa_e_tem_dominio(extrator, cliente_falso):
    url_episodio = f"{extrator.BASE_URL}/episodio/tensei-shitara-slime-datta-ken-episodio-1"
    cliente = cliente_falso(
        html_por_url={url_episodio: _ler_fixture("episodio_sem_iframe.html")}
    )

    with pytest.raises(EstruturaDoSiteMudou) as excinfo:
        extrator.resolver_midia(cliente, url_episodio)

    assert excinfo.value.permite_retentativa is False
    assert excinfo.value.dominio == "animesdrive.online"

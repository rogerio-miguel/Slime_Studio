"""Testes de parsing de `extractors/animesdrive.py`, sem rede — `ClienteFalso`
(via fixture `cliente_falso` de `conftest.py`) devolve fixtures HTML escritas
à mão em `tests/fixtures/animesdrive/`."""

from pathlib import Path

import pytest

from core.erros import EstruturaDoSiteMudou
from extractors.animesdrive import AnimesDriveProvider
from extractors.base import EpisodioRemoto, ResultadoBusca

_FIXTURES = Path(__file__).parent / "fixtures" / "animesdrive"


def _ler_fixture(nome: str) -> str:
    return (_FIXTURES / nome).read_text(encoding="utf-8")


@pytest.fixture
def extrator() -> AnimesDriveProvider:
    return AnimesDriveProvider()


def test_buscar_com_resultado_devolve_candidatos(extrator, cliente_falso):
    url_busca = f"{extrator.BASE_URL}/?s=Tensei+Shitara+Slime+Datta+Ken"
    cliente = cliente_falso(html_por_url={url_busca: _ler_fixture("busca.html")})

    resultados = extrator.buscar(cliente, "Tensei Shitara Slime Datta Ken")

    assert resultados == [
        ResultadoBusca(
            titulo_exibicao="Tensei Shitara Slime Datta Ken",
            identificador="tensei-shitara-slime-datta-ken",
            url="https://animesdrive.online/anime/tensei-shitara-slime-datta-ken",
        ),
        ResultadoBusca(
            titulo_exibicao="Tensei Shitara Slime Datta Ken Dublado",
            identificador="tensei-shitara-slime-datta-ken-dublado",
            url="https://animesdrive.online/anime/tensei-shitara-slime-datta-ken-dublado",
        ),
    ]


def test_buscar_sem_resultado_devolve_lista_vazia_mesmo_com_widget(extrator, cliente_falso):
    """Regressão do fallback perigoso (`article.w_item_a` é o widget de sidebar
    "mais vistos", presente mesmo quando a busca não acha nada)."""
    url_busca = f"{extrator.BASE_URL}/?s=Anime+Inexistente"
    cliente = cliente_falso(html_por_url={url_busca: _ler_fixture("busca_vazia.html")})

    assert extrator.buscar(cliente, "Anime Inexistente") == []


def test_listar_episodios_deduplica_ordena_e_ignora_invalidos(extrator, cliente_falso):
    identificador = "tensei-shitara-slime-datta-ken"
    url_anime = f"{extrator.BASE_URL}/anime/{identificador}"
    cliente = cliente_falso(html_por_url={url_anime: _ler_fixture("episodios.html")})

    episodios = extrator.listar_episodios(cliente, identificador)

    assert episodios == [
        EpisodioRemoto(
            numero=1,
            url="https://animesdrive.online/episodio/tensei-shitara-slime-datta-ken-episodio-1",
        ),
        EpisodioRemoto(
            numero=2,
            url="https://animesdrive.online/episodio/tensei-shitara-slime-datta-ken-episodio-2",
        ),
        EpisodioRemoto(
            numero=3,
            url="https://animesdrive.online/episodio/tensei-shitara-slime-datta-ken-episodio-3",
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

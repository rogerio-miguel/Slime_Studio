"""Testes de parsing de `extractors/animesdrive.py`, sem rede — `ClienteFalso`
(via fixture `cliente_falso` de `conftest.py`) devolve fixtures HTML escritas
à mão em `tests/fixtures/animesdrive/`."""

from pathlib import Path

import pytest

from core.enums import VersaoEpisodio
from core.erros import EstruturaDoSiteMudou, FalhaDeExtracao, FonteNaoEncontrada, SessaoRejeitada
from extractors import animesdrive as modulo_animesdrive
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


class _RelogioFalso:
    """Substitui `time.monotonic` nos testes de orçamento compartilhado
    (`_ORCAMENTO_CAPTURAS_S`) — avança só quando mandado, nunca sozinho."""

    def __init__(self, inicio: float = 0.0) -> None:
        self.agora = inicio

    def monotonic(self) -> float:
        return self.agora

    def avancar(self, segundos: float) -> None:
        self.agora += segundos


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
    Chromium nenhum.

    `capturada=None` simula o navegador não observar mídia nenhuma (qualquer
    seletor). `capturada_por_seletor` simula sucesso condicionado ao seletor
    pedido (ex. FHD falha, HD funciona). `seletores_a_falhar` simula captura
    que levanta `FalhaDeExtracao` pra um seletor específico.
    """

    def __init__(
        self,
        *,
        html: str,
        capturada: MidiaCapturada | None = None,
        capturada_por_seletor: dict[str | None, MidiaCapturada] | None = None,
        seletores_a_falhar: set[str | None] | None = None,
        sessao_rejeitada_em: set[str | None] | None = None,
        relogio: _RelogioFalso | None = None,
    ) -> None:
        self._html = html
        self._capturada = capturada
        self._capturada_por_seletor = capturada_por_seletor or {}
        self._seletores_a_falhar = seletores_a_falhar or set()
        self._sessao_rejeitada_em = sessao_rejeitada_em or set()
        self._relogio = relogio
        self.pedidos: list[tuple[str, tuple[str, ...], str | None, int]] = []

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
        self,
        url_pagina: str,
        *,
        hosts_ignorados: tuple[str, ...] = (),
        seletor_para_ativar: str | None = None,
        timeout_s: int,
    ) -> MidiaCapturada:
        self.pedidos.append((url_pagina, hosts_ignorados, seletor_para_ativar, timeout_s))
        if seletor_para_ativar in self._sessao_rejeitada_em:
            self._consumir_janela(timeout_s)
            raise SessaoRejeitada(f"sessão rejeitada ao ativar {seletor_para_ativar}")
        if seletor_para_ativar in self._seletores_a_falhar:
            self._consumir_janela(timeout_s)
            raise FalhaDeExtracao(
                f"captura falhou para o seletor {seletor_para_ativar}", permite_retentativa=True
            )
        if seletor_para_ativar in self._capturada_por_seletor:
            return self._capturada_por_seletor[seletor_para_ativar]
        if self._capturada is None:
            self._consumir_janela(timeout_s)
            raise FalhaDeExtracao(
                f"nenhuma requisição de mídia observada em {url_pagina}",
                permite_retentativa=True,
            )
        return self._capturada

    def _consumir_janela(self, timeout_s: int) -> None:
        """Simula uma captura real que só desiste no fim da janela — sem isso um
        relógio falso instantâneo não consumiria o orçamento compartilhado entre
        tentativas, e `_janela_de_captura` calcularia o mesmo `restante` de novo
        pra cada candidato."""
        if self._relogio is not None:
            self._relogio.avancar(timeout_s)


def test_buscar_com_resultado_devolve_candidatos(extrator, cliente_falso):
    url_busca = f"{extrator.BASE_URL}/?s=Tensei+Shitara+Slime+Datta+Ken"
    cliente = cliente_falso(html_por_url={url_busca: _ler_fixture("busca.html")})

    resultados = extrator.buscar(cliente, "Tensei Shitara Slime Datta Ken")

    assert resultados == [
        ResultadoBusca(
            titulo_exibicao="Tensei Shitara Slime Datta Ken",
            identificador="tensei-shitara-slime-datta-ken",
            url="https://animesdrive.cloud/anime/tensei-shitara-slime-datta-ken",
            capa_url="https://animesdrive.cloud/capa1.jpg",
            versao=VersaoEpisodio.LEGENDADO,
        ),
        ResultadoBusca(
            titulo_exibicao="Tensei Shitara Slime Datta Ken Dublado",
            identificador="tensei-shitara-slime-datta-ken-dublado",
            url="https://animesdrive.cloud/anime/tensei-shitara-slime-datta-ken-dublado",
            capa_url="https://animesdrive.cloud/capa2.jpg",
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
        <a href="https://animesdrive.cloud/anime/relativo"><img src="/relativo.jpg"></a>
      </div></div>
      <div class="details"><div class="title">
        <a href="https://animesdrive.cloud/anime/relativo">Relativo</a>
      </div></div>
    </article></div>
    <div class="result-item"><article>
      <div class="image"><div class="thumbnail">
        <a href="https://animesdrive.cloud/anime/protocolo-relativo"
           ><img src="//cdn.animesdrive.cloud/protocolo.jpg"></a>
      </div></div>
      <div class="details"><div class="title">
        <a href="https://animesdrive.cloud/anime/protocolo-relativo">Protocolo Relativo</a>
      </div></div>
    </article></div>
    <div class="result-item"><article>
      <div class="image"><div class="thumbnail">
        <a href="https://animesdrive.cloud/anime/absoluto"><img src="https://cdn.outra.com/absoluta.jpg"></a>
      </div></div>
      <div class="details"><div class="title">
        <a href="https://animesdrive.cloud/anime/absoluto">Absoluto</a>
      </div></div>
    </article></div>
    <div class="result-item"><article>
      <div class="image"><div class="thumbnail">
        <a href="https://animesdrive.cloud/anime/src-vazio"><img src="   "></a>
      </div></div>
      <div class="details"><div class="title">
        <a href="https://animesdrive.cloud/anime/src-vazio">Src Vazio</a>
      </div></div>
    </article></div>
    """
    url_busca = f"{extrator.BASE_URL}/?s=teste"
    cliente = cliente_falso(html_por_url={url_busca: html})

    resultados = extrator.buscar(cliente, "teste")

    capas = {resultado.identificador: resultado.capa_url for resultado in resultados}
    assert capas["relativo"] == "https://animesdrive.cloud/relativo.jpg"
    assert capas["protocolo-relativo"] == "https://cdn.animesdrive.cloud/protocolo.jpg"
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
    produto: sem seção "especial" separada, só não capturável ainda).

    A thumb do card (`<img src="/thumbN.jpg">`, no `<a>` irmão do título) é
    reanexada absolutizada; o card "especial" não tem `<img>` → `thumb_url=None`."""
    identificador = "tensei-shitara-slime-datta-ken"
    url_anime = f"{extrator.BASE_URL}/anime/{identificador}"
    cliente = cliente_falso(html_por_url={url_anime: _ler_fixture("episodios.html")})

    episodios = extrator.listar_episodios(cliente, identificador)

    assert episodios == [
        EpisodioRemoto(
            rotulo="1",
            numero=1,
            url="https://animesdrive.cloud/episodio/tensei-shitara-slime-datta-ken-episodio-1",
            thumb_url="https://animesdrive.cloud/thumb1.jpg",
        ),
        EpisodioRemoto(
            rotulo="2",
            numero=2,
            url="https://animesdrive.cloud/episodio/tensei-shitara-slime-datta-ken-episodio-2",
            thumb_url="https://animesdrive.cloud/thumb2.jpg",
        ),
        EpisodioRemoto(
            rotulo="3",
            numero=3,
            url="https://animesdrive.cloud/episodio/tensei-shitara-slime-datta-ken-episodio-3",
            thumb_url="https://animesdrive.cloud/thumb3.jpg",
        ),
        EpisodioRemoto(
            rotulo="especial",
            numero=None,
            url=(
                "https://animesdrive.cloud/episodio/"
                "tensei-shitara-slime-datta-ken-episodio-especial"
            ),
            thumb_url=None,
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
        "https://animesdrive.cloud/episodio/tensei-shitara-slime-datta-ken-episodio-7",
        "https://animesdrive.cloud/episodio/tensei-shitara-slime-datta-ken-episodio-07",
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
        "https://animesdrive.cloud/episodio/tensei-shitara-slime-datta-ken-episodio-1/"
    )
    url_anime = f"{extrator.BASE_URL}/anime/{identificador}"
    cliente = cliente_falso(html_por_url={url_anime: html})

    episodios = extrator.listar_episodios(cliente, identificador)

    assert episodios == [
        EpisodioRemoto(
            rotulo="1",
            numero=1,
            url="https://animesdrive.cloud/episodio/tensei-shitara-slime-datta-ken-episodio-1/",
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
        "https://animesdrive.cloud/episodio/one-piece-dublado-episodio-1",
        "https://animesdrive.cloud/episodio/one-piece-dublado-episodio-2",
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
        "https://animesdrive.cloud/episodio/tensei-shitara-slime-datta-ken-4th-season-episodio-1",
        "https://animesdrive.cloud/episodio/tensei-shitara-slime-datta-ken-4th-season-episodio-2",
        "https://animesdrive.cloud/episodio/"
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
                "https://animesdrive.cloud/episodio/"
                "tensei-shitara-slime-datta-ken-4th-season-episodio-1"
            ),
            versao=VersaoEpisodio.LEGENDADO,
        ),
        EpisodioRemoto(
            rotulo="1",
            numero=1,
            url=(
                "https://animesdrive.cloud/episodio/"
                "tensei-shitara-slime-datta-ken-4th-season-dublado-episodio-1"
            ),
            versao=VersaoEpisodio.DUBLADO,
        ),
        EpisodioRemoto(
            rotulo="2",
            numero=2,
            url=(
                "https://animesdrive.cloud/episodio/"
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
        "https://animesdrive.cloud/episodio/tensei-shitara-slime-datta-ken-ova-episodio-1",
        "https://animesdrive.cloud/episodio/tensei-shitara-slime-datta-ken-ova-episodio-2",
        "https://animesdrive.cloud/episodio/tensei-shitara-slime-datta-ken-movie-episodio-1",
    )
    url_anime = f"{extrator.BASE_URL}/anime/{identificador}"
    cliente = cliente_falso(html_por_url={url_anime: html})

    episodios = extrator.listar_episodios(cliente, identificador)

    assert [episodio.url for episodio in episodios] == [
        "https://animesdrive.cloud/episodio/tensei-shitara-slime-datta-ken-ova-episodio-1",
        "https://animesdrive.cloud/episodio/tensei-shitara-slime-datta-ken-ova-episodio-2",
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
    `Referer`, que ao vivo é só a origem (`https://animesdrive.cloud/`) e não a
    URL do embed nem a do episódio."""
    url_episodio = f"{extrator.BASE_URL}/episodio/tensei-shitara-slime-datta-ken-episodio-1"
    capturada = MidiaCapturada(
        url="https://mangas.cloud/Animes/Letra-T/Tensei/01.mp4",
        cabecalhos={"User-Agent": "Chrome/150", "Referer": "https://animesdrive.cloud/"},
    )
    cliente = _ClienteNavegadorFalso(
        html=_ler_fixture("episodio_tres_servidores.html"), capturada=capturada
    )

    link = extrator.resolver_midia(cliente, url_episodio)

    assert link.url == capturada.url
    assert link.cabecalhos == capturada.cabecalhos
    assert cliente.pedidos == [(url_episodio, ("youtube.com", "youtu.be"), None, 90)]


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
    assert excinfo.value.dominio == "animesdrive"
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
    assert cliente.pedidos == [(url_episodio, ("youtube.com", "youtu.be"), None, 90)]


def test_resolver_midia_prefere_fhd_de_video_direto_sem_gastar_navegador(extrator, monkeypatch):
    """`episodio_qualidades.html`: SD é o botão `is-active` (o default ruim),
    mas a escolha ignora isso e vai direto pro FHD de vídeo direto — sem
    sequer chamar `capturar_midia`."""
    monkeypatch.setattr(modulo_animesdrive, "responde", lambda url, cabecalhos: True)
    url_episodio = f"{extrator.BASE_URL}/episodio/ep-16"
    cliente = _ClienteNavegadorFalso(html=_ler_fixture("episodio_qualidades.html"))

    link = extrator.resolver_midia(cliente, url_episodio)

    assert link.url == "https://aniplay.online/fhd.mp4"
    assert link.cabecalhos == {
        "User-Agent": "NavegadorFalso/1.0",
        "Referer": "https://animesdrive.cloud/",
    }
    assert cliente.pedidos == []


def test_resolver_midia_cai_pra_hd_quando_o_fhd_nao_responde(extrator, monkeypatch):
    """URL estática do FHD morta (`responde` falso) — cai pro HD (iframe),
    nunca pro SD `is-active`."""
    monkeypatch.setattr(modulo_animesdrive, "responde", lambda url, cabecalhos: False)
    capturada_hd = MidiaCapturada(
        url="https://draft.blogger.com/hd_resolvido.mp4",
        cabecalhos={"User-Agent": "NavegadorFalso/1.0", "Referer": "https://animesdrive.cloud/"},
    )
    cliente = _ClienteNavegadorFalso(
        html=_ler_fixture("episodio_qualidades.html"),
        capturada_por_seletor={'[data-animeq-switch="1"]': capturada_hd},
    )
    url_episodio = f"{extrator.BASE_URL}/episodio/ep-16"

    link = extrator.resolver_midia(cliente, url_episodio)

    assert link.url == capturada_hd.url
    assert "animes.click" not in link.url
    seletores_pedidos = [pedido[2] for pedido in cliente.pedidos]
    assert seletores_pedidos == ['[data-animeq-switch="1"]']


def test_resolver_midia_nunca_usa_sd_mesmo_sendo_o_servidor_ativo(extrator, monkeypatch):
    """FHD (vídeo direto) e HD (captura) falham os dois — a exceção final é
    retentável, e o SD `is-active` nunca chega a ser tentado."""
    monkeypatch.setattr(modulo_animesdrive, "responde", lambda url, cabecalhos: False)
    cliente = _ClienteNavegadorFalso(
        html=_ler_fixture("episodio_qualidades.html"),
        seletores_a_falhar={'[data-animeq-switch="1"]'},
    )
    url_episodio = f"{extrator.BASE_URL}/episodio/ep-16"

    with pytest.raises(FalhaDeExtracao) as excinfo:
        extrator.resolver_midia(cliente, url_episodio)

    assert excinfo.value.permite_retentativa is True
    assert all(pedido[2] != '[data-animeq-switch="0"]' for pedido in cliente.pedidos)


def test_resolver_midia_so_com_sd_falha_sem_gastar_navegador(extrator):
    """`episodio_so_sd.html`: só SD e Mobile/Celular (os dois abaixo do piso) —
    falha em ~1s, não retentável, sem chamar `capturar_midia` nenhuma vez."""
    cliente = _ClienteNavegadorFalso(html=_ler_fixture("episodio_so_sd.html"))
    url_episodio = f"{extrator.BASE_URL}/episodio/so-sd"

    with pytest.raises(FalhaDeExtracao) as excinfo:
        extrator.resolver_midia(cliente, url_episodio)

    assert excinfo.value.permite_retentativa is False
    assert cliente.pedidos == []
    assert "SD" in str(excinfo.value)


def test_resolver_midia_tenta_video_direto_antes_de_iframe_no_mesmo_tier(extrator, monkeypatch):
    """`episodio_qualidades_fhd_iframe.html`: 3 candidatos FHD (1 vídeo direto,
    2 iframes) — a 1ª coisa conferida é a URL direta; falhando ela, a ordem
    das capturas segue a ordem da página entre os iframes do mesmo tier. O
    Mobile/Celular (abaixo do piso) nunca aparece."""
    monkeypatch.setattr(modulo_animesdrive, "responde", lambda url, cabecalhos: False)
    capturada_final = MidiaCapturada(
        url="https://animes.strp2p.com/final.mp4",
        cabecalhos={"User-Agent": "NavegadorFalso/1.0", "Referer": "https://animesdrive.cloud/"},
    )
    cliente = _ClienteNavegadorFalso(
        html=_ler_fixture("episodio_qualidades_fhd_iframe.html"),
        seletores_a_falhar={'[data-animeq-switch="2"]'},
        capturada_por_seletor={'[data-animeq-switch="3"]': capturada_final},
    )
    url_episodio = f"{extrator.BASE_URL}/episodio/ep-01"

    link = extrator.resolver_midia(cliente, url_episodio)

    assert link.url == capturada_final.url
    seletores_pedidos = [pedido[2] for pedido in cliente.pedidos]
    assert seletores_pedidos == ['[data-animeq-switch="2"]', '[data-animeq-switch="3"]']


def test_resolver_midia_divide_o_orcamento_entre_capturas(extrator, monkeypatch):
    """Vídeo direto e os 2 iframes FHD falhando: soma dos `timeout_s` pedidos
    cabe no orçamento, cada um positivo e no máximo 90s, e no máximo
    `_MAX_CAPTURAS_POR_EPISODIO` pedidos de captura.

    Relógio falso: uma captura real só desiste no fim da própria janela, então
    o orçamento compartilhado só encolhe de verdade se o relógio avançar junto
    — sem isso um fake instantâneo computaria o mesmo `restante` pra cada
    candidato e a soma dos timeouts poderia passar do orçamento à toa."""
    relogio = _RelogioFalso()
    monkeypatch.setattr(modulo_animesdrive.time, "monotonic", relogio.monotonic)
    monkeypatch.setattr(modulo_animesdrive, "responde", lambda url, cabecalhos: False)
    cliente = _ClienteNavegadorFalso(
        html=_ler_fixture("episodio_qualidades_fhd_iframe.html"),
        seletores_a_falhar={'[data-animeq-switch="2"]', '[data-animeq-switch="3"]'},
        relogio=relogio,
    )
    url_episodio = f"{extrator.BASE_URL}/episodio/ep-01"

    with pytest.raises(FalhaDeExtracao):
        extrator.resolver_midia(cliente, url_episodio)

    timeouts = [pedido[3] for pedido in cliente.pedidos]
    assert len(timeouts) <= modulo_animesdrive._MAX_CAPTURAS_POR_EPISODIO
    assert all(0 < t <= 90 for t in timeouts)
    assert sum(timeouts) <= modulo_animesdrive._ORCAMENTO_CAPTURAS_S


def test_resolver_midia_com_um_candidato_so_mantem_a_janela_calibrada_de_90s(extrator):
    """Modo A com um único candidato de navegador: a janela calculada dá
    min(90, 120) = 90 — idêntica a hoje, sem regressão da calibração medida."""
    html = """
    <div class="animeq-player">
      <button data-animeq-switch="0" data-source-name="FHD" class="is-active">FHD</button>
      <div data-animeq-source="0" class="is-active">
        <iframe data-lazy-src="https://animeshd.cloud/embed/unico" src="about:blank"></iframe>
      </div>
    </div>
    """
    capturada = MidiaCapturada(
        url="https://animeshd.cloud/final.mp4",
        cabecalhos={"User-Agent": "NavegadorFalso/1.0", "Referer": "https://animesdrive.cloud/"},
    )
    cliente = _ClienteNavegadorFalso(
        html=html, capturada_por_seletor={'[data-animeq-switch="0"]': capturada}
    )
    url_episodio = f"{extrator.BASE_URL}/episodio/unico"

    extrator.resolver_midia(cliente, url_episodio)

    assert cliente.pedidos == [
        (url_episodio, ("youtube.com", "youtu.be"), '[data-animeq-switch="0"]', 90)
    ]


def test_resolver_midia_sem_rotulo_de_qualidade_usa_o_servidor_disponivel(extrator):
    """Página modo A com um único botão "Dublado" (sem vocabulário de
    qualidade, `DESCONHECIDA`) — continua funcionando via o ramo de fallback
    (D2): captura pedida com o seletor dele."""
    html = """
    <div class="animeq-player">
      <button data-animeq-switch="0" data-source-name="Dublado" class="is-active">Dublado</button>
      <div data-animeq-source="0" class="is-active">
        <iframe data-lazy-src="https://blogger.com/video.g?token=dublado" src="about:blank">
        </iframe>
      </div>
    </div>
    """
    capturada = MidiaCapturada(
        url="https://blogger.com/final.mp4",
        cabecalhos={"User-Agent": "NavegadorFalso/1.0", "Referer": "https://animesdrive.cloud/"},
    )
    cliente = _ClienteNavegadorFalso(
        html=html, capturada_por_seletor={'[data-animeq-switch="0"]': capturada}
    )
    url_episodio = f"{extrator.BASE_URL}/episodio/dublado"

    link = extrator.resolver_midia(cliente, url_episodio)

    assert link.url == capturada.url
    assert cliente.pedidos[0][2] == '[data-animeq-switch="0"]'


def test_resolver_midia_repassa_sessao_rejeitada_sem_tentar_o_proximo(extrator, monkeypatch):
    """`SessaoRejeitada` na 1ª captura de navegador propaga imediatamente —
    o próximo candidato bateria na mesma parede de sessão."""
    monkeypatch.setattr(modulo_animesdrive, "responde", lambda url, cabecalhos: False)
    cliente = _ClienteNavegadorFalso(
        html=_ler_fixture("episodio_qualidades_fhd_iframe.html"),
        sessao_rejeitada_em={'[data-animeq-switch="2"]'},
    )
    url_episodio = f"{extrator.BASE_URL}/episodio/ep-01"

    with pytest.raises(SessaoRejeitada):
        extrator.resolver_midia(cliente, url_episodio)

    assert len(cliente.pedidos) == 1


def test_candidatos_de_servidor_indice_duplicado_usa_o_primeiro_e_loga_warning(
    extrator, monkeypatch, caplog
):
    """Caso #9 (PLANO_ANIMESDRIVE.md §4): dois botões com o mesmo
    `data-animeq-switch` — o 2º é ignorado com warning (o `continue` pula
    antes de ler o painel dele), a resolução usa só o candidato do 1º."""
    monkeypatch.setattr(modulo_animesdrive, "responde", lambda url, cabecalhos: True)
    html = """
    <div class="animeq-player">
      <button data-animeq-switch="0" data-source-name="FHD" class="is-active">FHD</button>
      <div data-animeq-source="0" class="is-active">
        <video><source src="https://cdn.example.com/primeiro.mp4"></video>
      </div>
      <button data-animeq-switch="0" data-source-name="FHD Duplicado">FHD Duplicado</button>
      <div data-animeq-source="0">
        <video><source src="https://cdn.example.com/segundo.mp4"></video>
      </div>
    </div>
    """
    url_episodio = f"{extrator.BASE_URL}/episodio/indice-duplicado"
    cliente = _ClienteNavegadorFalso(html=html)

    with caplog.at_level("WARNING"):
        link = extrator.resolver_midia(cliente, url_episodio)

    assert link.url == "https://cdn.example.com/primeiro.mp4"
    assert "dois botões com data-animeq-switch" in caplog.text
    assert cliente.pedidos == []  # vídeo direto: nem chega a pedir captura


def test_candidatos_de_servidor_sem_data_source_name_usa_texto_do_botao(extrator):
    """Caso #10 (PLANO_ANIMESDRIVE.md §4): botão sem `data-source-name` cai
    pro texto do botão como rótulo — normalizado (`" ".join(...split())`),
    inclusive quando o texto vem quebrado em várias linhas no HTML."""
    html = """
    <div class="animeq-player">
      <button data-animeq-switch="0" class="is-active">
        SD
        Baixa
      </button>
      <div data-animeq-source="0" class="is-active">
        <video><source src="https://animes.click/sem-nome.mp4"></video>
      </div>
    </div>
    """
    url_episodio = f"{extrator.BASE_URL}/episodio/sem-data-source-name"
    cliente = _ClienteNavegadorFalso(html=html)

    with pytest.raises(FalhaDeExtracao) as excinfo:
        extrator.resolver_midia(cliente, url_episodio)

    assert "SD Baixa" in str(excinfo.value)
    assert excinfo.value.permite_retentativa is False
    assert cliente.pedidos == []


def test_candidatos_de_servidor_reconhece_iframe_com_data_animeq_src(extrator):
    """Regressão do painel HD real (migração 2026-08-25): o `src` cru fica
    `about:blank` e o `data-lazy-src` de sempre não existe — o site usa
    `data-animeq-src` como lazy-src do próprio player `animeq`. Sem esse
    atributo em `_ATRIBUTOS_DE_IFRAME`, o painel era descartado por inteiro
    (nem vídeo direto nem iframe utilizável)."""
    html = """
    <div class="animeq-player">
      <button data-animeq-switch="1" data-source-name="HD" class="is-active">HD</button>
      <div class="animeq-player__source" data-animeq-source="1" hidden="">
        <div class="animeq-player__media animeq-player__media--iframe">
          <iframe class="animeq-player__iframe" data-animeq-frame=""
            data-animeq-src="https://www.blogger.com/video.g?token=abc123"
            src="about:blank" title="HD"></iframe>
        </div>
      </div>
    </div>
    """
    url_episodio = f"{extrator.BASE_URL}/episodio/painel-hd"

    candidatos = extrator._candidatos_de_servidor(html, url_episodio)

    assert len(candidatos) == 1
    assert candidatos[0].tem_iframe is True
    assert candidatos[0].url_video is None
    assert candidatos[0].qualidade == modulo_animesdrive.NivelDeQualidade.HD


def test_candidatos_de_servidor_reconhece_videojs_host_como_video_direto(extrator):
    """Regressão do painel FHD real (migração 2026-08-25): 3º padrão de player,
    sem `<video>` nem `<iframe>` — um `<div data-animeq-videojs-host
    data-video-src>` montado por Video.js. `_url_de_video_direto` precisa
    reconhecer esse padrão como fallback do `<video><source>` de sempre."""
    html = """
    <div class="animeq-player">
      <button data-animeq-switch="2" data-source-name="FHD" class="is-active">FHD</button>
      <div class="animeq-player__source" data-animeq-source="2" hidden="">
        <div class="animeq-player__media animeq-player__media--videojs">
          <div class="animeq-player__videojs-host" data-animeq-videojs-host=""
            data-video-src="https://ccdn.xyz/stream.php?f=video.mp4"
            data-video-title="FHD"></div>
        </div>
      </div>
    </div>
    """
    url_episodio = f"{extrator.BASE_URL}/episodio/painel-fhd"

    candidatos = extrator._candidatos_de_servidor(html, url_episodio)

    assert len(candidatos) == 1
    assert candidatos[0].url_video == "https://ccdn.xyz/stream.php?f=video.mp4"
    assert candidatos[0].qualidade == modulo_animesdrive.NivelDeQualidade.FHD


def test_resolver_midia_legado_sem_seletor_de_qualidade_segue_como_antes(extrator):
    """`episodio_um_servidor.html` não tem `[data-animeq-switch]` — modo B,
    zero comportamento novo: uma captura, sem seletor."""
    url_episodio = f"{extrator.BASE_URL}/episodio/tensei-shitara-slime-datta-ken-episodio-1"
    capturada = MidiaCapturada(
        url="https://mangas.cloud/final.mp4",
        cabecalhos={"User-Agent": "NavegadorFalso/1.0", "Referer": "https://animesdrive.cloud/"},
    )
    cliente = _ClienteNavegadorFalso(
        html=_ler_fixture("episodio_um_servidor.html"), capturada=capturada
    )

    link = extrator.resolver_midia(cliente, url_episodio)

    assert link.url == capturada.url
    assert cliente.pedidos == [(url_episodio, ("youtube.com", "youtu.be"), None, 90)]

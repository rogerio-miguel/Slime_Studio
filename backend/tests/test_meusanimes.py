"""Testes de parsing de `extractors/meusanimes.py`, sem rede — fixtures de HTML
estáticas (strings neste arquivo) servidas pelo `ClienteFalso` da fixture
`cliente_falso` (`conftest.py`)."""

import pytest

from core.enums import VersaoEpisodio
from core.erros import EstruturaDoSiteMudou, FalhaDeExtracao, FonteNaoEncontrada
from extractors import meusanimes as modulo_meusanimes
from extractors.base import EpisodioRemoto, LinkDeMidia, ResultadoBusca
from extractors.meusanimes import MeusAnimesProvider


@pytest.fixture
def extrator() -> MeusAnimesProvider:
    return MeusAnimesProvider()


class _ClienteQueLevanta404:
    """Fake mínimo de `ClienteDeSite` que simula HTTP 404 (`FonteNaoEncontrada`)
    — o `ClienteFalso` do conftest só devolve HTML pré-programado, nunca levanta."""

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


# --- buscar ------------------------------------------------------------------


_BUSCA_HTML = """
<!DOCTYPE html><html><body>
<div class="search-page">
  <div class="result-item"><article>
    <div class="image"><div class="thumbnail">
      <a href="https://meusanimes.blog/a/one-piece/">
        <img src="/capa/one-piece-150x150.jpg" alt="One Piece" /></a>
    </div></div>
    <div class="details">
      <div class="title"><a href="https://meusanimes.blog/a/one-piece/">One Piece</a></div>
      <div class="meta"><span class="rating">IMDb 8.7</span> <span class="year">1999</span></div>
    </div>
  </article></div>
  <div class="result-item"><article>
    <div class="image"><div class="thumbnail">
      <a href="https://meusanimes.blog/a/one-piece-dublado/">
        <img src="https://cdn.meusanimes.blog/op-dub-150x150.jpg" alt="One Piece Dublado" /></a>
    </div></div>
    <div class="details">
      <div class="title">
        <a href="https://meusanimes.blog/a/one-piece-dublado/">One Piece Dublado</a>
      </div>
      <div class="meta"><span class="year">1999</span></div>
    </div>
  </article></div>
</div>
</body></html>
"""


def test_buscar_parseia_cards_com_identificador_titulo_capa_e_versao(extrator, cliente_falso):
    """Card sem sufixo → LEGENDADO; card com " Dublado"/`-dublado` → DUBLADO.
    Capa relativa é absolutizada pela `BASE_URL`, capa já absoluta sai intacta."""
    url_busca = f"{extrator.BASE_URL}/?s=One+Piece"
    cliente = cliente_falso(html_por_url={url_busca: _BUSCA_HTML})

    resultados = extrator.buscar(cliente, "One Piece")

    assert resultados == [
        ResultadoBusca(
            titulo_exibicao="One Piece",
            identificador="one-piece",
            url="https://meusanimes.blog/a/one-piece/",
            capa_url="https://meusanimes.blog/capa/one-piece-150x150.jpg",
            versao=VersaoEpisodio.LEGENDADO,
        ),
        ResultadoBusca(
            titulo_exibicao="One Piece Dublado",
            identificador="one-piece-dublado",
            url="https://meusanimes.blog/a/one-piece-dublado/",
            capa_url="https://cdn.meusanimes.blog/op-dub-150x150.jpg",
            versao=VersaoEpisodio.DUBLADO,
        ),
    ]


def test_buscar_card_sem_img_devolve_capa_url_none(extrator, cliente_falso):
    html = """
    <div class="result-item"><article>
      <div class="image"><div class="thumbnail">
        <a href="https://meusanimes.blog/a/naruto/"></a>
      </div></div>
      <div class="details"><div class="title">
        <a href="https://meusanimes.blog/a/naruto/">Naruto</a>
      </div></div>
    </article></div>
    """
    url_busca = f"{extrator.BASE_URL}/?s=Naruto"
    cliente = cliente_falso(html_por_url={url_busca: html})

    (resultado,) = extrator.buscar(cliente, "Naruto")

    assert resultado.capa_url is None
    assert resultado.identificador == "naruto"


def test_buscar_ignora_link_que_nao_e_de_anime(extrator, cliente_falso):
    """Só href com `/a/` é candidato — link de categoria/página no mesmo bloco
    de resultados não vira `ResultadoBusca`."""
    html = """
    <div class="result-item"><article>
      <div class="details"><div class="title">
        <a href="https://meusanimes.blog/genero/acao/">Ação</a>
      </div></div>
    </article></div>
    <div class="result-item"><article>
      <div class="details"><div class="title">
        <a href="https://meusanimes.blog/a/bleach/">Bleach</a>
      </div></div>
    </article></div>
    """
    url_busca = f"{extrator.BASE_URL}/?s=acao"
    cliente = cliente_falso(html_por_url={url_busca: html})

    resultados = extrator.buscar(cliente, "acao")

    assert [r.identificador for r in resultados] == ["bleach"]


def test_buscar_sem_cards_devolve_lista_vazia(extrator, cliente_falso):
    html = '<html><body><div class="search-page"><p>Nada encontrado.</p></div></body></html>'
    url_busca = f"{extrator.BASE_URL}/?s=Inexistente"
    cliente = cliente_falso(html_por_url={url_busca: html})

    assert extrator.buscar(cliente, "Inexistente") == []


def test_buscar_404_devolve_lista_vazia_sem_levantar(extrator):
    assert extrator.buscar(_ClienteQueLevanta404(), "Anime Inexistente") == []


def test_buscar_erro_de_parsing_inesperado_vira_estrutura_do_site_mudou(
    extrator, cliente_falso, monkeypatch
):
    """A rede `except AttributeError` traduz qualquer quebra inesperada de
    parsing em `EstruturaDoSiteMudou` com o domínio certo, em vez de vazar o
    erro cru para o circuit breaker."""

    def _estoura(*_a, **_k):
        raise AttributeError("markup inesperado")

    monkeypatch.setattr(modulo_meusanimes, "inferir_versao", _estoura)
    url_busca = f"{extrator.BASE_URL}/?s=One+Piece"
    cliente = cliente_falso(html_por_url={url_busca: _BUSCA_HTML})

    with pytest.raises(EstruturaDoSiteMudou) as info:
        extrator.buscar(cliente, "One Piece")

    assert info.value.dominio == "meusanimes"
    assert info.value.permite_retentativa is False


# --- listar_episodios ------------------------------------------------------------


def _thumb_fake(href: str) -> str:
    """Thumb determinística a partir da cauda do href (`...-episodio-2/` → `ep2`)
    — o markup real do tema põe `<div class="imagen"><img src=...>` dentro de
    cada `<li>` de episódio."""
    cauda = href.rstrip("/").rsplit("-", 1)[-1]
    return f"https://meusanimes.blog/wp-content/uploads/ep{cauda}-300x170.jpg"


def _pagina_de_temporadas(*temporadas: list[str]) -> str:
    """Envelopa cada temporada (lista de hrefs de episódio) num `div.se-c`
    dentro de `#seasons` — a estrutura real do tema DooPlay de onde
    `listar_episodios` lê."""
    blocos = []
    for indice, hrefs in enumerate(temporadas, start=1):
        itens = "".join(
            f"<li class='mark-1'>"
            f"<div class='imagen'><img src='{_thumb_fake(href)}'></div>"
            f"<div class='numerando'>{indice} - {i}</div>"
            f"<div class='episodiotitle'><a href='{href}'>Episódio {i}</a>"
            f"<span class='date'>Oct. 02, 2018</span></div></li>"
            for i, href in enumerate(hrefs, start=1)
        )
        blocos.append(
            f"<div class='se-c'>"
            f"<div class='se-q'><span class='se-t se-o'>{indice}</span>"
            f"<span class='title'>Temporada {indice}</span></div>"
            f"<div class='se-a'><ul class='episodios'>{itens}</ul></div>"
            f"</div>"
        )
    return f"<div id='seasons'>{''.join(blocos)}</div>"


def test_listar_episodios_uma_temporada_ordena_e_extrai_numero_do_path(extrator, cliente_falso):
    identificador = "tensei-shitara-slime-datta-ken-dublado"
    html = _pagina_de_temporadas(
        [
            f"https://meusanimes.blog/e/{identificador}-1-episodio-2/",
            f"https://meusanimes.blog/e/{identificador}-1-episodio-1/",
            f"https://meusanimes.blog/e/{identificador}-1-episodio-3/",
        ]
    )
    url_anime = f"{extrator.BASE_URL}/a/{identificador}/"
    cliente = cliente_falso(html_por_url={url_anime: html})

    episodios = extrator.listar_episodios(cliente, identificador)

    assert episodios == [
        EpisodioRemoto(
            rotulo="1",
            numero=1,
            url=f"https://meusanimes.blog/e/{identificador}-1-episodio-1/",
            thumb_url="https://meusanimes.blog/wp-content/uploads/ep1-300x170.jpg",
        ),
        EpisodioRemoto(
            rotulo="2",
            numero=2,
            url=f"https://meusanimes.blog/e/{identificador}-1-episodio-2/",
            thumb_url="https://meusanimes.blog/wp-content/uploads/ep2-300x170.jpg",
        ),
        EpisodioRemoto(
            rotulo="3",
            numero=3,
            url=f"https://meusanimes.blog/e/{identificador}-1-episodio-3/",
            thumb_url="https://meusanimes.blog/wp-content/uploads/ep3-300x170.jpg",
        ),
    ]


def test_listar_episodios_url_sem_numero_entra_com_numero_none_no_fim(extrator, cliente_falso):
    identificador = "one-piece"
    html = _pagina_de_temporadas(
        [
            "https://meusanimes.blog/e/one-piece-1-episodio-1/",
            "https://meusanimes.blog/e/one-piece-especial-piloto/",
        ]
    )
    url_anime = f"{extrator.BASE_URL}/a/{identificador}/"
    cliente = cliente_falso(html_por_url={url_anime: html})

    episodios = extrator.listar_episodios(cliente, identificador)

    assert [(e.rotulo, e.numero) for e in episodios] == [
        ("1", 1),
        ("one-piece-especial-piloto", None),
    ]


def test_listar_episodios_multiplas_temporadas_achata_em_ordem_de_documento_e_loga(
    extrator, cliente_falso, caplog
):
    identificador = "naruto"
    html = _pagina_de_temporadas(
        [
            "https://meusanimes.blog/e/naruto-1-episodio-1/",
            "https://meusanimes.blog/e/naruto-1-episodio-2/",
        ],
        [
            "https://meusanimes.blog/e/naruto-2-episodio-1/",
            "https://meusanimes.blog/e/naruto-2-episodio-2/",
        ],
    )
    url_anime = f"{extrator.BASE_URL}/a/{identificador}/"
    cliente = cliente_falso(html_por_url={url_anime: html})

    with caplog.at_level("INFO"):
        episodios = extrator.listar_episodios(cliente, identificador)

    # Sort estável: dentro de cada número, a ordem de documento (T1 antes de T2).
    assert [e.url for e in episodios] == [
        "https://meusanimes.blog/e/naruto-1-episodio-1/",
        "https://meusanimes.blog/e/naruto-2-episodio-1/",
        "https://meusanimes.blog/e/naruto-1-episodio-2/",
        "https://meusanimes.blog/e/naruto-2-episodio-2/",
    ]
    assert "2 temporadas" in caplog.text


def test_listar_episodios_deduplica_por_url_repetida(extrator, cliente_falso):
    identificador = "bleach"
    href = "https://meusanimes.blog/e/bleach-1-episodio-1/"
    html = _pagina_de_temporadas(
        [href, href, "https://meusanimes.blog/e/bleach-1-episodio-2/"]
    )
    url_anime = f"{extrator.BASE_URL}/a/{identificador}/"
    cliente = cliente_falso(html_por_url={url_anime: html})

    episodios = extrator.listar_episodios(cliente, identificador)

    assert [e.url for e in episodios] == [
        "https://meusanimes.blog/e/bleach-1-episodio-1/",
        "https://meusanimes.blog/e/bleach-1-episodio-2/",
    ]


def test_listar_episodios_extrai_thumb_do_li_e_none_quando_ausente(extrator, cliente_falso):
    """O `<img>` de `.imagen` dentro do `<li>` vira `thumb_url` (src cru, já
    absoluto no site real); `<li>` sem `.imagen` → `thumb_url=None`."""
    identificador = "bleach"
    thumb = "https://meusanimes.blog/wp/x-300x170.jpg"
    html = (
        "<div id='seasons'><div class='se-c'><div class='se-a'><ul class='episodios'>"
        "<li class='mark-1'>"
        f"<div class='imagen'><img src='{thumb}'></div>"
        "<div class='episodiotitle'>"
        "<a href='https://meusanimes.blog/e/bleach-1-episodio-1/'>Episódio 1</a></div></li>"
        "<li class='mark-1'>"
        "<div class='episodiotitle'>"
        "<a href='https://meusanimes.blog/e/bleach-1-episodio-2/'>Episódio 2</a></div></li>"
        "</ul></div></div></div>"
    )
    url_anime = f"{extrator.BASE_URL}/a/{identificador}/"
    cliente = cliente_falso(html_por_url={url_anime: html})

    episodios = extrator.listar_episodios(cliente, identificador)

    assert [(e.numero, e.thumb_url) for e in episodios] == [(1, thumb), (2, None)]


def test_listar_episodios_sem_bloco_seasons_levanta_estrutura_do_site_mudou(
    extrator, cliente_falso
):
    identificador = "anime-fantasma"
    url_anime = f"{extrator.BASE_URL}/a/{identificador}/"
    cliente = cliente_falso(
        html_por_url={url_anime: "<html><body><h1>Sem temporadas</h1></body></html>"}
    )

    with pytest.raises(EstruturaDoSiteMudou) as info:
        extrator.listar_episodios(cliente, identificador)

    assert info.value.dominio == "meusanimes"
    assert info.value.permite_retentativa is False


def test_listar_episodios_com_seasons_vazio_levanta_estrutura_do_site_mudou(
    extrator, cliente_falso
):
    identificador = "anime-sem-eps"
    url_anime = f"{extrator.BASE_URL}/a/{identificador}/"
    cliente = cliente_falso(
        html_por_url={url_anime: "<div id='seasons'><div class='se-c'></div></div>"}
    )

    with pytest.raises(EstruturaDoSiteMudou):
        extrator.listar_episodios(cliente, identificador)


# --- resolver_midia ------------------------------------------------------------


_EPISODIO_HTML = """
<!DOCTYPE html><html><body>
  <div class="video-player">
    <iframe src="https://serv01.meusdoramas.club/#/video/12345/1/7/" allowfullscreen></iframe>
  </div>
</body></html>
"""

_URL_EPISODIO = "https://meusanimes.blog/e/one-piece-1-episodio-7/"
_URL_GET_VIDEO = (
    "https://serv01.meusdoramas.club/posts/get-video.php"
    "?tmdb=12345&season_number=1&episode_number=7"
)


def test_resolver_midia_com_token_blogger_delega_para_resolver_token(
    extrator, cliente_falso, monkeypatch
):
    chamadas: list[tuple[str, str]] = []

    def _stub(cliente, url_token, *, dominio):
        chamadas.append((url_token, dominio))
        return LinkDeMidia(
            url="https://r1.googlevideo.com/videoplayback?itag=22", cabecalhos={"User-Agent": "x"}
        )

    monkeypatch.setattr(modulo_meusanimes, "resolver_token", _stub)
    cliente = cliente_falso(
        html_por_url={_URL_EPISODIO: _EPISODIO_HTML},
        json_por_url={
            _URL_GET_VIDEO: {
                "success": True,
                "videoUrl": "https://www.blogger.com/video.g?token=abc123",
            }
        },
    )

    link = extrator.resolver_midia(cliente, _URL_EPISODIO)

    assert chamadas == [("https://www.blogger.com/video.g?token=abc123", "meusanimes")]
    assert link.url == "https://r1.googlevideo.com/videoplayback?itag=22"


def test_resolver_midia_com_success_false_levanta_falha_de_extracao_retentavel(
    extrator, cliente_falso
):
    cliente = cliente_falso(
        html_por_url={_URL_EPISODIO: _EPISODIO_HTML},
        json_por_url={_URL_GET_VIDEO: {"success": False}},
    )

    with pytest.raises(FalhaDeExtracao) as info:
        extrator.resolver_midia(cliente, _URL_EPISODIO)

    assert info.value.permite_retentativa is True
    assert info.value.dominio == "meusanimes"
    assert not isinstance(info.value, EstruturaDoSiteMudou)


def test_resolver_midia_sem_iframe_do_player_levanta_estrutura_do_site_mudou(
    extrator, cliente_falso
):
    html = (
        '<html><body><div class="video-player">'
        '<iframe src="https://www.youtube.com/embed/dQw4w9WgXcQ"></iframe>'
        "</div></body></html>"
    )
    cliente = cliente_falso(html_por_url={_URL_EPISODIO: html})

    with pytest.raises(EstruturaDoSiteMudou) as info:
        extrator.resolver_midia(cliente, _URL_EPISODIO)

    assert info.value.dominio == "meusanimes"
    assert info.value.permite_retentativa is False


def test_resolver_midia_com_video_url_http_direta_nao_blogger_usa_direta(extrator, cliente_falso):
    cliente = cliente_falso(
        html_por_url={_URL_EPISODIO: _EPISODIO_HTML},
        json_por_url={
            _URL_GET_VIDEO: {
                "success": True,
                "videoUrl": "https://cdn.meusdoramas.club/stream/op-7.mp4",
            }
        },
    )

    link = extrator.resolver_midia(cliente, _URL_EPISODIO)

    assert link == LinkDeMidia(
        url="https://cdn.meusdoramas.club/stream/op-7.mp4",
        cabecalhos={"User-Agent": "ClienteFalso/1.0"},
    )


def test_resolver_midia_com_video_url_em_lista_vira_estrutura_do_site_mudou(
    extrator, cliente_falso
):
    """Forma `[{label, file}]` nunca observada — defensivo: estrutura
    desconhecida vira `EstruturaDoSiteMudou`, não é usada às cegas."""
    cliente = cliente_falso(
        html_por_url={_URL_EPISODIO: _EPISODIO_HTML},
        json_por_url={
            _URL_GET_VIDEO: {
                "success": True,
                "videoUrl": [{"label": "720p", "file": "https://x/y.mp4"}],
            }
        },
    )

    with pytest.raises(EstruturaDoSiteMudou):
        extrator.resolver_midia(cliente, _URL_EPISODIO)


# --- capabilities ------------------------------------------------------------


def test_capabilities_do_provedor(extrator):
    assert extrator.dominio == "meusanimes"
    assert extrator.exige_navegador is False
    assert extrator.exige_navegador_para_midia is False
    assert extrator.diferencia_versao is True

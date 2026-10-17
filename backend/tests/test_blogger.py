"""Testes de `fontes/adaptadores/blogger.py::resolver_token` com fixtures estáticas — sem
rede, sem navegador. O cliente é um dublê que devolve o HTML `video.g` e a
resposta `batchexecute` pré-gravados (ou levanta a exceção já traduzida que o
cliente real levantaria).

O que exercita o Blogger de verdade é o smoke do AnimesDrive
(`test_smoke_scrapers.py`, marcador `rede`)."""

import json

import pytest

from core.erros import EstruturaDoSiteMudou, FalhaDeExtracao, SessaoRejeitada
from fontes.adaptadores import blogger

# `video.g` realista: `WIZ_global_data` numa linha (com `{}` aninhado e `{}`
# dentro de string, para travar que o fatiador de bloco não usa `{.*}`), um
# `<c-wiz>` de distração sem `data-p` no formato `%.@.` e o `<c-wiz>` do player
# (`jsrenderer="W8PsLe"`), cujo `data-p` começa em `%.@.` fazendo as vezes do
# `[` de abertura — a lista de argumentos vem sem o `[`, com o `]` de fechamento.
_HTML_VIDEO_G = (
    "<!doctype html><html><head>"
    '<script nonce="x">window.WIZ_global_data = {"cfb2h":'
    '"boq_bloggeruiserver_20260831.03_p0","FdrFJe":"-6837128027805418408",'
    '"rotulo":"chave com }{ chaves","aninhado":{"a":1,"b":{"c":2}}};</script>'
    "</head><body>"
    '<c-wiz jsrenderer="q" data-p="[1,2]" class="distracao"></c-wiz>'
    '<c-wiz jsrenderer="W8PsLe" jsmodel="hc6Ubd" '
    r'data-p="%.@.&quot;AIzaSyTESTKEY&quot;,null,false,null,'
    r'&quot;https://www.blogger.com/video.g?token=abc&quot;,'
    r'[null,null,null,&quot;token-abc-123&quot;]]" '
    'class="player"></c-wiz>'
    "</body></html>"
)

_DATA_P_DECODIFICADO = [
    "AIzaSyTESTKEY",
    None,
    False,
    None,
    "https://www.blogger.com/video.g?token=abc",
    [None, None, None, "token-abc-123"],
]

_PAYLOAD_DOIS_ITAGS = [
    1,
    None,
    [
        ["https://r1.googlevideo.com/videoplayback?itag=18&id=abc", [18]],
        ["https://r1.googlevideo.com/videoplayback?itag=22&id=abc", [22]],
    ],
    "https://thumb.example/x.jpg",
    "BLOGGER-video-abc",
    "abc123",
]

_URL_TOKEN = "https://www.blogger.com/video.g?token=abc"


def _envelope(payload: object) -> str:
    """Envelope `batchexecute` line-delimited com a entrada `wrb.fr` da RPC."""
    wrb = ["wrb.fr", "WcwnYd", json.dumps(payload), None, None, None, "generic"]
    linha = json.dumps([wrb, ["di", 41], ["af.httprm", 40, "1", 6]])
    cauda = '[["e",4,null,null,131]]'
    return f")]}}'\n\n{len(linha)}\n{linha}\n{len(cauda)}\n{cauda}\n"


class _ClienteBloggerFalso:
    def __init__(
        self,
        *,
        html: str = _HTML_VIDEO_G,
        resposta_post: str = "",
        erro_post: BaseException | None = None,
    ) -> None:
        self._html = html
        self._resposta_post = resposta_post
        self._erro_post = erro_post
        self.posts: list[tuple[str, dict[str, str]]] = []

    def obter_html(self, url: str, *, timeout_s: int) -> str:
        return self._html

    def postar_formulario(self, url: str, campos: dict[str, str], *, timeout_s: int) -> str:
        self.posts.append((url, campos))
        if self._erro_post is not None:
            raise self._erro_post
        return self._resposta_post

    def obter_json(self, url: str, *, timeout_s: int) -> dict | list:
        raise AssertionError("blogger não usa obter_json")

    def cookies(self) -> dict[str, str]:
        return {}

    def user_agent(self) -> str:
        return "ClienteFalso/1.0"

    def fechar(self) -> None:
        pass


def test_resolve_e_escolhe_o_itag_maior():
    cliente = _ClienteBloggerFalso(resposta_post=_envelope(_PAYLOAD_DOIS_ITAGS))

    link = blogger.resolver_token(cliente, _URL_TOKEN)

    assert link.url == "https://r1.googlevideo.com/videoplayback?itag=22&id=abc"
    assert link.cabecalhos == {"User-Agent": "ClienteFalso/1.0"}


def test_monta_a_query_e_o_f_req_no_formato_batchexecute():
    cliente = _ClienteBloggerFalso(resposta_post=_envelope(_PAYLOAD_DOIS_ITAGS))

    blogger.resolver_token(cliente, _URL_TOKEN)

    url, campos = cliente.posts[0]
    assert url.startswith(
        "https://www.blogger.com/_/BloggerVideoPlayerUi/data/batchexecute?"
    )
    assert "rpcids=WcwnYd" in url
    assert "source-path=%2Fvideo.g" in url
    assert "f.sid=-6837128027805418408" in url
    assert "bl=boq_bloggeruiserver_20260831.03_p0" in url

    externo = json.loads(campos["f.req"])
    rpc = externo[0][0]
    assert rpc[0] == "WcwnYd"
    assert rpc[2] is None
    assert rpc[3] == "generic"
    assert json.loads(rpc[1]) == _DATA_P_DECODIFICADO


def test_html_sem_wiz_global_data_vira_estrutura_mudou():
    cliente = _ClienteBloggerFalso(html="<html><body>vazio</body></html>")

    with pytest.raises(EstruturaDoSiteMudou) as info:
        blogger.resolver_token(cliente, _URL_TOKEN, dominio="meusanimes")

    assert info.value.dominio == "meusanimes"
    assert info.value.permite_retentativa is False


def test_cliente_sem_capacidade_de_post_falha_por_contrato(cliente_falso):
    with pytest.raises(FalhaDeExtracao) as info:
        blogger.resolver_token(cliente_falso(), _URL_TOKEN)

    assert info.value.permite_retentativa is False
    assert not isinstance(info.value, EstruturaDoSiteMudou)


def test_post_400_vira_estrutura_mudou_com_dica_de_recuperacao():
    cliente = _ClienteBloggerFalso(
        erro_post=FalhaDeExtracao("HTTP 400 em .../batchexecute", permite_retentativa=True)
    )

    with pytest.raises(EstruturaDoSiteMudou) as info:
        blogger.resolver_token(cliente, _URL_TOKEN)

    texto = str(info.value)
    assert "OXnWq" in texto and "WcwnYd" in texto


def test_sessao_rejeitada_no_post_propaga_sem_conversao():
    cliente = _ClienteBloggerFalso(erro_post=SessaoRejeitada("desafio Cloudflare"))

    with pytest.raises(SessaoRejeitada):
        blogger.resolver_token(cliente, _URL_TOKEN)


def test_payload_sem_formatos_vira_estrutura_mudou():
    payload_vazio = [1, None, [], "thumb", "BLOGGER-video-x", "x"]
    cliente = _ClienteBloggerFalso(resposta_post=_envelope(payload_vazio))

    with pytest.raises(EstruturaDoSiteMudou):
        blogger.resolver_token(cliente, _URL_TOKEN)


def test_resposta_sem_wrb_fr_vira_estrutura_mudou():
    cliente = _ClienteBloggerFalso(resposta_post=")]}'\n\n23\n[[\"e\",4,null,null,131]]\n")

    with pytest.raises(EstruturaDoSiteMudou):
        blogger.resolver_token(cliente, _URL_TOKEN)

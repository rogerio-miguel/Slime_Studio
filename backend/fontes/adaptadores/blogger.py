"""Resolve um token de vídeo do Blogger numa URL de vídeo direta, por HTTP puro.

`blogger.com/video.g?token=...` é o player de vídeo do Blogger — uma SPA do
framework "Wiz" do Google. A página não traz a URL do vídeo: traz só os dados
para montar a chamada RPC que o JS faria (`rpcid=WcwnYd`, serviço
`BloggerVideoPlayerService.GetVideoPlay`). Este helper faz a mesma chamada:

1. GET `video.g?token=...` — a página tem `window.WIZ_global_data = {...}` (ids
   de build e de sessão) e um `<c-wiz data-p="%.@.,...">` (parâmetros da RPC:
   `%.@.` faz as vezes do `[` de abertura da lista de argumentos, o resto vem
   duplamente escapado — entidade HTML + escape de string JS).
2. POST `batchexecute` com esses parâmetros → resposta JSON delimitada por linha
   com a lista de formatos (`itag` 18 = 360p, 22 = 720p, ambos mp4 progressivo
   muxado).
3. Escolhe o de maior `itag` e devolve `LinkDeMidia` — só `User-Agent` nos
   cabeçalhos: o host de mídia do Google não valida hotlink (confirmado ao vivo).

Helper compartilhável — AnimesDrive e MeusAnimes embutem players do Blogger. O
parâmetro `dominio` deixa o chamador propagar o próprio identificador para o
circuit breaker dele quando o parsing falha (`EstruturaDoSiteMudou`).

Sem HTTP próprio: recebe o `ClienteDeSite` já injetado e, para o POST, exige a
capacidade `ClienteComPost` (`fontes/rede/cliente.py`) — mesma disciplina de
`isinstance` que `animesdrive.py` aplica a `ClienteComCaptura`. Toda exceção de
`requests` continua morrendo lá dentro; aqui só trafega `FalhaDeExtracao`.
"""

import html
import json
import re
import urllib.parse

from core.erros import EstruturaDoSiteMudou, FalhaDeExtracao, FonteNaoEncontrada, SessaoRejeitada
from fontes.adaptadores.base import LinkDeMidia
from fontes.rede.cliente import ClienteComPost, ClienteDeSite

_TIMEOUT_S = 15

_URL_BATCHEXECUTE = "https://www.blogger.com/_/BloggerVideoPlayerUi/data/batchexecute"
_RPCID = "WcwnYd"
_PREFIXO_DATA_P = "%.@."

# `window.WIZ_global_data = { ... };` — objeto minificado do Wiz, normalmente numa
# linha só. Ancorado no `WIZ_global_data =` e fatiado por contagem de chaves
# (`_bloco_json`), nunca por regex `{.*}`: o objeto tem `{}` aninhado e `{}`
# dentro de string.
_REGEX_WIZ_INICIO = re.compile(r"WIZ_global_data\s*=\s*\{")
# Tag `<c-wiz ...>` de abertura. A página `video.g` tem um único `<c-wiz>` (o
# player, `jsrenderer="W8PsLe"`), e o `data-p` dele começa em `%.@.` — é esse que
# se pega. `jscontroller="OXnWq"` existe na página, mas num contêiner externo,
# não no `<c-wiz>`.
_REGEX_CWIZ_TAG = re.compile(r"<c-wiz\b[^>]*>", re.IGNORECASE)
_REGEX_DATA_P = re.compile(r'\bdata-p="([^"]*)"')

# Anexado quando o POST falha: o rpcid é o ponto mais provável de quebra numa
# mudança do player.
_DICA_RPCID = (
    f"rpcid {_RPCID} pode ter mudado — redescobrir no módulo JS m=OXnWq, procurar "
    '`new x2("...", ... "/BloggerVideoPlayerService.GetVideoPl…"'
)


def resolver_token(
    cliente: ClienteDeSite, url_token: str, *, dominio: str = "blogger"
) -> LinkDeMidia:
    """Resolve `url_token` (`https://www.blogger.com/video.g?token=...`) na URL de
    vídeo direta de maior qualidade disponível.

    `dominio` vai em todo `EstruturaDoSiteMudou` levantado aqui — o chamador
    (AnimesDrive, MeusAnimes) passa o próprio para o circuit breaker dele
    contabilizar a falha na conta certa; o default cobre o uso avulso.
    """
    if not isinstance(cliente, ClienteComPost):
        raise FalhaDeExtracao(
            "resolver token do Blogger exige cliente com POST de formulário, recebido"
            f" {type(cliente).__name__}",
            dominio=dominio,
            permite_retentativa=False,
        )

    html_pagina = cliente.obter_html(url_token, timeout_s=_TIMEOUT_S)
    bl, f_sid = _extrair_wiz(html_pagina, dominio)
    data_p = _extrair_data_p(html_pagina, dominio)

    f_req = json.dumps(
        [[[_RPCID, json.dumps(data_p, separators=(",", ":")), None, "generic"]]],
        separators=(",", ":"),
    )
    url_post = f"{_URL_BATCHEXECUTE}?{_montar_query(bl, f_sid)}"

    try:
        corpo = cliente.postar_formulario(url_post, {"f.req": f_req}, timeout_s=_TIMEOUT_S)
    except (SessaoRejeitada, FonteNaoEncontrada):
        # Sessão/token, não estrutura: `SessaoRejeitada` precisa chegar intacta
        # em `resiliencia.py` para escalar ao navegador; `FonteNaoEncontrada`
        # (token expirado) aciona o fallback de site do chamador.
        raise
    except FalhaDeExtracao as excecao:
        raise EstruturaDoSiteMudou(
            f"POST batchexecute do Blogger falhou ({excecao}); {_DICA_RPCID}",
            dominio=dominio,
        ) from excecao

    payload = _extrair_payload_wrb(corpo, dominio)
    url_video = _melhor_formato(payload, dominio)
    return LinkDeMidia(url=url_video, cabecalhos={"User-Agent": cliente.user_agent()})


def _extrair_wiz(html_pagina: str, dominio: str) -> tuple[str, str]:
    """`(bl, f_sid)` de `WIZ_global_data` — `cfb2h` (id de build) e `FdrFJe`
    (id de sessão), ambos exigidos pela query do `batchexecute`."""
    inicio = _REGEX_WIZ_INICIO.search(html_pagina)
    if inicio is None:
        raise EstruturaDoSiteMudou(
            "página video.g do Blogger sem bloco WIZ_global_data", dominio=dominio
        )
    bloco = _bloco_json(html_pagina, inicio.end() - 1)
    if bloco is None:
        raise EstruturaDoSiteMudou(
            "bloco WIZ_global_data do Blogger não fecha as chaves", dominio=dominio
        )
    try:
        dados = json.loads(bloco)
    except json.JSONDecodeError as excecao:
        raise EstruturaDoSiteMudou(
            f"WIZ_global_data do Blogger não é JSON: {excecao}", dominio=dominio
        ) from excecao

    bl = dados.get("cfb2h") if isinstance(dados, dict) else None
    f_sid = dados.get("FdrFJe") if isinstance(dados, dict) else None
    if not isinstance(bl, str) or not bl or not isinstance(f_sid, str) or not f_sid:
        raise EstruturaDoSiteMudou(
            "WIZ_global_data do Blogger sem cfb2h/FdrFJe utilizáveis", dominio=dominio
        )
    return bl, f_sid


def _bloco_json(texto: str, inicio: int) -> str | None:
    """Fatia de `texto` do `{` em `inicio` até a chave que o fecha, ignorando
    chaves dentro de string (com escape). `None` se não fechar."""
    profundidade = 0
    em_string = False
    escapando = False
    for indice in range(inicio, len(texto)):
        caractere = texto[indice]
        if escapando:
            escapando = False
        elif caractere == "\\":
            escapando = True
        elif caractere == '"':
            em_string = not em_string
        elif em_string:
            continue
        elif caractere == "{":
            profundidade += 1
        elif caractere == "}":
            profundidade -= 1
            if profundidade == 0:
                fim = indice + 1
                return texto[inicio:fim]
    return None


def _extrair_data_p(html_pagina: str, dominio: str) -> list:
    """Lista de parâmetros da RPC, do atributo `data-p` do `<c-wiz>` do player.

    Formato Wiz: o prefixo `%.@.` faz as vezes do `[` de abertura — o restante é
    a lista de argumentos já com o `]` de fechamento, mas sem o `[`. Troca-se
    `%.@.` por `[` e então se decodifica os dois níveis de escape (entidade HTML
    e escape de string JS, nessa ordem)."""
    bruto = _data_p_bruto(html_pagina)
    if bruto is None:
        raise EstruturaDoSiteMudou(
            "página video.g do Blogger sem <c-wiz data-p> do player", dominio=dominio
        )
    if bruto.startswith(_PREFIXO_DATA_P):
        bruto = "[" + bruto[len(_PREFIXO_DATA_P):]
    corpo = html.unescape(bruto).encode().decode("unicode_escape")
    try:
        return json.loads(corpo)
    except json.JSONDecodeError as excecao:
        raise EstruturaDoSiteMudou(
            f"data-p do player do Blogger não decodificou para JSON: {excecao}",
            dominio=dominio,
        ) from excecao


def _data_p_bruto(html_pagina: str) -> str | None:
    for match in _REGEX_CWIZ_TAG.finditer(html_pagina):
        atributo = _REGEX_DATA_P.search(match.group(0))
        if atributo is not None and atributo.group(1).startswith(_PREFIXO_DATA_P):
            return atributo.group(1)
    return None


def _montar_query(bl: str, f_sid: str) -> str:
    return urllib.parse.urlencode(
        {
            "rpcids": _RPCID,
            "source-path": "/video.g",
            "f.sid": f_sid,
            "bl": bl,
            "hl": "pt-BR",
            "_reqid": "81894",
            "rt": "c",
        }
    )


def _extrair_payload_wrb(corpo: str, dominio: str) -> list:
    """`json.loads` do 3º elemento da entrada `wrb.fr` do envelope `batchexecute`
    (o payload da nossa RPC, ele mesmo uma string JSON)."""
    for linha_bruta in corpo.splitlines():
        linha = linha_bruta.strip()
        if not linha.startswith("["):
            continue
        try:
            envelope = json.loads(linha)
        except json.JSONDecodeError:
            continue
        for entrada in envelope:
            if (
                isinstance(entrada, list)
                and len(entrada) >= 3
                and entrada[0] == "wrb.fr"
                and entrada[1] == _RPCID
            ):
                if not isinstance(entrada[2], str):
                    raise EstruturaDoSiteMudou(
                        "entrada wrb.fr do Blogger sem payload de string", dominio=dominio
                    )
                try:
                    return json.loads(entrada[2])
                except json.JSONDecodeError as excecao:
                    raise EstruturaDoSiteMudou(
                        f"payload wrb.fr do Blogger não é JSON: {excecao}", dominio=dominio
                    ) from excecao
    raise EstruturaDoSiteMudou(
        f"resposta batchexecute do Blogger sem entrada wrb.fr para {_RPCID}; {_DICA_RPCID}",
        dominio=dominio,
    )


def _melhor_formato(payload: list, dominio: str) -> str:
    """URL de vídeo de maior `itag` em `payload[2]` (`[[url, [itag]], ...]`)."""
    formatos = payload[2] if isinstance(payload, list) and len(payload) > 2 else None
    if not isinstance(formatos, list) or not formatos:
        raise EstruturaDoSiteMudou(
            "payload de vídeo do Blogger sem lista de formatos (payload[2])",
            dominio=dominio,
        )

    melhor_url: str | None = None
    melhor_itag = -1
    for formato in formatos:
        if not isinstance(formato, list) or not formato:
            continue
        url = formato[0]
        if not isinstance(url, str) or not url:
            continue
        itag = 0
        if len(formato) > 1 and isinstance(formato[1], list) and formato[1]:
            try:
                itag = int(formato[1][0])
            except (TypeError, ValueError):
                itag = 0
        if itag > melhor_itag:
            melhor_url, melhor_itag = url, itag

    if melhor_url is None:
        raise EstruturaDoSiteMudou(
            "nenhuma URL de vídeo utilizável no payload do Blogger", dominio=dominio
        )
    return melhor_url

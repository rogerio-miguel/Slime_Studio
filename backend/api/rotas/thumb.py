"""Proxy de thumbnail de episódio: `GET /api/thumb?url=<url absoluta>` busca a
imagem na fonte remota server-side e repassa os bytes, para que o navegador do
usuário nunca requisite direto o site de origem e para embutir o `Referer` que a
proteção de hotlink da fonte exige.

Sem persistência e sem cache em processo — o teto de tamanho + `Cache-Control`
público + o cache do navegador bastam (Escada de Minimalismo, CLAUDE.md §4).
`_HOSTS_PERMITIDOS` (derivada do registro de extratores, nunca hardcoded) é
guarda de SSRF: sem ela o endpoint seria um proxy HTTP aberto.
"""

import asyncio
import logging
import urllib.parse

import requests
from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import Response

from extractors.registro import EXTRATORES

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["thumb"])

# Hosts de terceiro cuja imagem um extrator pode legitimamente embutir sem
# hospedar ela mesmo — hoje só o CDN público do TMDB, que `extractors/animefire.py`
# passa a repassar em `poster_src`/`still_src` desde a migração pra API JSON
# (ESPECIFICACAO.md, 2026-09-04): não é o site de origem, então não aparece
# como host de nenhum `BASE_URL`, mas é uma origem confiável e deliberada, não
# uma brecha de SSRF.
_HOSTS_DE_CDN_DE_TERCEIRO = frozenset({"image.tmdb.org"})

# Hosts de onde uma thumb pode legitimamente vir: os sites de extração
# registrados. Derivada do host de `BASE_URL`, NÃO de `ExtratorDeSite.dominio` —
# `dominio` é identificador estável e nem sempre um hostname (ex. "animesdrive",
# "meusanimes"; ver `extractors/animesdrive.py`).
_HOSTS_PERMITIDOS = frozenset(
    host
    for extrator in EXTRATORES
    if (host := urllib.parse.urlparse(getattr(extrator, "BASE_URL", "")).hostname)
) | _HOSTS_DE_CDN_DE_TERCEIRO

# A thumb é uma imagem pequena: teto de tempo curto na busca à origem e teto de
# tamanho de resposta — acima disso quase certo que não é o que se espera.
_TIMEOUT_S = 10
_TETO_BYTES = 5 * 1024 * 1024
_BLOCO_BYTES = 64 * 1024
_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko)"
    " Chrome/150.0.0.0 Safari/537.36"
)
_CACHE = "public, max-age=86400"


@router.get("/thumb")
async def obter_thumb(url: str = Query(..., max_length=2048)) -> Response:
    """Repassa a imagem de `url` (host de fonte permitido, esquema `https`).

    Qualquer problema — host fora da allowlist, esquema != `https`, timeout,
    erro HTTP da origem, resposta que não é imagem, corpo acima do teto — vira
    404: o frontend tem `onError` que esconde a thumb. Nunca 500 com stack.
    """
    partes = urllib.parse.urlparse(url)
    if partes.scheme != "https" or partes.hostname not in _HOSTS_PERMITIDOS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="url de thumb não permitida"
        )

    imagem = await asyncio.to_thread(_buscar_imagem, url, partes.hostname)
    if imagem is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="thumb indisponível"
        )

    content_type, corpo = imagem
    return Response(content=corpo, media_type=content_type, headers={"Cache-Control": _CACHE})


def _buscar_imagem(url: str, host: str) -> tuple[str, bytes] | None:
    """GET síncrono (rodado em thread pela rota) com `Referer`/`User-Agent` de
    navegador, teto de tempo e de tamanho. `allow_redirects=False`: seguir um
    redirect para fora da allowlist seria SSRF — a fonte serve a imagem direto,
    redirect nenhum é esperado. Devolve `(content_type, bytes)` ou `None` em
    qualquer falha (sempre logada, nunca silenciosa)."""
    cabecalhos = {
        "Referer": f"https://{host}/",
        "User-Agent": _USER_AGENT,
        "Accept": "image/*",
    }
    try:
        with requests.get(
            url,
            headers=cabecalhos,
            timeout=_TIMEOUT_S,
            stream=True,
            allow_redirects=False,
        ) as resposta:
            if resposta.status_code != 200:
                logger.info("thumb %s: origem respondeu HTTP %s", url, resposta.status_code)
                return None

            content_type = (
                resposta.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            )
            if not content_type.startswith("image/"):
                logger.info("thumb %s: Content-Type não é imagem (%r)", url, content_type)
                return None

            declarado = resposta.headers.get("Content-Length", "")
            if declarado.isdigit() and int(declarado) > _TETO_BYTES:
                logger.info("thumb %s: Content-Length %s acima do teto", url, declarado)
                return None

            corpo = bytearray()
            for bloco in resposta.iter_content(chunk_size=_BLOCO_BYTES):
                corpo.extend(bloco)
                if len(corpo) > _TETO_BYTES:
                    logger.info("thumb %s: corpo acima do teto de %d bytes", url, _TETO_BYTES)
                    return None
            return content_type, bytes(corpo)
    except requests.RequestException as excecao:
        logger.info("thumb %s: falha de rede (%s)", url, excecao)
        return None

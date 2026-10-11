"""Testes de `GET /api/thumb` (`api/rotas/thumb.py`) — proxy de thumbnail de
episódio. `requests.get` é monkeypatchado; nenhum teste toca rede real (a suíte
roda com `rede` desselecionado)."""

import pytest
from httpx import AsyncClient


class _RespostaFake:
    """Contexto de resposta `requests` mínimo: `with`, `status_code`, `headers`,
    `iter_content`."""

    def __init__(
        self,
        *,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        blocos: tuple[bytes, ...] = (b"",),
    ) -> None:
        self.status_code = status_code
        self.headers = headers or {}
        self._blocos = blocos

    def __enter__(self):
        return self

    def __exit__(self, *_exc: object) -> bool:
        return False

    def iter_content(self, chunk_size: int):
        assert chunk_size > 0
        yield from self._blocos


def _fake_get(**resposta_kwargs):
    """Fábrica de substituto para `requests.get` que registra os argumentos
    recebidos em `.capturado` e devolve uma `_RespostaFake`."""
    capturado: dict[str, object] = {}

    def _get(url, *, headers, timeout, stream, allow_redirects):
        capturado.update(
            url=url, headers=headers, timeout=timeout, allow_redirects=allow_redirects
        )
        return _RespostaFake(**resposta_kwargs)

    _get.capturado = capturado
    return _get


def _get_que_explode(*_a: object, **_k: object):
    raise AssertionError("não deveria tocar rede")


async def test_thumb_host_permitido_repassa_imagem(
    cliente: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    fake = _fake_get(headers={"Content-Type": "image/webp"}, blocos=(b"RIFFxxxxWEBP",))
    monkeypatch.setattr("requests.get", fake)

    resposta = await cliente.get(
        "/api/thumb", params={"url": "https://animefire.one/img/video/42/1.webp"}
    )

    assert resposta.status_code == 200
    assert resposta.headers["content-type"] == "image/webp"
    assert resposta.headers["cache-control"] == "public, max-age=86400"
    assert resposta.content == b"RIFFxxxxWEBP"
    assert fake.capturado["headers"]["Referer"] == "https://animefire.one/"
    assert fake.capturado["allow_redirects"] is False


async def test_thumb_content_type_com_charset_normalizado(
    cliente: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        "requests.get",
        _fake_get(headers={"Content-Type": "image/jpeg; charset=binary"}, blocos=(b"\xff\xd8",)),
    )

    resposta = await cliente.get(
        "/api/thumb", params={"url": "https://meusanimes.blog/wp/ep1.jpg"}
    )

    assert resposta.status_code == 200
    assert resposta.headers["content-type"] == "image/jpeg"


async def test_thumb_cdn_de_terceiro_tmdb_e_permitido(
    cliente: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """`image.tmdb.org` não é `BASE_URL` de nenhum extrator, mas é a origem de
    `poster_src`/`still_src` que `fontes/adaptadores/animefire.py` passa a repassar
    desde a migração pra API JSON — precisa estar na allowlist mesmo assim."""
    fake = _fake_get(headers={"Content-Type": "image/jpeg"}, blocos=(b"\xff\xd8",))
    monkeypatch.setattr("requests.get", fake)

    resposta = await cliente.get(
        "/api/thumb",
        params={"url": "https://image.tmdb.org/t/p/original/abc123.jpg"},
    )

    assert resposta.status_code == 200
    assert fake.capturado["headers"]["Referer"] == "https://image.tmdb.org/"


async def test_thumb_host_nao_permitido_rejeita_sem_rede(
    cliente: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr("requests.get", _get_que_explode)

    resposta = await cliente.get(
        "/api/thumb", params={"url": "https://evil.example/x.jpg"}
    )

    assert resposta.status_code == 404


async def test_thumb_esquema_http_rejeitado_sem_rede(
    cliente: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr("requests.get", _get_que_explode)

    resposta = await cliente.get(
        "/api/thumb", params={"url": "http://animefire.one/img/video/42/1.webp"}
    )

    assert resposta.status_code == 404


async def test_thumb_origem_devolve_html_vira_404(
    cliente: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        "requests.get",
        _fake_get(headers={"Content-Type": "text/html; charset=utf-8"}, blocos=(b"<html>",)),
    )

    resposta = await cliente.get(
        "/api/thumb", params={"url": "https://animesdrive.cloud/thumb1.jpg"}
    )

    assert resposta.status_code == 404


async def test_thumb_origem_404_vira_404(
    cliente: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        "requests.get",
        _fake_get(status_code=404, headers={"Content-Type": "image/jpeg"}),
    )

    resposta = await cliente.get(
        "/api/thumb", params={"url": "https://meusanimes.blog/wp/ausente.jpg"}
    )

    assert resposta.status_code == 404


async def test_thumb_redirect_nao_e_seguido(
    cliente: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        "requests.get",
        _fake_get(status_code=302, headers={"Location": "https://evil.example/x.jpg"}),
    )

    resposta = await cliente.get(
        "/api/thumb", params={"url": "https://animefire.one/img/video/42/1.webp"}
    )

    assert resposta.status_code == 404


async def test_thumb_corpo_acima_do_teto_vira_404(
    cliente: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    grande = b"x" * (5 * 1024 * 1024 + 1)
    monkeypatch.setattr(
        "requests.get",
        _fake_get(headers={"Content-Type": "image/jpeg"}, blocos=(grande,)),
    )

    resposta = await cliente.get(
        "/api/thumb", params={"url": "https://animefire.one/img/video/42/1.webp"}
    )

    assert resposta.status_code == 404


async def test_thumb_falha_de_rede_vira_404(
    cliente: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    import requests

    def _get(*_a: object, **_k: object):
        raise requests.ConnectionError("sem rota para o host")

    monkeypatch.setattr("requests.get", _get)

    resposta = await cliente.get(
        "/api/thumb", params={"url": "https://animefire.one/img/video/42/1.webp"}
    )

    assert resposta.status_code == 404


async def test_thumb_sem_parametro_url_422(cliente: AsyncClient):
    resposta = await cliente.get("/api/thumb")

    assert resposta.status_code == 422

"""Fixtures compartilhadas de teste. `ClienteFalso` é usado por todo teste de
parsing de extrator (`test_animefire.py`, `test_animesdrive.py`), sem tocar
rede — auto-carregado pelo pytest, `tests/` não é pacote então zero atrito de
import."""

import pytest


class ClienteFalso:
    """Implementação de `ClienteDeSite` que devolve respostas pré-programadas por
    URL, em vez de tocar rede. URL não mapeada é erro de teste (`AssertionError`),
    não `None` silencioso."""

    def __init__(
        self,
        *,
        html_por_url: dict[str, str] | None = None,
        json_por_url: dict[str, object] | None = None,
    ) -> None:
        self._html_por_url = html_por_url or {}
        self._json_por_url = json_por_url or {}

    def obter_html(self, url: str, *, timeout_s: int) -> str:
        assert url in self._html_por_url, f"URL não mapeada no ClienteFalso: {url}"
        return self._html_por_url[url]

    def obter_json(self, url: str, *, timeout_s: int) -> dict | list:
        assert url in self._json_por_url, f"URL não mapeada no ClienteFalso: {url}"
        return self._json_por_url[url]

    def cookies(self) -> dict[str, str]:
        return {}

    def user_agent(self) -> str:
        return "ClienteFalso/1.0"


@pytest.fixture
def cliente_falso():
    """Fábrica de `ClienteFalso` — uso: `cliente_falso(html_por_url={...})`."""

    def _fabrica(
        *,
        html_por_url: dict[str, str] | None = None,
        json_por_url: dict[str, object] | None = None,
    ) -> ClienteFalso:
        return ClienteFalso(html_por_url=html_por_url, json_por_url=json_por_url)

    return _fabrica

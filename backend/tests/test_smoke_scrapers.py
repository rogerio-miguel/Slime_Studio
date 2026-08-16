"""Smoke test por scraper (ESPECIFICACAO.md §7) — verifica periodicamente se cada
extrator ainda consegue localizar o link de um episódio real, sem esperar até um
job falhar em produção pra descobrir que o site mudou.

`@pytest.mark.rede`: toca rede real de propósito — desselecionado por padrão
(`addopts = ["-m", "not rede"]`, `pyproject.toml`). É diagnóstico manual, não gate
de CI. Esqueleto nesta etapa (2A): implementar de fato fica para quando houver um
título real estável o bastante para servir de fixture de smoke test sem quebrar a
cada mudança de catálogo do site.
"""

import pytest

pytestmark = pytest.mark.rede


@pytest.mark.skip(
    reason="esqueleto (2A) — implementar quando houver um título de referência estável"
)
def test_animefire_localiza_link_de_um_episodio_real():
    pass

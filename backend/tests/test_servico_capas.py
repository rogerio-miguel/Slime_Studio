"""Testes de `api/servicos/capas.py::capas_por_titulo`, sem rede.

`integrations.servico.buscar_por_titulo` é monkeypatchado no nome do módulo de
origem (`integrations.servico`), não em `api.servicos.capas` — `capas.py` o
chama via `servico_metadados`, que aponta pro mesmo objeto de módulo, então o
patch na origem vale pros dois nomes (mesmo padrão de
`tests/test_api_buscar_fontes.py`)."""

import pytest

from api.servicos import capas as servico_capas
from extractors.base import ResultadoBusca
from extractors.busca.servico import ResultadoDeFonte
from integrations.base import MetadadosDeAnime


def _fonte(dominio: str, *candidatos: ResultadoBusca) -> ResultadoDeFonte:
    return ResultadoDeFonte(
        dominio=dominio, candidatos=list(candidatos), indisponivel=False, motivo=None
    )


async def test_capas_por_titulo_preenche_dict_com_capa_encontrada(
    monkeypatch: pytest.MonkeyPatch,
):
    async def _buscar_por_titulo_fake(titulo: str) -> MetadadosDeAnime | None:
        assert titulo == "Naruto"
        return MetadadosDeAnime(
            capa_url="https://cdn/naruto.jpg", sinopse=None, anilist_id=1, kitsu_id=None
        )

    monkeypatch.setattr("integrations.servico.buscar_por_titulo", _buscar_por_titulo_fake)

    fonte = _fonte(
        "animefire.io",
        ResultadoBusca(titulo_exibicao="Naruto", identificador="1", url="https://x/1"),
    )

    capas = await servico_capas.capas_por_titulo([fonte])

    assert capas == {"naruto": "https://cdn/naruto.jpg"}


async def test_capas_por_titulo_dedupe_por_titulo_normalizado(monkeypatch: pytest.MonkeyPatch):
    chamadas: list[str] = []

    async def _buscar_por_titulo_fake(titulo: str) -> MetadadosDeAnime | None:
        chamadas.append(titulo)
        return MetadadosDeAnime(
            capa_url="https://cdn/naruto.jpg", sinopse=None, anilist_id=None, kitsu_id=None
        )

    monkeypatch.setattr("integrations.servico.buscar_por_titulo", _buscar_por_titulo_fake)

    fontes = [
        _fonte(
            "animefire.io",
            ResultadoBusca(titulo_exibicao="Naruto", identificador="1", url="https://x/1"),
        ),
        _fonte(
            "animesdrive",
            ResultadoBusca(titulo_exibicao="naruto", identificador="2", url="https://y/2"),
        ),
    ]

    capas = await servico_capas.capas_por_titulo(fontes)

    assert len(chamadas) == 1
    assert capas == {"naruto": "https://cdn/naruto.jpg"}


async def test_capas_por_titulo_falha_de_uma_consulta_nao_derruba_as_outras(
    monkeypatch: pytest.MonkeyPatch,
):
    async def _buscar_por_titulo_fake(titulo: str) -> MetadadosDeAnime | None:
        if titulo == "Naruto":
            raise RuntimeError("provedor fora do ar")
        return MetadadosDeAnime(
            capa_url="https://cdn/bleach.jpg", sinopse=None, anilist_id=None, kitsu_id=None
        )

    monkeypatch.setattr("integrations.servico.buscar_por_titulo", _buscar_por_titulo_fake)

    fonte = _fonte(
        "animefire.io",
        ResultadoBusca(titulo_exibicao="Naruto", identificador="1", url="https://x/1"),
        ResultadoBusca(titulo_exibicao="Bleach", identificador="2", url="https://x/2"),
    )

    capas = await servico_capas.capas_por_titulo([fonte])

    assert capas == {"bleach": "https://cdn/bleach.jpg"}


async def test_capas_por_titulo_sem_candidatos_nao_consulta_provedor(
    monkeypatch: pytest.MonkeyPatch,
):
    async def _falha_se_chamado(titulo: str) -> MetadadosDeAnime | None:
        raise AssertionError("não deveria consultar quando não há candidatos")

    monkeypatch.setattr("integrations.servico.buscar_por_titulo", _falha_se_chamado)

    capas = await servico_capas.capas_por_titulo([_fonte("animefire.io")])

    assert capas == {}

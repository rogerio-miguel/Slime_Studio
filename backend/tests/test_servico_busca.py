"""Testes de `api/servicos/busca.py::enriquecer_capas`, sem rede —
`integrations.servico.buscar_por_titulo` é monkeypatchado (mesmo módulo que
`enriquecer_capas` chama via `servico_metadados`, então o patch vale pro
nome usado internamente), mesmo padrão de
`tests/test_api_buscar_fontes.py` para `extractors.servico.buscar_em`."""

import pytest

from api.servicos import busca as servico_busca
from extractors.base import ResultadoBusca
from extractors.servico import ResultadoDeFonte
from integrations.base import MetadadosDeAnime


def _fonte(dominio: str, *candidatos: ResultadoBusca) -> ResultadoDeFonte:
    return ResultadoDeFonte(
        dominio=dominio, candidatos=list(candidatos), indisponivel=False, motivo=None
    )


async def test_enriquecer_capas_preenche_resultado_sem_capa(monkeypatch: pytest.MonkeyPatch):
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

    resultado = await servico_busca.enriquecer_capas(None, [fonte])

    assert resultado[0].candidatos[0].capa_url == "https://cdn/naruto.jpg"


async def test_enriquecer_capas_dedupe_por_titulo_normalizado(monkeypatch: pytest.MonkeyPatch):
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
            "animesdrive.online",
            ResultadoBusca(titulo_exibicao="naruto", identificador="2", url="https://y/2"),
        ),
    ]

    resultado = await servico_busca.enriquecer_capas(None, fontes)

    assert len(chamadas) == 1
    assert resultado[0].candidatos[0].capa_url == "https://cdn/naruto.jpg"
    assert resultado[1].candidatos[0].capa_url == "https://cdn/naruto.jpg"


async def test_enriquecer_capas_falha_de_uma_consulta_nao_derruba_as_outras(
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

    resultado = await servico_busca.enriquecer_capas(None, [fonte])

    candidatos = resultado[0].candidatos
    assert candidatos[0].capa_url is None
    assert candidatos[1].capa_url == "https://cdn/bleach.jpg"


async def test_enriquecer_capas_nao_reconsulta_resultado_que_ja_tem_capa(
    monkeypatch: pytest.MonkeyPatch,
):
    async def _falha_se_chamado(titulo: str) -> MetadadosDeAnime | None:
        raise AssertionError("não deveria consultar título que já veio com capa")

    monkeypatch.setattr("integrations.servico.buscar_por_titulo", _falha_se_chamado)

    fonte = _fonte(
        "animesdrive.online",
        ResultadoBusca(
            titulo_exibicao="Naruto",
            identificador="1",
            url="https://x/1",
            capa_url="https://animesdrive.online/capa.jpg",
        ),
    )

    resultado = await servico_busca.enriquecer_capas(None, [fonte])

    assert resultado[0].candidatos[0].capa_url == "https://animesdrive.online/capa.jpg"

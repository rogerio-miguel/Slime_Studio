"""Testes de `api/servicos/busca.py`: `enriquecer_capas` e
`buscar_com_titulos_alternativos`, sem rede — `integrations.servico.
buscar_por_titulo`/`buscar_titulos` e `extractors.servico.
buscar_em_todas_as_fontes` são monkeypatchados nos nomes de módulo (mesmo
padrão de `tests/test_api_buscar_fontes.py` para `extractors.servico.
buscar_em`), pois `busca.py` os chama via `servico_metadados`/
`servico_extractors`, que apontam pro mesmo objeto de módulo."""

import pytest

from api.servicos import busca as servico_busca
from core.erros import FalhaDeMetadados
from extractors.base import ResultadoBusca
from extractors.servico import ResultadoDeFonte
from integrations.base import MetadadosDeAnime, TitulosDeAnime


def _fonte(dominio: str, *candidatos: ResultadoBusca) -> ResultadoDeFonte:
    return ResultadoDeFonte(
        dominio=dominio, candidatos=list(candidatos), indisponivel=False, motivo=None
    )


def _fonte_indisponivel(dominio: str, motivo: str = "falhou") -> ResultadoDeFonte:
    return ResultadoDeFonte(dominio=dominio, candidatos=[], indisponivel=True, motivo=motivo)


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


# --- buscar_com_titulos_alternativos ---


async def test_busca_alternativa_expande_quando_rodada_original_vazia(
    monkeypatch: pytest.MonkeyPatch,
):
    chamadas_busca: list[str] = []

    async def _buscar_em_todas_as_fontes_fake(sessionmaker, titulo):
        chamadas_busca.append(titulo)
        if titulo == "Slime":
            return [_fonte("animefire.io"), _fonte("animesdrive.online")]
        return [
            _fonte(
                "animefire.io",
                ResultadoBusca(titulo_exibicao="Tensei", identificador="1", url="https://x/1"),
            )
        ]

    async def _buscar_titulos_fake(titulo: str) -> TitulosDeAnime | None:
        assert titulo == "Slime"
        return TitulosDeAnime(titulo_romaji="Tensei", titulo_ingles="Reincarnated")

    monkeypatch.setattr(
        "extractors.servico.buscar_em_todas_as_fontes", _buscar_em_todas_as_fontes_fake
    )
    monkeypatch.setattr("integrations.servico.buscar_titulos", _buscar_titulos_fake)

    resultado = await servico_busca.buscar_com_titulos_alternativos(None, "Slime")

    assert resultado.termo_alternativo == "Tensei"
    assert resultado.fontes[0].candidatos[0].titulo_exibicao == "Tensei"
    assert chamadas_busca == ["Slime", "Tensei"]


async def test_busca_alternativa_nao_expande_se_alguma_fonte_ja_achou(
    monkeypatch: pytest.MonkeyPatch,
):
    async def _buscar_em_todas_as_fontes_fake(sessionmaker, titulo):
        return [
            _fonte(
                "animefire.io",
                ResultadoBusca(titulo_exibicao="Naruto", identificador="1", url="https://x/1"),
            ),
            _fonte_indisponivel("animesdrive.online"),
        ]

    async def _falha_se_chamado(titulo: str):
        raise AssertionError("buscar_titulos não deveria ser chamado quando já achou candidato")

    monkeypatch.setattr(
        "extractors.servico.buscar_em_todas_as_fontes", _buscar_em_todas_as_fontes_fake
    )
    monkeypatch.setattr("integrations.servico.buscar_titulos", _falha_se_chamado)

    resultado = await servico_busca.buscar_com_titulos_alternativos(None, "Naruto")

    assert resultado.termo_alternativo is None
    assert resultado.fontes[0].candidatos[0].titulo_exibicao == "Naruto"


async def test_busca_alternativa_nao_expande_se_todas_as_fontes_indisponiveis(
    monkeypatch: pytest.MonkeyPatch,
):
    fontes_indisponiveis = [
        _fonte_indisponivel("animefire.io"),
        _fonte_indisponivel("animesdrive.online"),
    ]

    async def _buscar_em_todas_as_fontes_fake(sessionmaker, titulo):
        return fontes_indisponiveis

    async def _falha_se_chamado(titulo: str):
        raise AssertionError(
            "buscar_titulos não deveria ser chamado quando todas as fontes estão indisponíveis"
        )

    monkeypatch.setattr(
        "extractors.servico.buscar_em_todas_as_fontes", _buscar_em_todas_as_fontes_fake
    )
    monkeypatch.setattr("integrations.servico.buscar_titulos", _falha_se_chamado)

    resultado = await servico_busca.buscar_com_titulos_alternativos(None, "Naruto")

    assert resultado.termo_alternativo is None
    assert resultado.fontes == fontes_indisponiveis


async def test_busca_alternativa_pula_termo_com_mesmo_slug_do_digitado(
    monkeypatch: pytest.MonkeyPatch,
):
    chamadas_busca: list[str] = []

    async def _buscar_em_todas_as_fontes_fake(sessionmaker, titulo):
        chamadas_busca.append(titulo)
        if titulo == "Reincarnated":
            return [
                _fonte(
                    "animefire.io",
                    ResultadoBusca(
                        titulo_exibicao="Reincarnated", identificador="1", url="https://x/1"
                    ),
                )
            ]
        return [_fonte("animefire.io"), _fonte("animesdrive.online")]

    async def _buscar_titulos_fake(titulo: str) -> TitulosDeAnime | None:
        # Mesmo slug do termo digitado ("Slime" -> "slime") — deve ser
        # descartado, só "Reincarnated" chega a virar uma rodada de busca.
        return TitulosDeAnime(titulo_romaji="slime", titulo_ingles="Reincarnated")

    monkeypatch.setattr(
        "extractors.servico.buscar_em_todas_as_fontes", _buscar_em_todas_as_fontes_fake
    )
    monkeypatch.setattr("integrations.servico.buscar_titulos", _buscar_titulos_fake)

    resultado = await servico_busca.buscar_com_titulos_alternativos(None, "Slime")

    assert resultado.termo_alternativo == "Reincarnated"
    assert chamadas_busca == ["Slime", "Reincarnated"]


async def test_busca_alternativa_devolve_rodada_original_quando_alternativo_tambem_vazio(
    monkeypatch: pytest.MonkeyPatch,
):
    fontes_originais = [_fonte("animefire.io"), _fonte("animesdrive.online")]
    fontes_alternativas = [_fonte_indisponivel("animefire.io", "outro motivo")]

    async def _buscar_em_todas_as_fontes_fake(sessionmaker, titulo):
        return fontes_originais if titulo == "Slime" else fontes_alternativas

    async def _buscar_titulos_fake(titulo: str) -> TitulosDeAnime | None:
        return TitulosDeAnime(titulo_romaji="Tensei", titulo_ingles="Reincarnated")

    monkeypatch.setattr(
        "extractors.servico.buscar_em_todas_as_fontes", _buscar_em_todas_as_fontes_fake
    )
    monkeypatch.setattr("integrations.servico.buscar_titulos", _buscar_titulos_fake)

    resultado = await servico_busca.buscar_com_titulos_alternativos(None, "Slime")

    assert resultado.termo_alternativo is None
    assert resultado.fontes == fontes_originais


async def test_busca_alternativa_falha_de_metadados_nao_propaga(monkeypatch: pytest.MonkeyPatch):
    fontes_originais = [_fonte("animefire.io"), _fonte("animesdrive.online")]

    async def _buscar_em_todas_as_fontes_fake(sessionmaker, titulo):
        return fontes_originais

    async def _buscar_titulos_falha(titulo: str):
        raise FalhaDeMetadados("todos os provedores de metadados falharam")

    monkeypatch.setattr(
        "extractors.servico.buscar_em_todas_as_fontes", _buscar_em_todas_as_fontes_fake
    )
    monkeypatch.setattr("integrations.servico.buscar_titulos", _buscar_titulos_falha)

    resultado = await servico_busca.buscar_com_titulos_alternativos(None, "Slime")

    assert resultado.termo_alternativo is None
    assert resultado.fontes == fontes_originais

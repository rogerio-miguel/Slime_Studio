"""Testes de `api/servicos/busca.py`: `enriquecer_capas` e
`buscar_com_titulos_alternativos`, sem rede — `integrations.servico.
buscar_por_titulo`/`buscar_titulos` e `extractors.servico.
buscar_em_com_variantes` são monkeypatchados nos nomes de módulo (mesmo
padrão usado em `tests/test_api_buscar_fontes.py`), pois `busca.py` os chama
via `servico_metadados`/`servico_extractors`, que apontam pro mesmo objeto de
módulo.

`buscar_com_titulos_alternativos` (Fase A, fatia 3 de
PLANO_PADRONIZACAO_FONTES.md) é sequencial por site (ordem de
`extractors.registro.EXTRATORES`: animefire.io primeiro, animesdrive.online
depois), em duas fases ordenadas por custo — Fase 1 com as variantes puras de
`extractors/nomes.py::variantes_de_busca`, Fase 2 (só se a Fase 1 não achou
nada em site nenhum) com termos de provedor externo. O fake de
`buscar_em_com_variantes` recebe `(sessionmaker, dominio, variantes)` e
devolve `(ResultadoDeFonte, variante_vencedora)`, mesmo contrato da função
real."""

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


async def test_fase1_acha_no_site_padrao_nao_chama_provedor_nem_o_2o_site(
    monkeypatch: pytest.MonkeyPatch,
):
    candidato = ResultadoBusca(titulo_exibicao="Naruto", identificador="1", url="https://x/1")
    chamadas: list[str] = []

    async def _buscar_em_com_variantes_fake(sessionmaker, dominio, variantes):
        chamadas.append(dominio)
        return _fonte(dominio, candidato), None

    async def _falha_se_chamado(titulo: str):
        raise AssertionError("buscar_titulos não deveria ser chamado quando a Fase 1 já achou")

    monkeypatch.setattr(
        "extractors.servico.buscar_em_com_variantes", _buscar_em_com_variantes_fake
    )
    monkeypatch.setattr("integrations.servico.buscar_titulos", _falha_se_chamado)

    resultado = await servico_busca.buscar_com_titulos_alternativos(None, "Naruto")

    assert resultado.termo_alternativo is None
    assert resultado.dominio_alternativo is None
    assert resultado.fontes[0].candidatos == [candidato]
    # Ordem de custo respeitada: o 2º site (animesdrive) nem chega a ser
    # tentado quando o padrão já achou na Fase 1.
    assert chamadas == ["animefire.io"]


async def test_fase1_so_acha_no_2o_site_dominio_alternativo_e_o_domino_real(
    monkeypatch: pytest.MonkeyPatch,
):
    candidato = ResultadoBusca(titulo_exibicao="Naruto", identificador="2", url="https://y/1")

    async def _buscar_em_com_variantes_fake(sessionmaker, dominio, variantes):
        if dominio == "animefire.io":
            return _fonte("animefire.io"), None
        return _fonte("animesdrive.online", candidato), None

    async def _falha_se_chamado(titulo: str):
        raise AssertionError("buscar_titulos não deveria ser chamado quando a Fase 1 já achou")

    monkeypatch.setattr(
        "extractors.servico.buscar_em_com_variantes", _buscar_em_com_variantes_fake
    )
    monkeypatch.setattr("integrations.servico.buscar_titulos", _falha_se_chamado)

    resultado = await servico_busca.buscar_com_titulos_alternativos(None, "Naruto")

    assert resultado.termo_alternativo is None
    assert resultado.dominio_alternativo == "animesdrive.online"
    assert resultado.fontes[1].candidatos == [candidato]


async def test_fase2_termo_de_provedor_acha_no_site_padrao(monkeypatch: pytest.MonkeyPatch):
    candidato = ResultadoBusca(titulo_exibicao="Tensei Slime", identificador="1", url="https://x/1")
    romaji = "Tensei Shitara Slime Datta Ken"

    async def _buscar_em_com_variantes_fake(sessionmaker, dominio, variantes):
        if romaji in variantes:
            return _fonte(dominio, candidato), None
        return _fonte(dominio), None

    async def _buscar_titulos_fake(titulo: str) -> TitulosDeAnime | None:
        assert titulo == "Slime"
        return TitulosDeAnime(titulo_romaji=romaji, titulo_ingles=None)

    monkeypatch.setattr(
        "extractors.servico.buscar_em_com_variantes", _buscar_em_com_variantes_fake
    )
    monkeypatch.setattr("integrations.servico.buscar_titulos", _buscar_titulos_fake)

    resultado = await servico_busca.buscar_com_titulos_alternativos(None, "Slime")

    assert resultado.termo_alternativo == romaji
    # Respondeu o site padrão, só que com outro termo.
    assert resultado.dominio_alternativo is None
    assert resultado.fontes[0].candidatos == [candidato]


async def test_fase2_termo_de_provedor_so_acha_no_2o_site(monkeypatch: pytest.MonkeyPatch):
    candidato = ResultadoBusca(titulo_exibicao="Tensei Slime", identificador="2", url="https://y/1")
    romaji = "Tensei Shitara Slime Datta Ken"

    async def _buscar_em_com_variantes_fake(sessionmaker, dominio, variantes):
        if dominio == "animesdrive.online" and romaji in variantes:
            return _fonte(dominio, candidato), None
        return _fonte(dominio), None

    async def _buscar_titulos_fake(titulo: str) -> TitulosDeAnime | None:
        return TitulosDeAnime(titulo_romaji=romaji, titulo_ingles=None)

    monkeypatch.setattr(
        "extractors.servico.buscar_em_com_variantes", _buscar_em_com_variantes_fake
    )
    monkeypatch.setattr("integrations.servico.buscar_titulos", _buscar_titulos_fake)

    resultado = await servico_busca.buscar_com_titulos_alternativos(None, "Slime")

    assert resultado.termo_alternativo == romaji
    assert resultado.dominio_alternativo == "animesdrive.online"


async def test_site_padrao_em_cooldown_nao_e_retentado_na_fase2(monkeypatch: pytest.MonkeyPatch):
    candidato = ResultadoBusca(titulo_exibicao="Naruto", identificador="2", url="https://y/1")
    romaji = "Naruto Shippuden"
    chamadas_animefire: list[list[str]] = []

    async def _buscar_em_com_variantes_fake(sessionmaker, dominio, variantes):
        if dominio == "animefire.io":
            chamadas_animefire.append(variantes)
            return _fonte_indisponivel("animefire.io", "em cooldown"), None
        if romaji in variantes:
            return _fonte("animesdrive.online", candidato), None
        return _fonte("animesdrive.online"), None

    async def _buscar_titulos_fake(titulo: str) -> TitulosDeAnime | None:
        return TitulosDeAnime(titulo_romaji=romaji, titulo_ingles=None)

    monkeypatch.setattr(
        "extractors.servico.buscar_em_com_variantes", _buscar_em_com_variantes_fake
    )
    monkeypatch.setattr("integrations.servico.buscar_titulos", _buscar_titulos_fake)

    resultado = await servico_busca.buscar_com_titulos_alternativos(None, "Naruto")

    # Só a tentativa da Fase 1 — site em cooldown não é retentado com termo de
    # provedor na Fase 2, é pulado direto (`resultados[...].indisponivel`).
    assert len(chamadas_animefire) == 1
    assert resultado.dominio_alternativo == "animesdrive.online"
    assert resultado.termo_alternativo == romaji


async def test_nenhum_site_acha_nada_em_fase_nenhuma(monkeypatch: pytest.MonkeyPatch):
    async def _buscar_em_com_variantes_fake(sessionmaker, dominio, variantes):
        return _fonte(dominio), None

    async def _buscar_titulos_fake(titulo: str) -> TitulosDeAnime | None:
        return None  # provedor não achou título nenhum

    monkeypatch.setattr(
        "extractors.servico.buscar_em_com_variantes", _buscar_em_com_variantes_fake
    )
    monkeypatch.setattr("integrations.servico.buscar_titulos", _buscar_titulos_fake)

    resultado = await servico_busca.buscar_com_titulos_alternativos(None, "Naruto")

    assert resultado.termo_alternativo is None
    assert resultado.dominio_alternativo is None
    dominios = {fonte.dominio for fonte in resultado.fontes}
    assert dominios == {"animefire.io", "animesdrive.online"}
    # Os dois sites foram de fato tentados (não "não consultado") — nenhum
    # candidato, nenhum indisponível, motivo None nos dois.
    assert all(not fonte.indisponivel and fonte.candidatos == [] for fonte in resultado.fontes)
    assert all(fonte.motivo is None for fonte in resultado.fontes)


async def test_completar_nao_consultados_marca_2o_site_como_nao_tentado(
    monkeypatch: pytest.MonkeyPatch,
):
    candidato = ResultadoBusca(titulo_exibicao="Naruto", identificador="1", url="https://x/1")

    async def _buscar_em_com_variantes_fake(sessionmaker, dominio, variantes):
        return _fonte(dominio, candidato), None

    async def _falha_se_chamado(titulo: str):
        raise AssertionError("buscar_titulos não deveria ser chamado quando a Fase 1 já achou")

    monkeypatch.setattr(
        "extractors.servico.buscar_em_com_variantes", _buscar_em_com_variantes_fake
    )
    monkeypatch.setattr("integrations.servico.buscar_titulos", _falha_se_chamado)

    resultado = await servico_busca.buscar_com_titulos_alternativos(None, "Naruto")

    fonte_animesdrive = next(f for f in resultado.fontes if f.dominio == "animesdrive.online")
    assert fonte_animesdrive.indisponivel is False
    assert fonte_animesdrive.candidatos == []
    assert fonte_animesdrive.motivo is not None
    assert "não consultado" in fonte_animesdrive.motivo


async def test_todos_os_sites_indisponiveis_nao_chama_provedor(monkeypatch: pytest.MonkeyPatch):
    """Regressão do `_merece_expansao` antigo: se os dois sites já vieram
    `indisponivel` na Fase 1, a Fase 2 vai pular os dois de qualquer forma
    (mesmo filtro de `_tentar_termos_de_provedor`) — chamar `buscar_titulos`
    aqui seria rede garantidamente desperdiçada."""

    async def _buscar_em_com_variantes_fake(sessionmaker, dominio, variantes):
        return _fonte_indisponivel(dominio), None

    async def _falha_se_chamado(titulo: str):
        raise AssertionError(
            "buscar_titulos não deveria ser chamado quando todos os sites já"
            " estão indisponíveis"
        )

    monkeypatch.setattr(
        "extractors.servico.buscar_em_com_variantes", _buscar_em_com_variantes_fake
    )
    monkeypatch.setattr("integrations.servico.buscar_titulos", _falha_se_chamado)

    resultado = await servico_busca.buscar_com_titulos_alternativos(None, "Naruto")

    assert resultado.termo_alternativo is None
    assert resultado.dominio_alternativo is None
    assert all(fonte.indisponivel for fonte in resultado.fontes)


def test_termos_alternativos_descarta_romaji_igual_ao_digitado_e_kanji_vazio():
    """`_termos_alternativos` não é tocada por esta fatia, mas perdeu sua
    única cobertura (indireta, via `buscar_com_titulos_alternativos`) quando
    os testes antigos de `_merece_expansao` saíram — trava direta pra não
    perder essa regra de novo."""
    titulos = TitulosDeAnime(titulo_romaji="Naruto", titulo_ingles="Naruto")

    termos = servico_busca._termos_alternativos(titulos, "Naruto")

    assert termos == []


def test_termos_alternativos_ordem_romaji_antes_de_ingles():
    titulos = TitulosDeAnime(
        titulo_romaji="Tensei Shitara Slime Datta Ken", titulo_ingles="That Time I Got Reincarnated"
    )

    termos = servico_busca._termos_alternativos(titulos, "Slime")

    assert termos == ["Tensei Shitara Slime Datta Ken", "That Time I Got Reincarnated"]


async def test_fase2_atualiza_status_do_site_mesmo_quando_ninguem_acha_nada(
    monkeypatch: pytest.MonkeyPatch,
):
    """Site que veio disponível-mas-vazio na Fase 1 e falha (`indisponivel`)
    durante a tentativa da Fase 2 não pode voltar a aparecer com o status
    otimista da Fase 1 na resposta final — `_tentar_termos_de_provedor` muta
    o dict do chamador, não uma cópia local descartada."""
    romaji = "Naruto Shippuden"

    async def _buscar_em_com_variantes_fake(sessionmaker, dominio, variantes):
        if romaji not in variantes:
            return _fonte(dominio), None  # Fase 1: disponível, mas vazio
        return _fonte_indisponivel(dominio, "caiu durante a Fase 2"), None

    async def _buscar_titulos_fake(titulo: str) -> TitulosDeAnime | None:
        return TitulosDeAnime(titulo_romaji=romaji, titulo_ingles=None)

    monkeypatch.setattr(
        "extractors.servico.buscar_em_com_variantes", _buscar_em_com_variantes_fake
    )
    monkeypatch.setattr("integrations.servico.buscar_titulos", _buscar_titulos_fake)

    resultado = await servico_busca.buscar_com_titulos_alternativos(None, "Naruto")

    fonte_animefire = next(f for f in resultado.fontes if f.dominio == "animefire.io")
    assert fonte_animefire.indisponivel is True
    assert fonte_animefire.motivo == "caiu durante a Fase 2"


async def test_fase2_falha_de_metadados_nao_propaga_devolve_rodada_da_fase1(
    monkeypatch: pytest.MonkeyPatch,
):
    async def _buscar_em_com_variantes_fake(sessionmaker, dominio, variantes):
        return _fonte(dominio), None

    async def _buscar_titulos_falha(titulo: str):
        raise FalhaDeMetadados("todos os provedores de metadados falharam")

    monkeypatch.setattr(
        "extractors.servico.buscar_em_com_variantes", _buscar_em_com_variantes_fake
    )
    monkeypatch.setattr("integrations.servico.buscar_titulos", _buscar_titulos_falha)

    resultado = await servico_busca.buscar_com_titulos_alternativos(None, "Slime")

    assert resultado.termo_alternativo is None
    assert resultado.dominio_alternativo is None
    dominios = {fonte.dominio for fonte in resultado.fontes}
    assert dominios == {"animefire.io", "animesdrive.online"}


# --- buscar_em_todas_as_fontes_com_titulos_alternativos (escopo `todas`) ---
#
# Mesmos 4 branches já cobertos acima para `buscar_com_titulos_alternativos`
# (escopo `padrao`), agora para o motor paralelo por rodada de variante. O
# fake de `buscar_em_todas_as_fontes_com_variantes` recebe `(sessionmaker,
# variantes)` e devolve `list[ResultadoDeFonte]` (uma entrada por domínio),
# mesmo contrato da função real.


async def test_todas_fase2_termo_de_provedor_acha_quando_fase1_vazia(
    monkeypatch: pytest.MonkeyPatch,
):
    candidato = ResultadoBusca(titulo_exibicao="Tensei Slime", identificador="1", url="https://x/1")
    romaji = "Tensei Shitara Slime Datta Ken"

    async def _buscar_em_todas_as_fontes_com_variantes_fake(sessionmaker, variantes):
        if romaji in variantes:
            return [_fonte("animefire.io", candidato), _fonte("animesdrive.online")]
        return [_fonte("animefire.io"), _fonte("animesdrive.online")]

    async def _buscar_titulos_fake(titulo: str) -> TitulosDeAnime | None:
        assert titulo == "Slime"
        return TitulosDeAnime(titulo_romaji=romaji, titulo_ingles=None)

    monkeypatch.setattr(
        "extractors.servico.buscar_em_todas_as_fontes_com_variantes",
        _buscar_em_todas_as_fontes_com_variantes_fake,
    )
    monkeypatch.setattr("integrations.servico.buscar_titulos", _buscar_titulos_fake)

    resultado = await servico_busca.buscar_em_todas_as_fontes_com_titulos_alternativos(
        None, "Slime"
    )

    # `termo_alternativo`/`dominio_alternativo` sempre `None` neste escopo
    # (docstring de `buscar_em_todas_as_fontes_com_titulos_alternativos`) —
    # mesmo achando só na Fase 2, com termo de provedor.
    assert resultado.termo_alternativo is None
    assert resultado.dominio_alternativo is None
    assert resultado.fontes[0].candidatos == [candidato]


async def test_todas_fase1_e_fase2_vazias_preserva_rodada_da_fase1(
    monkeypatch: pytest.MonkeyPatch,
):
    """Fase 2 também não acha nada (`_expandir_termo_de_provedor_em_todas_as_
    fontes` devolve `None`) — o chamador preserva a rodada original da Fase 1
    em vez de substituí-la por uma rodada vazia diferente. As duas rodadas
    vêm marcadas de forma distinguível (`indisponivel`/`motivo`) só pra provar
    que a substituição realmente não acontece."""
    romaji = "Naruto Shippuden"

    async def _buscar_em_todas_as_fontes_com_variantes_fake(sessionmaker, variantes):
        if romaji in variantes:
            return [
                _fonte_indisponivel("animefire.io", "fase2"),
                _fonte_indisponivel("animesdrive.online", "fase2"),
            ]
        return [_fonte("animefire.io"), _fonte("animesdrive.online")]

    async def _buscar_titulos_fake(titulo: str) -> TitulosDeAnime | None:
        return TitulosDeAnime(titulo_romaji=romaji, titulo_ingles=None)

    monkeypatch.setattr(
        "extractors.servico.buscar_em_todas_as_fontes_com_variantes",
        _buscar_em_todas_as_fontes_com_variantes_fake,
    )
    monkeypatch.setattr("integrations.servico.buscar_titulos", _buscar_titulos_fake)

    resultado = await servico_busca.buscar_em_todas_as_fontes_com_titulos_alternativos(
        None, "Naruto"
    )

    assert resultado.termo_alternativo is None
    assert resultado.dominio_alternativo is None
    # Rodada da Fase 1 (disponível, vazia), não a rodada "fase2" (indisponível).
    assert all(not fonte.indisponivel and fonte.candidatos == [] for fonte in resultado.fontes)
    assert all(fonte.motivo is None for fonte in resultado.fontes)


async def test_todas_fase2_falha_de_metadados_nao_propaga_devolve_rodada_da_fase1(
    monkeypatch: pytest.MonkeyPatch,
):
    async def _buscar_em_todas_as_fontes_com_variantes_fake(sessionmaker, variantes):
        return [_fonte("animefire.io"), _fonte("animesdrive.online")]

    async def _buscar_titulos_falha(titulo: str):
        raise FalhaDeMetadados("todos os provedores de metadados falharam")

    monkeypatch.setattr(
        "extractors.servico.buscar_em_todas_as_fontes_com_variantes",
        _buscar_em_todas_as_fontes_com_variantes_fake,
    )
    monkeypatch.setattr("integrations.servico.buscar_titulos", _buscar_titulos_falha)

    resultado = await servico_busca.buscar_em_todas_as_fontes_com_titulos_alternativos(
        None, "Slime"
    )

    assert resultado.termo_alternativo is None
    assert resultado.dominio_alternativo is None
    dominios = {fonte.dominio for fonte in resultado.fontes}
    assert dominios == {"animefire.io", "animesdrive.online"}


async def test_todas_todos_os_sites_indisponiveis_nao_chama_provedor(
    monkeypatch: pytest.MonkeyPatch,
):
    """Mesma regressão do `_merece_expansao` antigo, agora pro escopo `todas`:
    se os dois sites já vieram `indisponivel` na Fase 1, a Fase 2 é pulada
    inteira (`algum_site_disponivel` na guarda) — chamar `buscar_titulos`
    aqui seria rede garantidamente desperdiçada."""

    async def _buscar_em_todas_as_fontes_com_variantes_fake(sessionmaker, variantes):
        return [_fonte_indisponivel("animefire.io"), _fonte_indisponivel("animesdrive.online")]

    async def _falha_se_chamado(titulo: str):
        raise AssertionError(
            "buscar_titulos não deveria ser chamado quando todos os sites já"
            " estão indisponíveis"
        )

    monkeypatch.setattr(
        "extractors.servico.buscar_em_todas_as_fontes_com_variantes",
        _buscar_em_todas_as_fontes_com_variantes_fake,
    )
    monkeypatch.setattr("integrations.servico.buscar_titulos", _falha_se_chamado)

    resultado = await servico_busca.buscar_em_todas_as_fontes_com_titulos_alternativos(
        None, "Naruto"
    )

    assert resultado.termo_alternativo is None
    assert resultado.dominio_alternativo is None
    assert all(fonte.indisponivel for fonte in resultado.fontes)

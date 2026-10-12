"""Testes de `api/servicos/busca.py::buscar_em_todas_as_fontes_com_titulos_alternativos`
sem rede — `integrations.servico.
buscar_titulos` e `fontes.busca.servico.buscar_por_site_com_variantes` são
monkeypatchados nos nomes de módulo (mesmo padrão de `tests/test_api_buscar_fontes.py`),
pois `busca.py` os chama via `servico_metadados`/`servico_fontes`, que apontam
pro mesmo objeto de módulo.

A função devolve `list[ResultadoDeFonte]` — a UNIÃO das fontes que têm o anime, sem
vencedor nem termo alternativo. O fake de `buscar_por_site_com_variantes` recebe
`(sessionmaker, variantes, *, referencias, dominios=None)` e devolve
`dict[str, ResultadoDeFonte]`, mesmo contrato da função real.
`termos_de_busca`/`referencias_de_anime` NÃO são monkeypatchadas: rodam de verdade
sobre o `TitulosDeAnime` que o fake de `buscar_titulos` devolve.

O enriquecimento de capa saiu de `busca.py`; o módulo `api/servicos/capas.py` e seus
testes não existem mais."""

import pytest

from api.servicos import busca as servico_busca
from core.erros import FalhaDeMetadados
from fontes.adaptadores.base import ResultadoBusca
from fontes.adaptadores.registro import EXTRATORES
from fontes.busca.servico import ResultadoDeFonte
from integrations.base import TitulosDeAnime


def _fonte(dominio: str, *candidatos: ResultadoBusca) -> ResultadoDeFonte:
    return ResultadoDeFonte(
        dominio=dominio, candidatos=list(candidatos), indisponivel=False, motivo=None
    )


def _fonte_indisponivel(dominio: str, motivo: str = "falhou") -> ResultadoDeFonte:
    return ResultadoDeFonte(dominio=dominio, candidatos=[], indisponivel=True, motivo=motivo)


async def test_todas_termo_de_provedor_entra_na_escada_quando_o_digitado_nao_acha(
    monkeypatch: pytest.MonkeyPatch,
):
    candidato = ResultadoBusca(titulo_exibicao="Tensei Slime", identificador="1", url="https://x/1")
    romaji = "Tensei Shitara Slime Datta Ken"

    async def _buscar_por_site_com_variantes_fake(
        sessionmaker, variantes, *, referencias, dominios=None
    ):
        if romaji in variantes:
            return {
                "animefire.one": _fonte("animefire.one", candidato),
                "animesdrive": _fonte("animesdrive"),
            }
        return {
            "animefire.one": _fonte("animefire.one"),
            "animesdrive": _fonte("animesdrive"),
        }

    async def _buscar_titulos_fake(titulo: str) -> TitulosDeAnime | None:
        assert titulo == "Slime"
        return TitulosDeAnime(titulo_romaji=romaji, titulo_ingles=None)

    monkeypatch.setattr(
        "fontes.busca.servico.buscar_por_site_com_variantes",
        _buscar_por_site_com_variantes_fake,
    )
    monkeypatch.setattr("integrations.servico.buscar_titulos", _buscar_titulos_fake)

    resultado = await servico_busca.buscar_em_todas_as_fontes_com_titulos_alternativos(
        None, "Slime"
    )

    assert resultado[0].candidatos == [candidato]


async def test_todas_escada_combinada_une_romaji_e_ingles_numa_rodada_so(
    monkeypatch: pytest.MonkeyPatch,
):
    """A escada combinada traz romaji E inglês — um site que só indexa o romaji
    e outro que só indexa o inglês entram os dois na mesma rodada paralela.
    Contrato de UNIÃO: um candidato de cada site, numa rodada de scraping só."""
    romaji = "Naruto Shippuuden"
    ingles = "Naruto Hurricane Chronicles"
    candidato_af = ResultadoBusca(titulo_exibicao=romaji, identificador="1", url="https://af/1")
    candidato_ad = ResultadoBusca(titulo_exibicao=ingles, identificador="2", url="https://ad/2")
    rodadas: list[list[str] | None] = []

    async def _buscar_por_site_com_variantes_fake(
        sessionmaker, variantes, *, referencias, dominios=None
    ):
        rodadas.append(dominios)
        return {
            "animefire.one": (
                _fonte("animefire.one", candidato_af)
                if romaji in variantes
                else _fonte("animefire.one")
            ),
            "meusanimes": _fonte("meusanimes"),
            "animesdrive": (
                _fonte("animesdrive", candidato_ad)
                if ingles in variantes
                else _fonte("animesdrive")
            ),
        }

    async def _buscar_titulos_fake(titulo: str) -> TitulosDeAnime | None:
        return TitulosDeAnime(titulo_romaji=romaji, titulo_ingles=ingles)

    monkeypatch.setattr(
        "fontes.busca.servico.buscar_por_site_com_variantes",
        _buscar_por_site_com_variantes_fake,
    )
    monkeypatch.setattr("integrations.servico.buscar_titulos", _buscar_titulos_fake)

    resultado = await servico_busca.buscar_em_todas_as_fontes_com_titulos_alternativos(
        None, "Naruto"
    )

    assert rodadas == [None]  # uma rodada de scraping só
    fontes_por_dominio = {f.dominio: f for f in resultado}
    assert fontes_por_dominio["animefire.one"].candidatos == [candidato_af]
    assert fontes_por_dominio["animesdrive"].candidatos == [candidato_ad]
    assert fontes_por_dominio["meusanimes"].candidatos == []


async def test_todas_titulo_ingles_do_provedor_alcanca_site_pendente(
    monkeypatch: pytest.MonkeyPatch,
):
    """Bug real (2026-08-29, "Dogul Wang"): o AnimeFire achar pela escada de
    regex não pode impedir o AnimesDrive de ser alcançado com o título inglês
    do provedor ("Tomb Raider King"), onde o anime existe — antes o diálogo
    "Trocar fonte" listava uma fonte só. A escada COMBINADA
    (`termos_de_busca` = romaji + inglês + digitado) varre o inglês já na 1ª
    varredura, em paralelo, em todos os sites — a UNIÃO traz as duas fontes numa
    rodada de scraping só."""
    candidato_af = ResultadoBusca(
        titulo_exibicao="Dogul Wang", identificador="1", url="https://af/1"
    )
    candidato_ad = ResultadoBusca(
        titulo_exibicao="Tomb Raider King", identificador="2", url="https://ad/2"
    )
    rodadas: list[list[str] | None] = []

    async def _buscar_por_site_com_variantes_fake(
        sessionmaker, variantes, *, referencias, dominios=None
    ):
        rodadas.append(dominios)
        return {
            "animefire.one": _fonte("animefire.one", candidato_af),
            "meusanimes": _fonte("meusanimes"),
            "animesdrive": (
                _fonte("animesdrive", candidato_ad)
                if "Tomb Raider King" in variantes
                else _fonte("animesdrive")
            ),
        }

    async def _buscar_titulos_fake(titulo: str) -> TitulosDeAnime | None:
        assert titulo == "Dogul Wang"
        # romaji == título digitado; só o inglês diverge e amplia a escada.
        return TitulosDeAnime(titulo_romaji="Dogul Wang", titulo_ingles="Tomb Raider King")

    monkeypatch.setattr(
        "fontes.busca.servico.buscar_por_site_com_variantes",
        _buscar_por_site_com_variantes_fake,
    )
    monkeypatch.setattr("integrations.servico.buscar_titulos", _buscar_titulos_fake)

    resultado = await servico_busca.buscar_em_todas_as_fontes_com_titulos_alternativos(
        None, "Dogul Wang"
    )

    assert rodadas == [None]  # uma rodada de scraping só — o inglês entrou na Fase 1
    fontes = {f.dominio: f for f in resultado}
    assert fontes["animefire.one"].candidatos == [candidato_af]
    assert fontes["animesdrive"].candidatos == [candidato_ad]
    assert fontes["meusanimes"].candidatos == []


async def test_todas_faz_uma_rodada_so_quando_todos_os_sites_acham(
    monkeypatch: pytest.MonkeyPatch,
):
    """Os três sites acharam candidato: uma rodada de scraping só (o canônico já
    foi resolvido upfront, `buscar_titulos` stubado)."""
    candidato_af = ResultadoBusca(
        titulo_exibicao="Naruto", identificador="1", url="https://af/1"
    )
    candidato_am = ResultadoBusca(
        titulo_exibicao="Naruto", identificador="2", url="https://am/2"
    )
    candidato_ad = ResultadoBusca(
        titulo_exibicao="Naruto", identificador="3", url="https://ad/3"
    )
    rodadas: list[list[str] | None] = []

    async def _buscar_por_site_com_variantes_fake(
        sessionmaker, variantes, *, referencias, dominios=None
    ):
        rodadas.append(dominios)
        return {
            "animefire.one": _fonte("animefire.one", candidato_af),
            "meusanimes": _fonte("meusanimes", candidato_am),
            "animesdrive": _fonte("animesdrive", candidato_ad),
        }

    async def _buscar_titulos_fake(titulo: str) -> TitulosDeAnime | None:
        return TitulosDeAnime(titulo_romaji="Naruto", titulo_ingles=None)

    monkeypatch.setattr(
        "fontes.busca.servico.buscar_por_site_com_variantes",
        _buscar_por_site_com_variantes_fake,
    )
    monkeypatch.setattr("integrations.servico.buscar_titulos", _buscar_titulos_fake)

    resultado = await servico_busca.buscar_em_todas_as_fontes_com_titulos_alternativos(
        None, "Naruto"
    )

    assert rodadas == [None]  # uma rodada de scraping só
    fontes = {f.dominio: f for f in resultado}
    assert fontes["animefire.one"].candidatos == [candidato_af]
    assert fontes["meusanimes"].candidatos == [candidato_am]
    assert fontes["animesdrive"].candidatos == [candidato_ad]


async def test_todas_toda_vazia_e_preservada(monkeypatch: pytest.MonkeyPatch):
    """Nenhum site acha nada: cada fonte fica disponível-vazia com `motivo`
    `None` — "não achei" nunca vira "indisponível" nem "não consultado"
    (CLAUDE.md §4)."""
    romaji = "Naruto Shippuuden"

    async def _buscar_por_site_com_variantes_fake(
        sessionmaker, variantes, *, referencias, dominios=None
    ):
        return {
            "animefire.one": _fonte("animefire.one"),
            "meusanimes": _fonte("meusanimes"),
            "animesdrive": _fonte("animesdrive"),
        }

    async def _buscar_titulos_fake(titulo: str) -> TitulosDeAnime | None:
        return TitulosDeAnime(titulo_romaji=romaji, titulo_ingles=None)

    monkeypatch.setattr(
        "fontes.busca.servico.buscar_por_site_com_variantes",
        _buscar_por_site_com_variantes_fake,
    )
    monkeypatch.setattr("integrations.servico.buscar_titulos", _buscar_titulos_fake)

    resultado = await servico_busca.buscar_em_todas_as_fontes_com_titulos_alternativos(
        None, "Naruto"
    )

    assert all(not fonte.indisponivel and fonte.candidatos == [] for fonte in resultado)
    assert all(fonte.motivo is None for fonte in resultado)


async def test_todas_falha_de_metadados_nao_propaga_e_busca_so_com_o_digitado(
    monkeypatch: pytest.MonkeyPatch,
):
    """`buscar_titulos` lança → `resolver_titulos_canonicos` degrada pra
    `None` (best-effort, upfront) e a busca segue só com o título
    digitado como referência (`referencias == [titulo]`), sem propagar a
    exceção."""
    referencias_vistas: list[list[str]] = []

    async def _buscar_por_site_com_variantes_fake(
        sessionmaker, variantes, *, referencias, dominios=None
    ):
        referencias_vistas.append(referencias)
        return {
            "animefire.one": _fonte("animefire.one"),
            "meusanimes": _fonte("meusanimes"),
            "animesdrive": _fonte("animesdrive"),
        }

    async def _buscar_titulos_falha(titulo: str):
        raise FalhaDeMetadados("todos os provedores de metadados falharam")

    monkeypatch.setattr(
        "fontes.busca.servico.buscar_por_site_com_variantes",
        _buscar_por_site_com_variantes_fake,
    )
    monkeypatch.setattr("integrations.servico.buscar_titulos", _buscar_titulos_falha)

    resultado = await servico_busca.buscar_em_todas_as_fontes_com_titulos_alternativos(
        None, "Slime"
    )

    assert referencias_vistas == [["Slime"]]  # degradou: Fase 1 só com o digitado
    dominios = {fonte.dominio for fonte in resultado}
    assert dominios == {"animefire.one", "meusanimes", "animesdrive"}


async def test_todas_todos_os_sites_indisponiveis_ainda_resolve_o_canonico_upfront(
    monkeypatch: pytest.MonkeyPatch,
):
    """A resolução canônica roda SEMPRE, upfront (a escada combinada depende
    dela) — a orquestração antiga a pulava quando todo site já vinha
    `indisponivel`. Uma rodada de scraping só; cada fonte volta `indisponivel`."""
    titulos_chamado: list[str] = []
    rodadas: list[list[str] | None] = []

    async def _buscar_por_site_com_variantes_fake(
        sessionmaker, variantes, *, referencias, dominios=None
    ):
        rodadas.append(dominios)
        return {
            "animefire.one": _fonte_indisponivel("animefire.one"),
            "meusanimes": _fonte_indisponivel("meusanimes"),
            "animesdrive": _fonte_indisponivel("animesdrive"),
        }

    async def _buscar_titulos_fake(titulo: str) -> TitulosDeAnime | None:
        titulos_chamado.append(titulo)
        return TitulosDeAnime(titulo_romaji="Naruto Shippuuden", titulo_ingles=None)

    monkeypatch.setattr(
        "fontes.busca.servico.buscar_por_site_com_variantes",
        _buscar_por_site_com_variantes_fake,
    )
    monkeypatch.setattr("integrations.servico.buscar_titulos", _buscar_titulos_fake)

    resultado = await servico_busca.buscar_em_todas_as_fontes_com_titulos_alternativos(
        None, "Naruto"
    )

    assert titulos_chamado == ["Naruto"]
    assert rodadas == [None]  # uma rodada de scraping só
    assert all(fonte.indisponivel for fonte in resultado)


# --- cache de "Trocar fonte" ---


def _contador_de_buscas(monkeypatch: pytest.MonkeyPatch, fontes: list[ResultadoDeFonte]):
    chamadas = {"n": 0}

    async def _sem_titulos(titulo):
        return None

    async def _buscar(sessionmaker, variantes, *, referencias, dominios=None):
        chamadas["n"] += 1
        return {fonte.dominio: fonte for fonte in fontes}

    monkeypatch.setattr("integrations.servico.buscar_titulos", _sem_titulos)
    monkeypatch.setattr(servico_busca.servico_fontes, "buscar_por_site_com_variantes", _buscar)
    return chamadas


def _todas_com_candidato() -> list[ResultadoDeFonte]:
    return [_fonte_com(extrator.dominio) for extrator in EXTRATORES]


def _fonte_com(dominio: str) -> ResultadoDeFonte:
    candidato = ResultadoBusca(titulo_exibicao="Overlord", identificador="o", url="https://x/o")
    return ResultadoDeFonte(
        dominio=dominio, candidatos=[candidato], indisponivel=False, motivo=None
    )


async def test_cache_de_busca_reaproveita_resposta_positiva_dentro_do_ttl(monkeypatch):
    chamadas = _contador_de_buscas(monkeypatch, _todas_com_candidato())

    buscar = servico_busca.buscar_em_todas_as_fontes_com_titulos_alternativos
    primeira = await buscar(None, "Overlord II")
    segunda = await buscar(None, "  overlord ii ")

    assert chamadas["n"] == 1
    assert segunda == primeira


async def test_cache_de_busca_expira_depois_do_ttl(monkeypatch):
    chamadas = _contador_de_buscas(monkeypatch, _todas_com_candidato())
    relogio = {"t": 1000.0}
    monkeypatch.setattr(servico_busca, "_relogio", lambda: relogio["t"])

    await servico_busca.buscar_em_todas_as_fontes_com_titulos_alternativos(None, "Overlord II")
    relogio["t"] += servico_busca._TTL_CACHE_DE_BUSCA_S + 1
    await servico_busca.buscar_em_todas_as_fontes_com_titulos_alternativos(None, "Overlord II")

    assert chamadas["n"] == 2


async def test_cache_de_busca_nao_guarda_resposta_sem_candidato_nem_com_site_indisponivel(
    monkeypatch,
):
    vazia = ResultadoDeFonte(
        dominio="animefire.one", candidatos=[], indisponivel=False, motivo=None
    )
    fora = ResultadoDeFonte(
        dominio="animefire.one", candidatos=[], indisponivel=True, motivo="fora do ar"
    )
    # só o MeusAnimes respondeu: os demais sites saem como "não consultado"
    sem_consulta = [_fonte_com("meusanimes")]
    parcial = [fora, *_todas_com_candidato()[1:]]
    casos = (("Sem nada", [vazia]), ("Parcial", parcial), ("Incompleta", sem_consulta))
    for titulo, fontes in casos:
        chamadas = _contador_de_buscas(monkeypatch, fontes)
        await servico_busca.buscar_em_todas_as_fontes_com_titulos_alternativos(None, titulo)
        await servico_busca.buscar_em_todas_as_fontes_com_titulos_alternativos(None, titulo)
        assert chamadas["n"] == 2, titulo


async def test_cache_de_busca_e_limitado_e_descarta_a_entrada_mais_antiga(monkeypatch):
    chamadas = _contador_de_buscas(monkeypatch, _todas_com_candidato())
    monkeypatch.setattr(servico_busca, "_MAXIMO_ENTRADAS_CACHE_DE_BUSCA", 2)

    for titulo in ("Um", "Dois", "Tres"):
        await servico_busca.buscar_em_todas_as_fontes_com_titulos_alternativos(None, titulo)
    await servico_busca.buscar_em_todas_as_fontes_com_titulos_alternativos(None, "Um")

    assert chamadas["n"] == 4  # "Um" foi despejada ao entrar "Tres"

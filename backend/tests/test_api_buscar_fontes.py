"""Testes de `GET /api/animes/buscar-fontes` (`api/rotas/animes.py` ->
`api/servicos/busca.py::buscar_em_todas_as_fontes_com_titulos_alternativos` ->
`extractors/busca/servico.py::buscar_por_site_com_variantes`).

A busca é sempre a UNIÃO das fontes onde o anime existe: resolve o anime canônico no
provedor de metadados (`integrations.servico.buscar_titulos`) UPFRONT e consulta todos
os sites em paralelo, cada um esgotando sua própria escada de variantes. A resposta
traz `resultados` (um por candidato) e `fontes` (status de cada site, com motivo de
indisponibilidade); não há mais `termo_alternativo`/`dominio_alternativo` nem parâmetro
`escopo`. `buscar_em_com_variantes` é monkeypatchado em `extractors.busca.servico`
(`buscar_por_site_com_variantes` o chama pelo nome de módulo, então o patch alcança as
duas etapas); `extrator.buscar`/`resiliencia.chamar` têm cobertura própria em
`test_extractors_servico.py`.

`integrations.servico.buscar_titulos` é stubado por padrão pela fixture autouse
`_resolucao_de_titulo_canonico_sem_rede` deste arquivo (devolve `None`); testes que
precisam de um `TitulosDeAnime` específico re-`setattr`am por cima. O enriquecimento de
capa por `integrations.servico.buscar_por_titulo` é coberto pela autouse
`_busca_de_metadados_por_titulo_sem_rede` (conftest.py)."""


import pytest
from httpx import AsyncClient

from extractors.base import ResultadoBusca
from extractors.busca.servico import ResultadoDeFonte
from integrations.base import TitulosDeAnime


@pytest.fixture(autouse=True)
def _resolucao_de_titulo_canonico_sem_rede(monkeypatch: pytest.MonkeyPatch):
    """`buscar_com_titulos_alternativos` resolve o canônico no provedor
    (`integrations.servico.buscar_titulos`, só AniList — `PROVEDORES_DE_TITULO`)
    ANTES de qualquer scraping e SEMPRE — sem stub, todo teste deste arquivo
    bateria em AniList de verdade. Devolve `None` ("provedor respondeu, não
    achou"); os testes que exercitam o caminho de título alternativo
    re-`setattr`am por cima com um `TitulosDeAnime`."""

    async def _sem_titulos(titulo):
        return None

    monkeypatch.setattr("integrations.servico.buscar_titulos", _sem_titulos)


def _fonte(dominio: str, *candidatos: ResultadoBusca) -> ResultadoDeFonte:
    return ResultadoDeFonte(
        dominio=dominio, candidatos=list(candidatos), indisponivel=False, motivo=None
    )


def _fonte_indisponivel(dominio: str, motivo: str) -> ResultadoDeFonte:
    return ResultadoDeFonte(dominio=dominio, candidatos=[], indisponivel=True, motivo=motivo)


async def test_buscar_fontes_titulo_vazio_nao_chama_extrator(
    cliente: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    async def _falha_se_chamado(sessionmaker, dominio, variantes, *, referencias):
        raise AssertionError("buscar_em_com_variantes não deveria ser chamado para título vazio")

    monkeypatch.setattr("extractors.busca.servico.buscar_em_com_variantes", _falha_se_chamado)

    resposta = await cliente.get("/api/animes/buscar-fontes", params={"titulo": "   "})

    assert resposta.status_code == 200
    assert resposta.json() == {
        "resultados": [],
        "fontes": [],
    }


async def test_buscar_fontes_falha_de_um_extrator_nao_derruba_resposta(
    cliente: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    async def _buscar_em_com_variantes_fake(sessionmaker, dominio, variantes, *, referencias):
        if dominio == "animefire.one":
            return _fonte_indisponivel("animefire.one", "site fora do ar"), None
        if dominio == "meusanimes":
            return _fonte("meusanimes"), None
        candidato = ResultadoBusca(titulo_exibicao="Naruto", identificador="1", url="https://x/1")
        return _fonte("animesdrive", candidato), None

    async def _buscar_por_titulo_fake(titulo):
        return None

    monkeypatch.setattr(
        "extractors.busca.servico.buscar_em_com_variantes", _buscar_em_com_variantes_fake
    )
    monkeypatch.setattr("integrations.servico.buscar_por_titulo", _buscar_por_titulo_fake)

    resposta = await cliente.get("/api/animes/buscar-fontes", params={"titulo": "naruto"})

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert len(corpo["resultados"]) == 1
    assert corpo["resultados"][0]["dominio"] == "animesdrive"
    assert corpo["resultados"][0]["titulo_exibicao"] == "Naruto"

    fontes_por_dominio = {fonte["dominio"]: fonte for fonte in corpo["fontes"]}
    assert fontes_por_dominio["animefire.one"]["indisponivel"] is True
    assert fontes_por_dominio["animefire.one"]["motivo"] == "site fora do ar"
    assert fontes_por_dominio["animesdrive"]["indisponivel"] is False


async def test_buscar_fontes_fonte_em_cooldown_aparece_como_indisponivel(
    cliente: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """Um site em cooldown chega a `buscar_em_com_variantes` (que checa
    cooldown por dentro, via `resiliencia.chamar` — coberto em
    `test_extractors_servico.py`) já como `indisponivel=True`; aqui o que se
    cobre é que a API repassa esse status intacto, sem mascarar como "não
    achei nada"."""

    async def _buscar_em_com_variantes_fake(sessionmaker, dominio, variantes, *, referencias):
        if dominio == "animefire.one":
            return (
                _fonte_indisponivel("animefire.one", "em cooldown até 2026-01-01 12:00:00 UTC"),
                None,
            )
        if dominio == "meusanimes":
            return _fonte("meusanimes"), None
        candidato = ResultadoBusca(titulo_exibicao="Naruto", identificador="1", url="https://x/1")
        return _fonte("animesdrive", candidato), None

    async def _buscar_por_titulo_fake(titulo):
        return None

    monkeypatch.setattr(
        "extractors.busca.servico.buscar_em_com_variantes", _buscar_em_com_variantes_fake
    )
    monkeypatch.setattr("integrations.servico.buscar_por_titulo", _buscar_por_titulo_fake)

    resposta = await cliente.get("/api/animes/buscar-fontes", params={"titulo": "naruto"})

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert len(corpo["resultados"]) == 1
    assert corpo["resultados"][0]["dominio"] == "animesdrive"

    fontes_por_dominio = {fonte["dominio"]: fonte for fonte in corpo["fontes"]}
    assert fontes_por_dominio["animefire.one"]["indisponivel"] is True
    motivo_esperado = "em cooldown até 2026-01-01 12:00:00 UTC"
    assert fontes_por_dominio["animefire.one"]["motivo"] == motivo_esperado
    assert fontes_por_dominio["animesdrive"]["indisponivel"] is False


async def test_buscar_fontes_site_padrao_indisponivel_faz_fan_out_e_preserva_o_motivo(
    cliente: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """Site padrão indisponível (em cooldown) -> fan-out nos restantes, que
    também vêm vazios, e o provedor não resolve título canônico nenhum. A
    resposta final não tem vencedor, mas o motivo de indisponibilidade do site
    padrão precisa chegar intacto (CLAUDE.md §4 — "indisponível" nunca vira
    "não achei nada")."""

    async def _buscar_em_com_variantes_fake(sessionmaker, dominio, variantes, *, referencias):
        if dominio == "animefire.one":
            return _fonte_indisponivel("animefire.one", "em cooldown"), None
        return _fonte(dominio), None

    monkeypatch.setattr(
        "extractors.busca.servico.buscar_em_com_variantes", _buscar_em_com_variantes_fake
    )

    resposta = await cliente.get("/api/animes/buscar-fontes", params={"titulo": "naruto"})

    assert resposta.status_code == 200
    corpo = resposta.json()
    fontes_por_dominio = {fonte["dominio"]: fonte for fonte in corpo["fontes"]}
    assert set(fontes_por_dominio) == {"animefire.one", "meusanimes", "animesdrive"}
    assert fontes_por_dominio["animefire.one"]["indisponivel"] is True
    assert fontes_por_dominio["animefire.one"]["motivo"] == "em cooldown"
    assert corpo["resultados"] == []


async def test_buscar_fontes_registrada_antes_do_catch_all_anime_id(
    cliente: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """Se `/buscar-fontes` estivesse declarada depois de `/{anime_id}`, esta
    chamada cairia no handler de `obter_anime` (que rejeitaria "buscar-fontes"
    como `anime_id: int` com 422) em vez de bater na busca em fontes."""

    async def _buscar_em_com_variantes_fake(sessionmaker, dominio, variantes, *, referencias):
        return _fonte(dominio), None

    async def _buscar_titulos_fake(titulo):
        return None

    monkeypatch.setattr(
        "extractors.busca.servico.buscar_em_com_variantes", _buscar_em_com_variantes_fake
    )
    # As duas fontes disponíveis vêm vazias -> dispara a Fase 2 (expansão por
    # termo de provedor); sem este patch, bateria no AniList/Kitsu de verdade.
    monkeypatch.setattr("integrations.servico.buscar_titulos", _buscar_titulos_fake)

    resposta = await cliente.get("/api/animes/buscar-fontes", params={"titulo": "naruto"})

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["resultados"] == []
    assert {fonte["dominio"] for fonte in corpo["fontes"]} == {
        "animefire.one",
        "meusanimes",
        "animesdrive",
    }


async def test_buscar_fontes_expande_com_titulo_alternativo_quando_termo_digitado_vazio(
    cliente: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """Ponta a ponta da tolerância a idioma (D3 do plano): a busca com o termo
    digitado (PT, que não alcança o card) vem vazia em todas as fontes
    disponíveis, mas o provedor de metadados acha o romaji, que devolve
    candidato — a resposta final expõe o candidato de cada site (contrato de
    UNIÃO: um resultado por fonte que tem o anime)."""

    romaji = "Tensei Shitara Slime Datta Ken"

    async def _buscar_em_com_variantes_fake(sessionmaker, dominio, variantes, *, referencias):
        if romaji in variantes:
            candidato = ResultadoBusca(
                titulo_exibicao=romaji,
                identificador="1",
                url="https://x/1",
            )
            return _fonte(dominio, candidato), None
        return _fonte(dominio), None

    async def _buscar_titulos_fake(titulo):
        assert titulo == "tensei slime"
        return TitulosDeAnime(titulo_romaji=romaji, titulo_ingles=None)

    monkeypatch.setattr(
        "extractors.busca.servico.buscar_em_com_variantes", _buscar_em_com_variantes_fake
    )
    monkeypatch.setattr("integrations.servico.buscar_titulos", _buscar_titulos_fake)

    resposta = await cliente.get("/api/animes/buscar-fontes", params={"titulo": "tensei slime"})

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert {r["dominio"] for r in corpo["resultados"]} == {
        "animefire.one",
        "meusanimes",
        "animesdrive",
    }
    assert {r["titulo_exibicao"] for r in corpo["resultados"]} == {romaji}


# --- motor paralelo (o parâmetro `escopo` foi removido; a busca é sempre em união) ---


async def test_buscar_fontes_escopo_todas_usa_caminho_paralelo_e_preserva_dominio(
    cliente: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """`escopo=todas` usa `buscar_por_site_com_variantes` (cada site esgotando
    sua própria escada em paralelo, INV-1') em vez do motor de fonte única do
    `padrao` (`buscar_com_titulos_alternativos`, que passa por
    `buscar_em_com_variantes`) — candidatos de domínios diferentes na mesma
    resposta preservam `dominio` cada um (D-B4/INV-1', nunca achatar/perder
    essa informação). A resolução canônica (`buscar_titulos`) roda upfront nos
    dois escopos."""
    titulos_chamado: list[str] = []

    async def _buscar_por_site_com_variantes_fake(
        sessionmaker, variantes, *, referencias, dominios=None
    ):
        candidato_af = ResultadoBusca(
            titulo_exibicao="Naruto", identificador="1", url="https://af/1"
        )
        candidato_ad = ResultadoBusca(
            titulo_exibicao="Naruto (Dublado)", identificador="2", url="https://ad/2"
        )
        return {
            "animefire.one": _fonte("animefire.one", candidato_af),
            "meusanimes": _fonte("meusanimes"),
            "animesdrive": _fonte("animesdrive", candidato_ad),
        }

    async def _falha_se_chamado(sessionmaker, dominio, variantes, *, referencias):
        raise AssertionError("escopo=todas não deveria usar o motor de fonte única do padrao")

    async def _sem_titulos_de_provedor(titulo):
        titulos_chamado.append(titulo)
        return None

    monkeypatch.setattr(
        "extractors.busca.servico.buscar_por_site_com_variantes",
        _buscar_por_site_com_variantes_fake,
    )
    monkeypatch.setattr("extractors.busca.servico.buscar_em_com_variantes", _falha_se_chamado)
    monkeypatch.setattr("integrations.servico.buscar_titulos", _sem_titulos_de_provedor)

    resposta = await cliente.get(
        "/api/animes/buscar-fontes", params={"titulo": "naruto", "escopo": "todas"}
    )

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert titulos_chamado == ["naruto"]  # canônico resolvido upfront no escopo `todas`
    assert len(corpo["resultados"]) == 2
    por_dominio = {resultado["dominio"]: resultado for resultado in corpo["resultados"]}
    assert set(por_dominio) == {"animefire.one", "animesdrive"}
    assert por_dominio["animefire.one"]["identificador"] == "1"
    assert por_dominio["animesdrive"]["identificador"] == "2"




async def test_buscar_fontes_correspondencia_incerta_vai_depois_dos_cards_validados(
    cliente: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """Regressão ao vivo (Wan Ren Zhi Shang): 3 cards incertos do AnimeFire, que vem
    primeiro na ordem dos sites, apareciam acima do card certo do MeusAnimes."""

    async def _buscar_em_com_variantes_fake(sessionmaker, dominio, variantes, *, referencias):
        if dominio == "animefire.one":
            incerto = ResultadoBusca(titulo_exibicao="Outro", identificador="x", url="https://x/x")
            return (
                ResultadoDeFonte(
                    dominio=dominio,
                    candidatos=[incerto],
                    indisponivel=False,
                    motivo=None,
                    correspondencia_incerta=True,
                ),
                None,
            )
        if dominio == "meusanimes":
            certo = ResultadoBusca(titulo_exibicao="Certo", identificador="c", url="https://x/c")
            return _fonte("meusanimes", certo), None
        return _fonte(dominio), None

    monkeypatch.setattr(
        "extractors.busca.servico.buscar_em_com_variantes", _buscar_em_com_variantes_fake
    )

    resposta = await cliente.get("/api/animes/buscar-fontes", params={"titulo": "Qualquer"})

    assert resposta.status_code == 200
    titulos = [r["titulo_exibicao"] for r in resposta.json()["resultados"]]
    assert titulos == ["Certo", "Outro"]

"""Testes de `GET /api/animes/buscar-fontes` (`api/rotas/animes.py` ->
`api/servicos/busca.py::buscar_com_titulos_alternativos` ->
`extractors/busca/servico.py::buscar_em_com_variantes`). A busca é sequencial por
site, em duas fases ordenadas por custo (Fase A, fatia 3 de
PLANO_PADRONIZACAO_FONTES.md): variantes puras de regex primeiro, termos de
provedor externo (romaji/inglês) só se nenhum site achar nada com elas.
`buscar_em_com_variantes` é monkeypatchado em `extractors.busca.servico` (mesmo
módulo que a rota chama via `servico_extractors`, então o patch vale pros
dois nomes) — mesmo padrão de `test_api_animes.py` para resolução de fonte,
um nível mais alto que `extrator.buscar`/`resiliencia.chamar` (essas duas
camadas já têm cobertura própria em `test_extractors_servico.py`). Testes
cujos candidatos falsos saem sem `capa_url` também monkeypatcham
`integrations.servico.buscar_por_titulo` — sem isso, `enriquecer_capas`
tentaria consultar AniList/Kitsu de verdade. Pelo mesmo motivo, testes cuja
Fase 1 vem vazia em todos os sites também monkeypatcham
`integrations.servico.buscar_titulos` — sem isso, a Fase 2 (expansão por
termo de provedor) tentaria consultar AniList/Kitsu de verdade."""

import pytest
from httpx import AsyncClient

from extractors.base import ResultadoBusca
from extractors.busca.servico import ResultadoDeFonte
from integrations.base import TitulosDeAnime


def _fonte(dominio: str, *candidatos: ResultadoBusca) -> ResultadoDeFonte:
    return ResultadoDeFonte(
        dominio=dominio, candidatos=list(candidatos), indisponivel=False, motivo=None
    )


def _fonte_indisponivel(dominio: str, motivo: str) -> ResultadoDeFonte:
    return ResultadoDeFonte(dominio=dominio, candidatos=[], indisponivel=True, motivo=motivo)


async def test_buscar_fontes_titulo_vazio_nao_chama_extrator(
    cliente: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    async def _falha_se_chamado(sessionmaker, dominio, variantes, *, referencia):
        raise AssertionError("buscar_em_com_variantes não deveria ser chamado para título vazio")

    monkeypatch.setattr("extractors.busca.servico.buscar_em_com_variantes", _falha_se_chamado)

    resposta = await cliente.get("/api/animes/buscar-fontes", params={"titulo": "   "})

    assert resposta.status_code == 200
    assert resposta.json() == {
        "resultados": [],
        "fontes": [],
        "termo_alternativo": None,
        "dominio_alternativo": None,
    }


async def test_buscar_fontes_falha_de_um_extrator_nao_derruba_resposta(
    cliente: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    async def _buscar_em_com_variantes_fake(sessionmaker, dominio, variantes, *, referencia):
        if dominio == "animefire.io":
            return _fonte_indisponivel("animefire.io", "site fora do ar"), None
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
    # Quem respondeu não foi o site padrão (animefire.io falhou) — preenchido.
    assert corpo["dominio_alternativo"] == "animesdrive"

    fontes_por_dominio = {fonte["dominio"]: fonte for fonte in corpo["fontes"]}
    assert fontes_por_dominio["animefire.io"]["indisponivel"] is True
    assert fontes_por_dominio["animefire.io"]["motivo"] == "site fora do ar"
    assert fontes_por_dominio["animesdrive"]["indisponivel"] is False


async def test_buscar_fontes_fonte_em_cooldown_aparece_como_indisponivel(
    cliente: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """Um site em cooldown chega a `buscar_em_com_variantes` (que checa
    cooldown por dentro, via `resiliencia.chamar` — coberto em
    `test_extractors_servico.py`) já como `indisponivel=True`; aqui o que se
    cobre é que a API repassa esse status intacto, sem mascarar como "não
    achei nada"."""

    async def _buscar_em_com_variantes_fake(sessionmaker, dominio, variantes, *, referencia):
        if dominio == "animefire.io":
            return (
                _fonte_indisponivel("animefire.io", "em cooldown até 2026-01-01 12:00:00 UTC"),
                None,
            )
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
    assert corpo["dominio_alternativo"] == "animesdrive"

    fontes_por_dominio = {fonte["dominio"]: fonte for fonte in corpo["fontes"]}
    assert fontes_por_dominio["animefire.io"]["indisponivel"] is True
    motivo_esperado = "em cooldown até 2026-01-01 12:00:00 UTC"
    assert fontes_por_dominio["animefire.io"]["motivo"] == motivo_esperado
    assert fontes_por_dominio["animesdrive"]["indisponivel"] is False


async def test_buscar_fontes_site_indisponivel_ainda_expande_com_termo_de_provedor_no_outro(
    cliente: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """Fase 1 vazia nos dois sites (um indisponível, o outro sem candidatos)
    -> dispara a Fase 2 (expansão por termo de provedor); aqui o provedor
    também não acha título nenhum, então a resposta final só precisa manter o
    motivo de indisponibilidade do site em cooldown intacto."""

    async def _buscar_em_com_variantes_fake(sessionmaker, dominio, variantes, *, referencia):
        if dominio == "animefire.io":
            return _fonte_indisponivel("animefire.io", "em cooldown"), None
        return _fonte("animesdrive"), None

    async def _buscar_titulos_fake(titulo):
        return None

    monkeypatch.setattr(
        "extractors.busca.servico.buscar_em_com_variantes", _buscar_em_com_variantes_fake
    )
    monkeypatch.setattr("integrations.servico.buscar_titulos", _buscar_titulos_fake)

    resposta = await cliente.get("/api/animes/buscar-fontes", params={"titulo": "naruto"})

    assert resposta.status_code == 200
    corpo = resposta.json()
    fontes_por_dominio = {fonte["dominio"]: fonte for fonte in corpo["fontes"]}
    assert fontes_por_dominio["animefire.io"]["motivo"] == "em cooldown"
    assert corpo["termo_alternativo"] is None
    assert corpo["dominio_alternativo"] is None


async def test_buscar_fontes_registrada_antes_do_catch_all_anime_id(
    cliente: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """Se `/buscar-fontes` estivesse declarada depois de `/{anime_id}`, esta
    chamada cairia no handler de `obter_anime` (que rejeitaria "buscar-fontes"
    como `anime_id: int` com 422) em vez de bater na busca em fontes."""

    async def _buscar_em_com_variantes_fake(sessionmaker, dominio, variantes, *, referencia):
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
    assert corpo["termo_alternativo"] is None
    assert corpo["dominio_alternativo"] is None
    assert {fonte["dominio"] for fonte in corpo["fontes"]} == {
        "animefire.io",
        "animesdrive",
    }


async def test_buscar_fontes_expande_com_titulo_alternativo_quando_termo_digitado_vazio(
    cliente: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """Ponta a ponta da tolerância a idioma (D3 do plano): a busca com o termo
    digitado vem vazia em todas as fontes disponíveis, mas o provedor de
    metadados acha um título alternativo (romaji) que devolve candidato — a
    resposta final expõe esse candidato junto com `termo_alternativo`
    preenchido, para a UI avisar que o resultado veio de um termo diferente.
    Como quem respondeu foi o site padrão (animefire.io), `dominio_alternativo`
    continua `None` — só o termo mudou, não o site."""

    romaji = "Naruto Shippuden"

    async def _buscar_em_com_variantes_fake(sessionmaker, dominio, variantes, *, referencia):
        if romaji in variantes:
            candidato = ResultadoBusca(
                titulo_exibicao="Naruto Shippuden",
                identificador="1",
                url="https://x/1",
                capa_url="https://cdn/naruto.jpg",
            )
            return _fonte(dominio, candidato), None
        return _fonte(dominio), None

    async def _buscar_titulos_fake(titulo):
        assert titulo == "naruto"
        return TitulosDeAnime(titulo_romaji=romaji, titulo_ingles=None)

    monkeypatch.setattr(
        "extractors.busca.servico.buscar_em_com_variantes", _buscar_em_com_variantes_fake
    )
    monkeypatch.setattr("integrations.servico.buscar_titulos", _buscar_titulos_fake)

    resposta = await cliente.get("/api/animes/buscar-fontes", params={"titulo": "naruto"})

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["termo_alternativo"] == "Naruto Shippuden"
    assert corpo["dominio_alternativo"] is None
    assert len(corpo["resultados"]) == 1
    assert corpo["resultados"][0]["titulo_exibicao"] == "Naruto Shippuden"
    assert corpo["resultados"][0]["dominio"] == "animefire.io"


# --- fatia 2 da Fase B: parâmetro `escopo` (PLANO_PADRONIZACAO_FONTES.md) ---


async def test_buscar_fontes_escopo_ausente_e_padrao_explicito_sao_identicos(
    cliente: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """`escopo` ausente cai no default `"padrao"` — mesmo resultado que passar
    `escopo=padrao` explicitamente. Regressão: o comportamento anterior a esta
    fatia (só existia o caminho `padrao`) não pode mudar."""

    async def _buscar_em_com_variantes_fake(sessionmaker, dominio, variantes, *, referencia):
        if dominio == "animefire.io":
            candidato = ResultadoBusca(
                titulo_exibicao="Naruto", identificador="1", url="https://x/1"
            )
            return _fonte(dominio, candidato), None
        return _fonte(dominio), None

    monkeypatch.setattr(
        "extractors.busca.servico.buscar_em_com_variantes", _buscar_em_com_variantes_fake
    )

    sem_escopo = await cliente.get("/api/animes/buscar-fontes", params={"titulo": "naruto"})
    com_escopo_padrao = await cliente.get(
        "/api/animes/buscar-fontes", params={"titulo": "naruto", "escopo": "padrao"}
    )

    assert sem_escopo.status_code == 200
    assert com_escopo_padrao.status_code == 200
    assert sem_escopo.json() == com_escopo_padrao.json()


async def test_buscar_fontes_padrao_lista_dominio_nao_consultado_quando_primeiro_ja_acha(
    cliente: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """AnimeFire (site padrão, `EXTRATORES[0]`) acha candidato na Fase 1 — o
    laço sequencial nunca chega a chamar `buscar_em_com_variantes` para
    animesdrive. Mesmo assim `fontes` tem que listar os dois domínios
    (D-B1): o não consultado sai com `indisponivel=False`, e um motivo que
    deixa isso explícito — senão `todasFontesIndisponiveis` da Home mentiria
    quando na verdade só um site foi de fato tentado."""

    async def _buscar_em_com_variantes_fake(sessionmaker, dominio, variantes, *, referencia):
        assert dominio == "animefire.io", "animesdrive não deveria ser consultado"
        candidato = ResultadoBusca(titulo_exibicao="Naruto", identificador="1", url="https://x/1")
        return _fonte(dominio, candidato), None

    monkeypatch.setattr(
        "extractors.busca.servico.buscar_em_com_variantes", _buscar_em_com_variantes_fake
    )

    resposta = await cliente.get("/api/animes/buscar-fontes", params={"titulo": "naruto"})

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert len(corpo["resultados"]) == 1
    fontes_por_dominio = {fonte["dominio"]: fonte for fonte in corpo["fontes"]}
    assert set(fontes_por_dominio) == {"animefire.io", "animesdrive"}
    assert fontes_por_dominio["animesdrive"]["indisponivel"] is False
    assert "não consultado" in fontes_por_dominio["animesdrive"]["motivo"]


async def test_buscar_fontes_escopo_todas_usa_caminho_paralelo_e_preserva_dominio(
    cliente: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """`escopo=todas` usa `buscar_por_site_com_variantes` (fatia 3/4, cada site
    esgotando sua própria escada em paralelo, INV-1') em vez do motor
    sequencial por site (`buscar_com_titulos_alternativos`) — candidatos de
    domínios diferentes na mesma resposta preservam `dominio` cada um
    (D-B4/INV-1', nunca achatar/perder essa informação)."""

    async def _buscar_por_site_com_variantes_fake(
        sessionmaker, variantes, *, referencia, dominios=None
    ):
        candidato_af = ResultadoBusca(
            titulo_exibicao="Naruto", identificador="1", url="https://af/1"
        )
        candidato_ad = ResultadoBusca(
            titulo_exibicao="Naruto (Dublado)", identificador="2", url="https://ad/2"
        )
        return {
            "animefire.io": _fonte("animefire.io", candidato_af),
            "animesdrive": _fonte("animesdrive", candidato_ad),
        }

    async def _falha_se_chamado(sessionmaker, dominio, variantes, *, referencia):
        raise AssertionError("escopo=todas não deveria usar o motor sequencial por site")

    monkeypatch.setattr(
        "extractors.busca.servico.buscar_por_site_com_variantes",
        _buscar_por_site_com_variantes_fake,
    )
    monkeypatch.setattr("extractors.busca.servico.buscar_em_com_variantes", _falha_se_chamado)

    resposta = await cliente.get(
        "/api/animes/buscar-fontes", params={"titulo": "naruto", "escopo": "todas"}
    )

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert len(corpo["resultados"]) == 2
    por_dominio = {resultado["dominio"]: resultado for resultado in corpo["resultados"]}
    assert set(por_dominio) == {"animefire.io", "animesdrive"}
    assert por_dominio["animefire.io"]["identificador"] == "1"
    assert por_dominio["animesdrive"]["identificador"] == "2"


async def test_buscar_fontes_escopo_invalido_da_422(cliente: AsyncClient):
    resposta = await cliente.get(
        "/api/animes/buscar-fontes", params={"titulo": "naruto", "escopo": "tudo"}
    )

    assert resposta.status_code == 422

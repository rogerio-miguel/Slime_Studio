"""Testes de `api/servicos/busca.py::buscar_com_titulos_alternativos` (e do
motor paralelo `buscar_em_todas_as_fontes_com_titulos_alternativos`), sem
rede — `integrations.servico.buscar_titulos` e `extractors.busca.servico.
buscar_em_com_variantes`/`buscar_por_site_com_variantes` são monkeypatchados
nos nomes de módulo (mesmo padrão usado em `tests/test_api_buscar_fontes.py`),
pois `busca.py` os chama via `servico_metadados`/`servico_extractors`, que
apontam pro mesmo objeto de módulo.

O enriquecimento de capa (`capas_por_titulo`) saiu de `busca.py` para
`api/servicos/capas.py` — sua cobertura mora em `tests/test_servico_capas.py`.

`buscar_com_titulos_alternativos` (escopo `padrao`, reescrito em 2026-09-06):
resolve o anime canônico no provedor UPFRONT (`buscar_titulos`, SEMPRE
chamado agora, não só quando a busca por regex deu zero), monta a escada
combinada `_termos_de_busca` e as `_referencias_de_anime`, consulta o site
padrão (`EXTRATORES[0]`, animefire.one) com `buscar_em_com_variantes` e — só se
o melhor candidato dele NÃO bate uma chave exata de referência — faz um
fan-out único (`buscar_por_site_com_variantes`, `dominios=EXTRATORES[1:]`) nos
sites restantes, elegendo UMA fonte vencedora por `proximidade_a_referencias`
com desempate pela ordem de `EXTRATORES`.

Fakes: `buscar_em_com_variantes` (passo 3, site padrão) recebe
`(sessionmaker, dominio, variantes, *, referencias)` e devolve
`(ResultadoDeFonte, variante_vencedora)`; `buscar_por_site_com_variantes`
(passo 5, fan-out) recebe `(sessionmaker, variantes, *, referencias,
dominios=None)` e devolve `dict[str, ResultadoDeFonte]` — mesmos contratos das
funções reais. `_termos_de_busca`/`_referencias_de_anime` NÃO são
monkeypatchadas: rodam de verdade sobre o `TitulosDeAnime` que o fake de
`buscar_titulos` devolve."""

import pytest

from api.servicos import busca as servico_busca
from core.erros import FalhaDeMetadados
from extractors.base import ResultadoBusca
from extractors.busca.servico import ResultadoDeFonte
from extractors.busca.termos import variantes_de_busca
from integrations.base import TitulosDeAnime


def _fonte(dominio: str, *candidatos: ResultadoBusca) -> ResultadoDeFonte:
    return ResultadoDeFonte(
        dominio=dominio, candidatos=list(candidatos), indisponivel=False, motivo=None
    )


def _fonte_indisponivel(dominio: str, motivo: str = "falhou") -> ResultadoDeFonte:
    return ResultadoDeFonte(dominio=dominio, candidatos=[], indisponivel=True, motivo=motivo)


# --- buscar_com_titulos_alternativos (escopo `padrao`) ---


def _fan_out(candidatos_por_dominio: dict[str, ResultadoBusca | None], dominios: list[str]):
    """Monta o dict de resposta de um fan-out (`buscar_por_site_com_variantes`)
    só com os `dominios` pedidos — o vencedor recebe seu candidato, o resto
    volta disponível-vazio."""
    return {
        dominio: (
            _fonte(dominio, candidatos_por_dominio[dominio])
            if candidatos_por_dominio.get(dominio) is not None
            else _fonte(dominio)
        )
        for dominio in dominios
    }


async def test_site_padrao_match_exato_faz_early_exit_sem_tocar_os_restantes(
    monkeypatch: pytest.MonkeyPatch,
):
    """O melhor candidato do site padrão bate uma chave exata de referência
    (`_e_exato`) — os demais sites nem chegam a ser consultados (contrato
    histórico preservado). `buscar_titulos` é chamado upfront de qualquer
    forma."""
    candidato = ResultadoBusca(titulo_exibicao="Naruto", identificador="1", url="https://x/1")
    chamadas: list[str] = []

    async def _buscar_em_com_variantes_fake(sessionmaker, dominio, variantes, *, referencias):
        chamadas.append(dominio)
        return _fonte(dominio, candidato), None

    async def _falha_se_chamado(sessionmaker, variantes, *, referencias, dominios=None):
        raise AssertionError("fan-out não deveria rodar após match de chave exata no site padrão")

    async def _buscar_titulos_fake(titulo: str) -> TitulosDeAnime | None:
        assert titulo == "Naruto"
        return TitulosDeAnime(titulo_romaji="Naruto", titulo_ingles=None)

    monkeypatch.setattr(
        "extractors.busca.servico.buscar_em_com_variantes", _buscar_em_com_variantes_fake
    )
    monkeypatch.setattr(
        "extractors.busca.servico.buscar_por_site_com_variantes", _falha_se_chamado
    )
    monkeypatch.setattr("integrations.servico.buscar_titulos", _buscar_titulos_fake)

    resultado = await servico_busca.buscar_com_titulos_alternativos(None, "Naruto")

    assert resultado.termo_alternativo is None
    assert resultado.dominio_alternativo is None
    assert resultado.fontes[0].candidatos == [candidato]
    assert chamadas == ["animefire.one"]


async def test_vencedor_e_site_nao_padrao_quando_so_ele_acha_no_fan_out(
    monkeypatch: pytest.MonkeyPatch,
):
    """Site padrão volta vazio (nada exato), o fan-out roda nos restantes e só
    um deles acha — ele vira o vencedor e `dominio_alternativo` traz o domínio
    real."""
    candidato = ResultadoBusca(titulo_exibicao="Naruto", identificador="2", url="https://y/1")

    async def _buscar_em_com_variantes_fake(sessionmaker, dominio, variantes, *, referencias):
        assert dominio == "animefire.one"
        return _fonte(dominio), None

    async def _buscar_por_site_com_variantes_fake(
        sessionmaker, variantes, *, referencias, dominios=None
    ):
        return _fan_out({"animesdrive": candidato}, dominios)

    async def _buscar_titulos_fake(titulo: str) -> TitulosDeAnime | None:
        return None

    monkeypatch.setattr(
        "extractors.busca.servico.buscar_em_com_variantes", _buscar_em_com_variantes_fake
    )
    monkeypatch.setattr(
        "extractors.busca.servico.buscar_por_site_com_variantes",
        _buscar_por_site_com_variantes_fake,
    )
    monkeypatch.setattr("integrations.servico.buscar_titulos", _buscar_titulos_fake)

    resultado = await servico_busca.buscar_com_titulos_alternativos(None, "Naruto")

    assert resultado.termo_alternativo is None
    assert resultado.dominio_alternativo == "animesdrive"
    # animesdrive é o 3º (último) de EXTRATORES: animefire.one → meusanimes → animesdrive.
    assert resultado.fontes[2].candidatos == [candidato]


async def test_card_do_site_padrao_casa_titulo_de_provedor_reporta_termo_alternativo(
    monkeypatch: pytest.MonkeyPatch,
):
    """O card do site padrão bate exatamente o título romaji do provedor (que
    difere do digitado) — early-exit no site padrão e `termo_alternativo` traz
    o romaji, `dominio_alternativo` fica `None` (o site foi o padrão)."""
    romaji = "Tensei Shitara Slime Datta Ken"
    candidato = ResultadoBusca(titulo_exibicao=romaji, identificador="1", url="https://x/1")

    async def _buscar_em_com_variantes_fake(sessionmaker, dominio, variantes, *, referencias):
        assert dominio == "animefire.one"
        return _fonte(dominio, candidato), None

    async def _falha_se_chamado(sessionmaker, variantes, *, referencias, dominios=None):
        raise AssertionError("match exato no site padrão dispensa o fan-out")

    async def _buscar_titulos_fake(titulo: str) -> TitulosDeAnime | None:
        assert titulo == "Slime"
        return TitulosDeAnime(titulo_romaji=romaji, titulo_ingles=None)

    monkeypatch.setattr(
        "extractors.busca.servico.buscar_em_com_variantes", _buscar_em_com_variantes_fake
    )
    monkeypatch.setattr(
        "extractors.busca.servico.buscar_por_site_com_variantes", _falha_se_chamado
    )
    monkeypatch.setattr("integrations.servico.buscar_titulos", _buscar_titulos_fake)

    resultado = await servico_busca.buscar_com_titulos_alternativos(None, "Slime")

    assert resultado.termo_alternativo == romaji
    assert resultado.dominio_alternativo is None
    assert resultado.fontes[0].candidatos == [candidato]


async def test_digitado_casa_o_card_vencedor_nao_reporta_termo_alternativo(
    monkeypatch: pytest.MonkeyPatch,
):
    """O título digitado JÁ corresponde ao card vencedor — houve resultado pro
    que o usuário digitou, então `termo_alternativo` fica `None` mesmo o romaji
    canônico slugificando diferente do digitado. Sem o guard, o banner da Home
    afirmaria "Nenhum resultado para X" quando havia."""
    candidato = ResultadoBusca(titulo_exibicao="Frieren", identificador="1", url="https://x/1")

    async def _buscar_em_com_variantes_fake(sessionmaker, dominio, variantes, *, referencias):
        assert dominio == "animefire.one"
        return _fonte(dominio, candidato), None

    async def _falha_se_chamado(sessionmaker, variantes, *, referencias, dominios=None):
        raise AssertionError("match exato no site padrão dispensa o fan-out")

    async def _buscar_titulos_fake(titulo: str) -> TitulosDeAnime | None:
        return TitulosDeAnime(
            titulo_romaji="Sousou no Frieren",
            titulo_ingles="Frieren: Beyond Journey's End",
        )

    monkeypatch.setattr(
        "extractors.busca.servico.buscar_em_com_variantes", _buscar_em_com_variantes_fake
    )
    monkeypatch.setattr(
        "extractors.busca.servico.buscar_por_site_com_variantes", _falha_se_chamado
    )
    monkeypatch.setattr("integrations.servico.buscar_titulos", _buscar_titulos_fake)

    resultado = await servico_busca.buscar_com_titulos_alternativos(None, "Frieren")

    assert resultado.termo_alternativo is None
    assert resultado.dominio_alternativo is None
    assert resultado.fontes[0].candidatos == [candidato]


async def test_card_de_site_nao_padrao_casa_titulo_de_provedor(monkeypatch: pytest.MonkeyPatch):
    """Igual ao anterior, mas quem acha o card romaji é um site restante — o
    fan-out roda, ele vence e `dominio_alternativo`/`termo_alternativo` vêm os
    dois preenchidos."""
    romaji = "Tensei Shitara Slime Datta Ken"
    candidato = ResultadoBusca(titulo_exibicao=romaji, identificador="2", url="https://y/1")

    async def _buscar_em_com_variantes_fake(sessionmaker, dominio, variantes, *, referencias):
        return _fonte(dominio), None

    async def _buscar_por_site_com_variantes_fake(
        sessionmaker, variantes, *, referencias, dominios=None
    ):
        assert referencias == ["Slime", romaji]
        return _fan_out({"animesdrive": candidato}, dominios)

    async def _buscar_titulos_fake(titulo: str) -> TitulosDeAnime | None:
        return TitulosDeAnime(titulo_romaji=romaji, titulo_ingles=None)

    monkeypatch.setattr(
        "extractors.busca.servico.buscar_em_com_variantes", _buscar_em_com_variantes_fake
    )
    monkeypatch.setattr(
        "extractors.busca.servico.buscar_por_site_com_variantes",
        _buscar_por_site_com_variantes_fake,
    )
    monkeypatch.setattr("integrations.servico.buscar_titulos", _buscar_titulos_fake)

    resultado = await servico_busca.buscar_com_titulos_alternativos(None, "Slime")

    assert resultado.termo_alternativo == romaji
    assert resultado.dominio_alternativo == "animesdrive"


async def test_termo_alternativo_resolve_para_o_ingles_quando_o_card_casa_o_ingles(
    monkeypatch: pytest.MonkeyPatch,
):
    """Escada combinada num único fan-out (não mais termo a termo): o card do
    vencedor bate exatamente o título INGLÊS do provedor, então
    `termo_alternativo` resolve pro inglês — `proximidade_a_referencias`
    isolada por candidato canônico escolhe a menor tupla, não a ordem da
    lista. `buscar_por_site_com_variantes` é chamado UMA vez, com a lista de
    referências multi-idioma."""
    romaji = "Kimi no Na wa"
    ingles = "Your Name"
    candidato = ResultadoBusca(titulo_exibicao="Your Name", identificador="9", url="https://y/9")
    chamadas_fan_out: list[list[str]] = []

    async def _buscar_em_com_variantes_fake(sessionmaker, dominio, variantes, *, referencias):
        return _fonte(dominio), None

    async def _buscar_por_site_com_variantes_fake(
        sessionmaker, variantes, *, referencias, dominios=None
    ):
        chamadas_fan_out.append(referencias)
        return _fan_out({"animesdrive": candidato}, dominios)

    async def _buscar_titulos_fake(titulo: str) -> TitulosDeAnime | None:
        return TitulosDeAnime(titulo_romaji=romaji, titulo_ingles=ingles)

    monkeypatch.setattr(
        "extractors.busca.servico.buscar_em_com_variantes", _buscar_em_com_variantes_fake
    )
    monkeypatch.setattr(
        "extractors.busca.servico.buscar_por_site_com_variantes",
        _buscar_por_site_com_variantes_fake,
    )
    monkeypatch.setattr("integrations.servico.buscar_titulos", _buscar_titulos_fake)

    resultado = await servico_busca.buscar_com_titulos_alternativos(None, "Kimi no Na wa")

    assert chamadas_fan_out == [["Kimi no Na wa", "Your Name"]]
    assert resultado.termo_alternativo == ingles
    assert resultado.dominio_alternativo == "animesdrive"


async def test_desempate_do_fan_out_por_prioridade_de_extratores(
    monkeypatch: pytest.MonkeyPatch,
):
    """Site padrão e um site restante acham candidatos de MESMA proximidade à
    referência (nenhum exato, então o fan-out roda). O vencedor reportado tem
    que ser determinístico — o primeiro em ordem de `EXTRATORES` (o site
    padrão), não "quem respondeu primeiro" no fan-out paralelo. O candidato
    genuíno do perdedor é suprimido (`candidatos=[]`) — o contrato do escopo
    `padrao` é uma fonte só."""
    romaji = "Naruto Shippuden"
    candidato_af = ResultadoBusca(
        titulo_exibicao="Naruto Shippuden Movie 6", identificador="1", url="https://af/1"
    )
    candidato_ad = ResultadoBusca(
        titulo_exibicao="Naruto Shippuden Movie 6", identificador="2", url="https://ad/2"
    )

    async def _buscar_em_com_variantes_fake(sessionmaker, dominio, variantes, *, referencias):
        assert dominio == "animefire.one"
        return _fonte("animefire.one", candidato_af), None

    async def _buscar_por_site_com_variantes_fake(
        sessionmaker, variantes, *, referencias, dominios=None
    ):
        return _fan_out({"animesdrive": candidato_ad}, dominios)

    async def _buscar_titulos_fake(titulo: str) -> TitulosDeAnime | None:
        return TitulosDeAnime(titulo_romaji=romaji, titulo_ingles=None)

    monkeypatch.setattr(
        "extractors.busca.servico.buscar_em_com_variantes", _buscar_em_com_variantes_fake
    )
    monkeypatch.setattr(
        "extractors.busca.servico.buscar_por_site_com_variantes",
        _buscar_por_site_com_variantes_fake,
    )
    monkeypatch.setattr("integrations.servico.buscar_titulos", _buscar_titulos_fake)

    resultado = await servico_busca.buscar_com_titulos_alternativos(None, "Naruto")

    # animefire.one (EXTRATORES[0]) venceu o desempate, não animesdrive.
    assert resultado.dominio_alternativo is None
    # "Naruto" já alcança o card "Naruto Shippuden Movie 6" por prefixo
    # (`corresponde_a_alguma_referencia`) — houve resultado pro que foi digitado,
    # então nada de banner de termo alternativo mesmo o romaji diferindo.
    assert resultado.termo_alternativo is None
    fontes_por_dominio = {f.dominio: f for f in resultado.fontes}
    assert fontes_por_dominio["animefire.one"].candidatos == [candidato_af]
    # animesdrive achou candidato_ad de verdade (fan-out paralelo), mas
    # perdeu o desempate — não pode vazar numa resposta de fonte única.
    assert fontes_por_dominio["animesdrive"].candidatos == []


def test_teto_expansao_e_190():
    """`_TETO_EXPANSAO_S` cobre dois perfis diferentes (ver o comentário-bloco):
    no `todas` é só a Fase 2 (escada por termo de provedor em
    `_expandir_com_termos_de_provedor_em_todas_as_fontes`, 2 × 90s = 180s); no
    `padrao` é um único fan-out da escada combinada `_termos_de_busca`. Nos
    DOIS o round-trip de `buscar_titulos` ficou FORA deste orçamento
    (`_TETO_METADADOS_S` próprio, upfront) desde 2026-09-07. Trava de
    regressão do valor."""
    assert servico_busca._TETO_EXPANSAO_S == 190


async def test_site_padrao_em_cooldown_fica_fora_do_fan_out(monkeypatch: pytest.MonkeyPatch):
    """O site padrão é consultado só no passo 3; o fan-out do passo 5 nunca
    inclui `EXTRATORES[0]`, em cooldown ou não. Aqui ele volta `indisponivel`
    do passo 3 e `dominios=` do fan-out traz só os sites restantes."""
    romaji = "Tensei Shitara Slime Datta Ken"
    candidato = ResultadoBusca(titulo_exibicao=romaji, identificador="2", url="https://y/1")
    chamadas_site_padrao: list[list[str]] = []
    dominios_fan_out: list[list[str] | None] = []

    async def _buscar_em_com_variantes_fake(sessionmaker, dominio, variantes, *, referencias):
        assert dominio == "animefire.one"
        chamadas_site_padrao.append(variantes)
        return _fonte_indisponivel("animefire.one", "em cooldown"), None

    async def _buscar_por_site_com_variantes_fake(
        sessionmaker, variantes, *, referencias, dominios=None
    ):
        dominios_fan_out.append(dominios)
        return _fan_out({"animesdrive": candidato}, dominios)

    async def _buscar_titulos_fake(titulo: str) -> TitulosDeAnime | None:
        return TitulosDeAnime(titulo_romaji=romaji, titulo_ingles=None)

    monkeypatch.setattr(
        "extractors.busca.servico.buscar_em_com_variantes", _buscar_em_com_variantes_fake
    )
    monkeypatch.setattr(
        "extractors.busca.servico.buscar_por_site_com_variantes",
        _buscar_por_site_com_variantes_fake,
    )
    monkeypatch.setattr("integrations.servico.buscar_titulos", _buscar_titulos_fake)

    resultado = await servico_busca.buscar_com_titulos_alternativos(None, "Slime")

    assert len(chamadas_site_padrao) == 1
    assert dominios_fan_out == [["meusanimes", "animesdrive"]]
    assert resultado.dominio_alternativo == "animesdrive"
    assert resultado.termo_alternativo == romaji


async def test_nenhum_site_acha_nada(monkeypatch: pytest.MonkeyPatch):
    async def _buscar_em_com_variantes_fake(sessionmaker, dominio, variantes, *, referencias):
        return _fonte(dominio), None

    async def _buscar_por_site_com_variantes_fake(
        sessionmaker, variantes, *, referencias, dominios=None
    ):
        return _fan_out({}, dominios)

    async def _buscar_titulos_fake(titulo: str) -> TitulosDeAnime | None:
        return None  # provedor não achou título nenhum

    monkeypatch.setattr(
        "extractors.busca.servico.buscar_em_com_variantes", _buscar_em_com_variantes_fake
    )
    monkeypatch.setattr(
        "extractors.busca.servico.buscar_por_site_com_variantes",
        _buscar_por_site_com_variantes_fake,
    )
    monkeypatch.setattr("integrations.servico.buscar_titulos", _buscar_titulos_fake)

    resultado = await servico_busca.buscar_com_titulos_alternativos(None, "Naruto")

    assert resultado.termo_alternativo is None
    assert resultado.dominio_alternativo is None
    dominios = {fonte.dominio for fonte in resultado.fontes}
    assert dominios == {"animefire.one", "meusanimes", "animesdrive"}
    # Todos os sites foram de fato consultados (não "não consultado") — nenhum
    # candidato, nenhum indisponível, motivo None em todos.
    assert all(not fonte.indisponivel and fonte.candidatos == [] for fonte in resultado.fontes)
    assert all(fonte.motivo is None for fonte in resultado.fontes)


async def test_early_exit_marca_sites_restantes_como_nao_consultados(
    monkeypatch: pytest.MonkeyPatch,
):
    """Match exato no site padrão → os sites restantes não são consultados,
    mas ainda aparecem em `fontes` com `indisponivel=False` e um motivo
    explícito (senão `todasFontesIndisponiveis` da Home mentiria)."""
    candidato = ResultadoBusca(titulo_exibicao="Naruto", identificador="1", url="https://x/1")

    async def _buscar_em_com_variantes_fake(sessionmaker, dominio, variantes, *, referencias):
        return _fonte(dominio, candidato), None

    async def _falha_se_chamado(sessionmaker, variantes, *, referencias, dominios=None):
        raise AssertionError("early-exit não deveria disparar o fan-out")

    async def _buscar_titulos_fake(titulo: str) -> TitulosDeAnime | None:
        return None

    monkeypatch.setattr(
        "extractors.busca.servico.buscar_em_com_variantes", _buscar_em_com_variantes_fake
    )
    monkeypatch.setattr(
        "extractors.busca.servico.buscar_por_site_com_variantes", _falha_se_chamado
    )
    monkeypatch.setattr("integrations.servico.buscar_titulos", _buscar_titulos_fake)

    resultado = await servico_busca.buscar_com_titulos_alternativos(None, "Naruto")

    for dominio in ("meusanimes", "animesdrive"):
        fonte = next(f for f in resultado.fontes if f.dominio == dominio)
        assert fonte.indisponivel is False
        assert fonte.candidatos == []
        assert fonte.motivo is not None and "não consultado" in fonte.motivo


async def test_todos_os_sites_indisponiveis_ainda_resolve_o_canonico_upfront(
    monkeypatch: pytest.MonkeyPatch,
):
    """A resolução do canônico agora roda SEMPRE, upfront — a orquestração
    antiga a pulava quando todo site estava em cooldown. Sem site disponível
    não há vencedor, e cada fonte volta `indisponivel`."""
    buscar_titulos_chamado: list[str] = []

    async def _buscar_em_com_variantes_fake(sessionmaker, dominio, variantes, *, referencias):
        return _fonte_indisponivel(dominio), None

    async def _buscar_por_site_com_variantes_fake(
        sessionmaker, variantes, *, referencias, dominios=None
    ):
        return {dominio: _fonte_indisponivel(dominio) for dominio in dominios}

    async def _buscar_titulos_fake(titulo: str) -> TitulosDeAnime | None:
        buscar_titulos_chamado.append(titulo)
        return None

    monkeypatch.setattr(
        "extractors.busca.servico.buscar_em_com_variantes", _buscar_em_com_variantes_fake
    )
    monkeypatch.setattr(
        "extractors.busca.servico.buscar_por_site_com_variantes",
        _buscar_por_site_com_variantes_fake,
    )
    monkeypatch.setattr("integrations.servico.buscar_titulos", _buscar_titulos_fake)

    resultado = await servico_busca.buscar_com_titulos_alternativos(None, "Naruto")

    assert buscar_titulos_chamado == ["Naruto"]
    assert resultado.termo_alternativo is None
    assert resultado.dominio_alternativo is None
    assert all(fonte.indisponivel for fonte in resultado.fontes)


def test_termos_alternativos_descarta_romaji_igual_ao_digitado_e_kanji_vazio():
    """`_termos_alternativos` ainda é usada pelo escopo `todas` (não pelo
    `padrao`, que passou a usar `_termos_de_busca`) — trava direta pra não
    perder essa regra."""
    titulos = TitulosDeAnime(titulo_romaji="Naruto", titulo_ingles="Naruto")

    termos = servico_busca._termos_alternativos(titulos, "Naruto")

    assert termos == []


def test_termos_alternativos_ordem_romaji_antes_de_ingles():
    titulos = TitulosDeAnime(
        titulo_romaji="Tensei Shitara Slime Datta Ken", titulo_ingles="That Time I Got Reincarnated"
    )

    termos = servico_busca._termos_alternativos(titulos, "Slime")

    assert termos == ["Tensei Shitara Slime Datta Ken", "That Time I Got Reincarnated"]


async def test_fan_out_reporta_indisponivel_fresco_dos_sites_restantes(
    monkeypatch: pytest.MonkeyPatch,
):
    """Os sites restantes entram em `resultados` direto da resposta fresca do
    fan-out (`{site_padrao: r1, **resto}`), sem status congelado a
    sobrescrever — um site que caiu durante o fan-out aparece `indisponivel`,
    não com o status otimista de antes (CLAUDE.md §4)."""
    romaji = "Naruto Shippuden"

    async def _buscar_em_com_variantes_fake(sessionmaker, dominio, variantes, *, referencias):
        return _fonte(dominio), None  # site padrão disponível-vazio

    async def _buscar_por_site_com_variantes_fake(
        sessionmaker, variantes, *, referencias, dominios=None
    ):
        return {
            dominio: _fonte_indisponivel(dominio, "caiu durante o fan-out")
            for dominio in dominios
        }

    async def _buscar_titulos_fake(titulo: str) -> TitulosDeAnime | None:
        return TitulosDeAnime(titulo_romaji=romaji, titulo_ingles=None)

    monkeypatch.setattr(
        "extractors.busca.servico.buscar_em_com_variantes", _buscar_em_com_variantes_fake
    )
    monkeypatch.setattr(
        "extractors.busca.servico.buscar_por_site_com_variantes",
        _buscar_por_site_com_variantes_fake,
    )
    monkeypatch.setattr("integrations.servico.buscar_titulos", _buscar_titulos_fake)

    resultado = await servico_busca.buscar_com_titulos_alternativos(None, "Naruto")

    fontes = {f.dominio: f for f in resultado.fontes}
    for dominio in ("meusanimes", "animesdrive"):
        assert fontes[dominio].indisponivel is True
        assert fontes[dominio].motivo == "caiu durante o fan-out"
    assert fontes["animefire.one"].indisponivel is False


async def test_falha_de_metadados_nao_propaga_degrada_para_titulo_digitado(
    monkeypatch: pytest.MonkeyPatch,
):
    """`buscar_titulos` lança → `_resolver_titulos_canonicos` degrada pra
    `None` (best-effort) e a busca segue só com o título digitado como
    referência, sem propagar a exceção."""

    async def _buscar_em_com_variantes_fake(sessionmaker, dominio, variantes, *, referencias):
        assert referencias == ["Slime"]  # sem títulos de provedor, só o digitado
        return _fonte(dominio), None

    async def _buscar_por_site_com_variantes_fake(
        sessionmaker, variantes, *, referencias, dominios=None
    ):
        assert referencias == ["Slime"]
        return _fan_out({}, dominios)

    async def _buscar_titulos_falha(titulo: str):
        raise FalhaDeMetadados("todos os provedores de metadados falharam")

    monkeypatch.setattr(
        "extractors.busca.servico.buscar_em_com_variantes", _buscar_em_com_variantes_fake
    )
    monkeypatch.setattr(
        "extractors.busca.servico.buscar_por_site_com_variantes",
        _buscar_por_site_com_variantes_fake,
    )
    monkeypatch.setattr("integrations.servico.buscar_titulos", _buscar_titulos_falha)

    resultado = await servico_busca.buscar_com_titulos_alternativos(None, "Slime")

    assert resultado.termo_alternativo is None
    assert resultado.dominio_alternativo is None
    dominios = {fonte.dominio for fonte in resultado.fontes}
    assert dominios == {"animefire.one", "meusanimes", "animesdrive"}


# --- buscar_em_todas_as_fontes_com_titulos_alternativos (escopo `todas`) ---
#
# Desde 2026-09-07 o `todas` espelha a resolução canônica do `padrao`:
# `_resolver_titulos_canonicos` UPFRONT (SEMPRE), depois Fase 1 paralela por
# site com a escada COMBINADA `_termos_de_busca` (`buscar_por_site_com_
# variantes`, INV-1' — cada site esgota a própria escada) e validação
# multi-referência. A Fase 2 (`_expandir_com_termos_de_provedor_em_todas_as_
# fontes`, gate por-site) virou redundante — a escada combinada da Fase 1 já
# cobre romaji+inglês — e não toca mais a rede; segue no código até uma fatia
# de remoção própria. O fake de `buscar_por_site_com_variantes` recebe
# `(sessionmaker, variantes, *, referencias, dominios=None)` e devolve
# `dict[str, ResultadoDeFonte]`, mesmo contrato da função real; `buscar_titulos`
# é stubado em `integrations.servico.buscar_titulos`.


async def test_todas_fase2_termo_de_provedor_acha_quando_fase1_vazia(
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
        "extractors.busca.servico.buscar_por_site_com_variantes",
        _buscar_por_site_com_variantes_fake,
    )
    monkeypatch.setattr("integrations.servico.buscar_titulos", _buscar_titulos_fake)

    resultado = await servico_busca.buscar_em_todas_as_fontes_com_titulos_alternativos(
        None, "Slime"
    )

    # `termo_alternativo`/`dominio_alternativo` sempre `None` neste escopo
    # (docstring de `buscar_em_todas_as_fontes_com_titulos_alternativos`) —
    # mesmo achando por um termo de provedor.
    assert resultado.termo_alternativo is None
    assert resultado.dominio_alternativo is None
    assert resultado.fontes[0].candidatos == [candidato]


async def test_todas_fase1_combinada_une_romaji_e_ingles_numa_rodada_so(
    monkeypatch: pytest.MonkeyPatch,
):
    """A escada combinada da Fase 1 traz romaji E inglês — um site que só
    indexa o romaji e outro que só indexa o inglês entram os dois na mesma
    rodada paralela da Fase 1. Contrato de UNIÃO: um candidato de cada site,
    numa rodada de scraping só, sem a expansão termo a termo da Fase 2
    (redundante — a Fase 2 não chega a tocar a rede)."""
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
        "extractors.busca.servico.buscar_por_site_com_variantes",
        _buscar_por_site_com_variantes_fake,
    )
    monkeypatch.setattr("integrations.servico.buscar_titulos", _buscar_titulos_fake)

    resultado = await servico_busca.buscar_em_todas_as_fontes_com_titulos_alternativos(
        None, "Naruto"
    )

    assert rodadas == [None]  # Fase 1 só; a Fase 2 (redundante) não toca a rede
    fontes_por_dominio = {f.dominio: f for f in resultado.fontes}
    assert fontes_por_dominio["animefire.one"].candidatos == [candidato_af]
    assert fontes_por_dominio["animesdrive"].candidatos == [candidato_ad]
    assert fontes_por_dominio["meusanimes"].candidatos == []
    assert resultado.termo_alternativo is None
    assert resultado.dominio_alternativo is None


async def test_todas_titulo_ingles_do_provedor_alcanca_site_pendente(
    monkeypatch: pytest.MonkeyPatch,
):
    """Bug real (2026-08-29, "Dogul Wang"): o AnimeFire achar pela escada de
    regex não pode impedir o AnimesDrive de ser alcançado com o título inglês
    do provedor ("Tomb Raider King"), onde o anime existe — antes o diálogo
    "Trocar fonte" listava uma fonte só. A escada COMBINADA da Fase 1
    (`_termos_de_busca` = romaji + inglês + digitado) varre o inglês já na
    Fase 1, em paralelo, em todos os sites — a UNIÃO traz as duas fontes numa
    rodada de scraping só (o gate por-site da Fase 2 continua no lugar, mas a
    Fase 2 nem chega a tocar a rede)."""
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
        "extractors.busca.servico.buscar_por_site_com_variantes",
        _buscar_por_site_com_variantes_fake,
    )
    monkeypatch.setattr("integrations.servico.buscar_titulos", _buscar_titulos_fake)

    resultado = await servico_busca.buscar_em_todas_as_fontes_com_titulos_alternativos(
        None, "Dogul Wang"
    )

    assert rodadas == [None]  # uma rodada de scraping só — o inglês entrou na Fase 1
    fontes = {f.dominio: f for f in resultado.fontes}
    assert fontes["animefire.one"].candidatos == [candidato_af]
    assert fontes["animesdrive"].candidatos == [candidato_ad]
    assert fontes["meusanimes"].candidatos == []
    assert resultado.termo_alternativo is None
    assert resultado.dominio_alternativo is None


async def test_todas_fase2_nao_roda_quando_todos_os_sites_ja_acharam(
    monkeypatch: pytest.MonkeyPatch,
):
    """Contrapartida do gate POR-SITE: quando NENHUM site ficou pendente (os
    três acharam candidato na Fase 1), a Fase 2 é pulada inteira — sem segunda
    rodada de scraping (o canônico já foi resolvido upfront, `buscar_titulos`
    stubado)."""
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
        "extractors.busca.servico.buscar_por_site_com_variantes",
        _buscar_por_site_com_variantes_fake,
    )
    monkeypatch.setattr("integrations.servico.buscar_titulos", _buscar_titulos_fake)

    resultado = await servico_busca.buscar_em_todas_as_fontes_com_titulos_alternativos(
        None, "Naruto"
    )

    assert rodadas == [None]  # só a Fase 1; Fase 2 pulada (nenhum pendente)
    assert resultado.termo_alternativo is None
    assert resultado.dominio_alternativo is None
    fontes = {f.dominio: f for f in resultado.fontes}
    assert fontes["animefire.one"].candidatos == [candidato_af]
    assert fontes["meusanimes"].candidatos == [candidato_am]
    assert fontes["animesdrive"].candidatos == [candidato_ad]


async def test_todas_fase1_toda_vazia_e_preservada(monkeypatch: pytest.MonkeyPatch):
    """Fase 1 não acha nada em site nenhum e a Fase 2 também não
    (`_expandir_com_termos_de_provedor_em_todas_as_fontes` → `None`): o
    chamador preserva a rodada da Fase 1 (`if expandido is not None`), cada
    fonte fica disponível-vazia com `motivo` `None` — "não achei" nunca vira
    "indisponível" nem "não consultado" (CLAUDE.md §4)."""
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
        "extractors.busca.servico.buscar_por_site_com_variantes",
        _buscar_por_site_com_variantes_fake,
    )
    monkeypatch.setattr("integrations.servico.buscar_titulos", _buscar_titulos_fake)

    resultado = await servico_busca.buscar_em_todas_as_fontes_com_titulos_alternativos(
        None, "Naruto"
    )

    assert resultado.termo_alternativo is None
    assert resultado.dominio_alternativo is None
    assert all(not fonte.indisponivel and fonte.candidatos == [] for fonte in resultado.fontes)
    assert all(fonte.motivo is None for fonte in resultado.fontes)


async def test_todas_fase2_falha_de_metadados_nao_propaga_devolve_rodada_da_fase1(
    monkeypatch: pytest.MonkeyPatch,
):
    """`buscar_titulos` lança → `_resolver_titulos_canonicos` degrada pra
    `None` (best-effort, upfront) e a Fase 1 do `todas` segue só com o título
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
        "extractors.busca.servico.buscar_por_site_com_variantes",
        _buscar_por_site_com_variantes_fake,
    )
    monkeypatch.setattr("integrations.servico.buscar_titulos", _buscar_titulos_falha)

    resultado = await servico_busca.buscar_em_todas_as_fontes_com_titulos_alternativos(
        None, "Slime"
    )

    assert referencias_vistas == [["Slime"]]  # degradou: Fase 1 só com o digitado
    assert resultado.termo_alternativo is None
    assert resultado.dominio_alternativo is None
    dominios = {fonte.dominio for fonte in resultado.fontes}
    assert dominios == {"animefire.one", "meusanimes", "animesdrive"}


async def test_todas_todos_os_sites_indisponiveis_ainda_resolve_o_canonico_upfront(
    monkeypatch: pytest.MonkeyPatch,
):
    """A resolução canônica do `todas` agora roda SEMPRE, upfront (a escada
    combinada da Fase 1 depende dela) — a orquestração antiga a pulava quando
    todo site já vinha `indisponivel`. Sem site pendente, a Fase 2 continua
    pulada (`algum_site_pendente` na guarda: site indisponível não é pendente),
    sem segunda rodada de scraping; cada fonte volta `indisponivel`."""
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
        "extractors.busca.servico.buscar_por_site_com_variantes",
        _buscar_por_site_com_variantes_fake,
    )
    monkeypatch.setattr("integrations.servico.buscar_titulos", _buscar_titulos_fake)

    resultado = await servico_busca.buscar_em_todas_as_fontes_com_titulos_alternativos(
        None, "Naruto"
    )

    assert titulos_chamado == ["Naruto"]
    assert rodadas == [None]  # só a Fase 1; nenhum pendente → Fase 2 pulada
    assert resultado.termo_alternativo is None
    assert resultado.dominio_alternativo is None
    assert all(fonte.indisponivel for fonte in resultado.fontes)


# --- _referencias_de_anime / _termos_de_busca (helpers puros, fatia d1) ---
#
# Helpers de domínio puro consumidos pela Fase 1 dos DOIS escopos
# (`buscar_com_titulos_alternativos` e
# `buscar_em_todas_as_fontes_com_titulos_alternativos`, exercitadas acima).
# Cobertura direta aqui além da indireta pelas funções públicas — o caso de
# borda de cada um (kanji vazio, dedupe por slug, `titulos is None`) fica mais
# legível isolado.


def test_referencias_de_anime_ordem_digitado_primeiro_depois_campos_do_provedor():
    titulos = TitulosDeAnime(
        titulo_romaji="Tensei Shitara Slime Datta Ken",
        titulo_ingles="That Time I Got Reincarnated as a Slime",
        titulo_nativo="転生したらスライムだった件",
        sinonimos=("TenSura", "Regarding Reincarnated to Slime"),
    )

    referencias = servico_busca._referencias_de_anime(titulos, "Slime")

    # `titulo` na frente; romaji, inglês e cada sinônimo na ordem; o nativo em
    # kanji slugifica pra vazio e sai.
    assert referencias == [
        "Slime",
        "Tensei Shitara Slime Datta Ken",
        "That Time I Got Reincarnated as a Slime",
        "TenSura",
        "Regarding Reincarnated to Slime",
    ]


def test_referencias_de_anime_dedupe_por_slug_ignora_caixa_e_pontuacao():
    titulos = TitulosDeAnime(
        titulo_romaji="Re:Zero kara Hajimeru Isekai Seikatsu",
        titulo_ingles="Re Zero kara Hajimeru Isekai Seikatsu",
        sinonimos=("Tomb Raider King",),
    )

    referencias = servico_busca._referencias_de_anime(
        titulos, "re:zero kara hajimeru isekai seikatsu"
    )

    # digitado (caixa baixa), romaji (com ":") e inglês (com espaço) slugificam
    # todos pra "re-zero-kara-hajimeru-isekai-seikatsu" — colapsam; só o
    # sinônimo distinto sobra.
    assert referencias == [
        "re:zero kara hajimeru isekai seikatsu",
        "Tomb Raider King",
    ]


def test_referencias_de_anime_descarta_none_e_string_em_branco():
    titulos = TitulosDeAnime(
        titulo_romaji=None,
        titulo_ingles="   ",
        titulo_nativo=None,
        sinonimos=("", "Blue Lock"),
    )

    referencias = servico_busca._referencias_de_anime(titulos, "Aoki")

    assert referencias == ["Aoki", "Blue Lock"]


def test_referencias_de_anime_titulos_none_devolve_so_o_digitado():
    assert servico_busca._referencias_de_anime(None, "Naruto") == ["Naruto"]


def test_referencias_de_anime_mantem_digitado_mesmo_quando_slugifica_pra_vazio():
    titulos = TitulosDeAnime(titulo_romaji="Sono Bisque Doll", titulo_ingles=None)

    referencias = servico_busca._referencias_de_anime(titulos, "着せ替え人形")

    # kanji digitado slugifica pra vazio, mas é a âncora — fica na posição 0
    # (`corresponde_a_alguma_referencia` degrada pra aceitar referência sem
    # chave); o romaji entra normalmente.
    assert referencias == ["着せ替え人形", "Sono Bisque Doll"]


def test_termos_de_busca_titulos_none_cai_em_variantes_de_busca():
    assert servico_busca._termos_de_busca(None, "Kimetsu no Yaiba") == variantes_de_busca(
        "Kimetsu no Yaiba"
    )


def test_termos_de_busca_ordem_romaji_antes_de_ingles_antes_do_digitado():
    titulos = TitulosDeAnime(
        titulo_romaji="Shingeki no Kyojin",
        titulo_ingles="Attack on Titan",
    )

    termos = servico_busca._termos_de_busca(titulos, "AoT")

    assert termos[0] == "Shingeki no Kyojin"
    assert (
        termos.index("Shingeki no Kyojin")
        < termos.index("Attack on Titan")
        < termos.index("AoT")
    )


def test_termos_de_busca_dedupe_entre_escadas_por_slug():
    titulos = TitulosDeAnime(titulo_romaji="Naruto", titulo_ingles="Naruto")

    termos = servico_busca._termos_de_busca(titulos, "Naruto")

    # romaji, inglês e digitado slugificam igual — a escada do romaji sobra só.
    assert termos == ["Naruto"]


def test_termos_de_busca_ignora_nativo_e_sinonimos():
    titulos = TitulosDeAnime(
        titulo_romaji="Bocchi the Rock",
        titulo_ingles=None,
        titulo_nativo="ぼっち・ざ・ろっく",
        sinonimos=("BtR", "Kessoku Band"),
    )

    termos = servico_busca._termos_de_busca(titulos, "Bocchi the Rock")

    # inglês None e digitado == romaji (colapsa): sobra exatamente a escada do
    # romaji — nativo e sinônimos não contribuem termo nenhum.
    assert termos == variantes_de_busca("Bocchi the Rock")


def test_termos_de_busca_nunca_vazia_quando_so_o_digitado_e_util():
    titulos = TitulosDeAnime(titulo_romaji=None, titulo_ingles=None)

    termos = servico_busca._termos_de_busca(titulos, "One Piece")

    assert termos == variantes_de_busca("One Piece")


def test_variantes_sem_repetir_fase1_filtra_slugs_ja_tentados():
    """`_variantes_sem_repetir_fase1` não é mais usada pelo escopo `padrao`
    (que passou a rodar uma escada combinada só, sem dedupe entre fases), mas
    continua no caminho do escopo `todas` — trava direta pra não perder essa
    regra."""
    variantes = [
        "Boku no Hero Academia World Heroes",
        "Boku no Hero Academia",
        "Boku no Hero",
        "Boku no",
        "Boku",
    ]
    slugs_fase1 = {
        servico_busca.slugificar("Boku no Hero Academia"),
        servico_busca.slugificar("Boku no Hero"),
        servico_busca.slugificar("Boku no"),
    }

    resultado = servico_busca._variantes_sem_repetir_fase1(variantes, slugs_fase1)

    assert resultado == ["Boku no Hero Academia World Heroes", "Boku"]

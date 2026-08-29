"""Testes de `api/servicos/busca.py`: `enriquecer_capas` e
`buscar_com_titulos_alternativos`, sem rede — `integrations.servico.
buscar_por_titulo`/`buscar_titulos` e `extractors.servico.
buscar_em_com_variantes`/`buscar_por_site_com_variantes` são monkeypatchados
nos nomes de módulo (mesmo padrão usado em `tests/test_api_buscar_fontes.py`),
pois `busca.py` os chama via `servico_metadados`/`servico_extractors`, que
apontam pro mesmo objeto de módulo.

`buscar_com_titulos_alternativos` (Fase A, fatia 3 de
PLANO_PADRONIZACAO_FONTES.md) é sequencial por site na Fase 1 (ordem de
`extractors.registro.EXTRATORES`: animefire.io primeiro, animesdrive depois,
via `buscar_em_com_variantes`). Fase 2 (só se a Fase 1 não achou nada em site
nenhum) — desde a correção que paraleliza sites dentro do termo (fan-out,
mesmo molde do escopo `todas`) — chama `buscar_por_site_com_variantes` uma
vez por termo de provedor, com `referencia=<esse termo>` e `dominios=` os
sites ainda disponíveis, não mais `buscar_em_com_variantes` site a site.
Testes que cobrem Fase 2 monkeypatcham as DUAS funções: `buscar_em_com_
variantes` pra Fase 1 (site a site, fake recebe `(sessionmaker, dominio,
variantes, *, referencia)` e devolve `(ResultadoDeFonte, variante_
vencedora)`) e `buscar_por_site_com_variantes` pra Fase 2 (fan-out por termo,
fake recebe `(sessionmaker, variantes, *, referencia, dominios=None)` e
devolve `dict[str, ResultadoDeFonte]`) — mesmos contratos das funções reais,
`referencia` usado pra diferenciar em qual termo cada chamada aconteceu."""

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
            "animesdrive",
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
        "animesdrive",
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

    async def _buscar_em_com_variantes_fake(sessionmaker, dominio, variantes, *, referencia):
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

    async def _buscar_em_com_variantes_fake(sessionmaker, dominio, variantes, *, referencia):
        if dominio == "animefire.io":
            return _fonte("animefire.io"), None
        return _fonte("animesdrive", candidato), None

    async def _falha_se_chamado(titulo: str):
        raise AssertionError("buscar_titulos não deveria ser chamado quando a Fase 1 já achou")

    monkeypatch.setattr(
        "extractors.servico.buscar_em_com_variantes", _buscar_em_com_variantes_fake
    )
    monkeypatch.setattr("integrations.servico.buscar_titulos", _falha_se_chamado)

    resultado = await servico_busca.buscar_com_titulos_alternativos(None, "Naruto")

    assert resultado.termo_alternativo is None
    assert resultado.dominio_alternativo == "animesdrive"
    assert resultado.fontes[1].candidatos == [candidato]


async def test_fase2_termo_de_provedor_acha_no_site_padrao(monkeypatch: pytest.MonkeyPatch):
    candidato = ResultadoBusca(titulo_exibicao="Tensei Slime", identificador="1", url="https://x/1")
    romaji = "Tensei Shitara Slime Datta Ken"

    async def _buscar_em_com_variantes_fake(sessionmaker, dominio, variantes, *, referencia):
        return _fonte(dominio), None  # Fase 1 sempre vazia, força a Fase 2

    async def _buscar_por_site_com_variantes_fake(
        sessionmaker, variantes, *, referencia, dominios=None
    ):
        assert referencia == romaji
        return {
            "animefire.io": _fonte("animefire.io", candidato),
            "animesdrive": _fonte("animesdrive"),
        }

    async def _buscar_titulos_fake(titulo: str) -> TitulosDeAnime | None:
        assert titulo == "Slime"
        return TitulosDeAnime(titulo_romaji=romaji, titulo_ingles=None)

    monkeypatch.setattr(
        "extractors.servico.buscar_em_com_variantes", _buscar_em_com_variantes_fake
    )
    monkeypatch.setattr(
        "extractors.servico.buscar_por_site_com_variantes", _buscar_por_site_com_variantes_fake
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

    async def _buscar_em_com_variantes_fake(sessionmaker, dominio, variantes, *, referencia):
        return _fonte(dominio), None  # Fase 1 sempre vazia, força a Fase 2

    async def _buscar_por_site_com_variantes_fake(
        sessionmaker, variantes, *, referencia, dominios=None
    ):
        assert referencia == romaji
        return {
            "animefire.io": _fonte("animefire.io"),
            "animesdrive": _fonte("animesdrive", candidato),
        }

    async def _buscar_titulos_fake(titulo: str) -> TitulosDeAnime | None:
        return TitulosDeAnime(titulo_romaji=romaji, titulo_ingles=None)

    monkeypatch.setattr(
        "extractors.servico.buscar_em_com_variantes", _buscar_em_com_variantes_fake
    )
    monkeypatch.setattr(
        "extractors.servico.buscar_por_site_com_variantes", _buscar_por_site_com_variantes_fake
    )
    monkeypatch.setattr("integrations.servico.buscar_titulos", _buscar_titulos_fake)

    resultado = await servico_busca.buscar_com_titulos_alternativos(None, "Slime")

    assert resultado.termo_alternativo == romaji
    assert resultado.dominio_alternativo == "animesdrive"


async def test_fase2_termo_a_falha_termo_b_acha_escada_por_termo(monkeypatch: pytest.MonkeyPatch):
    """Fatia 5 (+ correção de paralelismo entre sites): cada termo de provedor
    tem sua própria escada E sua própria referência (`referencia=<esse
    termo>`, nunca mais `referencia=titulo` compartilhado) — o romaji não acha
    candidato em site nenhum, então a Fase 2 cede a vez pro inglês (não aborta
    a fase inteira). A ordem das chamadas a `buscar_por_site_com_variantes`
    prova o nesting termo-major: o fan-out inteiro do romaji roda (e falha)
    ANTES do fan-out do inglês começar — nunca intercala termos. Dentro de
    cada termo, os sites já não são mais sequenciais (fan-out único por
    chamada), então não há mais uma ordem de site pra afirmar aqui — essa
    parte é responsabilidade de `buscar_por_site_com_variantes`
    (`extractors/test_extractors_servico.py`), não desta função."""
    romaji = "Kimi no Na wa Zenpen"
    ingles = "Your Name Part One"
    candidato = ResultadoBusca(titulo_exibicao="Your Name", identificador="9", url="https://y/9")
    chamadas_fase2: list[str] = []

    async def _buscar_em_com_variantes_fake(sessionmaker, dominio, variantes, *, referencia):
        return _fonte(dominio), None  # Fase 1 sempre vazia, força a Fase 2

    async def _buscar_por_site_com_variantes_fake(
        sessionmaker, variantes, *, referencia, dominios=None
    ):
        chamadas_fase2.append(referencia)
        if referencia == ingles:
            return {
                "animefire.io": _fonte("animefire.io"),
                "animesdrive": _fonte("animesdrive", candidato),
            }
        return {"animefire.io": _fonte("animefire.io"), "animesdrive": _fonte("animesdrive")}

    async def _buscar_titulos_fake(titulo: str) -> TitulosDeAnime | None:
        return TitulosDeAnime(titulo_romaji=romaji, titulo_ingles=ingles)

    monkeypatch.setattr(
        "extractors.servico.buscar_em_com_variantes", _buscar_em_com_variantes_fake
    )
    monkeypatch.setattr(
        "extractors.servico.buscar_por_site_com_variantes", _buscar_por_site_com_variantes_fake
    )
    monkeypatch.setattr("integrations.servico.buscar_titulos", _buscar_titulos_fake)

    resultado = await servico_busca.buscar_com_titulos_alternativos(None, "Kimi no Na wa")

    # termo A esgota o fan-out (falha) antes de B começar
    assert chamadas_fase2 == [romaji, ingles]
    assert resultado.termo_alternativo == ingles
    assert resultado.dominio_alternativo == "animesdrive"


async def test_fase2_dois_sites_acham_no_mesmo_termo_desempate_por_prioridade_extratores(
    monkeypatch: pytest.MonkeyPatch,
):
    """Desempate do fan-out paralelo por site dentro do termo: quando os DOIS
    sites acham candidato no mesmo termo (`buscar_por_site_com_variantes`
    roda os dois em paralelo, sem garantia de ordem de chegada), o vencedor
    reportado (`termo_alternativo`/`dominio_alternativo`) tem que ser
    determinístico — o primeiro em ordem de prioridade de
    `extractors.registro.EXTRATORES` (animefire.io antes de animesdrive), não
    "quem respondeu primeiro". O fake devolve animesdrive ANTES de
    animefire.io no dict pra provar que a ordem de inserção/iteração do dict
    de resposta não é o que decide. Escopo `padrao` reporta uma fonte só: o
    candidato genuíno que o perdedor do desempate achou não pode vazar pra
    `resultado.fontes` (contrato de fonte única, mesmo que o site tenha sido
    realmente consultado em paralelo)."""
    romaji = "Naruto Shippuden"
    candidato_af = ResultadoBusca(
        titulo_exibicao="Naruto Shippuden", identificador="1", url="https://af/1"
    )
    candidato_ad = ResultadoBusca(
        titulo_exibicao="Naruto Shippuden", identificador="2", url="https://ad/2"
    )

    async def _buscar_em_com_variantes_fake(sessionmaker, dominio, variantes, *, referencia):
        return _fonte(dominio), None  # Fase 1 sempre vazia, força a Fase 2

    async def _buscar_por_site_com_variantes_fake(
        sessionmaker, variantes, *, referencia, dominios=None
    ):
        return {
            "animesdrive": _fonte("animesdrive", candidato_ad),
            "animefire.io": _fonte("animefire.io", candidato_af),
        }

    async def _buscar_titulos_fake(titulo: str) -> TitulosDeAnime | None:
        return TitulosDeAnime(titulo_romaji=romaji, titulo_ingles=None)

    monkeypatch.setattr(
        "extractors.servico.buscar_em_com_variantes", _buscar_em_com_variantes_fake
    )
    monkeypatch.setattr(
        "extractors.servico.buscar_por_site_com_variantes", _buscar_por_site_com_variantes_fake
    )
    monkeypatch.setattr("integrations.servico.buscar_titulos", _buscar_titulos_fake)

    resultado = await servico_busca.buscar_com_titulos_alternativos(None, "Naruto")

    # animefire.io (EXTRATORES[0]) venceu o desempate, não animesdrive.
    assert resultado.dominio_alternativo is None
    assert resultado.termo_alternativo == romaji
    fontes_por_dominio = {f.dominio: f for f in resultado.fontes}
    assert fontes_por_dominio["animefire.io"].candidatos == [candidato_af]
    # animesdrive achou candidato_ad de verdade (fan-out paralelo), mas
    # perdeu o desempate — não pode vazar numa resposta de fonte única.
    assert fontes_por_dominio["animesdrive"].candidatos == []


async def test_fase2_dedupe_nao_reconsulta_variante_ja_tentada_na_fase1(
    monkeypatch: pytest.MonkeyPatch,
):
    """Dedupe entre Fase 1 e Fase 2: a escada de variantes de um termo de
    provedor (`variantes_de_busca(termo)`) pode gerar, por truncamento de
    prefixo, uma variante cujo slug já foi tentado na Fase 1 — essa variante
    tem que ser descartada antes de chegar em `buscar_em_com_variantes`, não
    só o termo em si. "Naruto Shippuden Movie" tem como prefixo de 2 palavras
    exatamente "Naruto Shippuden" — o mesmo (único) item que
    `variantes_de_busca("Naruto Shippuden")` gera na Fase 1."""
    titulo = "Naruto Shippuden"
    romaji = "Naruto Shippuden Movie"
    candidato = ResultadoBusca(
        titulo_exibicao="Naruto Shippuden Movie", identificador="9", url="https://x/9"
    )
    variantes_recebidas: list[str] = []

    async def _buscar_em_com_variantes_fake(sessionmaker, dominio, variantes, *, referencia):
        return _fonte(dominio), None  # Fase 1 sempre vazia, força a Fase 2

    async def _buscar_por_site_com_variantes_fake(
        sessionmaker, variantes, *, referencia, dominios=None
    ):
        assert referencia == romaji
        variantes_recebidas.extend(variantes)
        return {
            "animefire.io": _fonte("animefire.io", candidato),
            "animesdrive": _fonte("animesdrive"),
        }

    async def _buscar_titulos_fake(titulo_buscado: str) -> TitulosDeAnime | None:
        return TitulosDeAnime(titulo_romaji=romaji, titulo_ingles=None)

    monkeypatch.setattr(
        "extractors.servico.buscar_em_com_variantes", _buscar_em_com_variantes_fake
    )
    monkeypatch.setattr(
        "extractors.servico.buscar_por_site_com_variantes", _buscar_por_site_com_variantes_fake
    )
    monkeypatch.setattr("integrations.servico.buscar_titulos", _buscar_titulos_fake)

    resultado = await servico_busca.buscar_com_titulos_alternativos(None, titulo)

    assert "Naruto Shippuden" not in variantes_recebidas
    assert variantes_recebidas == ["Naruto Shippuden Movie"]
    assert resultado.termo_alternativo == "Naruto Shippuden Movie"


def test_variantes_sem_repetir_fase1_filtra_slugs_ja_tentados():
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


def test_teto_expansao_revisado_para_escada_por_termo():
    """A fatia 5 trocou a semântica de Fase 2 (termos tratados como uma lista
    plana de variantes, 1 request por termo por site) por uma escada própria
    por termo (até ~7 variantes por termo, mesmo gerador da Fase 1). Uma
    correção posterior paralelizou os sites dentro de cada termo em
    `_tentar_termos_de_provedor` (fan-out via `buscar_por_site_com_variantes`,
    mesmo molde do escopo `todas`) — eliminando o fator de 2 sites que
    multiplicava o pior caso antigo (2 termos × 2 sites × 105s = 420s, teto de
    430s). Trava de regressão do valor documentado no comentário de
    `_TETO_EXPANSAO_S` (10s de metadado + até 2 termos × 105s, sites em
    paralelo dentro de cada termo)."""
    assert servico_busca._TETO_EXPANSAO_S == 220


async def test_site_padrao_em_cooldown_nao_e_retentado_na_fase2(monkeypatch: pytest.MonkeyPatch):
    candidato = ResultadoBusca(titulo_exibicao="Naruto", identificador="2", url="https://y/1")
    romaji = "Naruto Shippuden"
    chamadas_animefire: list[list[str]] = []
    dominios_fase2: list[list[str] | None] = []

    async def _buscar_em_com_variantes_fake(sessionmaker, dominio, variantes, *, referencia):
        if dominio == "animefire.io":
            chamadas_animefire.append(variantes)
            return _fonte_indisponivel("animefire.io", "em cooldown"), None
        return _fonte("animesdrive"), None

    async def _buscar_por_site_com_variantes_fake(
        sessionmaker, variantes, *, referencia, dominios=None
    ):
        dominios_fase2.append(dominios)
        return {"animesdrive": _fonte("animesdrive", candidato)}

    async def _buscar_titulos_fake(titulo: str) -> TitulosDeAnime | None:
        return TitulosDeAnime(titulo_romaji=romaji, titulo_ingles=None)

    monkeypatch.setattr(
        "extractors.servico.buscar_em_com_variantes", _buscar_em_com_variantes_fake
    )
    monkeypatch.setattr(
        "extractors.servico.buscar_por_site_com_variantes", _buscar_por_site_com_variantes_fake
    )
    monkeypatch.setattr("integrations.servico.buscar_titulos", _buscar_titulos_fake)

    resultado = await servico_busca.buscar_com_titulos_alternativos(None, "Naruto")

    # Só a tentativa da Fase 1 — site em cooldown não é retentado com termo de
    # provedor na Fase 2, é excluído do `dominios=` do fan-out
    # (`resultados[...].indisponivel`), nunca repassado a
    # `buscar_por_site_com_variantes`.
    assert len(chamadas_animefire) == 1
    assert dominios_fase2 == [["animesdrive"]]
    assert resultado.dominio_alternativo == "animesdrive"
    assert resultado.termo_alternativo == romaji


async def test_nenhum_site_acha_nada_em_fase_nenhuma(monkeypatch: pytest.MonkeyPatch):
    async def _buscar_em_com_variantes_fake(sessionmaker, dominio, variantes, *, referencia):
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
    assert dominios == {"animefire.io", "animesdrive"}
    # Os dois sites foram de fato tentados (não "não consultado") — nenhum
    # candidato, nenhum indisponível, motivo None nos dois.
    assert all(not fonte.indisponivel and fonte.candidatos == [] for fonte in resultado.fontes)
    assert all(fonte.motivo is None for fonte in resultado.fontes)


async def test_completar_nao_consultados_marca_2o_site_como_nao_tentado(
    monkeypatch: pytest.MonkeyPatch,
):
    candidato = ResultadoBusca(titulo_exibicao="Naruto", identificador="1", url="https://x/1")

    async def _buscar_em_com_variantes_fake(sessionmaker, dominio, variantes, *, referencia):
        return _fonte(dominio, candidato), None

    async def _falha_se_chamado(titulo: str):
        raise AssertionError("buscar_titulos não deveria ser chamado quando a Fase 1 já achou")

    monkeypatch.setattr(
        "extractors.servico.buscar_em_com_variantes", _buscar_em_com_variantes_fake
    )
    monkeypatch.setattr("integrations.servico.buscar_titulos", _falha_se_chamado)

    resultado = await servico_busca.buscar_com_titulos_alternativos(None, "Naruto")

    fonte_animesdrive = next(f for f in resultado.fontes if f.dominio == "animesdrive")
    assert fonte_animesdrive.indisponivel is False
    assert fonte_animesdrive.candidatos == []
    assert fonte_animesdrive.motivo is not None
    assert "não consultado" in fonte_animesdrive.motivo


async def test_todos_os_sites_indisponiveis_nao_chama_provedor(monkeypatch: pytest.MonkeyPatch):
    """Regressão do `_merece_expansao` antigo: se os dois sites já vieram
    `indisponivel` na Fase 1, a Fase 2 vai pular os dois de qualquer forma
    (mesmo filtro de `_tentar_termos_de_provedor`) — chamar `buscar_titulos`
    aqui seria rede garantidamente desperdiçada."""

    async def _buscar_em_com_variantes_fake(sessionmaker, dominio, variantes, *, referencia):
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

    async def _buscar_em_com_variantes_fake(sessionmaker, dominio, variantes, *, referencia):
        return _fonte(dominio), None  # Fase 1: disponível, mas vazio nos 2 sites

    async def _buscar_por_site_com_variantes_fake(
        sessionmaker, variantes, *, referencia, dominios=None
    ):
        return {
            "animefire.io": _fonte_indisponivel("animefire.io", "caiu durante a Fase 2"),
            "animesdrive": _fonte_indisponivel("animesdrive", "caiu durante a Fase 2"),
        }

    async def _buscar_titulos_fake(titulo: str) -> TitulosDeAnime | None:
        return TitulosDeAnime(titulo_romaji=romaji, titulo_ingles=None)

    monkeypatch.setattr(
        "extractors.servico.buscar_em_com_variantes", _buscar_em_com_variantes_fake
    )
    monkeypatch.setattr(
        "extractors.servico.buscar_por_site_com_variantes", _buscar_por_site_com_variantes_fake
    )
    monkeypatch.setattr("integrations.servico.buscar_titulos", _buscar_titulos_fake)

    resultado = await servico_busca.buscar_com_titulos_alternativos(None, "Naruto")

    fonte_animefire = next(f for f in resultado.fontes if f.dominio == "animefire.io")
    assert fonte_animefire.indisponivel is True
    assert fonte_animefire.motivo == "caiu durante a Fase 2"


async def test_fase2_falha_de_metadados_nao_propaga_devolve_rodada_da_fase1(
    monkeypatch: pytest.MonkeyPatch,
):
    async def _buscar_em_com_variantes_fake(sessionmaker, dominio, variantes, *, referencia):
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
    assert dominios == {"animefire.io", "animesdrive"}


# --- buscar_em_todas_as_fontes_com_titulos_alternativos (escopo `todas`) ---
#
# Mesmos 4 branches já cobertos acima para `buscar_com_titulos_alternativos`
# (escopo `padrao`), agora para o motor paralelo por site (fatia 3/4: cada
# site esgota sua própria escada de variantes, INV-1'). O fake de
# `buscar_por_site_com_variantes` recebe `(sessionmaker, variantes, *,
# referencia, dominios=None)` e devolve `dict[str, ResultadoDeFonte]` (uma
# entrada por domínio), mesmo contrato da função real.


async def test_todas_fase2_termo_de_provedor_acha_quando_fase1_vazia(
    monkeypatch: pytest.MonkeyPatch,
):
    candidato = ResultadoBusca(titulo_exibicao="Tensei Slime", identificador="1", url="https://x/1")
    romaji = "Tensei Shitara Slime Datta Ken"

    async def _buscar_por_site_com_variantes_fake(
        sessionmaker, variantes, *, referencia, dominios=None
    ):
        if romaji in variantes:
            return {
                "animefire.io": _fonte("animefire.io", candidato),
                "animesdrive": _fonte("animesdrive"),
            }
        return {
            "animefire.io": _fonte("animefire.io"),
            "animesdrive": _fonte("animesdrive"),
        }

    async def _buscar_titulos_fake(titulo: str) -> TitulosDeAnime | None:
        assert titulo == "Slime"
        return TitulosDeAnime(titulo_romaji=romaji, titulo_ingles=None)

    monkeypatch.setattr(
        "extractors.servico.buscar_por_site_com_variantes",
        _buscar_por_site_com_variantes_fake,
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


async def test_todas_fase2_termo_por_termo_restringe_dominios_aos_pendentes(
    monkeypatch: pytest.MonkeyPatch,
):
    """Fatia 5, escopo `todas`: escada por termo (cada termo com sua própria
    referência) + `dominios=` restringindo cada termo aos sites ainda
    pendentes — o romaji acha candidato no animefire.io; o termo seguinte
    (inglês) só pode ser consultado no animesdrive (o único ainda sem
    candidato), nunca reconsultando quem já achou. O resultado final é a
    união dos dois termos, um candidato de cada."""
    romaji = "Naruto Shippuden"
    ingles = "Naruto Hurricane Chronicles"
    candidato_af = ResultadoBusca(
        titulo_exibicao="Naruto Shippuden", identificador="1", url="https://af/1"
    )
    candidato_ad = ResultadoBusca(
        titulo_exibicao="Naruto Hurricane Chronicles", identificador="2", url="https://ad/2"
    )
    chamadas: list[tuple[str, list[str] | None]] = []

    async def _buscar_por_site_com_variantes_fake(
        sessionmaker, variantes, *, referencia, dominios=None
    ):
        chamadas.append((referencia, sorted(dominios) if dominios is not None else None))
        if referencia == romaji:
            return {
                "animefire.io": _fonte("animefire.io", candidato_af),
                "animesdrive": _fonte("animesdrive"),
            }
        if referencia == ingles:
            return {"animesdrive": _fonte("animesdrive", candidato_ad)}
        return {
            "animefire.io": _fonte("animefire.io"),
            "animesdrive": _fonte("animesdrive"),
        }

    async def _buscar_titulos_fake(titulo: str) -> TitulosDeAnime | None:
        return TitulosDeAnime(titulo_romaji=romaji, titulo_ingles=ingles)

    monkeypatch.setattr(
        "extractors.servico.buscar_por_site_com_variantes",
        _buscar_por_site_com_variantes_fake,
    )
    monkeypatch.setattr("integrations.servico.buscar_titulos", _buscar_titulos_fake)

    resultado = await servico_busca.buscar_em_todas_as_fontes_com_titulos_alternativos(
        None, "Naruto"
    )

    assert chamadas == [
        ("Naruto", None),  # Fase 1
        (romaji, ["animefire.io", "animesdrive"]),  # termo A: os 2 ainda pendentes
        (ingles, ["animesdrive"]),  # termo B: só quem A não achou
    ]
    fontes_por_dominio = {f.dominio: f for f in resultado.fontes}
    assert fontes_por_dominio["animefire.io"].candidatos == [candidato_af]
    assert fontes_por_dominio["animesdrive"].candidatos == [candidato_ad]


async def test_todas_fase1_e_fase2_vazias_preserva_rodada_da_fase1(
    monkeypatch: pytest.MonkeyPatch,
):
    """Fase 2 também não acha nada (`_expandir_termo_de_provedor_em_todas_as_
    fontes` devolve `None`) — o chamador preserva a rodada original da Fase 1
    em vez de substituí-la por uma rodada vazia diferente. As duas rodadas
    vêm marcadas de forma distinguível (`indisponivel`/`motivo`) só pra provar
    que a substituição realmente não acontece."""
    romaji = "Naruto Shippuden"

    async def _buscar_por_site_com_variantes_fake(
        sessionmaker, variantes, *, referencia, dominios=None
    ):
        if romaji in variantes:
            return {
                "animefire.io": _fonte_indisponivel("animefire.io", "fase2"),
                "animesdrive": _fonte_indisponivel("animesdrive", "fase2"),
            }
        return {
            "animefire.io": _fonte("animefire.io"),
            "animesdrive": _fonte("animesdrive"),
        }

    async def _buscar_titulos_fake(titulo: str) -> TitulosDeAnime | None:
        return TitulosDeAnime(titulo_romaji=romaji, titulo_ingles=None)

    monkeypatch.setattr(
        "extractors.servico.buscar_por_site_com_variantes",
        _buscar_por_site_com_variantes_fake,
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
    async def _buscar_por_site_com_variantes_fake(
        sessionmaker, variantes, *, referencia, dominios=None
    ):
        return {
            "animefire.io": _fonte("animefire.io"),
            "animesdrive": _fonte("animesdrive"),
        }

    async def _buscar_titulos_falha(titulo: str):
        raise FalhaDeMetadados("todos os provedores de metadados falharam")

    monkeypatch.setattr(
        "extractors.servico.buscar_por_site_com_variantes",
        _buscar_por_site_com_variantes_fake,
    )
    monkeypatch.setattr("integrations.servico.buscar_titulos", _buscar_titulos_falha)

    resultado = await servico_busca.buscar_em_todas_as_fontes_com_titulos_alternativos(
        None, "Slime"
    )

    assert resultado.termo_alternativo is None
    assert resultado.dominio_alternativo is None
    dominios = {fonte.dominio for fonte in resultado.fontes}
    assert dominios == {"animefire.io", "animesdrive"}


async def test_todas_todos_os_sites_indisponiveis_nao_chama_provedor(
    monkeypatch: pytest.MonkeyPatch,
):
    """Mesma regressão do `_merece_expansao` antigo, agora pro escopo `todas`:
    se os dois sites já vieram `indisponivel` na Fase 1, a Fase 2 é pulada
    inteira (`algum_site_disponivel` na guarda) — chamar `buscar_titulos`
    aqui seria rede garantidamente desperdiçada."""

    async def _buscar_por_site_com_variantes_fake(
        sessionmaker, variantes, *, referencia, dominios=None
    ):
        return {
            "animefire.io": _fonte_indisponivel("animefire.io"),
            "animesdrive": _fonte_indisponivel("animesdrive"),
        }

    async def _falha_se_chamado(titulo: str):
        raise AssertionError(
            "buscar_titulos não deveria ser chamado quando todos os sites já"
            " estão indisponíveis"
        )

    monkeypatch.setattr(
        "extractors.servico.buscar_por_site_com_variantes",
        _buscar_por_site_com_variantes_fake,
    )
    monkeypatch.setattr("integrations.servico.buscar_titulos", _falha_se_chamado)

    resultado = await servico_busca.buscar_em_todas_as_fontes_com_titulos_alternativos(
        None, "Naruto"
    )

    assert resultado.termo_alternativo is None
    assert resultado.dominio_alternativo is None
    assert all(fonte.indisponivel for fonte in resultado.fontes)

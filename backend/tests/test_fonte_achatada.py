"""`api/servicos/fontes.py::_recortar_se_fonte_achatada` — fonte que devolve a
franquia inteira numerada de forma contínua (AnimeFire sem `season` por episódio)."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from api.servicos import fontes
from core.enums import StatusLancamento
from fontes.adaptadores.base import EpisodioRemoto


def _eps(quantidade: int) -> list[EpisodioRemoto]:
    return [
        EpisodioRemoto(rotulo=str(n), numero=n, url=f"https://x/{n}")
        for n in range(1, quantidade + 1)
    ]


def _anime(**campos):
    base = {
        "titulo": "Teste",
        "numero_temporada": 2,
        "total_episodios_anilist": None,
        "status_lancamento": StatusLancamento.FINALIZADO,
        "proximo_ep_numero": None,
    }
    return SimpleNamespace(**(base | campos))


@pytest.fixture
def offset_de(monkeypatch):
    async def _sem_partes(_sessionmaker, _anime):
        return 0

    monkeypatch.setattr(fontes, "total_das_partes_irmas", _sem_partes)

    def _fixar(valor: int) -> None:
        async def _falso(_sessionmaker, _anime):
            return valor

        monkeypatch.setattr(fontes, "offset_de_temporada", _falso)

    return _fixar


async def test_temporada_em_exibicao_sem_total_corta_pelo_offset(offset_de):
    # T1 tem 12 eps; T2 foi ao ar até o ep 2 (próximo = 3) e a fonte lista 14 contínuos.
    offset_de(12)
    anime = _anime(status_lancamento=StatusLancamento.EM_LANCAMENTO, proximo_ep_numero=3)

    recortados = await fontes._recortar_se_fonte_achatada(None, anime, _eps(14))

    assert [ep.numero for ep in recortados] == [1, 2]
    assert [ep.rotulo for ep in recortados] == ["13", "14"]


async def test_temporada_em_exibicao_com_fonte_a_frente_por_um_nao_corta(offset_de):
    # Recorte nativo já feito pelo adapter: 3 eps contra 2 declarados (fonte à frente).
    offset_de(12)
    anime = _anime(status_lancamento=StatusLancamento.EM_LANCAMENTO, proximo_ep_numero=3)

    assert await fontes._recortar_se_fonte_achatada(None, anime, _eps(3)) == _eps(3)


async def test_primeira_temporada_em_exibicao_nao_corta(offset_de):
    offset_de(0)
    anime = _anime(
        numero_temporada=1, status_lancamento=StatusLancamento.EM_LANCAMENTO, proximo_ep_numero=3
    )

    assert await fontes._recortar_se_fonte_achatada(None, anime, _eps(8)) == _eps(8)


async def test_temporada_fechada_corta_com_teto(offset_de):
    offset_de(12)
    anime = _anime(total_episodios_anilist=12)

    recortados = await fontes._recortar_se_fonte_achatada(None, anime, _eps(30))

    assert [ep.numero for ep in recortados] == list(range(1, 13))
    assert recortados[0].rotulo == "13"


async def test_sem_contagem_esperada_devolve_intacto(offset_de):
    offset_de(12)

    assert await fontes._recortar_se_fonte_achatada(None, _anime(), _eps(14)) == _eps(14)


async def test_temporada_dividida_em_partes_soma_os_totais(monkeypatch, offset_de):
    # Slime T2: AniList divide em Part 1 (12) + Part 2 (12); o site serve os 24 juntos.
    offset_de(0)

    async def _partes(_sessionmaker, _anime):
        return 12

    monkeypatch.setattr(fontes, "total_das_partes_irmas", _partes)
    anime = _anime(total_episodios_anilist=12)

    assert await fontes._recortar_se_fonte_achatada(None, anime, _eps(24)) == _eps(24)


async def test_recorte_nativo_de_temporada_fechada_apara_o_que_passa_do_total(offset_de):
    # Go-toubun T2: MeusAnimes já recortou a temporada (16 eps = 12 + 4 OVAs arquivadas
    # nela) e a AniList declara 12. O corte por offset NÃO roda (deixaria só 13..16);
    # só o excedente cai.
    offset_de(12)
    anime = _anime(total_episodios_anilist=12)
    nativos = [replace(ep, recortado_pela_fonte=True) for ep in _eps(16)]

    aparados = await fontes._recortar_se_fonte_achatada(None, anime, nativos)

    assert [ep.numero for ep in aparados] == list(range(1, 13))


async def test_recorte_nativo_em_exibicao_nao_apara(offset_de):
    offset_de(12)
    anime = _anime(status_lancamento=StatusLancamento.EM_LANCAMENTO, proximo_ep_numero=3)
    nativos = [replace(ep, recortado_pela_fonte=True) for ep in _eps(4)]

    assert await fontes._recortar_se_fonte_achatada(None, anime, nativos) == nativos


async def test_lista_so_com_episodios_de_temporadas_anteriores_vira_vazia(offset_de):
    # Hyouken T2 em exibição (1 ep no ar): o dublado do MeusAnimes só tem a T1 (12 eps)
    # e o adapter a devolve inteira. Não é conteúdo da T2.
    offset_de(12)
    anime = _anime(status_lancamento=StatusLancamento.EM_LANCAMENTO, proximo_ep_numero=2)

    assert await fontes._recortar_se_fonte_achatada(None, anime, _eps(12)) == []


def test_seletor_colapsa_partes_da_mesma_temporada_numa_entrada():
    from api.rotas.animes import _temporadas_e_proxima

    def _linha(id_: int, numero: int, total: int, tem_episodios: bool):
        return SimpleNamespace(
            id=id_,
            numero_temporada=numero,
            titulo=f"T{numero}",
            status_lancamento=StatusLancamento.FINALIZADO,
            estreia_em=None,
            ano=None,
            formato_midia=None,
            total_episodios_anilist=total,
            tem_episodios=tem_episodios,
        )

    # T2 dividida: 43 (Part 1, com episódios) e 143 (Part 2, sem nada capturado).
    grupo = [_linha(42, 1, 24, True), _linha(43, 2, 12, True), _linha(143, 2, 12, False)]

    temporadas, _ = _temporadas_e_proxima(42, 1, grupo)

    assert [(t.id, t.numero_temporada, t.total_episodios) for t in temporadas] == [
        (42, 1, 24),
        (43, 2, 24),
    ]
    assert temporadas[1].ids_das_partes == [143]

    # Aberta pela Part 2, ela continua sendo a entrada marcada no seletor.
    temporadas, _ = _temporadas_e_proxima(143, 2, grupo)
    assert [t.id for t in temporadas] == [42, 143]
    assert temporadas[1].ids_das_partes == [43]


def test_parte_nova_de_temporada_existente_vira_proxima_como_nova_parte():
    from api.rotas.animes import _temporadas_e_proxima

    def _linha(id_: int, numero: int, status: StatusLancamento, tem_episodios: bool):
        return SimpleNamespace(
            id=id_,
            numero_temporada=numero,
            titulo=f"T{numero}",
            status_lancamento=status,
            estreia_em=None,
            ano=2027,
            formato_midia=None,
            total_episodios_anilist=None,
            tem_episodios=tem_episodios,
        )

    # Slime: T4 (22) existe; "4th Season Part 3" (144) é parte dela, não a "4ª temporada".
    grupo = [
        _linha(42, 1, StatusLancamento.FINALIZADO, True),
        _linha(22, 4, StatusLancamento.FINALIZADO, True),
        _linha(144, 4, StatusLancamento.NAO_LANCADO, False),
    ]

    for aberto, numero in ((42, 1), (22, 4)):
        _, proxima = _temporadas_e_proxima(aberto, numero, grupo)
        assert (proxima.id, proxima.nova_parte) == (144, True)

    # Uma temporada genuinamente nova (número acima) continua sem o marcador.
    grupo.append(_linha(200, 5, StatusLancamento.NAO_LANCADO, False))
    grupo.remove(grupo[2])
    _, proxima = _temporadas_e_proxima(22, 4, grupo)
    assert (proxima.id, proxima.nova_parte) == (200, False)

"""`fontes/recorte.py` — fonte que devolve a franquia inteira numerada de forma
contínua (AnimeFire sem `season` por episódio)."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from core.enums import StatusLancamento
from fontes import recorte
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

    monkeypatch.setattr(recorte, "total_das_partes_irmas", _sem_partes)

    def _fixar(valor: int) -> None:
        async def _falso(_sessionmaker, _anime):
            return valor

        monkeypatch.setattr(recorte, "offset_de_temporada", _falso)

    return _fixar


async def test_temporada_em_exibicao_sem_total_corta_pelo_offset(offset_de):
    # T1 tem 12 eps; T2 foi ao ar até o ep 2 (próximo = 3) e a fonte lista 14 contínuos.
    offset_de(12)
    anime = _anime(status_lancamento=StatusLancamento.EM_LANCAMENTO, proximo_ep_numero=3)

    recortados = await recorte.recortar_se_fonte_achatada(None, anime, _eps(14))

    assert [ep.numero for ep in recortados] == [1, 2]
    assert [ep.rotulo for ep in recortados] == ["13", "14"]


async def test_temporada_em_exibicao_com_fonte_a_frente_por_um_nao_corta(offset_de):
    # Recorte nativo já feito pelo adapter: 3 eps contra 2 declarados (fonte à frente).
    offset_de(12)
    anime = _anime(status_lancamento=StatusLancamento.EM_LANCAMENTO, proximo_ep_numero=3)

    assert await recorte.recortar_se_fonte_achatada(None, anime, _eps(3)) == _eps(3)


async def test_primeira_temporada_em_exibicao_nao_corta(offset_de):
    offset_de(0)
    anime = _anime(
        numero_temporada=1, status_lancamento=StatusLancamento.EM_LANCAMENTO, proximo_ep_numero=3
    )

    assert await recorte.recortar_se_fonte_achatada(None, anime, _eps(8)) == _eps(8)


async def test_temporada_fechada_corta_com_teto(offset_de):
    offset_de(12)
    anime = _anime(total_episodios_anilist=12)

    recortados = await recorte.recortar_se_fonte_achatada(None, anime, _eps(30))

    assert [ep.numero for ep in recortados] == list(range(1, 13))
    assert recortados[0].rotulo == "13"


async def test_sem_contagem_esperada_devolve_intacto(offset_de):
    offset_de(12)

    assert await recorte.recortar_se_fonte_achatada(None, _anime(), _eps(14)) == _eps(14)


async def test_temporada_dividida_em_partes_soma_os_totais(monkeypatch, offset_de):
    # Slime T2: AniList divide em Part 1 (12) + Part 2 (12); o site serve os 24 juntos.
    offset_de(0)

    async def _partes(_sessionmaker, _anime):
        return 12

    monkeypatch.setattr(recorte, "total_das_partes_irmas", _partes)
    anime = _anime(total_episodios_anilist=12)

    assert await recorte.recortar_se_fonte_achatada(None, anime, _eps(24)) == _eps(24)


async def test_recorte_nativo_de_temporada_fechada_apara_o_que_passa_do_total(offset_de):
    # Go-toubun T2: MeusAnimes já recortou a temporada (16 eps = 12 + 4 OVAs arquivadas
    # nela) e a AniList declara 12. O corte por offset NÃO roda (deixaria só 13..16);
    # só o excedente cai.
    offset_de(12)
    anime = _anime(total_episodios_anilist=12)
    nativos = [replace(ep, recortado_pela_fonte=True) for ep in _eps(16)]

    aparados = await recorte.recortar_se_fonte_achatada(None, anime, nativos)

    assert [ep.numero for ep in aparados] == list(range(1, 13))


async def test_recorte_nativo_em_exibicao_nao_apara(offset_de):
    offset_de(12)
    anime = _anime(status_lancamento=StatusLancamento.EM_LANCAMENTO, proximo_ep_numero=3)
    nativos = [replace(ep, recortado_pela_fonte=True) for ep in _eps(4)]

    assert await recorte.recortar_se_fonte_achatada(None, anime, nativos) == nativos


async def test_lista_so_com_episodios_de_temporadas_anteriores_vira_vazia(offset_de):
    # Hyouken T2 em exibição (1 ep no ar): o dublado do MeusAnimes só tem a T1 (12 eps)
    # e o adapter a devolve inteira. Não é conteúdo da T2.
    offset_de(12)
    anime = _anime(status_lancamento=StatusLancamento.EM_LANCAMENTO, proximo_ep_numero=2)

    assert await recorte.recortar_se_fonte_achatada(None, anime, _eps(12)) == []


# --- decisão pura ---


def test_episodios_esperados_de_temporada_fechada_e_em_exibicao():
    assert recorte.episodios_esperados(_anime(total_episodios_anilist=12)) == recorte.Esperados(
        12, em_aberto=False
    )
    em_exibicao = _anime(status_lancamento=StatusLancamento.EM_LANCAMENTO, proximo_ep_numero=4)
    assert recorte.episodios_esperados(em_exibicao) == recorte.Esperados(3, em_aberto=True)
    # Estreia: nenhum episódio no ar ainda, nada a esperar.
    estreia = _anime(status_lancamento=StatusLancamento.EM_LANCAMENTO, proximo_ep_numero=1)
    assert recorte.episodios_esperados(estreia) is None
    assert recorte.episodios_esperados(_anime()) is None


def test_excede_a_temporada_respeita_folga_de_exibicao_e_partes_irmas():
    fechada = recorte.Esperados(12, em_aberto=False)
    assert not recorte.excede_a_temporada(_eps(12), fechada)
    assert recorte.excede_a_temporada(_eps(13), fechada)
    assert not recorte.excede_a_temporada(_eps(24), fechada, partes_irmas=12)

    aberta = recorte.Esperados(2, em_aberto=True)
    assert not recorte.excede_a_temporada(_eps(3), aberta)
    assert recorte.excede_a_temporada(_eps(4), aberta)
    # Temporada em exibição não soma partes irmãs.
    assert recorte.excede_a_temporada(_eps(4), aberta, partes_irmas=12)


def test_recortar_por_offset_renumera_e_preserva_o_rotulo():
    resultado = recorte.recortar_por_offset(_eps(24), offset=12, teto=24)

    assert resultado.resultado is recorte.ResultadoDoRecorte.RECORTADA
    assert [ep.numero for ep in resultado.episodios] == list(range(1, 13))
    assert resultado.episodios[0].rotulo == "13"


def test_recortar_por_offset_mantem_episodio_sem_numero():
    especial = EpisodioRemoto(rotulo="Especial", numero=None, url="https://x/esp")

    resultado = recorte.recortar_por_offset([*_eps(24), especial], offset=12, teto=24)

    assert resultado.episodios[-1] is especial
    assert len(resultado.episodios) == 13


def test_recortar_por_offset_so_com_temporadas_anteriores_sobra_so_o_sem_numero():
    especial = EpisodioRemoto(rotulo="Especial", numero=None, url="https://x/esp")

    resultado = recorte.recortar_por_offset([*_eps(12), especial], offset=12, teto=24)

    assert resultado.resultado is recorte.ResultadoDoRecorte.SO_TEMPORADAS_ANTERIORES
    assert resultado.episodios == [especial]


def test_recortar_por_offset_sem_cobertura_devolve_a_lista_intacta():
    # Offset maior que a numeração da fonte E lista que ultrapassa o offset... sem
    # nenhum episódio no intervalo: não dá pra afirmar nada, não mexe.
    episodios = [EpisodioRemoto(rotulo=str(n), numero=n, url=f"https://x/{n}") for n in (1, 2, 40)]

    resultado = recorte.recortar_por_offset(episodios, offset=12, teto=24)

    assert resultado.resultado is recorte.ResultadoDoRecorte.OFFSET_NAO_COBRIU
    assert resultado.episodios == episodios


def test_aparar_excedente_corta_acima_do_teto_e_preserva_sem_numero():
    especial = EpisodioRemoto(rotulo="Especial", numero=None, url="https://x/esp")

    aparados = recorte.aparar_excedente([*_eps(16), especial], teto=12)

    assert [ep.numero for ep in aparados] == [*range(1, 13), None]

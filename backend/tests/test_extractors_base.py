"""`extractors/base.py::ordenar_episodios` — ordem comum a todos os adapters."""

from extractors.base import EpisodioRemoto, ordenar_episodios


def _ep(rotulo: str, numero: int | None) -> EpisodioRemoto:
    return EpisodioRemoto(rotulo=rotulo, numero=numero, url=f"https://x/{rotulo}")


def test_numericos_em_ordem_crescente_e_nao_numericos_no_fim():
    episodios = [_ep("Especial", None), _ep("3", 3), _ep("1", 1), _ep("OVA 2", None), _ep("2", 2)]

    assert [ep.rotulo for ep in ordenar_episodios(episodios)] == [
        "1",
        "2",
        "3",
        "Especial",
        "OVA 2",
    ]


def test_mesmo_numero_mantem_a_ordem_em_que_apareceu():
    # "07" antes de "7" na página: o desempate não pode ser lexicográfico por rótulo.
    episodios = [_ep("07", 7), _ep("7", 7), _ep("6", 6)]

    assert [ep.rotulo for ep in ordenar_episodios(episodios)] == ["6", "07", "7"]


def test_aceita_qualquer_iteravel_e_nao_altera_a_entrada():
    por_rotulo = {"2": _ep("2", 2), "1": _ep("1", 1)}

    assert [ep.numero for ep in ordenar_episodios(por_rotulo.values())] == [1, 2]
    assert list(por_rotulo) == ["2", "1"]

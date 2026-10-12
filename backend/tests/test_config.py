"""Leitura de variáveis booleanas do `.env`."""

import pytest

from core.config import _ler_booleano
from core.erros import ErroDeConfiguracao


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [("true", True), ("TRUE", True), ("1", True), ("false", False), (" 0 ", False)],
)
def test_ler_booleano_aceita_true_false_0_1(valor, esperado):
    assert _ler_booleano("X", valor, padrao=not esperado) is esperado


@pytest.mark.parametrize("valor", [None, "", "   "])
def test_ler_booleano_ausente_usa_o_padrao(valor):
    assert _ler_booleano("X", valor, padrao=True) is True
    assert _ler_booleano("X", valor, padrao=False) is False


def test_ler_booleano_invalido_levanta_com_o_nome_da_variavel():
    with pytest.raises(ErroDeConfiguracao, match="ZELADOR_ATIVO"):
        _ler_booleano("ZELADOR_ATIVO", "talvez", padrao=True)

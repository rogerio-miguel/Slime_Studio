"""Testes de `fontes/adaptadores/qualidade.py::qualidade_do_rotulo` — domínio puro, sem
rede. Tabela de classificação equivalente à documentada em `PLANO_ANIMESDRIVE.md`
D1, compartilhada entre `animesdrive.py` e `animefire.py`."""

import pytest

from fontes.adaptadores.qualidade import NivelDeQualidade, qualidade_do_rotulo


@pytest.mark.parametrize(
    ("rotulo", "esperado"),
    [
        ("FullHD / HLS", NivelDeQualidade.FHD),
        ("FHD", NivelDeQualidade.FHD),
        ("Full HD", NivelDeQualidade.FHD),
        ("1080p", NivelDeQualidade.FHD),
        ("2160p", NivelDeQualidade.FHD),
        ("4K", NivelDeQualidade.FHD),
        ("FHD / HD", NivelDeQualidade.FHD),
        ("HD", NivelDeQualidade.HD),
        ("720p", NivelDeQualidade.HD),
        ("SD/HD", NivelDeQualidade.HD),
        ("SD", NivelDeQualidade.ABAIXO_DO_PISO),
        ("480p", NivelDeQualidade.ABAIXO_DO_PISO),
        ("360p", NivelDeQualidade.ABAIXO_DO_PISO),
        ("Mobile / Celular", NivelDeQualidade.ABAIXO_DO_PISO),
        ("Dublado", NivelDeQualidade.DESCONHECIDA),
        ("Servidor 2", NivelDeQualidade.DESCONHECIDA),
        ("", NivelDeQualidade.DESCONHECIDA),
        ("F-HD", NivelDeQualidade.FHD),
        ("Fullhd", NivelDeQualidade.FHD),
    ],
)
def test_qualidade_do_rotulo(rotulo, esperado):
    assert qualidade_do_rotulo(rotulo) == esperado


def test_qualidade_do_rotulo_ignora_acento_e_caixa():
    """`unicodedata.normalize` + `casefold` deixam "Móvel"/"CELULAR" fora do
    jogo sem precisar listar cada variação acentuada/maiúscula à mão."""
    assert qualidade_do_rotulo("MÓVEL") == NivelDeQualidade.ABAIXO_DO_PISO
    assert qualidade_do_rotulo("celular") == NivelDeQualidade.ABAIXO_DO_PISO


def test_ordem_dos_niveis_e_crescente():
    """O `IntEnum` sustenta comparação direta (`>=`) usada pelos adapters pra
    escolher o maior tier — travar a ordem evita regressão silenciosa se
    alguém reordenar os membros."""
    assert (
        NivelDeQualidade.ABAIXO_DO_PISO
        < NivelDeQualidade.DESCONHECIDA
        < NivelDeQualidade.HD
        < NivelDeQualidade.FHD
    )

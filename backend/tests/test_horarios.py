"""Configuração de horários do zelador: interpretação do TOML, janelas (inclusive
as que cruzam a meia-noite) e o leitor que mantém a última versão válida."""

import os
from datetime import datetime, time
from pathlib import Path

import pytest

from api.servicos.horarios import LeitorDeHorarios
from core.erros import ErroDeConfiguracao
from core.horarios import ConfigDoZelador, Janela, interpretar_config, interpretar_janela

_EXEMPLO = Path(__file__).resolve().parents[2] / "config" / "horarios.exemplo.toml"


def _as(hora: str) -> datetime:
    return datetime(2026, 10, 11, *map(int, hora.split(":")))


def test_exemplo_versionado_e_valido_e_traz_as_janelas_iniciais():
    config = interpretar_config(_EXEMPLO.read_text(encoding="utf-8"))

    assert config.ativo is True
    assert config.janelas_do_navegador == (
        Janela(time(12, 0), time(13, 30)),
        Janela(time(19, 0), time(21, 30)),
    )
    assert config.teto_diario_de_aberturas == 3


@pytest.mark.parametrize(
    ("hora", "liberado"),
    [
        ("11:59", False),
        ("12:00", True),  # início inclusivo
        ("13:29", True),
        ("13:30", False),  # fim exclusivo
        ("18:00", False),
        ("20:00", True),
        ("21:30", False),
    ],
)
def test_navegador_liberado_so_dentro_das_janelas(hora, liberado):
    config = ConfigDoZelador(
        janelas_do_navegador=(
            interpretar_janela("12:00-13:30"),
            interpretar_janela("19:00-21:30"),
        )
    )
    assert config.navegador_liberado_em(_as(hora)) is liberado


def test_janela_que_cruza_a_meia_noite():
    janela = interpretar_janela("22:00-02:00")
    assert janela.contem(time(23, 0)) and janela.contem(time(1, 0))
    assert not janela.contem(time(2, 0)) and not janela.contem(time(12, 0))


def test_sem_janelas_o_navegador_nunca_abre():
    assert ConfigDoZelador().navegador_liberado_em(_as("12:30")) is False


def test_valores_padrao_quando_o_arquivo_esta_vazio():
    assert interpretar_config("") == ConfigDoZelador()


@pytest.mark.parametrize(
    "texto",
    [
        "zelador_ativo = ",  # TOML quebrado
        "janela_do_navegador = []",  # chave desconhecida (erro de digitação)
        'zelador_ativo = "sim"',
        "janelas_do_navegador = 12",
        'janelas_do_navegador = ["12:00"]',  # sem fim
        'janelas_do_navegador = ["25:00-26:00"]',
        'janelas_do_navegador = ["12:00-12:00"]',  # início == fim
        "teto_diario_de_aberturas = -1",
        "teto_diario_de_aberturas = true",
    ],
)
def test_config_invalida_levanta_erro_explicito(texto):
    with pytest.raises(ErroDeConfiguracao):
        interpretar_config(texto)


# --- leitor do arquivo ---


def _gravar(caminho: Path, texto: str, mtime: float) -> None:
    caminho.write_text(texto, encoding="utf-8")
    os.utime(caminho, (mtime, mtime))


def test_leitor_prefere_horarios_toml_ao_exemplo(tmp_path):
    _gravar(tmp_path / "horarios.exemplo.toml", "teto_diario_de_aberturas = 1", 100)
    _gravar(tmp_path / "horarios.toml", "teto_diario_de_aberturas = 7", 100)

    assert LeitorDeHorarios(tmp_path).atual().teto_diario_de_aberturas == 7


def test_leitor_cai_no_exemplo_sem_horarios_toml(tmp_path):
    _gravar(tmp_path / "horarios.exemplo.toml", "teto_diario_de_aberturas = 1", 100)

    assert LeitorDeHorarios(tmp_path).atual().teto_diario_de_aberturas == 1


def test_leitor_relê_quando_o_arquivo_muda_sem_reiniciar(tmp_path):
    arquivo = tmp_path / "horarios.toml"
    _gravar(arquivo, "teto_diario_de_aberturas = 1", 100)
    leitor = LeitorDeHorarios(tmp_path)
    assert leitor.atual().teto_diario_de_aberturas == 1

    _gravar(arquivo, "teto_diario_de_aberturas = 5", 200)

    assert leitor.atual().teto_diario_de_aberturas == 5


def test_leitor_mantem_a_ultima_config_valida_e_avisa_uma_vez(tmp_path, caplog):
    arquivo = tmp_path / "horarios.toml"
    _gravar(arquivo, "teto_diario_de_aberturas = 4", 100)
    leitor = LeitorDeHorarios(tmp_path)
    assert leitor.atual().teto_diario_de_aberturas == 4

    _gravar(arquivo, "teto_diario_de_aberturas = ", 200)
    with caplog.at_level("WARNING", logger="api.servicos.horarios"):
        assert leitor.atual().teto_diario_de_aberturas == 4
        assert leitor.atual().teto_diario_de_aberturas == 4

    assert caplog.text.count("mantendo a última configuração válida") == 1


def test_leitor_sem_nenhum_arquivo_usa_o_padrao_seguro(tmp_path):
    config = LeitorDeHorarios(tmp_path).atual()

    assert config.janelas_do_navegador == () and config.teto_diario_de_aberturas == 0

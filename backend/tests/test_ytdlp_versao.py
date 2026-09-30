"""Testes de `worker/pipeline/ferramentas.py::registrar_versao_do_ytdlp`."""

import logging
from datetime import date

import pytest

from worker.pipeline.ferramentas import registrar_versao_do_ytdlp

_HOJE = date(2026, 9, 30)


def test_versao_recente_so_informa(caplog: pytest.LogCaptureFixture):
    with caplog.at_level(logging.INFO):
        registrar_versao_do_ytdlp(versao="2026.08.19", hoje=_HOJE)

    assert [r.levelno for r in caplog.records] == [logging.INFO]
    assert "2026.08.19" in caplog.text


def test_versao_no_limite_de_90_dias_nao_avisa(caplog: pytest.LogCaptureFixture):
    with caplog.at_level(logging.INFO):
        registrar_versao_do_ytdlp(versao="2026.07.02", hoje=_HOJE)  # 90 dias

    assert logging.WARNING not in [r.levelno for r in caplog.records]


def test_versao_velha_avisa_como_atualizar(caplog: pytest.LogCaptureFixture):
    with caplog.at_level(logging.INFO):
        registrar_versao_do_ytdlp(versao="2026.03.01", hoje=_HOJE)

    aviso = next(r for r in caplog.records if r.levelno == logging.WARNING)
    assert "uv lock --upgrade-package yt-dlp" in aviso.getMessage()


def test_versao_nightly_com_sufixo_de_hora_e_lida(caplog: pytest.LogCaptureFixture):
    with caplog.at_level(logging.INFO):
        registrar_versao_do_ytdlp(versao="2026.09.20.232741", hoje=_HOJE)

    assert logging.WARNING not in [r.levelno for r in caplog.records]


@pytest.mark.parametrize("versao", ["desconhecida", "2026.13.40", ""])
def test_formato_inesperado_avisa_em_vez_de_silenciar(caplog: pytest.LogCaptureFixture, versao):
    with caplog.at_level(logging.INFO):
        registrar_versao_do_ytdlp(versao=versao, hoje=_HOJE)

    assert "formato inesperado" in caplog.text

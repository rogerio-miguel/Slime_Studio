"""Leitor do arquivo de horários do zelador (`config/horarios.toml`).

O usuário ajusta o arquivo à mão com a API no ar, então ele é relido a cada
consulta (barato: só relê quando a data de modificação muda). Arquivo inválido
nunca derruba o zelador nem o liga "por garantia": mantém a última configuração
válida e avisa no log, uma vez por versão do arquivo. Sem `horarios.toml`, vale o
`horarios.exemplo.toml` versionado.
"""

import logging
from pathlib import Path

from core.erros import ErroDeConfiguracao
from core.horarios import ConfigDoZelador, interpretar_config

logger = logging.getLogger(__name__)

_RAIZ_REPO = Path(__file__).resolve().parents[3]
_PASTA_PADRAO = _RAIZ_REPO / "config"


class LeitorDeHorarios:
    def __init__(self, pasta: Path = _PASTA_PADRAO) -> None:
        self._arquivo = pasta / "horarios.toml"
        self._exemplo = pasta / "horarios.exemplo.toml"
        self._versao_lida: tuple[Path, float] | None = None
        self._atual = ConfigDoZelador()

    def atual(self) -> ConfigDoZelador:
        arquivo = self._arquivo if self._arquivo.exists() else self._exemplo
        try:
            versao = (arquivo, arquivo.stat().st_mtime)
        except OSError as erro:
            self._avisar_uma_vez((arquivo, -1.0), f"arquivo ilegível: {erro}")
            return self._atual
        if versao == self._versao_lida:
            return self._atual
        try:
            self._atual = interpretar_config(arquivo.read_text(encoding="utf-8"))
        except (ErroDeConfiguracao, OSError, UnicodeDecodeError) as erro:
            self._avisar_uma_vez(versao, str(erro))
            return self._atual
        self._versao_lida = versao
        logger.info("horários do zelador carregados de %s", arquivo.name)
        return self._atual

    def _avisar_uma_vez(self, versao: tuple[Path, float], motivo: str) -> None:
        if versao != self._versao_lida:
            logger.warning(
                "horários do zelador inválidos em %s (%s) — mantendo a última configuração válida",
                versao[0].name,
                motivo,
            )
            self._versao_lida = versao

"""Configuração de horários do zelador de fontes (quando ele pode abrir o
navegador, quantas vezes por dia, se está ligado).

Domínio puro: interpreta o TEXTO do arquivo de configuração e responde "agora
está dentro de uma janela?". Ler o arquivo e manter a última versão válida é de
`api/servicos/horarios.py`. Hora sempre no relógio local do computador — o
usuário pensa em "almoço" e "noite", não em UTC.
"""

import tomllib
from dataclasses import dataclass
from datetime import datetime, time

from core.erros import ErroDeConfiguracao

_CHAVES = frozenset({"zelador_ativo", "janelas_do_navegador", "teto_diario_de_aberturas"})


@dataclass(frozen=True)
class Janela:
    inicio: time
    fim: time

    def contem(self, momento: time) -> bool:
        if self.inicio < self.fim:
            return self.inicio <= momento < self.fim
        return momento >= self.inicio or momento < self.fim  # cruza a meia-noite


@dataclass(frozen=True)
class ConfigDoZelador:
    ativo: bool = True
    janelas_do_navegador: tuple[Janela, ...] = ()
    teto_diario_de_aberturas: int = 0

    def navegador_liberado_em(self, agora: datetime) -> bool:
        return any(janela.contem(agora.time()) for janela in self.janelas_do_navegador)


def _horario(texto: str) -> time:
    try:
        return datetime.strptime(texto.strip(), "%H:%M").time()
    except ValueError:
        raise ErroDeConfiguracao(f"horário inválido {texto!r} (use HH:MM)") from None


def interpretar_janela(texto: str) -> Janela:
    inicio, separador, fim = texto.partition("-")
    if not separador:
        raise ErroDeConfiguracao(f"janela inválida {texto!r} (use HH:MM-HH:MM)")
    janela = Janela(_horario(inicio), _horario(fim))
    if janela.inicio == janela.fim:
        raise ErroDeConfiguracao(f"janela {texto!r} tem início igual ao fim")
    return janela


def interpretar_config(texto_toml: str) -> ConfigDoZelador:
    """Valida e converte o conteúdo do arquivo. Qualquer problema levanta
    `ErroDeConfiguracao` com a causa: chave desconhecida também falha, senão um
    erro de digitação (`janela_do_navegador`) desligaria o navegador em silêncio."""
    try:
        bruto = tomllib.loads(texto_toml)
    except tomllib.TOMLDecodeError as erro:
        raise ErroDeConfiguracao(f"TOML inválido: {erro}") from None

    desconhecidas = sorted(set(bruto) - _CHAVES)
    if desconhecidas:
        raise ErroDeConfiguracao(f"chave(s) desconhecida(s): {', '.join(desconhecidas)}")

    padrao = ConfigDoZelador()
    ativo = bruto.get("zelador_ativo", padrao.ativo)
    if not isinstance(ativo, bool):
        raise ErroDeConfiguracao("zelador_ativo deve ser true ou false")

    janelas_brutas = bruto.get("janelas_do_navegador", [])
    if not isinstance(janelas_brutas, list) or not all(isinstance(j, str) for j in janelas_brutas):
        raise ErroDeConfiguracao('janelas_do_navegador deve ser uma lista de "HH:MM-HH:MM"')

    teto = bruto.get("teto_diario_de_aberturas", padrao.teto_diario_de_aberturas)
    if not isinstance(teto, int) or isinstance(teto, bool) or teto < 0:
        raise ErroDeConfiguracao("teto_diario_de_aberturas deve ser um inteiro >= 0")

    return ConfigDoZelador(
        ativo=ativo,
        janelas_do_navegador=tuple(interpretar_janela(j) for j in janelas_brutas),
        teto_diario_de_aberturas=teto,
    )

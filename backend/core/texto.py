"""Utilitários de texto de domínio — sem dependências externas (Escada de Minimalismo)."""

import re
import unicodedata


def slugificar(texto: str) -> str:
    """Converte texto livre num slug ASCII (`a-z0-9-`), usado tanto pelo CLI
    produtor de jobs quanto pelo layout de diretório HLS.

    Ex.: "Tensei Shitara Slime Datta Ken 2" -> "tensei-shitara-slime-datta-ken-2"
    """
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    minusculo = sem_acento.lower()
    com_hifens = re.sub(r"[^a-z0-9]+", "-", minusculo)
    return com_hifens.strip("-")

"""Resolução da fonte de mídia — arquivo local (Fase 1) ou download remoto via
extrator de site (Fase 2, ESPECIFICACAO.md §3A).
"""

import os
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from captura.download import caminho_raw
from captura.servico import baixar_com_fallback_de_site
from core.config import Config
from core.enums import SITE_LOCAL
from core.erros import FonteInvalida
from models.anime import Anime
from models.episodio import Episodio

_SessionMaker = async_sessionmaker[AsyncSession]


async def resolver_fonte(
    sessionmaker: _SessionMaker, config: Config, *, anime: Anime, episodio: Episodio
) -> Path:
    """Modo arquivo local (`episodio.site_origem == SITE_LOCAL`): confere o caminho
    já presente em `episodio.url_fonte`. Caso contrário, baixa via extrator do
    site (com fallback entre sites — `captura/servico.py::baixar_com_fallback_de_site`)
    e valida o arquivo baixado com a mesma checagem de integridade de sempre.
    """
    if episodio.site_origem == SITE_LOCAL:
        return resolver_fonte_local(episodio.url_fonte)

    destino = caminho_raw(
        config.media_root, anime.slug, episodio.numero, episodio.tipo, episodio.versao
    )
    baixado = await baixar_com_fallback_de_site(
        sessionmaker, config, anime=anime, episodio=episodio, destino=destino
    )
    return resolver_fonte_local(str(baixado))


def resolver_fonte_local(caminho: str) -> Path:
    """Confere que `caminho` aponta para um arquivo de mídia local válido.

    Levanta `FonteInvalida` se o caminho não for absoluto, não existir, não for
    um arquivo regular, não for legível ou estiver vazio.
    """
    caminho_path = Path(caminho)

    if not caminho_path.is_absolute():
        raise FonteInvalida(f"caminho de fonte não é absoluto: {caminho}")
    if not caminho_path.exists():
        raise FonteInvalida(f"arquivo de fonte não existe: {caminho}")
    if not caminho_path.is_file():
        raise FonteInvalida(f"caminho de fonte não é um arquivo: {caminho}")
    if not os.access(caminho_path, os.R_OK):
        raise FonteInvalida(f"arquivo de fonte não é legível: {caminho}")
    if caminho_path.stat().st_size <= 0:
        raise FonteInvalida(f"arquivo de fonte está vazio: {caminho}")

    return caminho_path

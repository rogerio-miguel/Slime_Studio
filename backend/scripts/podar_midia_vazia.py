"""Poda de uma vez as pastas de mídia vazias herdadas de remoções antigas.

Antes de `core.midia.podar_diretorios_do_anime` passar a rodar no ponto de
convergência (`api/servicos/catalogo.py::remover_arquivos_do_episodio`), apagar
um episódio (ou liberar seus arquivos) removia o conteúdo mas deixava a árvore
de diretórios (`hls/<slug>/<episodio>/<qualidade>`, `raw/<slug>`) vazia e órfã
em disco. Este script varre `MEDIA_ROOT/hls` e `MEDIA_ROOT/raw` de baixo para
cima e remove todo diretório vazio abaixo dessas raízes, em qualquer
profundidade — uma qualidade vazia deixa o episódio vazio, que deixa o slug
vazio, e todos caem na mesma passada.

Idempotente e só-vazio: usa `Path.rmdir()`, que nunca remove diretório com
conteúdo. Rodar de novo em seguida é um no-op.

Uso (a partir de `backend/`):
    uv run python -m scripts.podar_midia_vazia
"""

import logging
import os
from pathlib import Path

from core.config import carregar_config

logger = logging.getLogger(__name__)


def _remover_se_vazio(diretorio: Path) -> bool:
    """`True` se removeu; `False` se o diretório não existe ou não está vazio
    (ambos `OSError` — casos esperados numa varredura bottom-up)."""
    try:
        diretorio.rmdir()
    except OSError:
        return False
    logger.info("removido: %s", diretorio)
    return True


def podar(media_root: Path) -> int:
    """Remove, bottom-up, todo diretório vazio sob `hls/` e `raw/` (as raízes em
    si nunca são removidas). `os.walk(topdown=False)` entrega os filhos antes do
    pai, então esvaziar uma folha faz o pai cair na mesma varredura."""
    removidos = 0
    for base in ("hls", "raw"):
        base_dir = media_root / base
        if not base_dir.is_dir():
            continue
        for dirpath, _, _ in os.walk(base_dir, topdown=False):
            diretorio = Path(dirpath)
            if diretorio != base_dir and _remover_se_vazio(diretorio):
                removidos += 1
    return removidos


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    media_root = carregar_config().media_root
    total = podar(media_root)
    print(f"pastas vazias removidas: {total}")


if __name__ == "__main__":
    main()

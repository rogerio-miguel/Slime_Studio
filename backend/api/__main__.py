"""Entry point do processo API (ESPECIFICACAO.md §2.1/§5) — espelha
`worker/__main__.py`: carrega `Config`, monta a app via `criar_app` e sobe o
uvicorn. Processo separado do worker — comunicam só via a tabela `Job`.
"""

import logging
import os

import uvicorn

from api.main import criar_app
from core.config import carregar_config


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    # Banco, mídia e logs criados por este processo ficam legíveis só pelo dono.
    os.umask(0o077)
    app = criar_app(carregar_config())
    uvicorn.run(app, host="127.0.0.1", port=8000, server_header=False)


if __name__ == "__main__":
    main()

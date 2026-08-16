"""Entry point do processo API (ESPECIFICACAO.md §2.1/§5) — espelha
`worker/__main__.py`: carrega `Config`, monta a app via `criar_app` e sobe o
uvicorn. Processo separado do worker — comunicam só via a tabela `Job`.
"""

import logging

import uvicorn

from api.main import criar_app
from core.config import carregar_config


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    app = criar_app(carregar_config())
    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()

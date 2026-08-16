"""Camada de serviço da API — regra de verdade (criação de job, remoção com
arquivos, resolução de caminho de mídia). Não importa `fastapi`: recebe
`sessionmaker`/`Config`, devolve dataclass/dict ou levanta erro de
`core/erros.py` (CLAUDE.md §1, regra de dependência)."""

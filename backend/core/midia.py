"""Convenção de caminho do diretório HLS de um episódio (ESPECIFICACAO.md §3D/§4).

Função pura (sem I/O, sem subprocess) — mora aqui, fora de `worker/`, porque
`api/servicos/catalogo.py` precisa do mesmo caminho para apagar o diretório ao
remover um episódio, e API/worker só podem se comunicar via a tabela `Job`
(CLAUDE.md §2) — `api/` nunca importa de `worker/`.
"""

from pathlib import Path

from core.enums import TipoEpisodio, VersaoEpisodio


def diretorio_do_episodio(
    media_root: Path,
    anime_slug: str,
    numero: int,
    tipo: TipoEpisodio,
    versao: VersaoEpisodio,
) -> Path:
    nome_pasta = f"{numero:03d}-{tipo.value}-{versao.value}"
    return media_root / "hls" / anime_slug / nome_pasta

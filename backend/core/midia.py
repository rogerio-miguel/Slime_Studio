"""Convenções de caminho de mídia de anime/episódio (ESPECIFICACAO.md §3D/§4) e
poda dos diretórios de anime que ficaram vazios.

`diretorio_do_episodio`/`diretorio_do_anime` são funções puras (só montam
`Path`, sem I/O) — moram aqui, fora de `worker/`, porque
`api/servicos/catalogo.py` precisa do mesmo caminho para apagar o diretório ao
remover um episódio, e API/worker só podem se comunicar via a tabela `Job`
(CLAUDE.md §2) — `api/` nunca importa de `worker/`.

`podar_diretorios_do_anime` é a exceção que toca o filesystem: chamada no mesmo
ponto de convergência, remove os diretórios de nível de anime só quando já estão
vazios (nunca recursivo).
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


def diretorio_do_anime(media_root: Path, slug: str) -> tuple[Path, Path]:
    """Os dois diretórios de nível de anime, nesta ordem: `hls/<slug>` (raiz das
    subpastas de episódio empacotadas) e `raw/<slug>` (arquivos `.mkv` brutos)."""
    return media_root / "hls" / slug, media_root / "raw" / slug


def podar_diretorios_do_anime(media_root: Path, slug: str) -> None:
    """Remove `hls/<slug>` e `raw/<slug>` se — e somente se — estiverem vazios.

    `Path.rmdir()` levanta `OSError` tanto quando o diretório ainda tem conteúdo
    quanto quando não existe: os dois são casos esperados aqui (a poda roda a
    cada episódio removido e só "vinga" quando a última subpasta sai), não erro.
    Melhor esforço, igual a `remover_arquivos_do_episodio`: um diretório que
    resista (permissão, I/O) fica para limpeza manual em vez de abortar a
    remoção — por isso o `except` engloba `OSError`, mas nada além dele."""
    for diretorio in diretorio_do_anime(media_root, slug):
        try:
            diretorio.rmdir()
        except OSError:
            pass

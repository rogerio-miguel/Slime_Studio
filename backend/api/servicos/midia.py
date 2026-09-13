"""Resolução de caminho de mídia HLS (episódio -> arquivo em disco), com guarda
contra path traversal (ESPECIFICACAO.md §5, Passo 3 do plano da Fase 3).

Só cobre a rota catch-all (variante `index.m3u8`, segmentos `seg_*.ts` e o
sprite `storyboard.jpg`, opcional) — o master manifest (`Episodio.hls_path`,
dado do servidor, não input do usuário) é resolvido direto em
`api/rotas/episodios.py`, sem passar por aqui.
"""

from pathlib import Path

from core.config import Config
from core.erros import ErroSlimeStudio
from models.episodio import Episodio

# .jpg: storyboard.jpg (worker/pipeline/storyboard.py)
_SUFIXOS_PERMITIDOS = {".m3u8", ".ts", ".jpg"}


class RecursoDeMidiaInvalido(ErroSlimeStudio):
    """Requisição de recurso HLS fora do diretório do episódio, ou extensão não
    permitida — nunca deveria acontecer via uso normal do player, só via URL
    manipulada; a rota mapeia para 404 (não vaza detalhe do path real)."""


def resolver_caminho(config: Config, episodio: Episodio, recurso: str) -> Path:
    """`Episodio.hls_path` é relativo a `MEDIA_ROOT` e aponta para o master
    manifest do episódio (`<dir>/master.m3u8`); `recurso` é o nome de arquivo
    pedido dentro do MESMO diretório (variante `index.m3u8` ou segmento
    `seg_%05d.ts`, referenciados pelo master relativamente; ou
    `storyboard.jpg`, pedido direto pelo frontend — não referenciado por
    nenhum manifesto)."""
    if episodio.hls_path is None:
        raise RecursoDeMidiaInvalido(f"episódio {episodio.id} não tem HLS empacotado")

    diretorio = (config.media_root / episodio.hls_path).resolve().parent
    candidato = (diretorio / recurso).resolve()

    if not candidato.is_relative_to(diretorio):
        raise RecursoDeMidiaInvalido(f"recurso fora do diretório do episódio: {recurso!r}")
    if candidato.suffix not in _SUFIXOS_PERMITIDOS:
        raise RecursoDeMidiaInvalido(f"extensão não permitida: {recurso!r}")
    if not candidato.is_file():
        raise RecursoDeMidiaInvalido(f"recurso não encontrado: {recurso!r}")

    return candidato

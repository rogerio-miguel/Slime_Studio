"""Configuração de runtime do Slime Studio — bootstrap/infraestrutura, não domínio
puro (faz I/O: lê `.env` via `python-dotenv`, cria diretório, sonda gravabilidade,
resolve binários no PATH).

Lê `.env` ancorado na raiz do repositório (nunca no cwd — o worker e a API podem
ser invocados de diretórios diferentes) e resolve os caminhos/ferramentas que o
resto do sistema depende, falhando cedo e explicitamente se algo estiver faltando.
"""

import shutil
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

from core.erros import ErroDeConfiguracao

# backend/core/config.py -> parents[0]=core, [1]=backend, [2]=raiz do repo.
_RAIZ_REPO = Path(__file__).resolve().parents[2]

_NOME_ARQUIVO_LOCK = "worker.lock"


@dataclass(frozen=True, slots=True)
class Config:
    database_url: str
    media_root: Path
    raiz_repo: Path
    ffmpeg: Path
    ffprobe: Path
    caminho_lock: Path
    # Token do TMDB (provedor padrão de arte — capa/banner/thumb de episódio,
    # ver PLANO_ARTE_TMDB.md). Default `None` obrigatório: ausência é DEGRADE
    # pra AniList (D2 do plano), nunca `ErroDeConfiguracao` — ao contrário de
    # `database_url`/`ffmpeg`/`ffprobe` acima, que são hard-fail. Campo NOVO
    # no fim da dataclass pra não quebrar as construções por keyword já
    # existentes em `tests/conftest.py` e outros arquivos de teste.
    tmdb_token: str | None = None


def carregar_config(env_path: Path | None = None) -> Config:
    """Carrega e valida a configuração. Levanta `ErroDeConfiguracao` com mensagem
    explícita se algo obrigatório faltar ou for inválido."""
    caminho_env = env_path if env_path is not None else _RAIZ_REPO / ".env"
    valores = dict(dotenv_values(caminho_env)) if caminho_env.exists() else {}

    database_url = valores.get("DATABASE_URL")
    if not database_url:
        raise ErroDeConfiguracao(
            f"DATABASE_URL não definida (esperada em {caminho_env})."
        )

    media_root = _resolver_media_root(valores.get("MEDIA_ROOT") or "./media")
    ffmpeg = _localizar_ferramenta("ffmpeg")
    ffprobe = _localizar_ferramenta("ffprobe")
    caminho_lock = _extrair_caminho_banco(database_url).parent / _NOME_ARQUIVO_LOCK
    tmdb_token = valores.get("TMDB_READ_ACCESS_TOKEN") or None

    return Config(
        database_url=database_url,
        media_root=media_root,
        raiz_repo=_RAIZ_REPO,
        ffmpeg=ffmpeg,
        ffprobe=ffprobe,
        caminho_lock=caminho_lock,
        tmdb_token=tmdb_token,
    )


def _resolver_media_root(valor: str) -> Path:
    caminho = Path(valor)
    if not caminho.is_absolute():
        caminho = _RAIZ_REPO / caminho
    caminho = caminho.resolve()

    caminho.mkdir(parents=True, exist_ok=True)
    if not _diretorio_gravavel(caminho):
        raise ErroDeConfiguracao(f"MEDIA_ROOT não é gravável: {caminho}")
    return caminho


def _diretorio_gravavel(caminho: Path) -> bool:
    sonda = caminho / ".escrita_sonda"
    try:
        sonda.touch()
    except OSError:
        return False
    else:
        sonda.unlink()
        return True


def _localizar_ferramenta(nome: str) -> Path:
    encontrado = shutil.which(nome)
    if not encontrado:
        raise ErroDeConfiguracao(f"'{nome}' não encontrado no PATH.")
    return Path(encontrado)


def _extrair_caminho_banco(database_url: str) -> Path:
    """Extrai o caminho de arquivo de uma `DATABASE_URL` sqlite (`sqlite[+driver]://...`).

    Convenção sqlite: `sqlite:///relativo.db` (3 barras, relativo) vs.
    `sqlite:////absoluto.db` (4 barras, absoluto).
    """
    if "://" not in database_url:
        raise ErroDeConfiguracao(f"DATABASE_URL inválida: {database_url!r}")
    sufixo = database_url.split("://", 1)[1]
    if sufixo.startswith("//"):
        caminho = Path(sufixo[1:])  # absoluto: mantém a barra restante
    else:
        caminho = Path(sufixo.lstrip("/"))  # relativo ao cwd de invocação
        if not caminho.is_absolute():
            caminho = _RAIZ_REPO / caminho
    return caminho

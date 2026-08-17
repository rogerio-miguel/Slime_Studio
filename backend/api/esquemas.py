"""Modelos Pydantic (I/O HTTP) — só `api/rotas/` importa este módulo;
`api/servicos/` não conhece Pydantic nem `fastapi` (regra de dependência da
Clean Architecture, CLAUDE.md §1).
"""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from core.enums import StatusEpisodio, StatusJob, TipoEpisodio, VersaoEpisodio

# --- jobs (api/rotas/jobs.py) ---


class CriarJobLocalRequest(BaseModel):
    modo: Literal["local"]
    anime: str
    numero: int
    tipo: TipoEpisodio
    versao: VersaoEpisodio = VersaoEpisodio.LEGENDADO
    # Sem validação de existência/formato aqui (mesmo comportamento de
    # `scripts/enfileirar_local.py` hoje) — o worker é quem valida o arquivo de
    # fato (`worker/pipeline/validacao.py::sondar`, levanta `FonteInvalida`).
    # Aceitável porque o app é local-only por natureza (uso pessoal, sem
    # múltiplos usuários), não input de usuário final não confiável.
    caminho_local: str
    titulo_episodio: str | None = None
    ano: int | None = None
    duracao_esperada_s: int | None = None


class CriarJobSiteRequest(BaseModel):
    modo: Literal["site"]
    anime_id: int
    numero: int
    tipo: TipoEpisodio
    versao: VersaoEpisodio = VersaoEpisodio.LEGENDADO
    duracao_esperada_s: int | None = None


CriarJobRequest = Annotated[
    CriarJobLocalRequest | CriarJobSiteRequest, Field(discriminator="modo")
]


class JobCriadoSaida(BaseModel):
    job_id: int


class JobSaida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    episodio_id: int
    status: StatusJob
    etapa_atual: str | None
    progresso_pct: int
    erro_msg: str | None
    tentativas: int
    duracao_esperada_s: int | None
    criado_em: datetime
    iniciado_em: datetime | None
    finalizado_em: datetime | None
    heartbeat_em: datetime | None


class CancelarJobSaida(BaseModel):
    status: Literal["cancelado", "cancelando"]


class RetryJobSaida(BaseModel):
    job_id: int


# --- animes (api/rotas/animes.py) ---


class CriarAnimeRequest(BaseModel):
    titulo: str
    ano: int | None = None
    # Metadados de provedor externo (AniList/Kitsu) — opcionais: se vierem
    # preenchidos, persistem direto; se ausentes, `api/servicos/descoberta.py`
    # tenta enriquecer por título em best-effort (ver `api/rotas/animes.py`).
    anilist_id: int | None = None
    kitsu_id: int | None = None
    capa_url: str | None = None
    sinopse: str | None = None


class AnimeSaida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    titulo: str
    slug: str
    ano: int | None
    capa_path: str | None
    criado_em: datetime


class AnimeEmAltaSaida(BaseModel):
    """Item do feed `GET /api/animes/em-alta` (`integrations.base.AnimeEmAlta`)
    já cruzado com o catálogo local — `anime_id` vem preenchido pelo servidor
    quando o anime já está catalogado, `None` caso contrário."""

    titulo_romaji: str
    titulo_ingles: str | None
    capa_url: str | None
    banner_url: str | None
    anilist_id: int | None
    anime_id: int | None


class AnimeDetalheSaida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    titulo: str
    slug: str
    ano: int | None
    capa_path: str | None
    sinopse: str | None
    criado_em: datetime


class ConfirmarFonteRequest(BaseModel):
    dominio: str
    identificador: str
    titulo_exibicao: str
    url: str


class ResultadoBuscaFonteSaida(BaseModel):
    """Item de `GET /api/animes/buscar-fontes` — candidato ainda não catalogado
    localmente, encontrado ao vivo em um site de extração (`extractors.base.
    ResultadoBusca`); `dominio` identifica de qual site veio, necessário pra
    depois confirmar a fonte (`POST /api/admin/animes/{id}/fontes/confirmar`)."""

    titulo_exibicao: str
    identificador: str
    url: str
    dominio: str


class EpisodioRemotoSaida(BaseModel):
    """Posição na fonte remota (site) — `extractors.base.EpisodioRemoto` só carrega
    `numero`/`url`, sem título; a grade prontos/não capturados do frontend cruza
    isto com `EpisodioSaida.numero` de `GET /api/animes/{id}/episodios`."""

    model_config = ConfigDict(from_attributes=True)

    numero: int


# --- episódios (api/rotas/episodios.py) ---


class AtualizarEpisodioRequest(BaseModel):
    numero: int | None = None
    tipo: TipoEpisodio | None = None
    versao: VersaoEpisodio | None = None


class EpisodioSaida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    anime_id: int
    numero: int
    titulo: str | None
    tipo: TipoEpisodio
    versao: VersaoEpisodio
    status: StatusEpisodio
    hls_path: str | None
    renditions_disponiveis: list[str] | None
    duracao_s: int | None
    assistido_em: datetime | None
    criado_em: datetime


# --- sites (api/rotas/sites.py) ---


class SiteSaida(BaseModel):
    dominio: str
    falhas_consecutivas: int
    degradado: bool
    cooldown_ate: datetime
    ultima_falha_em: datetime | None
    ultimo_erro: str | None


# --- saúde/operação (api/rotas/saude.py) ---


class SaudeSaida(BaseModel):
    status: Literal["ok"]


class DiscoSaida(BaseModel):
    total_bytes: int
    livre_bytes: int
    usado_por_midia_bytes: int


class WorkerSaida(BaseModel):
    vivo: bool

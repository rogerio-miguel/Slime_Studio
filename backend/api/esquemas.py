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
    # Derivado das linhas de `FonteAnime` já mapeadas pro anime (não é
    # live-probe) — ver `api/rotas/animes.py::obter_anime`. Qualquer linha
    # `NAO_DIFERENCIADA` habilita as duas versões; sem nenhuma linha ainda
    # (fonte nunca resolvida), também as duas, otimista.
    versoes_disponiveis: list[VersaoEpisodio]
    # Versão da linha de `FonteAnime` com o `resolvido_em` mais recente pro
    # anime — reflete a última troca de fonte CONFIRMADA pelo usuário (via
    # "Trocar fonte"), mesmo quando ainda não gerou nenhum episódio local
    # capturado nessa versão. `NAO_DIFERENCIADA` vira `VersaoEpisodio.
    # DESCONHECIDA` (mesma conversão de `api/servicos/jobs.py::
    # versao_episodio_da_fonte`). `None` quando o anime não tem nenhuma
    # linha em `FonteAnime` ainda.
    versao_confirmada_mais_recente: VersaoEpisodio | None


class ConfirmarFonteRequest(BaseModel):
    dominio: str
    identificador: str
    titulo_exibicao: str
    url: str
    # Round-trip do `versao` que o frontend recebeu em `ResultadoBuscaFonteSaida`
    # pro candidato escolhido — o servidor não confia cegamente nisso, sempre
    # rederiva via `extractors.versao.inferir_versao` e loga divergência
    # (`api/rotas/animes.py::confirmar_fonte_do_anime`).
    versao: VersaoEpisodio | None = None


class ResultadoBuscaFonteSaida(BaseModel):
    """Item de `GET /api/animes/buscar-fontes` — candidato ainda não catalogado
    localmente, encontrado ao vivo em um site de extração (`extractors.base.
    ResultadoBusca`); `dominio` identifica de qual site veio, necessário pra
    depois confirmar a fonte (`POST /api/admin/animes/{id}/fontes/confirmar`)."""

    titulo_exibicao: str
    identificador: str
    url: str
    dominio: str
    # Preenchida direto do parsing (AnimesDrive) ou por enriquecimento
    # best-effort via metadado de provedor externo (AnimeFire, que não expõe
    # imagem na busca — `api/servicos/busca.py::enriquecer_capas`). `None`
    # quando nenhuma das duas fontes achou capa.
    capa_url: str | None = None
    # `None` quando o site não diferencia versão ou nenhum marcador foi
    # detectado neste candidato específico (`extractors.base.ResultadoBusca.versao`).
    versao: VersaoEpisodio | None = None
    # Capability do site que resolveu este candidato (`ExtratorDeSite.diferencia_versao`)
    # — a UI usa isso pra decidir se oferece a escolha legendado/dublado.
    site_diferencia_versao: bool = False


class FonteConsultadaSaida(BaseModel):
    """Status de uma fonte consultada em `GET /api/animes/buscar-fontes` — inclui
    fontes indisponíveis (cooldown ou erro), não só as que responderam
    candidatos, pra UI distinguir "não achei nada" de "não consegui nem
    tentar" (CLAUDE.md §4, erro nunca silencioso)."""

    dominio: str
    indisponivel: bool
    motivo: str | None = None


class BuscaEmFontesSaida(BaseModel):
    """Corpo de `GET /api/animes/buscar-fontes`: candidatos achatados de todas as
    fontes disponíveis (`resultados`) + status de cada fonte consultada,
    disponível ou não (`fontes`)."""

    resultados: list[ResultadoBuscaFonteSaida]
    fontes: list[FonteConsultadaSaida]
    # Preenchido quando a busca com o termo digitado veio vazia e os resultados
    # acima vieram de um título alternativo do mesmo anime (romaji/inglês,
    # via provedor de metadados). `None` = resultados do termo digitado.
    termo_alternativo: str | None = None


class EpisodioRemotoSaida(BaseModel):
    """Posição na fonte remota (site) — `extractors.base.EpisodioRemoto` não expõe
    `url` aqui (uso só server-side); a grade prontos/não capturados do frontend
    cruza `numero` com `EpisodioSaida.numero` de `GET /api/animes/{id}/episodios`.
    `numero` é `None` quando `rotulo` não é puramente numérico (ex. "Especial")
    — o episódio ainda aparece na listagem, só não é capturável ainda."""

    model_config = ConfigDict(from_attributes=True)

    rotulo: str
    numero: int | None


class EpisodiosRemotosSaida(BaseModel):
    """Corpo de `GET /api/admin/animes/{id}/episodios-remotos`: `dominio` expõe
    qual site resolveu a lista de episódios abaixo — sem isto o usuário não tinha
    como notar quando a fonte "errada" (com contagem divergente) foi a
    resolvida, causa mais provável de divergência de contagem de episódios."""

    dominio: str
    episodios: list[EpisodioRemotoSaida]


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

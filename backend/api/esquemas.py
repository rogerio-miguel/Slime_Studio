"""Modelos Pydantic (I/O HTTP) — só `api/rotas/` importa este módulo;
`api/servicos/` não conhece Pydantic nem `fastapi` (regra de dependência da
Clean Architecture, CLAUDE.md §1).
"""

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, NonNegativeInt

from core.enums import StatusEpisodio, StatusJob, StatusLancamento, TipoEpisodio, VersaoEpisodio

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
    # Arte horizontal (`bannerImage` da AniList) e cor dominante da capa
    # (`coverImage.color`) do item do feed da Home — persistem direto quando
    # vêm no payload (mesmo caminho de `capa_url`).
    banner_url: str | None = None
    capa_cor: str | None = None
    # Gêneros crus (`genres` da AniList) do item do feed "em alta" — a
    # materialização repassa e persiste direto (mesmo curto-circuito de
    # `capa_url`/`banner_url`); tradução pt-BR é no frontend.
    generos: list[str] | None = None


class AnimeSaida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    titulo: str
    slug: str
    ano: int | None
    capa_path: str | None
    # 1:1 com as colunas homônimas de `Anime` (via `model_validate`). Default
    # para não quebrar a resposta de animes sem metadado visual ainda.
    banner_path: str | None = None
    capa_cor: str | None = None
    criado_em: datetime
    # Detector de episódios novos (badge no catálogo) e rótulo de estreia do card
    # de bookmark no catálogo (rota `/animes` do frontend). Todos com default:
    # animes sem refresh de lançamento têm as colunas NULL e a resposta não pode
    # quebrar. `status_lancamento`, `proximo_ep_em` e `estreia_em` saem 1:1 das
    # colunas homônimas de `Anime` (via `model_validate`); `episodios_novos` e
    # `tem_episodios` são derivados (não são colunas) e injetados na rota —
    # `episodios_novos` por `api/servicos/lancamentos.py::episodios_novos`
    # (gate: só `status_lancamento == EM_LANCAMENTO`),
    # `tem_episodios` por `api/servicos/catalogo.py::ids_com_episodios`.
    # `proximo_ep_em` e `estreia_em` alimentam o rótulo de estreia do card de
    # bookmark (e `proximo_ep_em`, a tagline do carrossel) — não o detector de badge.
    status_lancamento: StatusLancamento | None = None
    episodios_novos: int = 0
    proximo_ep_em: datetime | None = None
    estreia_em: date | None = None
    tem_episodios: bool = False


class AnimeEmAltaSaida(BaseModel):
    """Item do feed `GET /api/animes/em-alta` (`integrations.base.AnimeEmAlta`)
    já cruzado com o catálogo local — `anime_id` vem preenchido pelo servidor
    quando o anime já está catalogado, `None` caso contrário.

    `ano_estreia`/`generos`/`capa_cor` e o trio de lançamento
    (`status_lancamento`, `proximo_ep_numero`, `proximo_ep_em`) alimentam o
    carrossel da Home — `capa_cor` é o fundo do slide sem `banner_url`, o resto
    a tagline. Todos com default: só o AniList preenche ano/gêneros/cor (Kitsu
    deixa nos defaults) e nem todo item do feed traz bloco de lançamento — a
    resposta não pode quebrar para item sem esses dados. `status_lancamento` sai
    1:1 do enum de domínio, igual a `AnimeSaida`."""

    titulo_romaji: str
    titulo_ingles: str | None
    capa_url: str | None
    banner_url: str | None
    anilist_id: int | None
    anime_id: int | None
    ano_estreia: int | None = None
    generos: list[str] = []
    # Cor dominante da capa (`coverImage.color` da AniList) — fundo do slide do
    # carrossel da Home quando não há `banner_url`. Só o AniList preenche.
    capa_cor: str | None = None
    status_lancamento: StatusLancamento | None = None
    proximo_ep_numero: int | None = None
    proximo_ep_em: datetime | None = None


class AnimeDetalheSaida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    titulo: str
    slug: str
    ano: int | None
    capa_path: str | None
    # Hero da página do anime: `banner_path` é a arte horizontal; quando nula, o
    # frontend usa `capa_cor` como fundo do fallback (mesma cor do carrossel da
    # Home). Preenchidos explicitamente em `obter_anime`, 1:1 com as colunas.
    banner_path: str | None
    capa_cor: str | None
    # Gêneros crus da AniList (tradução pt-BR é no frontend). Default `[]`:
    # preenchido explicitamente em `obter_anime` como `anime.generos or []`,
    # animes sem esse metadado ainda não podem quebrar a resposta.
    generos: list[str] = []
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
    # Estado de lançamento da AniList (1:1 com a coluna homônima).
    status_lancamento: StatusLancamento | None = None


# Parâmetro `escopo` de `GET /api/animes/buscar-fontes` (D-B1,
# PLANO_PADRONIZACAO_FONTES.md — Fase B). `Literal` (não `str` + `if` manual)
# pra ganhar 422 de graça do FastAPI/Pydantic num valor inválido (caso de
# borda 1 da Fase B). `"padrao"`: motor sequencial por site da Fase A (Home).
# `"todas"`: motor paralelo × variantes da fatia 1 de `extractors/busca/servico.py`
# (diálogo "Trocar fonte").
EscopoBusca = Literal["padrao", "todas"]


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
    # imagem na busca — `api/servicos/capas.py::enriquecer_capas`). `None`
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
    # Preenchido quando os resultados vieram de um termo diferente do digitado
    # — variante de regex reduzida (`extractors.busca.termos.variantes_de_busca`, ex.
    # sem subtítulo/sufixo de temporada) ou, se nenhuma variante achou nada,
    # título alternativo do mesmo anime (romaji/inglês, via provedor de
    # metadados). `None` = resultados vieram do termo exatamente digitado.
    # Exceção: sempre `None` quando `escopo=todas` — com cada site esgotando
    # sua própria escada de variantes em paralelo (INV-1',
    # `buscar_em_todas_as_fontes_com_titulos_alternativos` em
    # `api/servicos/busca.py`) não há uma única variante/rodada vencedora pra
    # reportar, ver docstring de lá pro racional completo.
    termo_alternativo: str | None = None
    # Preenchido quando quem respondeu não foi o site padrão (índice 0 de
    # `extractors.registro.EXTRATORES`, ex. AnimeFire) — distingue "achei com
    # um termo diferente no MESMO site" de "tive que cair pra OUTRO site",
    # sinal que a Home usa pro aviso de resultado alternativo.
    # Exceção: sempre `None` quando `escopo=todas`, mesmo motivo do campo
    # acima — ver `api/servicos/busca.py::
    # buscar_em_todas_as_fontes_com_titulos_alternativos`.
    dominio_alternativo: str | None = None


class EpisodioRemotoSaida(BaseModel):
    """Posição na fonte remota (site) — `extractors.base.EpisodioRemoto` não expõe
    `url` aqui (uso só server-side); a grade prontos/não capturados do frontend
    cruza `numero` com `EpisodioSaida.numero` de `GET /api/animes/{id}/episodios`.
    `numero` é `None` quando `rotulo` não é puramente numérico (ex. "Especial")
    — o episódio ainda aparece na listagem, só não é capturável ainda.

    `thumb_url` é a URL crua da thumbnail do episódio na fonte (`None` quando o
    site não expõe) — nunca baixada aqui; o frontend a serve via o proxy
    `GET /api/thumb` (`api/rotas/thumb.py`), que embute o `Referer` de hotlink."""

    model_config = ConfigDict(from_attributes=True)

    rotulo: str
    numero: int | None
    thumb_url: str | None = None


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
    site_origem: str
    # URL da thumbnail do episódio na fonte, gravada na captura a partir de
    # `EpisodioRemoto.thumb_url` (URL string, mesma convenção de `Anime.capa_path`
    # — nunca caminho em disco). Servida ao navegador via `GET /api/thumb`.
    capa_path: str | None = None
    hls_path: str | None
    renditions_disponiveis: list[str] | None
    duracao_s: int | None
    progresso_s: int | None
    assistido_em: datetime | None
    criado_em: datetime


class SalvarProgressoRequest(BaseModel):
    segundos: NonNegativeInt


class ContinuarAssistindoSaida(BaseModel):
    """Item da prateleira "Continuar assistindo" da Inicio —
    `api/servicos/progresso.py::listar_continuar_assistindo` (join
    `Episodio`+`Anime`, já achatado)."""

    episodio_id: int
    anime_id: int
    anime_titulo: str
    # Thumb do EPISÓDIO (`Episodio.capa_path`, não `Anime.capa_path`) — mesma
    # convenção de URL crua servida via `GET /api/thumb` que `EpisodioSaida.
    # capa_path`/`EpisodioRemotoSaida.thumb_url` usam.
    thumb: str | None
    numero: int
    titulo: str | None
    progresso_s: int
    duracao_s: int | None


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

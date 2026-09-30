"""Modelos Pydantic (I/O HTTP) — só `api/rotas/` importa este módulo;
`api/servicos/` não conhece Pydantic nem `fastapi` (regra de dependência da
Clean Architecture, CLAUDE.md §1).
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, NonNegativeInt

from core.enums import StatusEpisodio, StatusJob, StatusLancamento, TipoEpisodio, VersaoEpisodio

# --- jobs (api/rotas/jobs.py) ---


# Só o modo `site` existe na API. O modo `local` (caminho de arquivo arbitrário do
# host, sem allowlist) foi removido: quem enfileira arquivo local usa
# `scripts/enfileirar_local.py`, que fala direto com o catálogo e não é alcançável
# por HTTP.
class CriarJobSiteRequest(BaseModel):
    modo: Literal["site"]
    anime_id: int
    numero: int
    tipo: TipoEpisodio
    versao: VersaoEpisodio = VersaoEpisodio.LEGENDADO
    duracao_esperada_s: int | None = None


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
    # Título em inglês (`title.english` da AniList) do item do feed — persiste
    # em `Anime.titulo_ingles` (só exibição, nunca substitui `Anime.titulo`).
    titulo_ingles: str | None = None
    # `format` cru da AniList do item clicado na busca da Home
    # (`AnimeEmAltaSaida.formato` abaixo) — `None` (padrão, série TV) segue o
    # cadastro de sempre; "MOVIE"/"OVA"/"ONA"/"SPECIAL" grava em `Anime.
    # formato_midia` na criação (`db.catalogo.obter_ou_criar_anime_id`) e
    # desvia a resolução de franquia pra `_aplicar_ancora_de_midia` (só
    # `serie_ancora`, nunca `numero_temporada`) — o item se agrupa no anime
    # original em vez de virar card solto no catálogo.
    formato: str | None = None


class TemporadaIrmaSaida(BaseModel):
    """Uma temporada da mesma franquia (`Anime.serie_ancora` em comum) — item do
    seletor de temporada da página do anime (Fase 5). `numero_temporada` pode ser
    NULL tanto pra série TV sem marcador de título quanto pra filme/OVA/ONA/
    especial (`formato_midia` distingue os dois — front cai no `titulo` como
    rótulo nos dois casos, mas só mostra o selo de formato quando `formato_
    midia` não é `None`). `estreia_em`/`ano` só vêm preenchidos quando este
    objeto é a `proxima_temporada` de `AnimeSaida`/`AnimeDetalheSaida` (aviso
    de estreia no card do catálogo e no hero) — nos itens do seletor são
    sempre `None`. `ano` é o fallback quando a AniList ainda não fechou a data
    completa: o aviso vira "Nª temporada estreia em 2026" (mesma degradação de
    `CartaoDeEstreia`). Definida ANTES de `AnimeSaida`/`AnimeDetalheSaida`
    porque as duas a referenciam em `proxima_temporada` — Pydantic resolve o
    tipo na ordem de definição do módulo, não por forward reference
    automático."""

    id: int
    numero_temporada: int | None
    titulo: str
    estreia_em: date | None = None
    ano: int | None = None
    formato_midia: str | None = None
    # Total declarado pela AniList (`Anime.total_episodios_anilist`, mesma
    # origem de `AnimeSaida.total_episodios_anilist`/`AnimeEmAltaSaida.
    # total_episodios`) — NÃO é progresso de captura local
    # (`AnimeSaida.episodios_atuais`, que mede até onde o usuário já baixou):
    # uma temporada pode ter só 1 episódio capturado e ainda assim declarar
    # 12 no total, e é o total que o seletor deve mostrar. `None` quando a
    # AniList ainda não fechou a contagem (comum em `nao_lancado`).
    total_episodios: int | None = None


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
    # `True` quando o usuário TERMINOU de ver o anime: a contagem de episódios
    # REGULAR assistidos alcança a contagem da fonte (`api/servicos/
    # lancamentos.py::ids_totalmente_assistidos`). Derivado (não é coluna),
    # injetado na rota. O catálogo (`paginas/Galeria.jsx`) usa pra marcar a tag
    # "Assistido" no card; `False` também pra anime sem nenhum episódio.
    assistido: bool = False
    # Agrupamento por franquia no catálogo (`paginas/Galeria.jsx`, Fase 5) — 1:1
    # com as colunas homônimas de `Anime` via `model_validate`, mesmo default
    # nullable do resto (animes antigos têm as colunas NULL). `serie_ancora` é um
    # `anilist_id` da T1 (não um `Anime.id` local, pode apontar pra fora do
    # catálogo): o front agrupa por ele, com fallback pro slug do título sem
    # marcador de temporada quando NULL. `numero_temporada` escolhe o card
    # representante do grupo (a maior temporada).
    serie_ancora: int | None = None
    numero_temporada: int | None = None
    # Total de episódios da temporada segundo a AniList (`Media.episodes`) — 1:1
    # com a coluna homônima via `model_validate`, mesmo default nullable do
    # resto (título antigo na AniList, ou refresh de lançamento nunca rodou).
    # Fallback de `episodios_atuais` abaixo quando a sondagem da fonte real
    # ainda não rodou pro anime.
    total_episodios_anilist: int | None = None
    # "Quantos episódios tem AGORA", pro card de catálogo (`components/
    # AnimeCard.jsx`, tag "Tn EP.n") — não é coluna, é derivado e injetado na
    # rota (`api/rotas/animes.py::listar_animes`): `max(maior número de
    # episódio já capturado localmente, episodios_na_fonte)`. Mesma dupla fonte
    # de `episodios_novos` (`api/servicos/lancamentos.py`), só que aqui não é
    # uma DIFERENÇA, é o maior valor conhecido — aproxima o que a página do
    # anime mostra (`linhas.length`, união local+remoto ao vivo,
    # `PaginaDoAnime.jsx`) sem repetir scraping por card na grade do catálogo.
    # `None` só quando as duas fontes estão vazias (nunca sondado e nada
    # capturado) — o front cai pro total da AniList acima nesse caso.
    episodios_atuais: int | None = None
    # Gêneros crus da AniList (tradução pt-BR é no frontend, `inicio/generos.js`)
    # — 1:1 com a coluna homônima via `model_validate`, igual a `status_lancamento`
    # acima. Nullable (não normalizado a `[]` aqui): animes sem esse metadado
    # ainda têm a coluna NULL, e `model_validate` valida o atributo bruto — um
    # default `[]` sem `| None` quebraria a resposta pra esses animes. Alimenta o
    # filtro por gênero do catálogo (`paginas/Galeria.jsx`).
    generos: list[str] | None = None
    # 1:1 com a coluna homônima via `model_validate`, mesmo default de
    # `banner_path`/`capa_cor` acima (animes sem metadado ainda têm a coluna
    # NULL). Alimenta o parágrafo de descrição dos "destaques grandes" da Home
    # (`inicio/DestaqueGrande.jsx`) sem precisar de um request por item —
    # `AnimeDetalheSaida` (GET /api/animes/{id}) já expõe o mesmo campo.
    sinopse: str | None = None
    # Derivado, injetado na rota (`api/rotas/animes.py::listar_animes`) — badge
    # "Dublado"/"Legendado" do card (`components/AnimeCard.jsx`). `None` sem
    # nenhuma `FonteAnime` mapeada ainda; `desconhecida` quando a fonte mapeada
    # não diferencia versão (`VersaoDeFonte.NAO_DIFERENCIADA`) — nenhum dos dois
    # rótulos aparece nesse caso. Mesmo campo/semântica de
    # `AnimeDetalheSaida.versao_confirmada_mais_recente` abaixo.
    versao_confirmada_mais_recente: VersaoEpisodio | None = None
    # Aviso "Nª temporada estreia em ..." no card do catálogo — derivado,
    # injetado na rota a partir do mesmo agrupamento de franquia usado no hero
    # da página do anime (`api/rotas/animes.py::_agrupar_franquias` +
    # `_temporadas_e_proxima`, reaproveitado por `obter_anime` abaixo).
    # `estreia_em`/`ano` vêm preenchidos aqui (ver docstring de
    # `TemporadaIrmaSaida`); `None` quando não há irmã `nao_lancado` prevista.
    proxima_temporada: TemporadaIrmaSaida | None = None


class AquecimentoCatalogoSaida(BaseModel):
    """Corpo de `GET /api/animes/aquecimento-em-andamento` — peek síncrono (sem
    I/O) nas duas cargas fire-and-forget que `?aquecer=true` agenda
    (`api/servicos/sondagem.py::agendar_sondagens` e `api/servicos/
    descoberta.py::agendar_refreshs_do_catalogo`). A Galeria
    (`paginas/Galeria.jsx`) usa esta flag pra saber se vale reconsultar
    `GET /api/animes` de novo em alguns segundos — mesmo papel de
    `ContinuarAssistindoRespostaSaida.sondagem_em_andamento`, só que num
    endpoint próprio (não dá pra pendurar a flag na lista crua de `AnimeSaida`
    sem quebrar o contrato que a Home também consome sem `?aquecer=true`)."""

    em_andamento: bool


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
    # Total de episódios da temporada (`LancamentoDeAnime.total_episodios`,
    # mesma origem AniList de `AnimeSaida.total_episodios_anilist`) — item do
    # feed ainda não é catalogado, então não há sondagem de fonte real pra
    # mostrar "quantos tem atualmente" (ver `AnimeSaida.episodios_atuais`); só
    # o total declarado faz sentido aqui. Alimenta a tag "Tn EP.n" do card de
    # catálogo (`components/AnimeCard.jsx`) quando o item vem do feed.
    total_episodios: int | None = None
    # Sinopse (`description` da AniList, sanitizada) — só o feed "em alta" a
    # traz; nos demais feeds (`/buscar`, próxima temporada, fileiras) fica
    # `None`. A Home a usa no bloco de conteúdo do carrossel de destaques.
    sinopse: str | None = None
    # `format` cru da AniList — só a busca livre (`/buscar`) traz hoje
    # (`integrations.base.AnimeEmAlta.formato`); os demais feeds ficam no
    # default `None`. O frontend repassa pra `POST /api/admin/animes`
    # (`CriarAnimeRequest.formato`) quando materializa um item clicado —
    # decide se ele vira temporada normal ou filme/OVA/especial agrupado.
    formato: str | None = None
    # Número do episódio recém-lançado (`integrations.base.AnimeEmAlta.
    # episodio_lancado`) — só o feed `/novos-lancamentos` preenche; os demais
    # ficam no default `None`. Frontend usa pra rotular o card ("EP.N").
    episodio_lancado: int | None = None


class FileiraTematicaSaida(BaseModel):
    """Item de `GET /api/animes/fileiras-tematicas`: uma fileira temática da
    Home (`integrations.registro.FILEIRAS_TEMATICAS`) com seus itens já
    cruzados com o catálogo local. `chave` é o id estável snake_case da
    fileira (ex. "found_family") — o rótulo em pt-BR é responsabilidade do
    frontend, mesma régua já usada para `AnimeSaida.generos`/`AnimeEmAltaSaida.
    generos` (tradução nunca no backend)."""

    chave: str
    itens: list[AnimeEmAltaSaida]


class AnimeDetalheSaida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    titulo: str
    # Título em inglês da AniList (`Anime.titulo_ingles`) — linha secundária do
    # hero (sob `titulo`), como o par título/subtítulo do carrossel. `None`
    # quando o anime não tem `anilist_id` ou o enriquecimento ainda não rodou.
    titulo_ingles: str | None = None
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
    # Seletor de temporada da página do anime (Fase 5). `serie_ancora`/
    # `numero_temporada` saem 1:1 das colunas homônimas; `temporadas` lista as
    # temporadas irmãs (mesmo `serie_ancora`, inclui a própria) já ordenadas por
    # número, para a troca de temporada via navegação de rota (`/anime/:id`).
    # Vazia quando `serie_ancora` é NULL (franquia não resolvida) ou só há uma
    # temporada catalogada — o front esconde o seletor nesses casos.
    serie_ancora: int | None = None
    numero_temporada: int | None = None
    temporadas: list[TemporadaIrmaSaida] = []
    # Temporada seguinte da franquia que ainda não estreou mas já tem data
    # completa (`estreia_em` no futuro) OU pelo menos o ano (`ano >= ano atual`)
    # — alimenta o aviso "Nª temporada estreia em ..." no hero da página do
    # anime, com o ano como fallback quando a AniList ainda não fechou a data.
    # `None` quando não há nenhuma nesse estado. `estreia_em`/`ano` do objeto
    # vêm preenchidos só aqui.
    proxima_temporada: TemporadaIrmaSaida | None = None


class ConfirmarFonteRequest(BaseModel):
    dominio: str
    identificador: str
    titulo_exibicao: str
    url: str
    # Round-trip do `versao` que o frontend recebeu em `ResultadoBuscaFonteSaida`
    # pro candidato escolhido — o servidor rederiva via
    # `extractors.versao.inferir_versao` (e loga divergência) quando o site
    # marca a versão no texto do slug/título; sites que diferenciam por um
    # campo à parte da API sem marcador textual (ex. AnimeFire, `audio`) não
    # têm como ser rederivados assim, e o servidor confia neste round-trip
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
    # `None` quando o site não diferencia versão ou nenhum marcador foi
    # detectado neste candidato específico (`extractors.base.ResultadoBusca.versao`).
    versao: VersaoEpisodio | None = None
    # Capability do site que resolveu este candidato (`ExtratorDeSite.diferencia_versao`)
    # — a UI usa isso pra decidir se oferece a escolha legendado/dublado.
    site_diferencia_versao: bool = False
    # `True` quando este candidato veio pelo degrau de "correspondência incerta"
    # (`extractors/busca/servico.py::buscar_em_com_variantes`): o site não
    # devolveu NENHUM card batendo as referências canônicas do anime, mas este
    # veio de uma busca por um termo que É um nome canônico (não um prefixo
    # curto) — provável acerto sob um título que o provedor de metadados não
    # conhece (ex. só PT-BR). A UI mostra um aviso e deixa o usuário decidir.
    # Homogêneo por fonte: se o site teve ao menos um card validado, todos os
    # candidatos daquela fonte saem com `False`.
    correspondencia_incerta: bool = False


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


class EpisodioRemotoSaida(BaseModel):
    """Posição na fonte remota (site) — `extractors.base.EpisodioRemoto` não expõe
    `url` aqui (uso só server-side); a grade prontos/não capturados do frontend
    cruza `numero` com `EpisodioSaida.numero` de `GET /api/animes/{id}/episodios`.
    `numero` é `None` quando `rotulo` não é puramente numérico (ex. "Especial")
    — o episódio ainda aparece na listagem, só não é capturável ainda.

    `thumb_url` é a URL crua da thumbnail do episódio na fonte (`None` quando o
    site não expõe) — nunca baixada aqui; o frontend a serve via o proxy
    `GET /api/thumb` (`api/rotas/thumb.py`), que embute o `Referer` de hotlink.

    `titulo`/`sinopse` NUNCA vêm da fonte de scraping (nenhum extractor os
    expõe) — só do overlay TMDB best-effort (`api/servicos/fontes.py::
    _sobrepor_stills_de_episodios`, mesmo mecanismo de `thumb_url`); `None`
    quando o TMDB não acha ou não tem tradução pt-BR."""

    model_config = ConfigDict(from_attributes=True)

    rotulo: str
    numero: int | None
    thumb_url: str | None = None
    titulo: str | None = None
    sinopse: str | None = None


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
    # Sinopse do episódio (TMDB, `api/servicos/jobs.py::info_de_episodio`) —
    # persistida na captura, mesma origem/momento de `titulo`. `None` quando o
    # TMDB não achou ou não tem tradução pt-BR, ou o episódio foi capturado
    # antes desta coluna existir (sem backfill).
    sinopse: str | None = None
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
    """Item da prateleira "Continuar assistindo" da Inicio — um por ANIME, não
    por episódio (`api/servicos/progresso.py::listar_continuar_assistindo`).

    `variante` decide o ramo que o frontend renderiza (`LinhaDeEpisodio.jsx`,
    reaproveitado da página do anime):
    - `'pronto'`: episódio existe e está `PRONTO` — link pro player; barra de
      progresso só aparece quando `progresso_s` tem valor (largada nova não
      tem barra, mesmo card).
    - `'processando'`: episódio existe mas o pipeline ainda não terminou (ou
      parou num estado neutro) — card estático/status ao vivo, sem clique.
    - `'capturavel'`: sem episódio `PRONTO` pra este número — clicar dispara a
      captura (`POST /api/admin/jobs/site`, reaproveita `FonteAnime` já
      resolvida). Cobre tanto "nunca capturado" quanto recaptura
      (`LIBERADO`/`FALHOU`) — visualmente idênticos no modo grade, que não
      exibe o verbo da ação.

    `episodio_id`/`status`/`progresso_s`/`duracao_s` só existem quando já há
    uma linha de `Episodio` pro slot (variantes `pronto`/`processando`, e
    `capturavel` no caso de recaptura); `versao` só é necessária pro cliente
    quando `variante == 'capturavel'` (monta o pedido de captura), mas sempre
    que presente reflete a fonte já confirmada do anime.
    """

    anime_id: int
    anime_titulo: str
    numero: int
    variante: str
    episodio_id: int | None
    status: StatusEpisodio | None
    progresso_s: int | None
    duracao_s: int | None
    # Thumb do EPISÓDIO quando existe (`Episodio.capa_path`), senão still TMDB
    # resolvido best-effort pro slot `capturavel` sem episódio ainda, senão a
    # arte do anime — mesma convenção de URL crua servida via `GET /api/thumb`
    # que `EpisodioSaida.capa_path`/`EpisodioRemotoSaida.thumb_url` usam.
    thumb: str | None
    titulo: str | None
    sinopse: str | None
    versao: VersaoEpisodio | None
    # Badge "Novo ep" (`components/CartaoContinuarAssistindo.jsx::BadgeNovo`)
    # — só quando `capturavel` E o episódio nunca existiu E o anime está
    # `EM_LANCAMENTO` E este slot É o episódio mais recente da fonte
    # (`numero == episodios_na_fonte`, 2026-09-19 — sem isso um anime muito
    # atrasado acendia a badge no próximo buraco do atraso, não no lançamento
    # de verdade). Ver docstring completa em `api/servicos/progresso.py`. Um
    # anime encerrado que o usuário só não terminou de acompanhar chega aqui
    # como `capturavel` sem a badge.
    episodio_novo: bool
    # `True` quando `variante == 'capturavel'` sem `Episodio` ainda e a still/
    # título/sinopse TMDB deste slot está em busca de segundo plano (cache-miss
    # em `api/servicos/progresso.py::_aplicar_still_capturavel`) — o card saiu
    # nesta resposta com o fallback de arte do anime. O frontend usa isto pra
    # decidir se vale recarregar a prateleira de novo em alguns segundos, sem
    # precisar de F5 (`paginas/Inicio.jsx`).
    still_pendente: bool = False


class ContinuarAssistindoRespostaSaida(BaseModel):
    """Corpo de `GET /api/episodios/continuar-assistindo` — envelope em vez de
    lista crua pra caber `sondagem_em_andamento` (nível da resposta, não por
    item: um anime cujo próximo episódio ainda não existe some inteiro de
    `itens` até a sondagem em segundo plano confirmar a contagem da fonte,
    `api/servicos/progresso.py::listar_continuar_assistindo`). Mesmo papel de
    `still_pendente` por item, só que pro caso que não tem item pra pendurar a
    flag — `paginas/Inicio.jsx` usa os dois pra decidir se vale reconsultar a
    prateleira de novo em alguns segundos."""

    itens: list[ContinuarAssistindoSaida]
    sondagem_em_andamento: bool


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

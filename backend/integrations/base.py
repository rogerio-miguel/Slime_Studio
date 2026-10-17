"""Contrato Strategy dos provedores de metadados externos de anime (AniList
principal, Kitsu fallback) — espelha `fontes/adaptadores/base.py`.

Domínio puro: sem HTTP, sem SQLAlchemy — só o formato dos dados que
atravessam a fronteira e o contrato abstrato que cada adapter implementa.
`ABC` (não `Protocol`) pela mesma razão de `fontes/adaptadores/base.py`: sem type
checker nos comandos de validação (`ruff` só), então a garantia de contrato
completo precisa vir de `TypeError` na instanciação.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from core.enums import StatusLancamento


@dataclass(frozen=True, slots=True)
class LancamentoDeAnime:
    """Estado de lançamento de um anime num provedor — alimenta o detector de
    episódios novos (`api/servicos/lancamentos.py`).

    Campos nulos são normais: nem todo provedor expõe todos (Kitsu não tem
    next-airing, AniList pode omitir `episodes` em títulos antigos). O detector
    de episódios novos (`api/servicos/lancamentos.py`) trata `proximo_ep_em` no
    futuro como sinal principal de "anime no ar"; sem ele, recai sobre o par
    `status` + `total_episodios` e, se ambos também faltarem, o badge fica 0 —
    erra para baixo, nunca infla.
    """

    status: StatusLancamento | None
    total_episodios: int | None
    proximo_ep_numero: int | None  # número do PRÓXIMO episódio a ir ao ar
    proximo_ep_em: datetime | None  # UTC aware
    # `startDate` completa da AniList (ano+mês+dia); None quando parcial ou ausente.
    estreia_em: date | None = None
    # Ano de estreia (`startDate.year` ou `seasonYear`) — fallback de `estreia_em`.
    ano_estreia: int | None = None


@dataclass(frozen=True, slots=True)
class MetadadosDeAnime:
    """Campos de `models/anime.py::Anime` que o cadastro manual não preenche
    hoje — `integrations/servico.py` decide qual provedor preencheu qual.

    `titulo_romaji` é material de corroboração de match por título (o casamento
    por título é heurístico — quem consome decide se é bom o bastante), **nunca
    persistido**: `Anime.titulo` é o título local, não o do provedor (mesma
    regra de `TitulosDeAnime`). `titulo_ingles` É persistido — em
    `Anime.titulo_ingles`, campo SÓ de exibição (linha secundária do hero da
    página do anime), que nunca substitui o `Anime.titulo` canônico.
    """

    capa_url: str | None
    sinopse: str | None
    anilist_id: int | None
    kitsu_id: int | None
    # Arte horizontal (`bannerImage` da AniList) e cor dominante da capa
    # (`coverImage.color`, ex. "#e4a15d"). AO CONTRÁRIO de `titulo_*` abaixo,
    # estes SÃO persistidos — em `Anime.banner_path`/`Anime.capa_cor`. Só o
    # AniList preenche; o Kitsu não conhece esses campos e deixa nos defaults.
    banner_url: str | None = None
    capa_cor: str | None = None
    # Gêneros crus da AniList (`genres`) e ano de estreia (`seasonYear` /
    # `startDate.year`). Como `banner_url`/`capa_cor` acima, estes SÃO
    # persistidos — em `Anime.generos`/`Anime.ano`. Só o AniList preenche; o
    # Kitsu não conhece esses campos e deixa nos defaults. `ano` aqui fecha o
    # buraco de animes sem bloco de lançamento vivo, que hoje ficam sem
    # `Anime.ano` (só `_aplicar_lancamento_no_anime` o preenche).
    generos: list[str] | None = None
    ano: int | None = None
    lancamento: LancamentoDeAnime | None = None
    titulo_romaji: str | None = None
    # Persistido em `Anime.titulo_ingles` (só exibição — ver docstring).
    titulo_ingles: str | None = None


@dataclass(frozen=True, slots=True)
class TitulosDeAnime:
    """Títulos conhecidos do anime em um provedor — usados só para expandir o
    termo de busca nos sites de extração (`api/servicos/busca.py`), nunca
    persistidos: `Anime.titulo` é o título local, não o do provedor.

    `titulo_nativo` é o título no idioma original (japonês em kanji/kana) e
    `sinonimos` são títulos alternativos que o provedor conhece (abreviações,
    títulos regionais) — só o AniList preenche os dois; o Kitsu deixa nos
    defaults (`None` / tupla vazia). Tupla, não lista, pela mesma imutabilidade
    de `AnimeEmAlta.generos`."""

    titulo_romaji: str | None
    titulo_ingles: str | None
    titulo_nativo: str | None = None
    sinonimos: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AnimeEmAlta:
    """Item de um feed de descoberta de metadados — "lançamentos em alta"
    (`status: RELEASING, sort: TRENDING_DESC` no AniList) e "próxima temporada"
    (`season`/`seasonYear` da estação seguinte) compartilham este formato.

    `anilist_id` é opcional: o provedor de fallback (Kitsu) não tem
    conhecimento do id AniList do item, só o seu próprio.

    `ano_estreia`/`generos`/`capa_cor` só o AniList preenche; no caminho
    degradado (Kitsu) ficam nos defaults — `None` para o ano (não há inteiro que
    signifique "desconhecido"), tupla vazia para os gêneros ("sem gêneros" e
    "lista vazia" são a mesma coisa para quem renderiza), `None` para a cor
    dominante da capa.
    """

    titulo_romaji: str
    titulo_ingles: str | None
    capa_url: str | None
    banner_url: str | None
    anilist_id: int | None
    ano_estreia: int | None = None
    generos: tuple[str, ...] = ()
    lancamento: LancamentoDeAnime | None = None
    # Sinopse (`description` da AniList, já sanitizada) — só o feed "em alta"
    # a traz (`_QUERY_EM_ALTA`); "próxima temporada"/fileiras temáticas/busca
    # não pedem `description` e deixam no default. A Home usa no bloco de
    # conteúdo do carrossel de destaques.
    sinopse: str | None = None
    # Cor dominante da capa (`coverImage.color` da AniList, ex. "#e4a15d") — só o
    # AniList preenche; Kitsu deixa no default `None` (e a própria AniList às
    # vezes devolve `null`). A Home usa como fundo do slide do carrossel quando o
    # item não tem arte horizontal (`banner_url`).
    capa_cor: str | None = None
    # `format` cru da AniList ("MOVIE"/"OVA"/"ONA"/"SPECIAL"/...) SÓ quando
    # `classificacao.eh_serie` trata o item como extra; `None` é série (TV, ONA,
    # ou feed sem `format`). Só `_QUERY_BUSCA_LISTA` e "Relacionados" trazem
    # `format` hoje (ver `Anime.formato_midia` em `models/anime.py`); os demais
    # feeds deixam `None` e o 2º estágio (`servico.formato_se_extra`) reclassifica
    # com as relações. Repassado cru pro payload de `POST /api/admin/animes` sem
    # tradução (pt-BR é responsabilidade do frontend, mesma regra de `generos`).
    formato: str | None = None
    # Número do episódio que motivou a entrada no feed "novos lançamentos"
    # (`AiringSchedule.episode` da AniList, ver `anilist.py::
    # _agenda_para_animes_em_alta`) — só esse feed preenche; os demais deixam
    # no default `None`. A Home usa pra rotular o card ("EP.N") sem imagem
    # específica do episódio (o card usa a capa do anime, não o still).
    episodio_lancado: int | None = None
    # Instante (UTC aware) em que esse episódio foi ao ar (`AiringSchedule.
    # airingAt`) — mesma origem e mesmo feed de `episodio_lancado`. A Home agrupa
    # "Acabou de sair" por dia com isso (Hoje/Ontem/...) e mostra a hora.
    episodio_lancado_em: datetime | None = None
    # `ArteDeAnime.banner_com_titulo_url`, sobreposto por `_com_arte`; `None` quando
    # o TMDB não tem arte com título — o frontend cai no `banner_url`.
    banner_com_titulo_url: str | None = None


@dataclass(frozen=True, slots=True)
class FileiraTematica:
    """Uma fileira temática da Home (`registro.py::FILEIRAS_TEMATICAS`) — par
    chave estável / filtro cru da AniList, mais o TIPO de filtro: `tag`
    (`minimumTagRank`, nicho — ex. "Isekai") ou `genero` (categoria ampla e
    sempre bem populada — ex. "Action"). `anilist.py::listar_fileira_tematica`
    escolhe a query certa a partir daqui."""

    chave: str  # id estável snake_case, usado na rota da API e no rótulo do frontend
    valor: str  # nome cru da tag/gênero na AniList (ex: "Isekai", "Action")
    tipo: Literal["tag", "genero"] = "tag"


@dataclass(frozen=True, slots=True)
class PaginaDeAnimes:
    """Uma página de `ProvedorComDescoberta.listar_descoberta` — os itens e se
    existe página seguinte (a grade da Descobrir carrega mais ao rolar e precisa
    saber quando parar)."""

    itens: list[AnimeEmAlta]
    tem_mais: bool


@dataclass(frozen=True, slots=True)
class NoDeSerie:
    """Um nó do grafo de `relations` da AniList — uma `Media` TV da franquia.

    `titulo` (romaji) é só para log/diagnóstico do walk, NUNCA persistido
    (mesma regra de `MetadadosDeAnime.titulo_romaji`). `ano`/`mes` vêm de
    `startDate` e servem ao desempate quando um nó tem mais de um prequel TV
    (`integrations/servico.py::resolver_serie`); `dia` não é necessário — uma
    franquia não lança duas temporadas no mesmo mês."""

    anilist_id: int
    titulo: str
    ano: int | None
    mes: int | None


@dataclass(frozen=True, slots=True)
class RelacoesDeAnime:
    """Vizinhança de `no` no grafo de `relations`, já reduzida ao que o walk de
    série usa: só prequels/sequels que são `Media` do tipo ANIME em formato de
    temporada (`classificacao.FORMATOS_DE_TEMPORADA`). O adapter (`anilist.py`)
    aplica esse filtro.

    `sequels` (para frente) espelha `prequels` (para trás) — usado por
    `integrations/servico.py::resolver_franquia` para enumerar a franquia
    inteira a partir da âncora já encontrada pelo walk `PREQUEL`.

    `formato`/`episodios`/`duracao_min`/`tem_pai` descrevem o PRÓPRIO `no` (não
    os vizinhos) e alimentam `classificacao.eh_serie`; `tem_pai` é a aresta
    `PARENT` para algum anime."""

    no: NoDeSerie
    prequels: tuple[NoDeSerie, ...]
    sequels: tuple[NoDeSerie, ...] = ()
    formato: str | None = None
    episodios: int | None = None
    duracao_min: int | None = None
    tem_pai: bool = False


class ProvedorDeMetadados(ABC):
    """Uma implementação por provedor (`anilist.py`, `kitsu.py`), síncrona —
    o `asyncio.to_thread`/timeout que a torna não-bloqueante mora só em
    `integrations/servico.py` (mesma separação de `fontes/rede/resiliencia.py`
    para os extratores de site)."""

    @property
    @abstractmethod
    def nome(self) -> str:
        """Chave para logs de fallback (ex.: "anilist", "kitsu")."""

    @abstractmethod
    def buscar_por_titulo(self, titulo: str) -> MetadadosDeAnime | None:
        """Busca metadados por título; `None` é resultado normal (título não
        encontrado neste provedor), não erro — mesma convenção de
        `fontes.adaptadores.base.ExtratorDeSite.buscar`."""

    def listar_por_busca(self, titulo: str) -> list[AnimeEmAlta]:
        """Candidatos de uma busca livre por `titulo` (a busca da Home) —
        mesmo formato de `listar_em_alta`. Capability opcional com
        implementação PADRÃO `[]` (mesmo padrão de
        `buscar_metadados_por_anilist_id`): só provedores com busca paginada a
        sobrescrevem — hoje só `anilist.py` (o Kitsu não expõe busca em lista)."""
        return []

    @abstractmethod
    def listar_em_alta(self) -> list[AnimeEmAlta]:
        """Lista animes em lançamento (`RELEASING`) ordenados por trending."""

    @abstractmethod
    def listar_proxima_temporada(self) -> list[AnimeEmAlta]:
        """Lista animes da próxima estação (a maioria ainda `NOT_YET_RELEASED`),
        ordenados por popularidade — mesmo formato de `listar_em_alta`. O
        provedor pode somar as estreias ainda não lançadas da estação atual."""

    def listar_novos_lancamentos(self) -> list[AnimeEmAlta]:
        """Animes com um episódio lançado recentemente (agenda de exibição da
        AniList), mais recente primeiro — um item por anime (dedup, mantendo só
        o episódio mais novo de cada um). Capability opcional com implementação
        PADRÃO `[]` (mesmo padrão de `listar_por_busca`): só `anilist.py` a
        sobrescreve — o Kitsu não expõe agenda de exibição por episódio."""
        return []

    @abstractmethod
    def buscar_titulos(self, titulo: str) -> TitulosDeAnime | None:
        """Títulos do melhor casamento para `titulo`; `None` quando o provedor
        não encontrou nada (mesma convenção de `buscar_por_titulo`)."""

    def buscar_metadados_por_anilist_id(self, anilist_id: int) -> MetadadosDeAnime | None:
        """Metadados (capa, banner, cor dominante, sinopse, títulos, bloco de
        lançamento) do anime de id AniList `anilist_id`. `lancamento` (status,
        total de episódios, próximo a ir ao ar) é o que permite ao chamador
        (`api/servicos/descoberta.py::_materializar_temporadas_irmas`) saber
        quantos episódios uma temporada irmã tem SEM outra chamada — sem isso,
        `Anime.total_episodios_anilist` fica `NULL` até um refresh de
        lançamento passar por ela, e o recorte de fonte achatada
        (`fontes/recorte.py::recortar_se_fonte_achatada`) não tem como
        calcular o offset entre temporadas nesse intervalo.

        Capability opcional com implementação PADRÃO
        `None` (não abstrata, ao contrário de
        `ProvedorComLancamento.buscar_lancamento_por_anilist_id`): só provedores
        que conhecem o id AniList a sobrescrevem — hoje só `anilist.py`; o Kitsu
        carrega apenas o seu próprio id. `integrations/servico.py` percorre a
        cadeia e aceita a primeira resposta não-`None`."""
        return None


@dataclass(frozen=True, slots=True)
class ArteDeAnime:
    """Banner resolvido por um `ProvedorDeArte` — formato mínimo, sem nenhum
    dos outros campos de `MetadadosDeAnime` (sinopse, ids, lançamento): quem
    resolve arte (TMDB) não é um `ProvedorDeMetadados`.

    Sem `capa_url`: a capa (pôster) voltou a ser responsabilidade exclusiva da
    cadeia normal de `ProvedorDeMetadados` (AniList/Kitsu) — a AniList modela
    cada temporada como uma `Media` própria, então já resolve a capa por
    temporada corretamente por construção, ao contrário do TMDB, que agrupa a
    série inteira sob um único id.

    `sinopse_serie`/`ano_da_serie`: sinopse pt-BR e ano de estreia da SÉRIE do
    TMDB (não da temporada) — insumo de `core/sinopse.py::escolher_sinopse`."""

    banner_url: str | None
    sinopse_serie: str | None = None
    ano_da_serie: int | None = None
    # Backdrop do TMDB COM o título desenhado na imagem (idioma pt/en de
    # `/tv/{id}/images`), ao contrário de `banner_url`, que é sempre a arte limpa —
    # o feed "Acabou de sair" não tem bloco de texto pra cobrir o banner.
    banner_com_titulo_url: str | None = None


@dataclass(frozen=True, slots=True)
class InfoDeEpisodio:
    """Still + nome + sinopse de UM episódio, resolvidos pelo `ProvedorDeArte`
    (TMDB) na mesma chamada (Fatia 6 — os dois primeiros já existiam via
    `still_url`/Fatia 5, `nome`/`sinopse` são novos). Qualquer campo pode ser
    `None` — TMDB best-effort, sem tradução pt-BR pra muito anime (`nome`/
    `sinopse` ficam vazios com mais frequência que `still_url`).

    `*_em_fallback`: o texto veio do idioma de fallback (en-US), não do pt-BR —
    quem persiste só o sobrescreve com texto que NÃO esteja em fallback, senão
    um texto melhor já gravado (pt-BR ou traduzido) regride pra inglês."""

    still_url: str | None
    nome: str | None = None
    sinopse: str | None = None
    nome_em_fallback: bool = False
    sinopse_em_fallback: bool = False


@dataclass(frozen=True, slots=True)
class CandidatoDeBanner:
    """Uma opção de banner do seletor da página do anime. `arquivo` é o
    identificador do provedor (no TMDB, o `file_path` com `/` inicial) — é o que
    volta do cliente ao escolher, nunca uma URL; `miniatura_url` é só para exibir."""

    arquivo: str
    miniatura_url: str


class ProvedorDeArte(ABC):
    """Capability autônoma, NÃO um `ProvedorDeMetadados` (D1 do plano de arte
    TMDB): o TMDB não responde sinopse/ids/feed, só imagem — por isso ganha
    contrato e tupla de registro (`registro.PROVEDORES_DE_ARTE`) próprios, em
    vez de entrar na tupla `PROVEDORES`/ser filtrado por `isinstance` a partir
    dela como as demais capabilities opcionais deste módulo. Síncrona pela
    mesma razão de `ProvedorDeMetadados` (o `to_thread`/timeout mora só no
    serviço)."""

    @property
    @abstractmethod
    def nome(self) -> str:
        """Chave para logs de fallback (ex.: "tmdb")."""

    @abstractmethod
    def buscar_arte_por_titulo(self, titulo: str, ano: int | None) -> ArteDeAnime | None:
        """Busca só banner por título (com `ano` só como desempate entre
        candidatos, nunca como filtro — D3 do plano); `None` é resultado
        normal (título não encontrado neste provedor), não erro — mesma
        convenção de `ProvedorDeMetadados.buscar_por_titulo`.

        Capa (pôster) NÃO é mais responsabilidade deste método/provedor —
        volta a ser resolvida só pela cadeia normal de `ProvedorDeMetadados`
        (AniList/Kitsu, que já modela capa por temporada corretamente)."""

    def buscar_info_de_episodio(
        self, titulo: str, ano: int | None, numero: int, temporada: int | None
    ) -> InfoDeEpisodio | None:
        """Still/nome/sinopse do episódio `numero` de `titulo`/`ano`. Com
        `temporada` dada (o `n` da temporada, `Anime.numero_temporada`),
        `numero` é o número do episódio DENTRO da temporada (1-based); com
        `temporada is None`, `numero` é a numeração absoluta local sobre a
        série inteira e o provedor resolve a temporada sozinho.

        Capability opcional com implementação PADRÃO `None` (não abstrata,
        mesmo padrão de `ProvedorDeMetadados.buscar_metadados_por_anilist_id`).
        Só `TmdbProvider` a sobrescreve."""
        return None

    def listar_candidatos_de_banner(self, titulo: str, ano: int | None) -> list[CandidatoDeBanner]:
        """Opções de banner da série de `titulo`/`ano`, da melhor para a pior
        segundo o provedor, para o usuário escolher. `[]` quando a série não é
        achada ou o provedor não tem arte.

        Capability opcional com implementação PADRÃO `[]` (mesmo padrão de
        `buscar_info_de_episodio`). Só `TmdbProvider` a sobrescreve."""
        return []


class ProvedorComLancamento(ABC):
    """Capability opcional: só provedores que expõem o estado de lançamento por
    id AniList a implementam (hoje só `anilist.py` — Kitsu não tem next-airing).
    `integrations/servico.py::buscar_lancamento_por_anilist_id` filtra
    `PROVEDORES` por `isinstance(p, ProvedorComLancamento)` antes de consultar.
    Síncrona pela mesma razão de `ProvedorDeMetadados` (o `to_thread`/timeout
    mora só no serviço)."""

    @abstractmethod
    def buscar_lancamento_por_anilist_id(self, anilist_id: int) -> LancamentoDeAnime | None:
        """Estado de lançamento do anime de id AniList `anilist_id`; `None`
        quando o provedor não conhece esse id."""


class ProvedorComRelacoes(ABC):
    """Capability opcional: só provedores que expõem o grafo de `relations`
    (prequel/sequel entre `Media`) a implementam — hoje só `anilist.py`
    (o Kitsu não modela relações entre temporadas).
    `integrations/servico.py::resolver_serie` filtra `PROVEDORES` por
    `isinstance(p, ProvedorComRelacoes)` antes de consultar. Síncrona pela
    mesma razão de `ProvedorDeMetadados` (o `to_thread`/timeout mora só no
    serviço)."""

    @abstractmethod
    def buscar_relacoes(self, anilist_id: int) -> RelacoesDeAnime | None:
        """Vizinhança de `anilist_id` no grafo de `relations`, com os prequels
        já filtrados a `Media` ANIME em formato de temporada (`TV`/`TV_SHORT`);
        `None` quando o provedor não conhece esse id."""

    @abstractmethod
    def buscar_serie_pai(self, anilist_id: int) -> NoDeSerie | None:
        """Série-mãe de `anilist_id`: o nó de formato de temporada (TV/TV_SHORT/
        ONA) ligado por aresta `PARENT`; sem `PARENT`, o primeiro nó de temporada
        de QUALQUER `relationType` (ao contrário de `buscar_relacoes`, que só
        anda `PREQUEL`) — um filme/OVA/especial quase nunca tem aresta
        `PREQUEL` de volta pra série-mãe (a AniList rotula essa ligação como
        `SIDE_STORY`/`ADAPTATION`/`ALTERNATIVE`/etc., variável por título).
        Usado só para ancorar um EXTRA (`integrations/servico.py::
        resolver_ancora_de_midia`) — nunca para o walk normal de `resolver_
        serie`. `None` quando não há nenhum nó de temporada relacionado ou o
        provedor não conhece o id."""


class ProvedorComRecomendacoes(ABC):
    """Capability opcional: só provedores que expõem sugestões de animes
    parecidos a implementam — hoje só `anilist.py` (o Kitsu não tem
    `recommendations`). `integrations/servico.py::listar_relacionados` filtra
    `PROVEDORES` por `isinstance(p, ProvedorComRecomendacoes)` antes de
    consultar. Síncrona pela mesma razão de `ProvedorDeMetadados` (o
    `to_thread`/timeout mora só no serviço)."""

    @abstractmethod
    def buscar_relacionados(self, anilist_id: int) -> list[AnimeEmAlta]:
        """Animes "relacionados" a `anilist_id` para a seção da página do
        anime — recomendações da comunidade (`recommendations`) e relações de
        franquia que NÃO são temporada de TV em sequência direta (`relations`
        exceto `PREQUEL`/`SEQUEL` de `Media` `TV`/`TV_SHORT`, já cobertas pelo
        seletor de temporada). `[]` quando o provedor não conhece o id ou não
        tem nada a sugerir — nunca `None` (não há "reconsultar mais tarde"
        aqui, ao contrário de `buscar_relacoes`)."""


class ProvedorComFileirasTematicas(ABC):
    """Capability opcional: só provedores que expõem busca por tag a
    implementam (hoje só `anilist.py` — Kitsu não tem esse recurso).
    `integrations/servico.py` filtra `PROVEDORES`/`PROVEDORES_DE_FEED` por
    `isinstance(p, ProvedorComFileirasTematicas)` antes de consultar. Síncrona
    pela mesma razão de `ProvedorDeMetadados` (o `to_thread`/timeout mora só
    no serviço)."""

    @abstractmethod
    def listar_fileira_tematica(self, fileira: FileiraTematica) -> list[AnimeEmAlta]:
        """Lista animes cuja tag/gênero AniList é `fileira.valor` (conforme
        `fileira.tipo`), ordenados por popularidade — mesmo formato de
        `ProvedorDeMetadados.listar_em_alta`."""


class ProvedorComDescoberta(ABC):
    """Capability opcional: listagem paginada por gênero (hoje só `anilist.py` —
    o Kitsu não tem filtro de gênero equivalente). `integrations/servico.py`
    filtra `PROVEDORES` por `isinstance(p, ProvedorComDescoberta)` antes de
    consultar. Síncrona pela mesma razão de `ProvedorDeMetadados` (o
    `to_thread`/timeout mora só no serviço)."""

    @abstractmethod
    def listar_descoberta(self, genero: str | None, pagina: int) -> PaginaDeAnimes:
        """Animes do `genero` (nome cru do provedor, ex. "Action"; `None` = sem
        filtro), por popularidade, na `pagina` pedida (1-based). Só títulos que
        já estrearam — a Descobrir não tem o que abrir de um anime sem fonte."""

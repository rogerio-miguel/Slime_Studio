"""Contrato Strategy dos provedores de metadados externos de anime (AniList
principal, Kitsu fallback) — espelha `extractors/base.py`.

Domínio puro: sem HTTP, sem SQLAlchemy — só o formato dos dados que
atravessam a fronteira e o contrato abstrato que cada adapter implementa.
`ABC` (não `Protocol`) pela mesma razão de `extractors/base.py`: sem type
checker nos comandos de validação (`ruff` só), então a garantia de contrato
completo precisa vir de `TypeError` na instanciação.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime

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

    `titulo_romaji`/`titulo_ingles` são material de corroboração de match por
    título (o casamento por título é heurístico — quem consome decide se é bom o
    bastante), **nunca persistidos**: `Anime.titulo` é o título local, não o do
    provedor (mesma regra de `TitulosDeAnime`).
    """

    capa_url: str | None
    sinopse: str | None
    anilist_id: int | None
    kitsu_id: int | None
    lancamento: LancamentoDeAnime | None = None
    titulo_romaji: str | None = None
    titulo_ingles: str | None = None


@dataclass(frozen=True, slots=True)
class TitulosDeAnime:
    """Títulos conhecidos do anime em um provedor — usados só para expandir o
    termo de busca nos sites de extração (`api/servicos/busca.py`), nunca
    persistidos: `Anime.titulo` é o título local, não o do provedor."""

    titulo_romaji: str | None
    titulo_ingles: str | None


@dataclass(frozen=True, slots=True)
class AnimeEmAlta:
    """Item de um feed de descoberta de metadados — "lançamentos em alta"
    (`status: RELEASING, sort: TRENDING_DESC` no AniList) e "próxima temporada"
    (`season`/`seasonYear` da estação seguinte) compartilham este formato.

    `anilist_id` é opcional: o provedor de fallback (Kitsu) não tem
    conhecimento do id AniList do item, só o seu próprio.

    `ano_estreia`/`generos` só o AniList preenche; no caminho degradado (Kitsu)
    ficam nos defaults — `None` para o ano (não há inteiro que signifique
    "desconhecido"), tupla vazia para os gêneros ("sem gêneros" e "lista vazia"
    são a mesma coisa para quem renderiza).
    """

    titulo_romaji: str
    titulo_ingles: str | None
    capa_url: str | None
    banner_url: str | None
    anilist_id: int | None
    ano_estreia: int | None = None
    generos: tuple[str, ...] = ()
    lancamento: LancamentoDeAnime | None = None


class ProvedorDeMetadados(ABC):
    """Uma implementação por provedor (`anilist.py`, `kitsu.py`), síncrona —
    o `asyncio.to_thread`/timeout que a torna não-bloqueante mora só em
    `integrations/servico.py` (mesma separação de `extractors/resiliencia.py`
    para os extratores de site)."""

    @property
    @abstractmethod
    def nome(self) -> str:
        """Chave para logs de fallback (ex.: "anilist", "kitsu")."""

    @abstractmethod
    def buscar_por_titulo(self, titulo: str) -> MetadadosDeAnime | None:
        """Busca metadados por título; `None` é resultado normal (título não
        encontrado neste provedor), não erro — mesma convenção de
        `extractors.base.ExtratorDeSite.buscar`."""

    @abstractmethod
    def listar_em_alta(self) -> list[AnimeEmAlta]:
        """Lista animes em lançamento (`RELEASING`) ordenados por trending."""

    @abstractmethod
    def listar_proxima_temporada(self) -> list[AnimeEmAlta]:
        """Lista animes da próxima estação (a maioria ainda `NOT_YET_RELEASED`),
        ordenados por popularidade — mesmo formato de `listar_em_alta`."""

    @abstractmethod
    def buscar_titulos(self, titulo: str) -> TitulosDeAnime | None:
        """Títulos do melhor casamento para `titulo`; `None` quando o provedor
        não encontrou nada (mesma convenção de `buscar_por_titulo`)."""


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

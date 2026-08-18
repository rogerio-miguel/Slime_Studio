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


@dataclass(frozen=True, slots=True)
class MetadadosDeAnime:
    """Campos de `models/anime.py::Anime` que o cadastro manual não preenche
    hoje — `integrations/servico.py` decide qual provedor preencheu qual."""

    capa_url: str | None
    sinopse: str | None
    anilist_id: int | None
    kitsu_id: int | None


@dataclass(frozen=True, slots=True)
class TitulosDeAnime:
    """Títulos conhecidos do anime em um provedor — usados só para expandir o
    termo de busca nos sites de extração (`api/servicos/busca.py`), nunca
    persistidos: `Anime.titulo` é o título local, não o do provedor."""

    titulo_romaji: str | None
    titulo_ingles: str | None


@dataclass(frozen=True, slots=True)
class AnimeEmAlta:
    """Item do feed "lançamentos em alta" (`status: RELEASING, sort:
    TRENDING_DESC` no AniList — decisão de produto, não "temporada estrita").

    `anilist_id` é opcional: o provedor de fallback (Kitsu) não tem
    conhecimento do id AniList do item, só o seu próprio.
    """

    titulo_romaji: str
    titulo_ingles: str | None
    capa_url: str | None
    banner_url: str | None
    anilist_id: int | None


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
    def buscar_titulos(self, titulo: str) -> TitulosDeAnime | None:
        """Títulos do melhor casamento para `titulo`; `None` quando o provedor
        não encontrou nada (mesma convenção de `buscar_por_titulo`)."""

"""Contrato Strategy dos extratores de site (ESPECIFICACAO.md §3A).

Domínio puro: sem SQLAlchemy, sem `cloudscraper`, sem I/O — só o formato dos
dados que atravessam a fronteira e o contrato abstrato que cada site implementa.
`ABC` (não `Protocol`) por decisão do plano: sem type checker nos comandos de
validação (`ruff` só), então a garantia de contrato completo precisa vir de
`TypeError` na instanciação, que só `ABC` dá.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from extractors.cliente import ClienteDeSite


@dataclass(frozen=True, slots=True)
class ResultadoBusca:
    titulo_exibicao: str
    identificador: str  # id do anime naquele site -> FonteAnime.identificador_no_site
    url: str
    # `None` quando o site não expõe capa na busca (ex. AnimeFire) ou a tag de
    # imagem está ausente no card — enriquecimento best-effort por metadado de
    # provedor externo mora em `api/servicos/busca.py::enriquecer_capas`.
    capa_url: str | None = None


@dataclass(frozen=True, slots=True)
class EpisodioRemoto:
    numero: int
    url: str


@dataclass(frozen=True, slots=True)
class LinkDeMidia:
    url: str
    cabecalhos: dict[str, str]  # Referer + User-Agent (+ Cookie) — hotlink protection


class ExtratorDeSite(ABC):
    """Uma implementação por site (`animefire.py`, etc.), síncrona (D1 do plano) —
    o `asyncio.to_thread` que a torna não-bloqueante mora só em `resiliencia.py`."""

    @property
    @abstractmethod
    def dominio(self) -> str:
        """Chave de `EstadoSite`/`SessaoBypass`/`FonteAnime`/`Episodio.site_origem`."""

    @property
    @abstractmethod
    def exige_navegador(self) -> bool:
        """`True` se este site nunca é alcançável via cliente leve (ex. proteção mais dura)."""

    @abstractmethod
    def buscar(self, cliente: ClienteDeSite, titulo: str) -> list[ResultadoBusca]:
        """Busca por título; lista vazia é resultado normal (título não existe neste site)."""

    @abstractmethod
    def listar_episodios(
        self, cliente: ClienteDeSite, identificador: str
    ) -> list[EpisodioRemoto]:
        """Lista episódios do anime já identificado neste site (via `buscar` anterior)."""

    @abstractmethod
    def resolver_midia(self, cliente: ClienteDeSite, url_episodio: str) -> LinkDeMidia:
        """Resolve a URL direta de mídia (com os cabeçalhos exigidos) de um episódio."""

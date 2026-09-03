"""Contrato Strategy dos extratores de site (ESPECIFICACAO.md §3A).

Domínio puro: sem SQLAlchemy, sem `cloudscraper`, sem I/O — só o formato dos
dados que atravessam a fronteira e o contrato abstrato que cada site implementa.
`ABC` (não `Protocol`) por decisão do plano: sem type checker nos comandos de
validação (`ruff` só), então a garantia de contrato completo precisa vir de
`TypeError` na instanciação, que só `ABC` dá.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from core.enums import VersaoEpisodio
from extractors.cliente import ClienteDeSite


@dataclass(frozen=True, slots=True)
class ResultadoBusca:
    titulo_exibicao: str
    identificador: str  # id do anime naquele site -> FonteAnime.identificador_no_site
    url: str
    # `None` quando o site não expõe capa na busca (ex. AnimeFire) ou a tag de
    # imagem está ausente no card — enriquecimento best-effort por metadado de
    # provedor externo mora em `api/servicos/capas.py::enriquecer_capas`.
    capa_url: str | None = None
    # `None` quando o site não diferencia versão (`diferencia_versao=False`) ou
    # o adapter não detectou marcador algum — não confundir com
    # `VersaoDeFonte.NAO_DIFERENCIADA` (esse é o estado do mapeamento, este
    # campo é o resultado por candidato de busca).
    versao: VersaoEpisodio | None = None


@dataclass(frozen=True, slots=True)
class EpisodioRemoto:
    # Texto/label cru do episódio como aparece na fonte (ex.: "7", "07",
    # "Especial") — chave de dedup em cada adapter (`animefire.py`,
    # `animesdrive.py`): rótulos com zero à esquerda ("07") não são
    # necessariamente o mesmo episódio que "7", então a chave nunca é
    # `int(numero)` (colapsaria os dois indevidamente).
    rotulo: str
    # `None` quando `rotulo` não é puramente numérico (ex. "Especial",
    # "OVA 2") — episódio ainda aparece normalmente na listagem (decisão do
    # produto), só não é capturável ainda: o frontend desabilita o botão
    # "Capturar" nesse caso.
    numero: int | None
    url: str
    # `None` quando o site não diferencia versão ou nenhum marcador foi
    # detectado nesse episódio específico.
    versao: VersaoEpisodio | None = None
    # URL da thumbnail do episódio na fonte (ou `None` quando o site não expõe
    # thumb pra esse episódio). String crua — nunca baixada pra disco; a fatia de
    # API serve via proxy `/api/thumb`.
    thumb_url: str | None = None


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

    @property
    def exige_navegador_para_midia(self) -> bool:
        """`True` quando só `resolver_midia` precisa de navegador — o player monta a
        URL de mídia em tempo de execução, mas busca e listagem seguem no cliente leve.

        Granularidade separada de `exige_navegador` de propósito: subir Chromium
        em toda busca (operação mais frequente do sistema, e paralela entre sites
        em `extractors/busca/servico.py::buscar_por_site_com_variantes`) pra atender um
        único método seria caro sem necessidade. Concreta, não abstrata: o caso
        normal é `False` e nenhum adapter existente precisa declarar isso.
        """
        return False

    @property
    def diferencia_versao(self) -> bool:
        """`True` quando este site separa legendado de dublado no próprio
        markup (slug/título de anime) — capability, não comportamento: quem
        lê isso é o chamador, decidindo se a ausência de marcador detectado
        por `extractors/versao.py::inferir_versao` vira `VersaoEpisodio.LEGENDADO`
        por convenção do site (dublado sempre marcado, legendado é o default
        silencioso) ou fica indeterminada.

        Concreta, não abstrata, mesmo padrão de `exige_navegador_para_midia`:
        o caso normal é `False`, só sites que sabem diferenciar sobrescrevem.
        """
        return False

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

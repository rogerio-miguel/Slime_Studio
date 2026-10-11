"""Contrato Strategy dos extratores de site (ESPECIFICACAO.md §3A).

Domínio puro: sem SQLAlchemy, sem `cloudscraper`, sem I/O — só o formato dos
dados que atravessam a fronteira e o contrato abstrato que cada site implementa.
`ABC` (não `Protocol`) por decisão do plano: sem type checker nos comandos de
validação (`ruff` só), então a garantia de contrato completo precisa vir de
`TypeError` na instanciação, que só `ABC` dá.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum

from core.enums import VersaoEpisodio
from fontes.rede.cliente import ClienteDeSite


@dataclass(frozen=True, slots=True)
class ResultadoBusca:
    titulo_exibicao: str
    identificador: str  # id do anime naquele site -> FonteAnime.identificador_no_site
    url: str
    # `None` quando o site não diferencia versão (`diferencia_versao=False`) ou
    # o adapter não detectou marcador algum — não confundir com
    # `VersaoDeFonte.NAO_DIFERENCIADA` (esse é o estado do mapeamento, este
    # campo é o resultado por candidato de busca).
    versao: VersaoEpisodio | None = None


@dataclass(frozen=True, slots=True)
class EpisodioRemoto:
    """Um episódio como a fonte o expõe, já recortado para a temporada pedida
    pelo adapter (`ExtratorDeSite.listar_episodios`).

    - `numero` é 1-based dentro da temporada pedida quando `listar_episodios`
      recebeu uma `temporada`; é a numeração contínua da fonte (absoluta entre
      temporadas, quando a fonte tem esse conceito) quando `temporada is None`.
      Casa com `Episodio.numero` no primeiro caso.
    - `rotulo` é sempre o texto/label cru da fonte (ex.: "7", "07", "Especial")
      e NUNCA é reescrito — é a chave de dedup de cada adapter (rótulos com zero
      à esquerda não são necessariamente o mesmo episódio) e PODE divergir de
      `numero`: no AnimeFire continua sendo o número absoluto da série; no
      MeusAnimes, o número por temporada cru da URL. `api/servicos/jobs.py`
      deriva `Episodio.numero_fonte` de `int(rotulo)`.
    """

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
    # Nome e sinopse do episódio — NUNCA vêm do extractor (nenhum site de
    # scraping expõe isso hoje); sempre `None` aqui na origem, preenchidos
    # depois só pelo overlay TMDB (`api/servicos/fontes.py::
    # _sobrepor_stills_de_episodios`, mesmo mecanismo de `thumb_url`).
    titulo: str | None = None
    sinopse: str | None = None
    # `True` quando o adapter recortou a temporada pelo marcador da própria fonte
    # (`numero` já é por temporada). Sem isto, `api/servicos/fontes.py::
    # _recortar_se_fonte_achatada` não distingue um recorte nativo que traz mais
    # episódios que a AniList (extras/especiais da temporada) de uma fonte
    # achatada, e cortaria o excedente como se fosse temporada seguinte.
    recortado_pela_fonte: bool = False


class FormatoDeMidia(StrEnum):
    """Formato do container/protocolo apontado por `LinkDeMidia.url` — vocabulário
    de extractor, não domínio persistido (mesmo racional de `fontes/adaptadores/qualidade.py`:
    fica fora de `core/enums.py` de propósito, pois é só o site que atravessou a
    fronteira, não algo que o resto do sistema precisa conhecer).

    `DESCONHECIDO` é o default: quem baixa infere o formato como sempre (extensão
    da URL/probe automático do ffmpeg). `DASH` e `HLS` sinalizam um manifesto
    mascarado de imagem (ex. AnimeFire: URL termina em `.jpg`, mas o corpo é XML
    de MPD ou uma playlist `#EXTM3U`) — sem essa distinção explícita, tanto a
    checagem de amostra quanto o probe do ffmpeg seriam enganados pela extensão
    de fachada.

    AnimeFire servia DASH mascarado até então; confirmado ao vivo em 2026-09-14
    que o CDN (`akumast.net`) passou a servir HLS mascarado do mesmo jeito
    (`content-type: application/vnd.apple.mpegurl`, corpo `#EXTM3U`) — daí `HLS`
    existir ao lado de `DASH` em vez de substituí-lo.
    """

    DESCONHECIDO = "desconhecido"
    DASH = "dash"
    HLS = "hls"


@dataclass(frozen=True, slots=True)
class LinkDeMidia:
    url: str
    cabecalhos: dict[str, str]  # Referer + User-Agent (+ Cookie) — hotlink protection
    # Último campo, com default — adapters existentes (`animesdrive`, `meusanimes`)
    # e seus testes instanciam `LinkDeMidia` sem este campo; não pode quebrar.
    formato: FormatoDeMidia = FormatoDeMidia.DESCONHECIDO


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
        em `fontes/busca/servico.py::buscar_por_site_com_variantes`) pra atender um
        único método seria caro sem necessidade. Concreta, não abstrata: o caso
        normal é `False` e nenhum adapter existente precisa declarar isso.
        """
        return False

    @property
    def diferencia_versao(self) -> bool:
        """`True` quando este site separa legendado de dublado no próprio
        markup (slug/título de anime) — capability, não comportamento: quem
        lê isso é o chamador, decidindo se a ausência de marcador detectado
        por `fontes/adaptadores/versao.py::inferir_versao` vira `VersaoEpisodio.LEGENDADO`
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
        self, cliente: ClienteDeSite, identificador: str, temporada: int | None
    ) -> list[EpisodioRemoto]:
        """Lista os episódios do anime já identificado neste site (via `buscar`
        anterior), recortados para `temporada` e numerados de 1.

        Contrato de degradação — obrigatório em TODO adapter, já que é aqui que
        mora o conhecimento dos defeitos de cada site:

        - `temporada is None` → devolve a listagem inteira da fonte, `numero` na
          numeração contínua dela (o anime é temporada única no nosso catálogo,
          ou o ordinal narrativo é desconhecido).
        - a fonte expõe a temporada pedida → devolve só ela, `numero`
          reiniciando em 1.
        - a fonte expõe UMA temporada só e ela não bate `temporada` → devolve a
          listagem inteira com `logger.info` (o rótulo de season da fonte
          diverge do nosso; numa fonte que carimba temporada de forma confiável
          isto pode trazer a temporada errada).
        - a fonte expõe VÁRIAS temporadas e nenhuma bate `temporada` → `[]` com
          `logger.warning` listando as disponíveis (esta temporada não existe
          nesta fonte).
        """

    @abstractmethod
    def resolver_midia(self, cliente: ClienteDeSite, url_episodio: str) -> LinkDeMidia:
        """Resolve a URL direta de mídia (com os cabeçalhos exigidos) de um episódio."""

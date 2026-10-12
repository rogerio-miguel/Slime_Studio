"""Recorte de temporada sobre a listagem de uma fonte "achatada".

O adapter recorta a temporada pedida quando a própria fonte a marca
(`ExtratorDeSite.listar_episodios`, `EpisodioRemoto.recortado_pela_fonte`). Sem
esse sinal (ex. AnimeFire cuja API devolve a franquia inteira como `season: 1`)
ele degrada para a série toda numerada de forma contínua, e o `numero` deixa de
casar com `Episodio.numero`, que é por temporada. Este módulo detecta o caso
comparando com o que a AniList atribui à temporada e corta pelo offset
acumulado das temporadas anteriores.

Passa por aqui TODO caminho que lista a fonte para casar um episódio por
número: a exibição e a sondagem (`api/servicos/fontes.py`) e a troca de site no
meio do download (`captura/servico.py`). Quem lista sem passar por aqui pega o
episódio absoluto 3 (da T1) quando o usuário pediu o 3 da T2.

A decisão é pura (funções sem I/O); só `recortar_se_fonte_achatada` lê o banco
(offset e partes irmãs, `db/franquias.py`) e só quando a detecção já disparou.
"""

import logging
from dataclasses import dataclass, replace
from enum import StrEnum

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.enums import StatusLancamento
from db.franquias import offset_de_temporada, total_das_partes_irmas
from fontes.adaptadores.base import EpisodioRemoto
from models.anime import Anime

logger = logging.getLogger(__name__)

_SessionMaker = async_sessionmaker[AsyncSession]


@dataclass(frozen=True, slots=True)
class Esperados:
    """Quantos episódios a AniList atribui à temporada. `em_aberto`: temporada
    em exibição, sem total — `quantidade` é só o piso (episódios já exibidos) e a
    fonte pode legitimamente estar à frente."""

    quantidade: int
    em_aberto: bool


def episodios_esperados(anime: Anime) -> Esperados | None:
    """Temporada fechada: `total_episodios_anilist`. Temporada em exibição não tem
    total (a AniList devolve `None`), mas `proximo_ep_numero - 1` é quantos já
    foram ao ar. `None` quando não há como saber."""
    if anime.total_episodios_anilist:
        return Esperados(anime.total_episodios_anilist, em_aberto=False)
    if (
        anime.status_lancamento is StatusLancamento.EM_LANCAMENTO
        and anime.proximo_ep_numero
        and anime.proximo_ep_numero > 1
    ):
        return Esperados(anime.proximo_ep_numero - 1, em_aberto=True)
    return None


def _numeros_distintos(episodios: list[EpisodioRemoto]) -> set[int]:
    return {ep.numero for ep in episodios if ep.numero is not None}


def excede_a_temporada(
    episodios: list[EpisodioRemoto], esperados: Esperados, partes_irmas: int = 0
) -> bool:
    """A lista tem mais episódios distintos que a temporada — sinal de que o
    recorte nativo não rodou. Em temporada em exibição a fonte pode estar 1 à
    frente da AniList, então só dispara com essa folga. `partes_irmas` soma as
    partes da mesma temporada que a AniList divide ("Part 1"/"Part 2" em linhas
    separadas) e o site serve juntas; temporada em exibição não as soma."""
    if esperados.em_aberto:
        return len(_numeros_distintos(episodios)) > esperados.quantidade + 1
    return len(_numeros_distintos(episodios)) > esperados.quantidade + partes_irmas


def aparar_excedente(episodios: list[EpisodioRemoto], teto: int) -> list[EpisodioRemoto]:
    """Descarta o que passa de `teto`. Rótulo não numérico (`numero=None`) fica."""
    return [ep for ep in episodios if ep.numero is None or ep.numero <= teto]


class ResultadoDoRecorte(StrEnum):
    RECORTADA = "recortada"
    SO_TEMPORADAS_ANTERIORES = "so_temporadas_anteriores"
    OFFSET_NAO_COBRIU = "offset_nao_cobriu"


@dataclass(frozen=True, slots=True)
class Recorte:
    episodios: list[EpisodioRemoto]
    resultado: ResultadoDoRecorte


def recortar_por_offset(
    episodios: list[EpisodioRemoto], offset: int, teto: int | None
) -> Recorte:
    """Fica com o intervalo absoluto `(offset, teto]` e renumera por `- offset`.
    `rotulo` não é tocado (chave de dedup do adapter e `Episodio.numero_fonte`).
    `teto=None` (temporada em exibição): os próximos episódios a estrear ainda
    pertencem a ela. Rótulo não numérico (`numero=None`) fica sempre.

    Intervalo vazio tem dois significados: a lista é inteira das temporadas
    anteriores (ex. dublado do MeusAnimes só com a T1, que o adapter devolve
    inteiro por ter uma única temporada carimbada) e a temporada não existe na
    fonte (`episodios` só com os não numéricos); ou o offset acumulado não bate
    com a numeração da fonte e nada se pode afirmar (`episodios` intacto)."""

    def _no_intervalo(ep: EpisodioRemoto) -> bool:
        return ep.numero is not None and ep.numero > offset and (teto is None or ep.numero <= teto)

    if any(_no_intervalo(ep) for ep in episodios):
        recortados = [
            replace(ep, numero=ep.numero - offset) if _no_intervalo(ep) else ep
            for ep in episodios
            if ep.numero is None or _no_intervalo(ep)
        ]
        return Recorte(recortados, ResultadoDoRecorte.RECORTADA)
    if offset > 0 and max(_numeros_distintos(episodios)) <= offset:
        sem_numero = [ep for ep in episodios if ep.numero is None]
        return Recorte(sem_numero, ResultadoDoRecorte.SO_TEMPORADAS_ANTERIORES)
    return Recorte(episodios, ResultadoDoRecorte.OFFSET_NAO_COBRIU)


async def recortar_se_fonte_achatada(
    sessionmaker: _SessionMaker, anime: Anime, episodios: list[EpisodioRemoto]
) -> list[EpisodioRemoto]:
    """`episodios` com a numeração da temporada de `anime`, mesmo que a fonte tenha
    devolvido a franquia inteira.

    Lista que o adapter já recortou pelo marcador da fonte
    (`EpisodioRemoto.recortado_pela_fonte`) não passa pelo corte por offset (que a
    reduziria ao excedente); só perde o que passa do total da AniList, em
    temporada fechada: OVAs/especiais que o site (ex. MeusAnimes) guarda como
    "episódio 13…16" da temporada e não existem no TMDB nem na AniList como
    episódio dela.

    Sem temporada pedida (`numero_temporada` nulo) ou sem contagem esperada não há
    como decidir — devolve `episodios` intacto, mesma degradação segura que o
    adapter já aplica."""
    esperados = episodios_esperados(anime)
    if anime.numero_temporada is None or esperados is None:
        return episodios

    if any(ep.recortado_pela_fonte for ep in episodios):
        return await _aparar_nativo(sessionmaker, anime, episodios, esperados)

    # A consulta ao catálogo só roda depois que a detecção sem ela já disparou.
    if not excede_a_temporada(episodios, esperados):
        return episodios
    partes = 0 if esperados.em_aberto else await total_das_partes_irmas(sessionmaker, anime)
    if not excede_a_temporada(episodios, esperados, partes):
        return episodios

    offset = await offset_de_temporada(sessionmaker, anime)
    if esperados.em_aberto and offset == 0:
        return episodios  # sem temporadas anteriores não há o que cortar
    teto = None if esperados.em_aberto else offset + esperados.quantidade + partes

    recorte = recortar_por_offset(episodios, offset, teto)
    _registrar(anime, recorte, esperados, offset, len(_numeros_distintos(episodios)))
    return recorte.episodios


async def _aparar_nativo(
    sessionmaker: _SessionMaker,
    anime: Anime,
    episodios: list[EpisodioRemoto],
    esperados: Esperados,
) -> list[EpisodioRemoto]:
    if esperados.em_aberto or all(
        ep.numero is None or ep.numero <= esperados.quantidade for ep in episodios
    ):
        return episodios
    partes = await total_das_partes_irmas(sessionmaker, anime)
    return aparar_excedente(episodios, esperados.quantidade + partes)


def _registrar(
    anime: Anime, recorte: Recorte, esperados: Esperados, offset: int, distintos: int
) -> None:
    contexto = (anime.titulo, anime.numero_temporada, distintos, esperados.quantidade, offset)
    if recorte.resultado is ResultadoDoRecorte.RECORTADA:
        logger.info(
            "fonte achatada para %r temporada %d (%d episódios distintos > %d esperados "
            "pela AniList) — recortada por offset acumulado (%d) para %d episódios",
            *contexto,
            len(recorte.episodios),
        )
    elif recorte.resultado is ResultadoDoRecorte.SO_TEMPORADAS_ANTERIORES:
        logger.info(
            "fonte para %r temporada %d só tem episódios de temporadas anteriores "
            "(%d distintos, esperados %d, offset %d) — temporada ausente na fonte",
            *contexto,
        )
    else:
        logger.warning(
            "fonte achatada para %r temporada %d (%d episódios distintos > %d "
            "esperados pela AniList) mas offset acumulado (%d) não cobriu nenhum "
            "episódio — mantendo lista sem recorte",
            *contexto,
        )

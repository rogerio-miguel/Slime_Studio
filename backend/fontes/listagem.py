"""Listagem de episódios de um site e filtro por número/versão — a leitura da
fonte, sem baixar nada. O download com fallback entre sites mora em
`captura/servico.py`.
"""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.enums import VersaoEpisodio
from fontes.adaptadores.base import EpisodioRemoto
from fontes.adaptadores.registro import obter_extrator
from fontes.rede import resiliencia

_SessionMaker = async_sessionmaker[AsyncSession]


async def listar_episodios_em(
    sessionmaker: _SessionMaker, dominio: str, identificador: str, temporada: int | None
) -> list[EpisodioRemoto]:
    extrator = obter_extrator(dominio)
    return await resiliencia.chamar(
        sessionmaker,
        extrator,
        lambda cliente: extrator.listar_episodios(cliente, identificador, temporada),
        nome_operacao="listar_episodios",
    )


def filtrar_por_numero_e_versao(
    episodios: list[EpisodioRemoto], numero: int, versao: VersaoEpisodio
) -> list[EpisodioRemoto]:
    """Casa por `numero` primeiro (comportamento base), depois delega o filtro
    de versão a `filtrar_por_versao`.

    Pública (não `_`-prefixada) porque também é usada por
    `api/servicos/jobs.py::criar_job_site` — mesmo risco de pegar o rótulo da
    versão errada existe lá (`resultado.dominio`/`resultado.identificador`
    pode listar episódios das duas versões, ex. página do AnimesDrive que
    cobre ambas)."""
    correspondentes = [ep for ep in episodios if ep.numero == numero]
    return filtrar_por_versao(correspondentes, versao)


def filtrar_por_versao(
    episodios: list[EpisodioRemoto], versao: VersaoEpisodio
) -> list[EpisodioRemoto]:
    """Quando a versão pedida é confirmada (LEGENDADO/DUBLADO) e a listagem
    rotula pelo menos um episódio (`ep.versao is not None` — site que
    diferencia, ex. AnimesDrive), EXIGE `ep.versao == versao`: a listagem tem
    episódios das duas versões e não filtrar pegaria a versão errada
    silenciosamente. Sites que não rotulam (`ep.versao` sempre `None`) ou
    `versao == DESCONHECIDA` devolvem a lista sem filtrar (comportamento
    anterior a esta fase).

    Pública (não `_`-prefixada) pelo mesmo motivo de `filtrar_por_numero_e_versao`
    — usada por mais de um módulo (`api/servicos/fontes.py::listar_episodios_remotos`)."""
    if versao == VersaoEpisodio.DESCONHECIDA:
        return episodios

    rotulados = [ep for ep in episodios if ep.versao is not None]
    if not rotulados:
        return episodios
    return [ep for ep in rotulados if ep.versao == versao]

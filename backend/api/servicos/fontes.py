"""Listagem de episódios na fonte remota (site) de um anime — permite a UI
"prontos vs. não capturados" da página do anime (Fase 4C do plano). Reusa a
mesma resolução de fonte e listagem de `api/servicos/jobs.py::criar_job_site`;
diferente dela, não persiste nenhum `Episodio`/`Job` — é só consulta.

Não importa `fastapi`: devolve `EpisodiosRemotosResultado` ou levanta erro de
`core/erros.py`; `api/rotas/animes.py` traduz para `HTTPException`/schemas.

Também sobrepõe, best-effort, a thumb de episódio do TMDB (Fatia 5 do
`PLANO_ARTE_TMDB.md`) sobre `EpisodioRemoto.thumb_url` — só nesta listagem de
EXIBIÇÃO; o pipeline de captura (`api/servicos/jobs.py::criar_job_site`, que
chama `extractors/servico.py::listar_episodios_em` direto) não passa por
aqui e continua sem este overlay, por design (thumb não influencia o que é
baixado).
"""

import asyncio
import logging
from dataclasses import dataclass, replace

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.enums import VersaoEpisodio
from core.erros import FalhaDeExtracao, FonteAmbigua, VersaoIndisponivelError
from extractors.base import EpisodioRemoto
from extractors.resolucao import ConfirmacaoNecessaria, VersaoIndisponivel, resolver_fonte_do_anime
from extractors.servico import filtrar_por_versao, listar_episodios_em
from integrations import servico as servico_metadados
from models.anime import Anime

logger = logging.getLogger(__name__)

_SessionMaker = async_sessionmaker[AsyncSession]

# Mesmo teto de `api/servicos/jobs.py::_TETO_CRIACAO_SITE_S` — rede de segurança
# acima dos timeouts internos dos extratores, não a primeira linha de defesa.
_TETO_LISTAGEM_REMOTA_S = 60

# Mesma concorrência/deadline de `api/servicos/capas.py::_consultar_capas` —
# outro enriquecimento best-effort sobre `integrations/servico.py`, mesma
# ordem de grandeza de chamadas em paralelo.
_CONCORRENCIA_STILLS = 5
_TETO_LOTE_STILLS_S = 18


@dataclass(frozen=True, slots=True)
class EpisodiosRemotosResultado:
    """`dominio` é o site que resolveu `episodios` — a rota (`api/rotas/animes.py`)
    expõe isto no contrato de saída (`EpisodiosRemotosSaida`) para o usuário
    poder notar quando a fonte "errada" foi resolvida."""

    dominio: str
    episodios: list[EpisodioRemoto]


async def listar_episodios_remotos(
    sessionmaker: _SessionMaker, anime: Anime, versao: VersaoEpisodio
) -> EpisodiosRemotosResultado:
    """`anime` já carregado por quem chama (`api/rotas/animes.py`, que faz o 404
    de `anime_id` inexistente antes de chegar aqui — mesmo padrão das outras
    rotas que operam por id).

    `ConfirmacaoNecessaria` (mais de um candidato, sem match exato de título)
    vira `FonteAmbigua` — mesmo comportamento de
    `api/servicos/jobs.py::criar_job_site`; o cliente resolve via
    `POST /api/admin/animes/{id}/fontes/confirmar` e reenvia esta chamada.

    `VersaoIndisponivel` (nenhum site serve `versao`) vira `VersaoIndisponivelError`
    — o handler de `api/main.py` traduz pra 409.
    """
    try:
        resultado = await asyncio.wait_for(
            resolver_fonte_do_anime(sessionmaker, anime, versao),
            timeout=_TETO_LISTAGEM_REMOTA_S,
        )
    except TimeoutError as excecao:
        raise FalhaDeExtracao(
            f"resolução de fonte excedeu o teto de {_TETO_LISTAGEM_REMOTA_S}s",
            permite_retentativa=True,
        ) from excecao

    if isinstance(resultado, ConfirmacaoNecessaria):
        raise FonteAmbigua(
            resultado.dominio,
            [
                {
                    "titulo_exibicao": candidato.titulo_exibicao,
                    "identificador": candidato.identificador,
                    "url": candidato.url,
                }
                for candidato in resultado.candidatos
            ],
        )
    if isinstance(resultado, VersaoIndisponivel):
        raise VersaoIndisponivelError(resultado.versao)

    try:
        episodios = await asyncio.wait_for(
            listar_episodios_em(sessionmaker, resultado.dominio, resultado.identificador),
            timeout=_TETO_LISTAGEM_REMOTA_S,
        )
    except TimeoutError as excecao:
        raise FalhaDeExtracao(
            f"listagem de episódios excedeu o teto de {_TETO_LISTAGEM_REMOTA_S}s",
            dominio=resultado.dominio,
            permite_retentativa=True,
        ) from excecao

    # Uma página pode cobrir as duas versões (ex. AnimesDrive quando legendado
    # e dublado compartilham a mesma listagem) — sem este filtro, a grade
    # remota misturaria episódios da versão errada. Mesma proteção que o
    # caminho de captura já aplica (`api/servicos/jobs.py::criar_job_site`).
    episodios = filtrar_por_versao(episodios, versao)

    episodios = await _sobrepor_stills_de_episodios(anime, episodios)

    return EpisodiosRemotosResultado(dominio=resultado.dominio, episodios=episodios)


async def _sobrepor_stills_de_episodios(
    anime: Anime, episodios: list[EpisodioRemoto]
) -> list[EpisodioRemoto]:
    """Overlay best-effort de thumb TMDB (Fatia 5, `PLANO_ARTE_TMDB.md`) sobre
    `EpisodioRemoto.thumb_url`: tenta a still do TMDB pelo número absoluto de
    cada episódio e preserva o `thumb_url` que o extractor já trouxe quando o
    TMDB não acha (id não resolvido, temporada fora do range, still nulo) ou
    quando o lote não termina a tempo. Episódio sem `numero` (rótulo não
    numérico, ex. "Especial") não tem como mapear pro TMDB — mantém o
    `thumb_url` original sem tentar.

    Mesma mecânica de concorrência/deadline de
    `api/servicos/capas.py::_consultar_capas`: `asyncio.wait` (não
    `wait_for`) pra aproveitar o que já terminou dentro do prazo; o que
    ainda estiver pendente é cancelado e a cancelação é aguardada antes de
    devolver — a *task* nunca some rodando solta.
    """
    indices_elegiveis = [indice for indice, ep in enumerate(episodios) if ep.numero is not None]
    if not indices_elegiveis:
        return episodios

    semaforo = asyncio.Semaphore(_CONCORRENCIA_STILLS)

    async def _buscar_um(indice: int) -> tuple[int, str | None]:
        episodio = episodios[indice]
        async with semaforo:
            try:
                still = await servico_metadados.buscar_still_de_episodio(
                    anime.titulo, anime.ano, episodio.numero
                )
            except Exception as excecao:
                # Captura ampla e intencional (mesmo espírito de
                # `api/servicos/capas.py::_consultar_um`): este overlay é
                # best-effort, nenhuma falha de provedor pode derrubar a
                # listagem nem os demais episódios do lote.
                logger.warning(
                    "overlay de still best-effort falhou pro episódio %s de %r: %s",
                    episodio.numero,
                    anime.titulo,
                    excecao,
                )
                return indice, None
        return indice, still

    tasks = [asyncio.ensure_future(_buscar_um(indice)) for indice in indices_elegiveis]
    concluidas, pendentes = await asyncio.wait(tasks, timeout=_TETO_LOTE_STILLS_S)
    if pendentes:
        for tarefa in pendentes:
            tarefa.cancel()
        await asyncio.gather(*pendentes, return_exceptions=True)

    resultado = list(episodios)
    for tarefa in concluidas:
        indice, still = tarefa.result()
        if still is not None:
            resultado[indice] = replace(resultado[indice], thumb_url=still)
    return resultado

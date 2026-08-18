"""Listagem de episódios na fonte remota (site) de um anime — permite a UI
"prontos vs. não capturados" da página do anime (Fase 4C do plano). Reusa a
mesma resolução de fonte e listagem de `api/servicos/jobs.py::criar_job_site`;
diferente dela, não persiste nenhum `Episodio`/`Job` — é só consulta.

Não importa `fastapi`: devolve `EpisodiosRemotosResultado` ou levanta erro de
`core/erros.py`; `api/rotas/animes.py` traduz para `HTTPException`/schemas.
"""

import asyncio
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.erros import FalhaDeExtracao, FonteAmbigua
from extractors.base import EpisodioRemoto
from extractors.resolucao import ConfirmacaoNecessaria, resolver_fonte_do_anime
from extractors.servico import listar_episodios_em
from models.anime import Anime

_SessionMaker = async_sessionmaker[AsyncSession]

# Mesmo teto de `api/servicos/jobs.py::_TETO_CRIACAO_SITE_S` — rede de segurança
# acima dos timeouts internos dos extratores, não a primeira linha de defesa.
_TETO_LISTAGEM_REMOTA_S = 60


@dataclass(frozen=True, slots=True)
class EpisodiosRemotosResultado:
    """`dominio` é o site que resolveu `episodios` — a rota (`api/rotas/animes.py`)
    expõe isto no contrato de saída (`EpisodiosRemotosSaida`) para o usuário
    poder notar quando a fonte "errada" foi resolvida."""

    dominio: str
    episodios: list[EpisodioRemoto]


async def listar_episodios_remotos(
    sessionmaker: _SessionMaker, anime: Anime
) -> EpisodiosRemotosResultado:
    """`anime` já carregado por quem chama (`api/rotas/animes.py`, que faz o 404
    de `anime_id` inexistente antes de chegar aqui — mesmo padrão das outras
    rotas que operam por id).

    `ConfirmacaoNecessaria` (mais de um candidato, sem match exato de título)
    vira `FonteAmbigua` — mesmo comportamento de
    `api/servicos/jobs.py::criar_job_site`; o cliente resolve via
    `POST /api/admin/animes/{id}/fontes/confirmar` e reenvia esta chamada.
    """
    try:
        resultado = await asyncio.wait_for(
            resolver_fonte_do_anime(sessionmaker, anime), timeout=_TETO_LISTAGEM_REMOTA_S
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

    return EpisodiosRemotosResultado(dominio=resultado.dominio, episodios=episodios)

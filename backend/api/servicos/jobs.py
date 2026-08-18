"""Criação de job nos dois modos (`local`, `site` — ESPECIFICACAO.md §5, Passo 4
do plano da Fase 3). Cancelamento/retry não têm serviço próprio: são uma
chamada só para `db/fila.py` (que já concentra toda a regra de verdade), então
`api/rotas/jobs.py` chama `db.fila` direto — "não criar serviço pass-through".

Não importa `fastapi`: devolve o `job_id` ou levanta erro de `core/erros.py`;
`api/rotas/jobs.py` traduz para `HTTPException`/schemas.
"""

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.enums import SITE_LOCAL, TipoEpisodio, VersaoEpisodio
from core.erros import FalhaDeExtracao, FonteAmbigua, FonteNaoEncontrada
from db import catalogo
from extractors.resolucao import ConfirmacaoNecessaria, resolver_fonte_do_anime
from extractors.servico import listar_episodios_em
from models.anime import Anime

_SessionMaker = async_sessionmaker[AsyncSession]

logger = logging.getLogger(__name__)

# Teto para a etapa de rede da criação de job em modo "site" (resolver fonte +
# listar episódios) — mesma filosofia de
# `extractors/servico.py::_TETO_ESPERA_CONFERENCIA_S`: rede de segurança acima
# dos timeouts internos dos extratores, não a primeira linha de defesa.
_TETO_CRIACAO_SITE_S = 60


async def criar_job_local(
    sessionmaker: _SessionMaker,
    *,
    anime: str,
    numero: int,
    tipo: TipoEpisodio,
    versao: VersaoEpisodio,
    caminho_local: str,
    titulo_episodio: str | None,
    ano: int | None,
    duracao_esperada_s: int | None,
) -> int:
    anime_id = await catalogo.obter_ou_criar_anime_id(sessionmaker, anime, ano)
    return await catalogo.criar_episodio_e_job(
        sessionmaker,
        anime_id,
        numero=numero,
        tipo=tipo,
        versao=versao,
        url_fonte=caminho_local,
        site_origem=SITE_LOCAL,
        titulo_episodio=titulo_episodio,
        duracao_esperada_s=duracao_esperada_s,
    )


async def criar_job_site(
    sessionmaker: _SessionMaker,
    *,
    anime: Anime,
    numero: int,
    tipo: TipoEpisodio,
    versao: VersaoEpisodio,
    duracao_esperada_s: int | None,
) -> int:
    """`anime` já carregado por quem chama (`api/rotas/jobs.py`, que faz o 404 de
    `anime_id` inexistente antes de chegar aqui — mesmo padrão das outras rotas
    que operam por id).

    `ConfirmacaoNecessaria` (mais de um candidato, sem match exato de título)
    vira `FonteAmbigua`; nenhum job é criado nesse caso — o cliente resolve via
    `POST /api/admin/animes/{id}/fontes/confirmar` e reenvia esta chamada.
    """
    try:
        resultado = await asyncio.wait_for(
            resolver_fonte_do_anime(sessionmaker, anime), timeout=_TETO_CRIACAO_SITE_S
        )
    except TimeoutError as excecao:
        raise FalhaDeExtracao(
            f"resolução de fonte excedeu o teto de {_TETO_CRIACAO_SITE_S}s",
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
        episodios_remotos = await asyncio.wait_for(
            listar_episodios_em(sessionmaker, resultado.dominio, resultado.identificador),
            timeout=_TETO_CRIACAO_SITE_S,
        )
    except TimeoutError as excecao:
        raise FalhaDeExtracao(
            f"listagem de episódios excedeu o teto de {_TETO_CRIACAO_SITE_S}s",
            dominio=resultado.dominio,
            permite_retentativa=True,
        ) from excecao
    correspondentes = [ep for ep in episodios_remotos if ep.numero == numero]
    if len(correspondentes) > 1:
        # Mais de um rótulo remoto mapeia pro mesmo `numero` (ex. "7"/"07" —
        # extractors/base.py::EpisodioRemoto) — o request só carrega `numero`
        # (int), sem como o cliente escolher o rótulo. Escolha determinística
        # (1ª ocorrência, ordem já estável do adapter) em vez de silenciosa —
        # nunca some do log.
        logger.warning(
            "%d episódios remotos com numero=%d em %r (rótulos: %s) — usando o 1º",
            len(correspondentes),
            numero,
            resultado.dominio,
            [ep.rotulo for ep in correspondentes],
        )
    correspondente = correspondentes[0] if correspondentes else None
    if correspondente is None:
        raise FonteNaoEncontrada(
            f"episódio {numero} não encontrado em {resultado.dominio} para {anime.titulo!r}",
            dominio=resultado.dominio,
        )

    return await catalogo.criar_episodio_e_job(
        sessionmaker,
        anime.id,
        numero=numero,
        tipo=tipo,
        versao=versao,
        url_fonte=correspondente.url,
        site_origem=resultado.dominio,
        duracao_esperada_s=duracao_esperada_s,
    )

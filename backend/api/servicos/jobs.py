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

from core.enums import SITE_LOCAL, TipoEpisodio, VersaoDeFonte, VersaoEpisodio
from core.erros import FalhaDeExtracao, FonteAmbigua, FonteNaoEncontrada, VersaoIndisponivelError
from db import catalogo
from extractors.resolucao import ConfirmacaoNecessaria, VersaoIndisponivel, resolver_fonte_do_anime
from extractors.servico import filtrar_por_numero_e_versao, listar_episodios_em
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

    `VersaoIndisponivel` (nenhum site serve `versao`) vira `VersaoIndisponivelError`
    — sem tratamento HTTP dedicado ainda (fase seguinte), propaga em vez de
    falhar silenciosamente tratando o resultado como `FonteResolvida`.

    Invariante: `Episodio.versao` (abaixo) NUNCA vem de `versao` (o pedido do
    cliente) direto — deriva de `resultado.versao_da_fonte`, a única fonte de
    verdade sobre o que a fonte resolvida realmente é.
    """
    try:
        resultado = await asyncio.wait_for(
            resolver_fonte_do_anime(sessionmaker, anime, versao), timeout=_TETO_CRIACAO_SITE_S
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
                    "versao": candidato.versao.value if candidato.versao else None,
                }
                for candidato in resultado.candidatos
            ],
        )
    if isinstance(resultado, VersaoIndisponivel):
        raise VersaoIndisponivelError(resultado.versao)

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
    # `Episodio.versao` deriva do que a fonte resolvida realmente é
    # (`resultado.versao_da_fonte`), nunca do `versao` pedido pelo cliente —
    # a invariante desta fase. Também usado para filtrar a listagem abaixo:
    # sem isso, um site que lista episódios das duas versões (mesmo risco de
    # `extractors/servico.py::_proximo_com_episodio`) poderia gravar a URL da
    # versão errada sob o rótulo certo.
    versao_do_episodio = versao_episodio_da_fonte(resultado.versao_da_fonte)

    correspondentes = filtrar_por_numero_e_versao(episodios_remotos, numero, versao_do_episodio)
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
        versao=versao_do_episodio,
        url_fonte=correspondente.url,
        site_origem=resultado.dominio,
        duracao_esperada_s=duracao_esperada_s,
    )


def versao_episodio_da_fonte(versao_da_fonte: VersaoDeFonte) -> VersaoEpisodio:
    """`VersaoDeFonte.NAO_DIFERENCIADA` vira sempre `VersaoEpisodio.DESCONHECIDA`
    — nunca herda o que o cliente pediu. `LEGENDADO`/`DUBLADO` convertem 1:1
    (mesmo valor de string por design, `core/enums.py`, mas enums separados
    de propósito — daí a conversão explícita em vez de reinterpretar um pelo
    outro).

    Pública (não `_`-prefixada) porque também é usada por
    `api/rotas/animes.py::obter_anime` para derivar
    `AnimeDetalheSaida.versao_confirmada_mais_recente`."""
    if versao_da_fonte == VersaoDeFonte.NAO_DIFERENCIADA:
        return VersaoEpisodio.DESCONHECIDA
    return VersaoEpisodio(versao_da_fonte.value)

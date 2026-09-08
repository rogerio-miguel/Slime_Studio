"""Resolução de fonte (site) + listagem de episódios de um anime. `resolver_e_
listar` é o núcleo comum de dois fluxos: esta `listar_episodios_remotos`
(exibição — a UI "prontos vs. não capturados" da página do anime, Fase 4C) e
`api/servicos/jobs.py::criar_job_site` (captura). `api/servicos/sondagem.py`
também consome `resolver_e_listar` direto.

O parâmetro `resolver_canonico` de `resolver_e_listar` formaliza a divergência
antes documentada como comentário (2026-09-07): a exibição (`True`) resolve os
títulos canônicos do anime na AniList ANTES da resolução de fonte e os passa
como `titulos_alternativos=` a `resolver_fonte_do_anime` — sem isso um site que
indexa o anime só pelo título inglês/romaji (ex. AnimeFire cataloga "Villainess
Level 99..." para *Akuyaku Reijou Level 99*) não é alcançado pela busca ao vivo
e a resolução cai pro próximo site. A captura (`False`) NÃO resolve canônico de
propósito: no fluxo normal a exibição roda antes, grava a `FonteAnime`, e a
captura só reusa o mapeamento.

`resolver_e_listar` não filtra por versão nem toca stills — cada chamador faz o
seu. `listar_episodios_remotos` não persiste `Episodio`/`Job` (é só consulta) e
sobrepõe, best-effort, a thumb de episódio do TMDB (Fatia 5 do
`PLANO_ARTE_TMDB.md`) sobre `EpisodioRemoto.thumb_url`.

Não importa `fastapi`: devolve dataclasses ou levanta erro de `core/erros.py`;
`api/rotas/animes.py` traduz para `HTTPException`/schemas.
"""

import asyncio
import logging
from dataclasses import dataclass, replace

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# `_referencias_de_anime` reusado de `busca.py` (mesmo par de módulos de
# orquestração cross-camada) — monta a lista slug-única de todos os nomes do
# anime, com o título cadastrado como âncora na posição 0.
from api.servicos.busca import _referencias_de_anime
from core.enums import VersaoDeFonte, VersaoEpisodio
from core.erros import FalhaDeExtracao, FonteAmbigua, VersaoIndisponivelError
from extractors.base import EpisodioRemoto
from extractors.resolucao import ConfirmacaoNecessaria, VersaoIndisponivel, resolver_fonte_do_anime
from extractors.servico import filtrar_por_versao, listar_episodios_em
from integrations import servico as servico_metadados
from integrations.base import TitulosDeAnime
from models.anime import Anime

logger = logging.getLogger(__name__)

_SessionMaker = async_sessionmaker[AsyncSession]

# Teto de cada etapa de rede de `resolver_e_listar` (resolução de fonte;
# listagem de episódios) — rede de segurança acima dos timeouts internos dos
# extratores, não a primeira linha de defesa. Vale para os três fluxos que
# passam por `resolver_e_listar`: exibição, captura e sondagem.
_TETO_LISTAGEM_REMOTA_S = 60

# Sub-teto só do round-trip de `buscar_titulos` (resolução do título canônico),
# consumido ANTES e FORA do `wait_for` de `_TETO_LISTAGEM_REMOTA_S` — mesmo
# arranjo e mesmo valor de `api/servicos/busca.py::_TETO_METADADOS_S`: uma
# AniList pendurada não pode segurar a resolução de fonte antes de ela começar.
_TETO_METADADOS_S = 9

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


@dataclass(frozen=True, slots=True)
class FonteComEpisodios:
    """Resultado de `resolver_e_listar` — a fonte resolvida mais a listagem crua
    da temporada, sem filtro de versão nem overlay de still. `versao_da_fonte` é
    o que a fonte resolvida realmente é (`extractors.resolucao.FonteResolvida`);
    a captura deriva `Episodio.versao` dela, nunca do que o cliente pediu."""

    dominio: str
    identificador: str
    versao_da_fonte: VersaoDeFonte
    episodios: list[EpisodioRemoto]


async def resolver_e_listar(
    sessionmaker: _SessionMaker,
    anime: Anime,
    versao: VersaoEpisodio,
    *,
    resolver_canonico: bool,
) -> FonteComEpisodios:
    """Resolve a fonte (site) de `anime` e lista os episódios da temporada
    `anime.numero_temporada` — o núcleo comum da exibição
    (`listar_episodios_remotos`), da captura (`api/servicos/jobs.py::
    criar_job_site`) e da sondagem (`api/servicos/sondagem.py`).

    `anime` já carregado por quem chama. `resolver_canonico`: ver a nota de
    módulo — `True` resolve os nomes canônicos na AniList (best-effort, teto
    próprio FORA do `wait_for`) e os passa como `titulos_alternativos`; `False`
    degrada para só o título cadastrado.

    `ConfirmacaoNecessaria` (mais de um candidato, sem match exato) vira
    `FonteAmbigua`; o cliente resolve via
    `POST /api/admin/animes/{id}/fontes/confirmar` e reenvia. `VersaoIndisponivel`
    vira `VersaoIndisponivelError`. Timeout de qualquer etapa de rede vira
    `FalhaDeExtracao` retentável (o orçamento é nosso, não uma falha do site).

    NÃO filtra por versão nem sobrepõe stills — cada chamador aplica o que
    precisa sobre `episodios`.
    """
    referencias: list[str] | None = None
    if resolver_canonico:
        titulos = await _resolver_titulos_canonicos(anime.titulo)
        referencias = _referencias_de_anime(titulos, anime.titulo)

    try:
        resolvida = await asyncio.wait_for(
            resolver_fonte_do_anime(
                sessionmaker, anime, versao, titulos_alternativos=referencias
            ),
            timeout=_TETO_LISTAGEM_REMOTA_S,
        )
    except TimeoutError as excecao:
        raise FalhaDeExtracao(
            f"resolução de fonte excedeu o teto de {_TETO_LISTAGEM_REMOTA_S}s",
            permite_retentativa=True,
        ) from excecao

    if isinstance(resolvida, ConfirmacaoNecessaria):
        raise FonteAmbigua(
            resolvida.dominio,
            [
                {
                    "titulo_exibicao": candidato.titulo_exibicao,
                    "identificador": candidato.identificador,
                    "url": candidato.url,
                    "versao": candidato.versao.value if candidato.versao else None,
                }
                for candidato in resolvida.candidatos
            ],
        )
    if isinstance(resolvida, VersaoIndisponivel):
        raise VersaoIndisponivelError(resolvida.versao)

    try:
        episodios = await asyncio.wait_for(
            listar_episodios_em(
                sessionmaker,
                resolvida.dominio,
                resolvida.identificador,
                anime.numero_temporada,
            ),
            timeout=_TETO_LISTAGEM_REMOTA_S,
        )
    except TimeoutError as excecao:
        raise FalhaDeExtracao(
            f"listagem de episódios excedeu o teto de {_TETO_LISTAGEM_REMOTA_S}s",
            dominio=resolvida.dominio,
            permite_retentativa=True,
        ) from excecao

    return FonteComEpisodios(
        dominio=resolvida.dominio,
        identificador=resolvida.identificador,
        versao_da_fonte=resolvida.versao_da_fonte,
        episodios=episodios,
    )


async def listar_episodios_remotos(
    sessionmaker: _SessionMaker, anime: Anime, versao: VersaoEpisodio
) -> EpisodiosRemotosResultado:
    """Listagem de EXIBIÇÃO da fonte remota — `resolver_e_listar` (com resolução
    canônica) mais os dois passos só-de-exibição: filtro de versão e overlay de
    still do TMDB.

    O adapter já devolveu a temporada de `anime.numero_temporada` numerada de 1
    (contrato de `ExtratorDeSite.listar_episodios`). `filtrar_por_versao`: uma
    página pode cobrir as duas versões (ex. AnimesDrive quando legendado e
    dublado compartilham a listagem) — sem o filtro, a grade misturaria a versão
    errada. Mesma proteção que a captura aplica (`filtrar_por_numero_e_versao`).
    """
    fonte = await resolver_e_listar(sessionmaker, anime, versao, resolver_canonico=True)
    episodios = filtrar_por_versao(fonte.episodios, versao)
    offset = await _offset_de_temporada(sessionmaker, anime)
    episodios = await _sobrepor_stills_de_episodios(anime, episodios, offset)
    return EpisodiosRemotosResultado(dominio=fonte.dominio, episodios=episodios)


async def _offset_de_temporada(sessionmaker: _SessionMaker, anime: Anime) -> int:
    """Nº absoluto do 1º episódio desta temporada na franquia, menos 1 — a soma
    de `total_episodios_anilist` das temporadas irmãs (mesmo `serie_ancora`) com
    `numero_temporada` menor. `0` para a 1ª temporada, anime sem `serie_ancora`,
    ou irmãs sem contagem.

    Serve só ao overlay de still: o TMDB às vezes modela a franquia inteira numa
    season só (ex. Kusuriya no Hitorigoto — 2 temporadas na AniList, 1 season de
    48 no TMDB), então pedir a still por `(numero_temporada, numero_por_temporada)`
    devolve vazio. Com o offset, o overlay pede pelo número ABSOLUTO e deixa a
    `TabelaDeTemporadas` do TMDB achar a season certa (funciona tanto pro TMDB
    achatado quanto pro dividido)."""
    if not anime.serie_ancora or not anime.numero_temporada or anime.numero_temporada <= 1:
        return 0
    async with sessionmaker() as sessao:
        total = await sessao.scalar(
            select(func.coalesce(func.sum(Anime.total_episodios_anilist), 0)).where(
                Anime.serie_ancora == anime.serie_ancora,
                Anime.numero_temporada.is_not(None),
                Anime.numero_temporada < anime.numero_temporada,
            )
        )
    return int(total or 0)


async def _resolver_titulos_canonicos(titulo: str) -> TitulosDeAnime | None:
    """Resolve os nomes canônicos de `titulo` na AniList
    (`integrations.servico.buscar_titulos` — percorre só `PROVEDORES_DE_TITULO`,
    Kitsu fora) para alimentar `_referencias_de_anime`, espelhando
    `api/servicos/busca.py::_resolver_titulos_canonicos`.

    Best-effort: qualquer falha (rede, timeout de `_TETO_METADADOS_S`, provedor
    fora do ar, formato inesperado) degrada para `None` e a resolução de fonte
    segue só com o título cadastrado como referência — o comportamento anterior
    a esta mudança. Captura ampla e intencional (CLAUDE.md §4 — degrada
    explícito com `logger.warning`, não silencioso): resolver o canônico é
    enriquecimento, não pré-condição; o provedor fora do ar não pode derrubar a
    listagem de episódios da fonte."""
    try:
        return await asyncio.wait_for(
            servico_metadados.buscar_titulos(titulo), timeout=_TETO_METADADOS_S
        )
    except Exception as excecao:
        logger.warning(
            "resolução de título canônico best-effort falhou para %r: %s", titulo, excecao
        )
        return None


async def _sobrepor_stills_de_episodios(
    anime: Anime, episodios: list[EpisodioRemoto], offset_de_temporada: int = 0
) -> list[EpisodioRemoto]:
    """Overlay best-effort de thumb TMDB (Fatia 5, `PLANO_ARTE_TMDB.md`) sobre
    `EpisodioRemoto.thumb_url`.

    Duas formas de pedir a still, conforme `offset_de_temporada` (ver
    `_offset_de_temporada`):

    - `> 0` (temporada 2+ de uma franquia): `numero` da fonte é por temporada;
      pede pelo ABSOLUTO (`offset + numero`, `temporada=None`) e deixa a
      `TabelaDeTemporadas` do TMDB achar a season — resiste ao TMDB que junta a
      franquia numa season só.
    - `0` (1ª temporada, ou franquia não resolvida): par
      `(episodio.numero, anime.numero_temporada)` — comportamento anterior.

    Preserva o `thumb_url` que o extractor já trouxe quando o TMDB não acha (id
    não resolvido, temporada fora do range, still nulo) ou quando o lote não
    termina a tempo. Episódio sem `numero` (rótulo não numérico, ex. "Especial")
    não tem como mapear pro TMDB — mantém o `thumb_url` original sem tentar.

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
        # offset > 0 (T2+ de franquia): pede pelo ABSOLUTO, `temporada=None`, e o
        # TMDB acha a season — resiste ao TMDB que junta a franquia numa season só.
        # offset 0: par `(numero_por_temporada, numero_temporada)`, direto à season.
        if offset_de_temporada:
            numero_tmdb, temporada_tmdb = offset_de_temporada + episodio.numero, None
        else:
            numero_tmdb, temporada_tmdb = episodio.numero, anime.numero_temporada
        async with semaforo:
            try:
                still = await servico_metadados.buscar_still_de_episodio(
                    anime.titulo, anime.ano, numero_tmdb, temporada_tmdb
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

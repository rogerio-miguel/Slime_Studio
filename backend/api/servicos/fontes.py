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
sobrepõe, best-effort (`stills_de_episodio.py`), a thumb/nome/sinopse de episódio
do TMDB sobre `EpisodioRemoto.thumb_url`/`titulo`/`sinopse`.

Não importa `fastapi`: devolve dataclasses ou levanta erro de `core/erros.py`;
`api/rotas/animes.py` traduz para `HTTPException`/schemas.
"""

import asyncio
import logging
from dataclasses import dataclass, replace

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.servicos.stills_de_episodio import sobrepor_stills_de_episodios
from api.servicos.temporadas import offset_de_temporada, total_das_partes_irmas
from api.servicos.titulos_canonicos import referencias_de_anime, resolver_titulos_canonicos
from core.enums import StatusLancamento, VersaoDeFonte, VersaoEpisodio
from core.erros import FalhaDeExtracao, FonteAmbigua, VersaoIndisponivelError
from fontes.adaptadores.base import EpisodioRemoto
from fontes.listagem import filtrar_por_versao, listar_episodios_em
from fontes.resolucao import (
    ConfirmacaoNecessaria,
    FonteResolvida,
    VersaoIndisponivel,
    fontes_mapeadas_alternativas,
    resolver_fonte_do_anime,
)
from models.anime import Anime

logger = logging.getLogger(__name__)

_SessionMaker = async_sessionmaker[AsyncSession]

# Teto de cada etapa de rede de `resolver_e_listar` (resolução de fonte;
# listagem de episódios) — rede de segurança acima dos timeouts internos dos
# extratores, não a primeira linha de defesa. Vale para os três fluxos que
# passam por `resolver_e_listar`: exibição, captura e sondagem.
_TETO_LISTAGEM_REMOTA_S = 60


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
    o que a fonte resolvida realmente é (`fontes.resolucao.FonteResolvida`);
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
    tentar_fontes_alternativas: bool = False,
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
    vira `VersaoIndisponivelError` — ou a falha de um site que não pôde ser consultado,
    pois então a versão não está provadamente ausente. Timeout de qualquer etapa de rede vira
    `FalhaDeExtracao` retentável (o orçamento é nosso, não uma falha do site).

    `tentar_fontes_alternativas` (só a sondagem liga): se listar a fonte escolhida
    falha, tenta as demais fontes JÁ MAPEADAS capazes da mesma versão, da mais
    recente para a mais antiga, e só então propaga o primeiro erro. A exibição e
    a captura seguem sem isto — lá o usuário escolheu a fonte e quer vê-la falhar.

    NÃO filtra por versão nem sobrepõe stills — cada chamador aplica o que
    precisa sobre `episodios`.
    """
    referencias: list[str] | None = None
    if resolver_canonico:
        titulos = await resolver_titulos_canonicos(anime.titulo)
        referencias = referencias_de_anime(titulos, anime.titulo)

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
        # Sites que não puderam ser consultados: não dá pra dizer que a versão
        # "não existe", então a falha deles sobe no lugar (ex. `SessaoRejeitada`
        # vira PRECISA_SESSAO na sondagem, `SiteEmCooldown` vira SITE_INDISPONIVEL).
        if resolvida.falha_principal is not None:
            raise resolvida.falha_principal
        raise VersaoIndisponivelError(resolvida.versao)

    resolvida, episodios = await _listar_com_alternativas(
        sessionmaker, anime, versao, resolvida, tentar_fontes_alternativas
    )

    episodios = await _recortar_se_fonte_achatada(sessionmaker, anime, episodios)

    return FonteComEpisodios(
        dominio=resolvida.dominio,
        identificador=resolvida.identificador,
        versao_da_fonte=resolvida.versao_da_fonte,
        episodios=episodios,
    )


async def _listar_episodios_da_fonte(
    sessionmaker: _SessionMaker, anime: Anime, fonte: FonteResolvida
) -> list[EpisodioRemoto]:
    try:
        return await asyncio.wait_for(
            listar_episodios_em(
                sessionmaker, fonte.dominio, fonte.identificador, anime.numero_temporada
            ),
            timeout=_TETO_LISTAGEM_REMOTA_S,
        )
    except TimeoutError as excecao:
        raise FalhaDeExtracao(
            f"listagem de episódios excedeu o teto de {_TETO_LISTAGEM_REMOTA_S}s",
            dominio=fonte.dominio,
            permite_retentativa=True,
        ) from excecao


async def _listar_com_alternativas(
    sessionmaker: _SessionMaker,
    anime: Anime,
    versao: VersaoEpisodio,
    escolhida: FonteResolvida,
    tentar_alternativas: bool,
) -> tuple[FonteResolvida, list[EpisodioRemoto]]:
    try:
        return escolhida, await _listar_episodios_da_fonte(sessionmaker, anime, escolhida)
    except FalhaDeExtracao as primeira_falha:
        if not tentar_alternativas:
            raise
        alternativas = await fontes_mapeadas_alternativas(
            sessionmaker, anime, versao, excluir_dominio=escolhida.dominio
        )
        for alternativa in alternativas:
            try:
                episodios = await _listar_episodios_da_fonte(sessionmaker, anime, alternativa)
            except FalhaDeExtracao as falha:
                logger.info(
                    "fonte alternativa %s também falhou para anime_id=%s: %s",
                    alternativa.dominio,
                    anime.id,
                    falha,
                )
                continue
            logger.info(
                "fonte %s falhou para anime_id=%s (%s); usando %s",
                escolhida.dominio,
                anime.id,
                primeira_falha,
                alternativa.dominio,
            )
            return alternativa, episodios
        raise primeira_falha


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
    offset = await offset_de_temporada(sessionmaker, anime)
    episodios = await sobrepor_stills_de_episodios(sessionmaker, anime, episodios, offset)
    return EpisodiosRemotosResultado(dominio=fonte.dominio, episodios=episodios)


def _episodios_esperados(anime: Anime) -> tuple[int, bool] | None:
    """`(quantidade, em_aberto)` de episódios que a AniList atribui a esta
    temporada. Temporada fechada: `total_episodios_anilist`. Temporada em
    exibição não tem total (a AniList devolve `None`), mas `proximo_ep_numero - 1`
    é quantos já foram ao ar — piso, não teto: a fonte pode estar à frente.
    `None` quando não há como saber."""
    if anime.total_episodios_anilist:
        return anime.total_episodios_anilist, False
    if (
        anime.status_lancamento is StatusLancamento.EM_LANCAMENTO
        and anime.proximo_ep_numero
        and anime.proximo_ep_numero > 1
    ):
        return anime.proximo_ep_numero - 1, True
    return None


async def _recortar_se_fonte_achatada(
    sessionmaker: _SessionMaker, anime: Anime, episodios: list[EpisodioRemoto]
) -> list[EpisodioRemoto]:
    """Corrige fonte "achatada": quando o adapter não teve sinal próprio de
    temporada (ex. AnimeFire sem `season` divergente por episódio) e devolveu
    a série inteira em vez de recortar (`ExtratorDeSite.listar_episodios`,
    degradação documentada em `fontes/adaptadores/base.py`).

    Detecção: nº de episódios com `numero` distinto excede o que a AniList
    atribui à temporada (`_episodios_esperados`) — sinal de que o recorte nativo
    não rodou. Em temporada em exibição a fonte pode legitimamente estar 1
    episódio à frente da AniList, então a detecção só dispara com folga de 1 e
    só quando há temporadas anteriores (`offset > 0`): sem elas não há o que
    cortar.
    Corte: mesmo offset acumulado de `offset_de_temporada` (soma de
    `total_episodios_anilist` das temporadas irmãs anteriores), aplicado como
    intervalo absoluto sobre `numero` — reaproveita o `numero` cru da fonte
    (que nesse caso é a numeração contínua da série, não 1-based) sem
    reescrever `rotulo` (chave de dedup do adapter). Temporada fechada corta
    também o teto (`offset + total`); em exibição fica sem teto, porque os
    próximos episódios a estrear ainda pertencem a ela.

    Lista que o adapter já recortou pelo marcador da fonte
    (`EpisodioRemoto.recortado_pela_fonte`) não passa pelo corte por offset (que a
    reduziria ao excedente); só perde o que passa do total da AniList, em
    temporada fechada (`_aparar_excedente_de_temporada_fechada`).

    Sem contagem esperada ou sem temporada pedida (`numero_temporada` nulo) não
    há como decidir — devolve `episodios` intacto, mesma degradação segura que o
    adapter já aplica.

    Episódios com `numero=None` (rótulo não-numérico, ex. "Especial"/"OVA 2")
    não entram no recorte por número (não têm como ser atribuídos a uma
    temporada) — preservados sempre, mesmo comportamento de antes desta
    correção."""
    esperados = _episodios_esperados(anime)
    if anime.numero_temporada is None or esperados is None:
        return episodios
    total_temporada, em_aberto = esperados

    if any(ep.recortado_pela_fonte for ep in episodios):
        return await _aparar_excedente_de_temporada_fechada(
            sessionmaker, anime, episodios, total_temporada, em_aberto
        )

    numeros = {ep.numero for ep in episodios if ep.numero is not None}
    folga = 1 if em_aberto else 0
    if len(numeros) <= total_temporada + folga:
        return episodios
    # Só aqui, porque a consulta varre o catálogo: a AniList às vezes divide uma
    # temporada em "Part 1"/"Part 2" (linhas separadas, mesmo `numero_temporada`)
    # enquanto o site serve as duas juntas — o total da temporada é a soma.
    if not em_aberto:
        total_temporada += await total_das_partes_irmas(sessionmaker, anime)
        if len(numeros) <= total_temporada:
            return episodios

    offset = await offset_de_temporada(sessionmaker, anime)
    if em_aberto and offset == 0:
        return episodios
    teto = None if em_aberto else offset + total_temporada

    def _no_intervalo(ep: EpisodioRemoto) -> bool:
        return ep.numero is not None and ep.numero > offset and (teto is None or ep.numero <= teto)

    if not any(_no_intervalo(ep) for ep in episodios):
        if offset > 0 and max(numeros) <= offset:
            # Lista mais longa que a temporada e inteira dentro das anteriores: é
            # o conteúdo delas (ex. dublado do MeusAnimes só com a T1, que o
            # adapter devolve inteiro por ter uma única temporada carimbada).
            logger.info(
                "fonte para %r temporada %d só tem episódios de temporadas anteriores "
                "(%d distintos, máx %d <= offset %d) — temporada ausente na fonte",
                anime.titulo,
                anime.numero_temporada,
                len(numeros),
                max(numeros),
                offset,
            )
            return [ep for ep in episodios if ep.numero is None]
        logger.warning(
            "fonte achatada para %r temporada %d (%d episódios distintos > %d "
            "esperados pela AniList) mas offset acumulado (%d) não cobriu nenhum "
            "episódio — mantendo lista sem recorte",
            anime.titulo,
            anime.numero_temporada,
            len(numeros),
            total_temporada,
            offset,
        )
        return episodios

    recortados = [
        replace(ep, numero=ep.numero - offset) if _no_intervalo(ep) else ep
        for ep in episodios
        if ep.numero is None or _no_intervalo(ep)
    ]
    logger.info(
        "fonte achatada para %r temporada %d (%d episódios distintos > %d "
        "esperados pela AniList) — recortada por offset acumulado (%d) para %d "
        "episódios",
        anime.titulo,
        anime.numero_temporada,
        len(numeros),
        total_temporada,
        offset,
        len(recortados),
    )
    return recortados


async def _aparar_excedente_de_temporada_fechada(
    sessionmaker: _SessionMaker,
    anime: Anime,
    episodios: list[EpisodioRemoto],
    total_temporada: int,
    em_aberto: bool,
) -> list[EpisodioRemoto]:
    """Descarta o que a fonte arquiva além do total da AniList numa temporada
    fechada — OVAs/especiais que o site (ex. MeusAnimes) guarda como "episódio
    13…16" da temporada: não existem no TMDB nem na AniList como episódio dela e
    chegariam à grade sem nome, sinopse nem still. Temporada em exibição não tem
    teto (a fonte pode estar à frente). Rótulo não numérico (`numero=None`) fica."""
    if em_aberto or all(ep.numero is None or ep.numero <= total_temporada for ep in episodios):
        return episodios
    teto = total_temporada + await total_das_partes_irmas(sessionmaker, anime)
    return [ep for ep in episodios if ep.numero is None or ep.numero <= teto]

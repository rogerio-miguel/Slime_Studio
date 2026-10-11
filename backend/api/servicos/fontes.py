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
sobrepõe, best-effort, a thumb/nome/sinopse de episódio do TMDB (Fatia 5/6 do
`PLANO_ARTE_TMDB.md`) sobre `EpisodioRemoto.thumb_url`/`titulo`/`sinopse`.

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
from api.servicos.catalogo import agrupar_franquias
from core.enums import StatusLancamento, VersaoDeFonte, VersaoEpisodio
from core.erros import FalhaDeExtracao, FonteAmbigua, VersaoIndisponivelError
from extractors.base import EpisodioRemoto
from extractors.resolucao import (
    ConfirmacaoNecessaria,
    FonteResolvida,
    VersaoIndisponivel,
    fontes_mapeadas_alternativas,
    resolver_fonte_do_anime,
)
from extractors.servico import filtrar_por_versao, listar_episodios_em
from integrations import servico as servico_metadados
from integrations.base import InfoDeEpisodio, TitulosDeAnime
from models.anime import Anime
from models.episodio import Episodio

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

# Teto do lookup de UM episódio (`info_de_episodio`, usado na captura — ver
# `api/servicos/jobs.py`) — mesma ordem de grandeza de `_TETO_METADADOS_S`,
# fora do lote, então sem a proteção do `asyncio.wait(timeout=...)` acima.
_TETO_STILL_UNICO_S = 9


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
    vira `VersaoIndisponivelError`. Timeout de qualquer etapa de rede vira
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
    offset = await _offset_de_temporada(sessionmaker, anime)
    episodios = await _sobrepor_stills_de_episodios(sessionmaker, anime, episodios, offset)
    return EpisodiosRemotosResultado(dominio=fonte.dominio, episodios=episodios)


async def _titulo_base_da_franquia(sessionmaker: _SessionMaker, anime: Anime) -> str:
    """Título a usar na busca de arte/still/nome/sinopse do TMDB — o nome BASE
    da franquia, sem o marcador de temporada, quando ele existir.

    `core/temporada.py::separar_temporada` (usado por dentro de
    `integrations/servico.py::buscar_arte_por_titulo`) só reconhece marcadores
    com palavra-chave ("Season 2", "2ª Temporada", "Part 2", "II"/"III"/"IV")
    — de propósito: um dígito solto no fim é ambíguo demais pra cortar sem
    contexto (cortaria "86" ou "91 Days"). Mas alguns títulos da própria
    AniList são exatamente esse caso ambíguo resolvido a favor do anime errado
    aqui: "Komi-san wa, Komyushou desu. 2" (a T2) não tem NENHUM marcador que a
    regex reconheça, então o TMDB era consultado com o "2" sobrando, não
    achava a série, e o still/nome/sinopse de todo episódio da T2 ficava
    `None` (capa/banner não são afetados — vêm da AniList direto, não do TMDB).

    Em vez de arriscar a regex genérica (afetaria TODOS os títulos, não só os
    de franquia), usa o dado que já temos com certeza: o título da temporada
    ÂNCORA (`Anime.serie_ancora`, o `anilist_id` da T1) NUNCA tem marcador de
    temporada por definição — é a própria T1. Quando a âncora está catalogada
    localmente, seu título já é a base certa da franquia inteira, sem precisar
    adivinhar via regex.

    Sem `serie_ancora`, com a âncora sendo o próprio anime (T1 catalogando a
    si mesma), ou com a âncora ainda não catalogada localmente, degrada para
    `anime.titulo` — mesmo comportamento de antes desta correção."""
    if anime.serie_ancora is None or anime.serie_ancora == anime.anilist_id:
        return anime.titulo
    async with sessionmaker() as sessao:
        titulo_ancora = await sessao.scalar(
            select(Anime.titulo).where(Anime.anilist_id == anime.serie_ancora)
        )
    return titulo_ancora if titulo_ancora is not None else anime.titulo


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


async def _total_das_partes_irmas(sessionmaker: _SessionMaker, anime: Anime) -> int:
    """Soma de `total_episodios_anilist` das OUTRAS linhas TV da mesma franquia
    com o mesmo `numero_temporada` (ex. "2nd Season" e "2nd Season Part 2").
    Agrupa por `agrupar_franquias` (slug do título base OU `serie_ancora`), não
    só por `serie_ancora`, que nessas partes costuma divergir."""
    if anime.numero_temporada is None or anime.formato_midia is not None:
        return 0
    async with sessionmaker() as sessao:
        grupos = await agrupar_franquias(sessao)
    return sum(
        linha.total_episodios_anilist or 0
        for linha in grupos.get(anime.id, [])
        if linha.id != anime.id
        and linha.numero_temporada == anime.numero_temporada
        and linha.formato_midia is None
    )


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
    degradação documentada em `extractors/base.py`).

    Detecção: nº de episódios com `numero` distinto excede o que a AniList
    atribui à temporada (`_episodios_esperados`) — sinal de que o recorte nativo
    não rodou. Em temporada em exibição a fonte pode legitimamente estar 1
    episódio à frente da AniList, então a detecção só dispara com folga de 1 e
    só quando há temporadas anteriores (`offset > 0`): sem elas não há o que
    cortar.
    Corte: mesmo offset acumulado de `_offset_de_temporada` (soma de
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
        total_temporada += await _total_das_partes_irmas(sessionmaker, anime)
        if len(numeros) <= total_temporada:
            return episodios

    offset = await _offset_de_temporada(sessionmaker, anime)
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
    teto = total_temporada + await _total_das_partes_irmas(sessionmaker, anime)
    return [ep for ep in episodios if ep.numero is None or ep.numero <= teto]


async def _info_do_tmdb(
    anime: Anime, titulo_base: str, numero: int, temporada: int | None
) -> InfoDeEpisodio | None:
    """`buscar_info_de_episodio` pelo título da franquia e, se o TMDB não achar a
    série, pelo `titulo_ingles`. O TMDB indexa muita série asiática só pelo nome
    inglês/nativo ("Above Myriads"), nunca pelo romaji da AniList ("Wan Ren Zhi
    Shang") — sem esta reserva todo episódio caía no banner, sem nome nem still,
    mesmo com a série completa no TMDB. Mesma ordem inglês→romaji do overlay de
    banner (`integrations/servico.py`), aqui com o romaji primeiro porque é o que
    já casa a maioria das séries."""
    info = await servico_metadados.buscar_info_de_episodio(
        titulo_base, anime.ano, numero, temporada
    )
    if info is None and anime.titulo_ingles and anime.titulo_ingles != titulo_base:
        info = await servico_metadados.buscar_info_de_episodio(
            anime.titulo_ingles, anime.ano, numero, temporada
        )
    return info


async def _info_direto_ou_absoluto(
    anime: Anime, titulo_base: str, numero: int, offset_de_temporada: int
) -> InfoDeEpisodio | None:
    """Still/nome/sinopse TMDB de um episódio: tenta primeiro o par DIRETO
    (`numero` dentro da temporada, `anime.numero_temporada`) — o caso comum,
    onde o TMDB tem uma season própria pra cada temporada da AniList. Só cai
    pro número ABSOLUTO (`offset_de_temporada + numero`, `temporada=None`)
    quando o direto não acha nada E há offset pra tentar — a franquia
    "achatada" numa season só no TMDB (ex. Kusuriya no Hitorigoto — 2
    temporadas na AniList, 1 season de 48 no TMDB).

    Direto primeiro, não o inverso: `offset_de_temporada` (`_offset_de_
    temporada`) só soma `total_episodios_anilist` das temporadas irmãs JÁ
    CATALOGADAS localmente com o mesmo `serie_ancora` — uma irmã anterior
    ainda não catalogada (comum: só as temporadas mais recentes de uma
    franquia longa costumam estar no catálogo) faz a soma sair sub-contada, e
    o número absoluto calculado cai sobre a info de OUTRO episódio (real,
    mas do lugar errado da série) em vez de vir vazio. Tentar o direto antes
    evita esse erro de atribuição sempre que o TMDB de fato tem a temporada
    separada — só recorre ao absoluto (com o mesmo risco de offset incompleto
    de sempre) quando o direto genuinamente não encontra a temporada.

    `titulo_base` (`_titulo_base_da_franquia`) substitui `anime.titulo` nas
    duas chamadas — título de temporada sem marcador reconhecível (ex.
    "Nome. 2", número solto) faria o TMDB não achar a série nenhuma vez."""
    info = await _info_do_tmdb(anime, titulo_base, numero, anime.numero_temporada)
    if info is not None or not offset_de_temporada:
        return info
    return await _info_do_tmdb(anime, titulo_base, offset_de_temporada + numero, None)


async def info_de_episodio(
    sessionmaker: _SessionMaker, anime: Anime, numero: int
) -> InfoDeEpisodio | None:
    """Still/nome/sinopse TMDB de UM episódio — usado na CAPTURA
    (`api/servicos/jobs.py`) pra gravar `Episodio.capa_path`/`titulo`/
    `sinopse`, ao contrário de `_sobrepor_stills_de_episodios` (lote,
    exibição). Mesma estratégia direto-depois-absoluto de `_info_direto_ou_
    absoluto`; sem a concorrência/semáforo do lote, só um episódio.
    `_offset_de_temporada` (consulta ao banco) só roda quando o direto falha
    — poupa a consulta no caso comum.

    Best-effort com teto próprio (`_TETO_STILL_UNICO_S`, fora do `_chamar`
    interno de `integrations/servico.py`), um por tentativa: qualquer
    falha/timeout vira `None` e é logada — a captura não pode travar nem
    falhar por causa de thumb/sinopse."""
    try:
        titulo_base = await _titulo_base_da_franquia(sessionmaker, anime)
        info = await asyncio.wait_for(
            _info_do_tmdb(anime, titulo_base, numero, anime.numero_temporada),
            timeout=_TETO_STILL_UNICO_S,
        )
        if info is not None:
            return info

        offset = await _offset_de_temporada(sessionmaker, anime)
        if not offset:
            return None
        return await asyncio.wait_for(
            _info_do_tmdb(anime, titulo_base, offset + numero, None),
            timeout=_TETO_STILL_UNICO_S,
        )
    except Exception as excecao:
        logger.warning(
            "info TMDB best-effort falhou pro episódio %s de %r na captura: %s",
            numero,
            anime.titulo,
            excecao,
        )
        return None


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
    sessionmaker: _SessionMaker,
    anime: Anime,
    episodios: list[EpisodioRemoto],
    offset_de_temporada: int = 0,
) -> list[EpisodioRemoto]:
    """Overlay best-effort de thumb/nome/sinopse TMDB (Fatia 5/6,
    `PLANO_ARTE_TMDB.md`) sobre `EpisodioRemoto.thumb_url`/`titulo`/`sinopse`.

    Cada episódio tenta primeiro o par DIRETO (`episodio.numero`,
    `anime.numero_temporada`) e só cai pro ABSOLUTO (`offset_de_temporada +
    numero`, `temporada=None`, deixando a `TabelaDeTemporadas` do TMDB achar a
    season) quando o direto não acha nada — ver `_info_direto_ou_absoluto`
    pro porquê dessa ordem (offset incompleto de uma temporada irmã ainda não
    catalogada localmente já causou still de episódio ERRADO, não só ausente).

    O fallback de THUMB quando o TMDB não acha (id não resolvido, temporada
    fora do range, still nulo) ou quando o lote não termina a tempo é a arte
    do PRÓPRIO anime (`anime.banner_path` ou `anime.capa_path`) — NUNCA MAIS o
    `thumb_url` que o extractor trouxe (pedido explícito do usuário: thumb de
    episódio não vem mais da fonte de scraping, só do TMDB ou da arte do
    anime já catalogada). `titulo`/`sinopse` não têm fallback equivalente
    (nenhum extractor os expõe) — ficam `None` quando o TMDB não acha ou não
    tem tradução pt-BR. Episódio sem `numero` (rótulo não numérico, ex.
    "Especial") não tem como mapear pro TMDB — cai direto no fallback, sem
    tentar.

    Mesma mecânica de concorrência/deadline de
    `api/servicos/capas.py::_consultar_capas`: `asyncio.wait` (não
    `wait_for`) pra aproveitar o que já terminou dentro do prazo; o que
    ainda estiver pendente é cancelado e a cancelação é aguardada antes de
    devolver — a *task* nunca some rodando solta.
    """
    fallback = anime.banner_path or anime.capa_path
    resultado = [replace(ep, thumb_url=fallback) for ep in episodios]

    indices_elegiveis = [indice for indice, ep in enumerate(episodios) if ep.numero is not None]
    if not indices_elegiveis:
        return resultado

    titulo_base = await _titulo_base_da_franquia(sessionmaker, anime)
    semaforo = asyncio.Semaphore(_CONCORRENCIA_STILLS)

    async def _buscar_um(indice: int) -> tuple[int, InfoDeEpisodio | None]:
        episodio = episodios[indice]
        async with semaforo:
            try:
                info = await _info_direto_ou_absoluto(
                    anime, titulo_base, episodio.numero, offset_de_temporada
                )
            except Exception as excecao:
                # Captura ampla e intencional (mesmo espírito de
                # `api/servicos/capas.py::_consultar_um`): este overlay é
                # best-effort, nenhuma falha de provedor pode derrubar a
                # listagem nem os demais episódios do lote.
                logger.warning(
                    "overlay de still/nome/sinopse best-effort falhou pro episódio %s de %r: %s",
                    episodio.numero,
                    anime.titulo,
                    excecao,
                )
                return indice, None
        return indice, info

    tasks = [asyncio.ensure_future(_buscar_um(indice)) for indice in indices_elegiveis]
    concluidas, pendentes = await asyncio.wait(tasks, timeout=_TETO_LOTE_STILLS_S)
    if pendentes:
        for tarefa in pendentes:
            tarefa.cancel()
        await asyncio.gather(*pendentes, return_exceptions=True)

    infos_por_numero: dict[int, InfoDeEpisodio] = {}
    for tarefa in concluidas:
        indice, info = tarefa.result()
        if info is None:
            continue
        resultado[indice] = replace(
            resultado[indice],
            thumb_url=info.still_url or fallback,
            titulo=info.nome,
            sinopse=info.sinopse,
        )
        infos_por_numero[episodios[indice].numero] = info

    await _atualizar_textos_gravados(sessionmaker, anime, infos_por_numero)
    return resultado


def _texto_atualizado(gravado: str | None, novo: str | None, novo_em_fallback: bool) -> str | None:
    """Texto a persistir: `novo` só substitui o gravado quando é pt-BR de verdade
    (ex. o TMDB ganhou a tradução desde a captura); em fallback (en-US) só
    preenche um campo vazio — nunca regride um texto melhor já gravado. `None`
    nunca apaga."""
    if novo is None:
        return gravado
    if gravado is None or not novo_em_fallback:
        return novo
    return gravado


async def _atualizar_textos_gravados(
    sessionmaker: _SessionMaker, anime: Anime, infos_por_numero: dict[int, InfoDeEpisodio]
) -> None:
    """Alinha `Episodio.titulo`/`sinopse` já gravados com o que o overlay acabou
    de resolver — "Continuar assistindo" lê só o valor gravado, então sem isto
    um nome em inglês de fallback ficaria pra sempre depois que o TMDB ganha o
    pt-BR. Best-effort: a listagem não pode falhar por causa disto."""
    if not infos_por_numero:
        return
    try:
        async with sessionmaker() as sessao:
            locais = await sessao.scalars(
                select(Episodio).where(
                    Episodio.anime_id == anime.id, Episodio.numero.in_(infos_por_numero)
                )
            )
            for episodio in locais:
                info = infos_por_numero[episodio.numero]
                episodio.titulo = _texto_atualizado(
                    episodio.titulo, info.nome, info.nome_em_fallback
                )
                episodio.sinopse = _texto_atualizado(
                    episodio.sinopse, info.sinopse, info.sinopse_em_fallback
                )
            await sessao.commit()
    except Exception as excecao:
        logger.warning(
            "atualização best-effort de título/sinopse gravados falhou pro anime %r: %s",
            anime.titulo,
            excecao,
        )

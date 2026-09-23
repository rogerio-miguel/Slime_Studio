"""Orquestração de metadados externos (`integrations/`) com o catálogo local
— mesmo papel de `api/servicos/fontes.py`, mas para `integrations/servico.py`
em vez de `extractors/`. Não importa `fastapi` nem Pydantic (regra de
dependência da Clean Architecture, CLAUDE.md §1); `api/rotas/animes.py`
traduz para schemas.
"""

import asyncio
import logging
import re
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.enums import StatusLancamento
from core.erros import FalhaDeMetadados
from core.temporada import PosicaoNaSerie, conciliar_posicao, separar_temporada
from core.texto import slugificar
from db.catalogo import (
    aplicar_lancamento_descoberto_por_titulo,
    aplicar_metadados,
    aplicar_posicao_na_serie,
    atualizar_lancamento,
    atualizar_lancamentos_em_lote,
    localizar_animes_por_anilist_id,
    localizar_animes_por_slug,
    preencher_banner_visual_em_lote,
    sobrescrever_arte,
)
from extractors.versao import remover_marcador_de_versao
from integrations import servico
from integrations.base import AnimeEmAlta, ArteDeAnime, MetadadosDeAnime
from models.anime import Anime

logger = logging.getLogger(__name__)

_SessionMaker = async_sessionmaker[AsyncSession]

# F4/F14 — aquecimento oportunista do estado de lançamento. Sem scheduler/cron
# (decisão de produto): o dado só é atualizado em três momentos de "carona":
#   1. o cruzamento do feed "em alta" (F4a, de graça: o feed já traz o bloco
#      fresco da AniList);
#   2. a abertura da página de um anime, ou a listagem do catálogo, para animes
#      COM `anilist_id` e dado mais velho que este TTL (F4b/F14, busca lazy por
#      id: `servico.buscar_lancamento_por_anilist_id`);
#   3. a listagem do catálogo, para animes SEM `anilist_id` (F14, busca lazy por
#      TÍTULO: `servico.buscar_por_titulo`, cadeia AniList→Kitsu) — senão esses
#      animes ficam com `status_lancamento` NULL para sempre e o badge de
#      "episódios novos" nunca dispara.
_TTL_LANCAMENTO_S = 6 * 3600

# Referência forte às buscas lazy em andamento: (1) deduplica aberturas
# concorrentes da mesma página / passadas do catálogo e (2) impede o GC de
# coletar uma `Task` fire-and-forget antes de ela terminar. A entrada sai no
# `add_done_callback`. Compartilhado pelos caminhos 2 e 3 acima — as listas de
# candidatos de cada um são disjuntas (um anime tem OU não tem `anilist_id`).
_refreshs_de_lancamento_em_voo: dict[int, asyncio.Task] = {}

# F14 — teto de animes por listagem de catálogo que disparam busca à AniList
# para aquecer o `status_lancamento`. Segura o rate limit num catálogo grande;
# em poucas visitas o catálogo inteiro esquenta.
_MAX_REFRESHS_DE_LANCAMENTO_POR_LOTE = 5

# F14 — teto próprio (e menor) das buscas por TÍTULO por listagem: cada uma
# custa até 2 round-trips (AniList + fallback Kitsu) contra 1 da busca por id,
# então tem orçamento independente. Pior caso por listagem: 5 (id) + 2 (título).
_MAX_BUSCAS_POR_TITULO_POR_LOTE = 2

# Segmento entre parênteses/colchetes no título local — os sites de extração
# marcam versão assim ("Nome (Dublado)"), fora da fronteira de token que
# `remover_marcador_de_versao` exige. `_termo_de_busca` remove o segmento
# inteiro antes de buscar metadados.
_REGEX_SEGMENTO_PARENTETICO = re.compile(r"[([][^)\]]*[)\]]")

# Sentinel *aware* para ordenar animes sem carimbo antes dos demais.
_CARIMBO_MINIMO = datetime.min.replace(tzinfo=UTC)

# Teto do enriquecimento best-effort no cadastro manual — a criação do anime
# é o objetivo primário; este valor é a rede de segurança que garante que o
# cadastro nunca fica preso esperando um provedor externo responder.
#
# `servico.buscar_por_titulo` pode tentar AniList e, se falhar, Kitsu, em
# sequência — cada um com até `integrations.servico._TIMEOUT_POR_PROVEDOR_S`
# (8s) de `wait_for`. Pior caso plausível: 8s + 8s = 16s, mais margem real
# acima disso (overhead de `asyncio.to_thread`/agendamento) para nunca ser o
# primeiro a estourar em condições normais — 18s.
_TETO_ENRIQUECIMENTO_S = 18

# Teto do walk de `relations` (`servico.resolver_serie`) no enriquecimento da
# materialização. Cada hop é uma chamada AniList sob o timeout por provedor de
# `integrations/`; o `_memo_serie` de processo faz a franquia inteira custar ~1
# caminhada depois da primeira. Best-effort como `_resolver_titulos_canonicos`
# — nunca bloqueia a criação do anime, que já aconteceu antes desta chamada.
_TETO_SERIE_S = 12


async def listar_em_alta_com_catalogo(
    sessionmaker: _SessionMaker,
) -> list[tuple[AnimeEmAlta, int | None]]:
    """Feed "em alta" (`integrations.servico.listar_em_alta`) pareado com
    `Anime.id` local (`_cruzar_com_catalogo`), quando o anime já está
    catalogado. Propaga `FalhaDeMetadados` se os provedores falharem — a rota
    pública nunca deve devolver `[]` como se fosse "sem lançamentos" quando na
    verdade os provedores estão fora do ar.

    Extra em relação a `listar_proxima_temporada_com_catalogo`: dispara o
    refresh oportunista de lançamento (F4a) — o feed "em alta" já traz o bloco
    fresco da AniList e o anime cruzado costuma estar em lançamento."""
    itens = await servico.listar_em_alta()
    pares = await _cruzar_com_catalogo(sessionmaker, itens)
    await _refrescar_lancamentos_do_cruzamento(sessionmaker, pares)
    await _preencher_banner_do_cruzamento(sessionmaker, pares)
    return pares


async def listar_novos_lancamentos_com_catalogo(
    sessionmaker: _SessionMaker,
) -> list[tuple[AnimeEmAlta, int | None]]:
    """Feed "novos lançamentos" (`integrations.servico.listar_novos_lancamentos`)
    pareado com `Anime.id` local. Mesmo formato/propagação de erro de
    `listar_em_alta_com_catalogo` — inclusive o refresh oportunista de
    lançamento (F4a): cada item aqui É um anime que acabou de ter um episódio
    ao ar, então o bloco fresco da AniList vale tanto quanto no feed "em alta"."""
    itens = await servico.listar_novos_lancamentos()
    pares = await _cruzar_com_catalogo(sessionmaker, itens)
    await _refrescar_lancamentos_do_cruzamento(sessionmaker, pares)
    await _preencher_banner_do_cruzamento(sessionmaker, pares)
    return pares


async def listar_fileiras_tematicas_com_catalogo(
    sessionmaker: _SessionMaker,
) -> list[tuple[str, list[tuple[AnimeEmAlta, int | None]]]]:
    """As fileiras temáticas da Home (`integrations.servico.
    listar_fileiras_tematicas`, quantidade e conteúdo vêm de
    `integrations/registro.py::FILEIRAS_TEMATICAS`) pareadas com `Anime.id`
    local. Achata os itens de todas as fileiras antes de cruzar
    (`_cruzar_com_catalogo`) — uma única consulta ao catálogo para todas as
    fileiras, não uma por fileira — e reagrupa de volta na mesma ordem/tamanho
    original de cada fileira.

    Sem o refresh oportunista de lançamento/banner de
    `listar_em_alta_com_catalogo` (F4a): esse efeito colateral existe porque o
    feed "em alta" traz um bloco de lançamento fresco e o item cruzado costuma
    estar em lançamento; popularidade histórica por tag/gênero não tem essa
    mesma correlação, e replicar o refresh aqui multiplicaria as escritas à
    toa.

    Propaga `FalhaDeMetadados` só se `listar_fileiras_tematicas` propagar
    (todas as fileiras falharam) — uma fileira isolada que falhou já vem
    omitida do dict de entrada, então some da lista de saída também."""
    por_fileira = await servico.listar_fileiras_tematicas()

    achatados: list[AnimeEmAlta] = []
    tamanhos: list[tuple[str, int]] = []
    for chave, itens in por_fileira.items():
        achatados.extend(itens)
        tamanhos.append((chave, len(itens)))

    pares_achatados = await _cruzar_com_catalogo(sessionmaker, achatados)

    resultado = []
    cursor = 0
    for chave, tamanho in tamanhos:
        resultado.append((chave, pares_achatados[cursor : cursor + tamanho]))
        cursor += tamanho
    return resultado


async def listar_proxima_temporada_com_catalogo(
    sessionmaker: _SessionMaker,
) -> list[tuple[AnimeEmAlta, int | None]]:
    """Feed "próxima temporada" (`integrations.servico.listar_proxima_temporada`)
    pareado com `Anime.id` local, quando o anime já está catalogado. Propaga
    `FalhaDeMetadados` se os provedores falharem — mesma razão de
    `listar_em_alta_com_catalogo`: a rota pública nunca devolve `[]` como se
    fosse "temporada vazia" quando os provedores estão fora do ar.

    Sem o refresh oportunista de lançamento de `listar_em_alta_com_catalogo`
    (F4a): animes que ainda não estrearam raramente estão catalogados, e o
    bloco de lançamento de um título não-lançado muda pouco — o cruzamento
    seco basta."""
    itens = await servico.listar_proxima_temporada()
    return await _cruzar_com_catalogo(sessionmaker, itens)


async def listar_busca_com_catalogo(
    sessionmaker: _SessionMaker, titulo: str
) -> list[tuple[AnimeEmAlta, int | None]]:
    """Busca livre do usuário (`integrations.servico.listar_por_busca`, só a
    AniList) pareada com `Anime.id` local — alimenta a busca da Home
    (`GET /api/animes/buscar`).

    Ao contrário dos feeds acima, NÃO propaga `FalhaDeMetadados`: a camada de
    `integrations/` já degrada AniList fora do ar para `[]` (busca do usuário,
    não pode quebrar a Home). Sem refresh oportunista de lançamento — resultado
    de busca é transitório, o anime cruzado nem sempre está em lançamento."""
    itens = await servico.listar_por_busca(titulo)
    return await _cruzar_com_catalogo(sessionmaker, itens)


async def listar_relacionados_com_catalogo(
    sessionmaker: _SessionMaker, anilist_id: int
) -> list[tuple[AnimeEmAlta, int | None]]:
    """"Relacionados" da página do anime (`integrations.servico.
    listar_relacionados`, recomendações + relações de franquia não
    sequenciais) pareados com `Anime.id` local — mesmo cruzamento de
    `listar_busca_com_catalogo`. Já degrada para `[]` na própria
    `integrations.servico` (conteúdo suplementar best-effort, não pode
    derrubar a página do anime); sem refresh oportunista de lançamento/banner
    pela mesma razão de `listar_proxima_temporada_com_catalogo` — resultado
    transitório de detalhe de página, não o feed central da Home."""
    itens = await servico.listar_relacionados(anilist_id)
    return await _cruzar_com_catalogo(sessionmaker, itens)


async def _cruzar_com_catalogo(
    sessionmaker: _SessionMaker, itens: list[AnimeEmAlta]
) -> list[tuple[AnimeEmAlta, int | None]]:
    """Pareia cada item de um feed de descoberta com `Anime.id` local.
    Prioridade: `anilist_id` primeiro (único, sem falso-negativo por
    subtítulo/pontuação divergente); slug do título romaji como fallback só
    para os itens sem match por `anilist_id` — necessário porque o Kitsu
    (provedor de fallback) não carrega `anilist_id`."""
    anilist_ids = [item.anilist_id for item in itens if item.anilist_id is not None]
    por_anilist_id = await localizar_animes_por_anilist_id(sessionmaker, anilist_ids)

    slugs_pendentes = [
        slugificar(item.titulo_romaji)
        for item in itens
        if item.anilist_id is None or item.anilist_id not in por_anilist_id
    ]
    por_slug = await localizar_animes_por_slug(sessionmaker, slugs_pendentes)

    pares = []
    for item in itens:
        anime_id = por_anilist_id.get(item.anilist_id) if item.anilist_id is not None else None
        if anime_id is None:
            anime_id = por_slug.get(slugificar(item.titulo_romaji))
        pares.append((item, anime_id))
    return pares


def carimbo_esta_velho(atualizado_em: datetime | None, limite: datetime) -> bool:
    """`True` quando o carimbo `atualizado_em` é nulo ou anterior a `limite`.
    `ColunaDataHoraUTC` devolve datetime *aware*, mas um valor naive vindo direto
    do SQLite é normalizado para UTC antes de comparar.

    Pública (sem `_`) porque `api/servicos/sondagem.py` reusa a mesma checagem de
    TTL para `Anime.fonte_verificada_em` — mesma semântica de "carimbo velho ou
    ausente", origem do carimbo diferente."""
    if atualizado_em is None:
        return True
    if atualizado_em.tzinfo is None:
        atualizado_em = atualizado_em.replace(tzinfo=UTC)
    return atualizado_em < limite


async def _refrescar_lancamentos_do_cruzamento(
    sessionmaker: _SessionMaker, pares: list[tuple[AnimeEmAlta, int | None]]
) -> None:
    """F4a — refresh "de graça": para cada item do feed que já traz `lancamento`
    e cruzou com um anime catalogado, sobrescreve as colunas de lançamento do
    anime quando o dado local está velho (> `_TTL_LANCAMENTO_S`) ou ausente. O
    bloco vem do próprio feed "em alta" — nenhuma chamada de rede extra.

    Best-effort de ponta a ponta: falha de leitura ou de escrita vira `warning` e
    nunca derruba `GET /api/animes/em-alta` (o cruzamento já foi montado)."""
    do_feed = {
        anime_id: item.lancamento
        for item, anime_id in pares
        if anime_id is not None and item.lancamento is not None
    }
    if not do_feed:
        return

    try:
        async with sessionmaker() as sessao:
            resultado = await sessao.execute(
                select(Anime.id, Anime.lancamento_atualizado_em).where(
                    Anime.id.in_(list(do_feed))
                )
            )
            carimbo_por_id = dict(resultado.all())

        limite = datetime.now(UTC) - timedelta(seconds=_TTL_LANCAMENTO_S)
        velhos = {
            anime_id: lancamento
            for anime_id, lancamento in do_feed.items()
            if carimbo_esta_velho(carimbo_por_id.get(anime_id), limite)
        }
        await atualizar_lancamentos_em_lote(sessionmaker, velhos)
    except SQLAlchemyError as excecao:
        logger.warning(
            "refresh oportunista de lançamento no cruzamento do feed falhou "
            "(%d candidato(s)): %s",
            len(do_feed),
            excecao,
        )


async def _preencher_banner_do_cruzamento(
    sessionmaker: _SessionMaker, pares: list[tuple[AnimeEmAlta, int | None]]
) -> None:
    """F4a visual — backfill "de graça" da arte horizontal: para cada item do
    feed "em alta" que traz `banner_url` e cruzou com um anime catalogado ainda
    SEM `banner_path` local, grava `banner_path`/`capa_cor` do próprio item do
    feed. Nenhuma chamada de rede extra (o bloco já veio no feed); nunca
    re-sobrescreve um banner já gravado (o filtro `banner_path IS NULL` é do
    SELECT abaixo — mesma abordagem de `_refrescar_lancamentos_do_cruzamento`,
    que filtra pelo carimbo no lado da leitura).

    Best-effort de ponta a ponta: falha de leitura ou de escrita vira `warning` e
    nunca derruba `GET /api/animes/em-alta` (o cruzamento já foi montado)."""
    do_feed = {
        anime_id: item
        for item, anime_id in pares
        if anime_id is not None and item.banner_url is not None
    }
    if not do_feed:
        return

    try:
        async with sessionmaker() as sessao:
            resultado = await sessao.execute(
                select(Anime.id).where(
                    Anime.id.in_(list(do_feed)), Anime.banner_path.is_(None)
                )
            )
            sem_banner = resultado.scalars().all()

        await preencher_banner_visual_em_lote(
            sessionmaker,
            {aid: (do_feed[aid].banner_url, do_feed[aid].capa_cor) for aid in sem_banner},
        )
    except SQLAlchemyError as excecao:
        logger.warning(
            "backfill oportunista de banner no cruzamento do feed falhou "
            "(%d candidato(s)): %s",
            len(do_feed),
            excecao,
        )


def agendar_refresh_de_lancamento(sessionmaker: _SessionMaker, anime: Anime) -> None:
    """F4b — dispara, sem bloquear, uma busca lazy do estado de lançamento à
    AniList quando a página de um anime em lançamento é aberta com dado velho.
    `GET /api/animes/{id}` chama e segue: o resultado entra no banco para a
    próxima leitura, não para esta.

    No-op silencioso (nenhuma destas condições é anormal, então sem log) quando:
    o anime não tem `anilist_id`; o status não é `EM_LANCAMENTO`, `NAO_LANCADO`
    nem nulo (`FINALIZADO`/`CANCELADO` não ganham episódios; `NAO_LANCADO` ainda
    vai estrear e precisa seguir sendo reconsultado até virar `EM_LANCAMENTO`); o
    dado ainda está dentro do TTL; já há uma busca em voo para este anime; ou não
    há event loop rodando."""
    if anime.anilist_id is None:
        return
    if anime.status_lancamento not in (
        StatusLancamento.EM_LANCAMENTO,
        StatusLancamento.NAO_LANCADO,
        None,
    ):
        return
    limite = datetime.now(UTC) - timedelta(seconds=_TTL_LANCAMENTO_S)
    if not carimbo_esta_velho(anime.lancamento_atualizado_em, limite):
        return

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    anime_id = anime.id
    if anime_id in _refreshs_de_lancamento_em_voo:
        return

    anilist_id = anime.anilist_id
    tarefa = loop.create_task(_buscar_e_persistir_lancamento(sessionmaker, anime_id, anilist_id))
    _refreshs_de_lancamento_em_voo[anime_id] = tarefa
    tarefa.add_done_callback(lambda _tarefa: _refreshs_de_lancamento_em_voo.pop(anime_id, None))


# Referência forte ao enriquecimento lazy de metadados "estáticos" (sinopse/
# banner/cor da capa/gêneros) em andamento — mesmo papel de dedupe/anti-GC de
# `_refreshs_de_lancamento_em_voo`, dict PRÓPRIO porque cobre um recorte
# diferente (`anilist_id` não-nulo, mas algum campo ainda faltando) e não deve
# competir pela mesma entrada com um refresh de lançamento em voo do mesmo
# anime_id.
_enriquecimentos_de_metadados_em_voo: dict[int, asyncio.Task] = {}


def agendar_enriquecimento_de_metadados(sessionmaker: _SessionMaker, anime: Anime) -> None:
    """Dispara, sem bloquear, uma busca lazy de metadados "estáticos" (sinopse,
    banner, cor da capa, gêneros, título em inglês) por `anilist_id` quando a
    página do anime é aberta e algum desses campos ainda está `NULL`. Cobre o
    anime materializado
    pelo feed "em alta" (`paginas/Inicio.jsx::materializarEIrPara`), cujo
    payload de criação já vem com `anilist_id`/capa mas nunca com sinopse — a
    AniList não a traz na listagem do feed, só no detalhe por id
    (`GET /api/animes/{id}` é justamente esse "primeiro carregamento da
    página" que o comentário de `Inicio.jsx` promete).

    Só por `anilist_id` já confirmado — nunca por título aqui: `aplicar_
    metadados` (só-quando-nulo) é seguro porque o id já é uma correspondência
    confirmada, ao contrário do casamento heurístico por título que
    `aplicar_lancamento_descoberto_por_titulo` evita deliberadamente para
    estes mesmos campos (ver docstring de `db/catalogo.py::
    aplicar_lancamento_descoberto_por_titulo` — não "simplifique" reusando
    aquele caminho aqui).

    Sem TTL: ao contrário do refresh de lançamento, estes campos não mudam
    depois de preenchidos — o próprio gate (`is None`) já garante no-op depois
    da primeira vez bem-sucedida, sem precisar recarimbar nada.

    No-op silencioso quando: sem `anilist_id`; nenhum campo faltando; já há
    uma busca em voo para este anime; ou não há event loop rodando."""
    if anime.anilist_id is None:
        return
    banner_pendente = _banner_e_fallback_anilist(anime.banner_path)
    if (
        anime.sinopse is not None
        and not banner_pendente
        and anime.capa_cor is not None
        and anime.generos is not None
        and anime.titulo_ingles is not None
    ):
        return

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    anime_id = anime.id
    if anime_id in _enriquecimentos_de_metadados_em_voo:
        return

    anilist_id = anime.anilist_id
    tarefa = loop.create_task(
        _buscar_metadados_e_persistir(sessionmaker, anime_id, anilist_id, banner_pendente)
    )
    _enriquecimentos_de_metadados_em_voo[anime_id] = tarefa
    tarefa.add_done_callback(
        lambda _tarefa, aid=anime_id: _enriquecimentos_de_metadados_em_voo.pop(aid, None)
    )


_HOST_BANNER_ANILIST = "anilistcdn"


def _banner_e_fallback_anilist(banner_path: str | None) -> bool:
    """`True` quando `banner_path` já está preenchido mas ainda é a imagem
    crua da AniList — o overlay do TMDB (`integrations/servico.py::_com_arte`)
    nunca pegou (falha de rede/circuit breaker no momento da materialização,
    ver PLANO_ARTE_TMDB.md). `banner_path is None` NÃO conta aqui: esse caso
    já é coberto pelo só-quando-nulo padrão de `aplicar_metadados`, sem
    precisar de sobrescrita explícita.

    Detecção por substring do CDN da AniList — só banners que o próprio
    provedor serviu vêm de `anilistcdn`; qualquer outro valor (já veio do
    TMDB, ou nulo) não conta como pendente."""
    return banner_path is not None and _HOST_BANNER_ANILIST in banner_path


async def _buscar_metadados_e_persistir(
    sessionmaker: _SessionMaker, anime_id: int, anilist_id: int, banner_pendente: bool
) -> None:
    """Corpo da `Task` fire-and-forget de `agendar_enriquecimento_de_metadados`.
    Mesma filosofia de `_buscar_e_persistir_lancamento`: toda exceção esperada
    vira `warning` e morre aqui; `CancelledError` e erros inesperados
    propagam de propósito."""
    try:
        metadados = await servico.buscar_metadados_por_anilist_id(anilist_id)
        if metadados is None:
            return
        await aplicar_metadados(sessionmaker, anime_id, metadados)
        # `aplicar_metadados` é só-quando-nulo: nunca troca um banner já
        # gravado, mesmo sendo o fallback cru da AniList que nunca recebeu o
        # overlay TMDB. Sobrescrita explícita só nesse caso — mesma escrita
        # de `scripts/rerresolver_banners.py`, só que em resposta a uma
        # abertura de página em vez de um lote manual; `sobrescrever_arte` já
        # não apaga banner existente quando o TMDB não devolve nada.
        if banner_pendente and metadados.banner_url is not None:
            await sobrescrever_arte(
                sessionmaker, anime_id, ArteDeAnime(banner_url=metadados.banner_url)
            )
    except (FalhaDeMetadados, TimeoutError, SQLAlchemyError) as excecao:
        logger.warning(
            "enriquecimento lazy de metadados falhou para anime_id=%s anilist_id=%s: %s",
            anime_id,
            anilist_id,
            excecao,
        )


def agendar_refreshs_do_catalogo(sessionmaker: _SessionMaker, animes: list[Anime]) -> None:
    """F14 — ao listar o catálogo, aquece o `status_lancamento` (filtro do badge
    de "episódios novos") dos animes que nunca foram abertos individualmente nem
    apareceram no feed "em alta" — senão ficam com status `NULL` para sempre e o
    badge nunca aparece, mesmo com contagem de fonte fresca.

    Dois orçamentos independentes por request, mesmo gate
    (`status_lancamento in (EM_LANCAMENTO, NAO_LANCADO, None)` + carimbo
    velho/ausente) e mesma ordenação (carimbo mais velho primeiro):

    - animes COM `anilist_id`: busca lazy por id (`agendar_refresh_de_lancamento`),
      teto `_MAX_REFRESHS_DE_LANCAMENTO_POR_LOTE`.
    - animes SEM `anilist_id`: busca lazy por TÍTULO (`_agendar_busca_por_titulo`,
      cadeia AniList→Kitsu), teto `_MAX_BUSCAS_POR_TITULO_POR_LOTE` (menor: custa
      2 round-trips). Sem esse caminho um anime sem `anilist_id` nunca casado
      pelo feed ficaria `NULL` para sempre.

    As duas listas de candidatos são disjuntas por construção (`anilist_id` é ou
    não é `None`), então compartilhar `_refreshs_de_lancamento_em_voo` é seguro.
    """
    limite = datetime.now(UTC) - timedelta(seconds=_TTL_LANCAMENTO_S)

    por_id = sorted(
        (a for a in animes if a.anilist_id is not None and _elegivel_para_aquecimento(a, limite)),
        key=_ordem_por_carimbo,
    )
    for anime in por_id[:_MAX_REFRESHS_DE_LANCAMENTO_POR_LOTE]:
        agendar_refresh_de_lancamento(sessionmaker, anime)

    por_titulo = sorted(
        (a for a in animes if a.anilist_id is None and _elegivel_para_aquecimento(a, limite)),
        key=_ordem_por_carimbo,
    )
    for anime in por_titulo[:_MAX_BUSCAS_POR_TITULO_POR_LOTE]:
        _agendar_busca_por_titulo(sessionmaker, anime)


def refresh_em_andamento(ids: Iterable[int]) -> bool:
    """`True` se algum dos `ids` tem uma busca lazy de lançamento em voo agora
    (peek em `_refreshs_de_lancamento_em_voo`, sem I/O) — espelha
    `api/servicos/sondagem.py::sondagem_em_andamento`. Usado por
    `GET /api/animes/aquecimento-em-andamento` (`api/rotas/animes.py`) junto
    com `sondagem_em_andamento` pra sinalizar à Galeria que vale reconsultar o
    catálogo em alguns segundos em vez de esperar F5."""
    return any(anime_id in _refreshs_de_lancamento_em_voo for anime_id in ids)


def _elegivel_para_aquecimento(anime: Anime, limite: datetime) -> bool:
    """Gate comum aos dois caminhos de `agendar_refreshs_do_catalogo`: status de
    lançamento que ainda pode ganhar episódios (`EM_LANCAMENTO`, `NAO_LANCADO`
    ou nulo) e carimbo mais velho que `limite` (ou ausente).

    `NAO_LANCADO` entra na tupla porque um bookmark de "Próximas estreias" nasce
    com `status_lancamento` NULL, é aquecido uma única vez para `NAO_LANCADO` +
    `proximo_ep_em` e — sem ele aqui — nunca mais seria reconsultado: a data de
    estreia congelaria e o anime jamais transicionaria para `EM_LANCAMENTO` ao
    estrear. Mesmo motivo no gate de `agendar_refresh_de_lancamento` (esses
    bookmarks têm `anilist_id`, então passam pela busca lazy por id)."""
    return anime.status_lancamento in (
        StatusLancamento.EM_LANCAMENTO,
        StatusLancamento.NAO_LANCADO,
        None,
    ) and carimbo_esta_velho(anime.lancamento_atualizado_em, limite)


def _ordem_por_carimbo(anime: Anime) -> datetime:
    return anime.lancamento_atualizado_em or _CARIMBO_MINIMO


async def _buscar_e_persistir_lancamento(
    sessionmaker: _SessionMaker, anime_id: int, anilist_id: int
) -> None:
    """Corpo da `Task` fire-and-forget de F4b. Toda exceção esperada (provedor
    fora do ar, timeout, erro de banco) vira `warning` e morre aqui — nunca
    propaga para o event loop. `CancelledError` e erros inesperados propagam de
    propósito."""
    try:
        lancamento = await servico.buscar_lancamento_por_anilist_id(anilist_id)
        if lancamento is not None:
            await atualizar_lancamento(sessionmaker, anime_id, lancamento)
    except (FalhaDeMetadados, TimeoutError, SQLAlchemyError) as excecao:
        logger.warning(
            "refresh lazy de lançamento falhou para anime_id=%s anilist_id=%s: %s",
            anime_id,
            anilist_id,
            excecao,
        )


def _agendar_busca_por_titulo(sessionmaker: _SessionMaker, anime: Anime) -> None:
    """Espelha `agendar_refresh_de_lancamento`, mas para animes SEM `anilist_id`:
    dispara, sem bloquear, uma `Task` que busca o estado de lançamento por
    TÍTULO (cadeia AniList→Kitsu). O gate de status/carimbo é do chamador
    (`agendar_refreshs_do_catalogo`); aqui só o try de event loop, o dedupe no
    mesmo `_refreshs_de_lancamento_em_voo` (disjunto do caminho por id) e a ref
    forte contra o GC."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    anime_id = anime.id
    if anime_id in _refreshs_de_lancamento_em_voo:
        return

    tarefa = loop.create_task(
        _buscar_por_titulo_e_persistir(sessionmaker, anime_id, anime.titulo)
    )
    _refreshs_de_lancamento_em_voo[anime_id] = tarefa
    tarefa.add_done_callback(
        lambda _tarefa, aid=anime_id: _refreshs_de_lancamento_em_voo.pop(aid, None)
    )


async def _buscar_por_titulo_e_persistir(
    sessionmaker: _SessionMaker, anime_id: int, titulo: str
) -> None:
    """Corpo da `Task` fire-and-forget de aquecimento por título (F14, caminho 3
    da nota de bloco no topo do módulo). Busca o lançamento na cadeia
    AniList→Kitsu e persiste via `aplicar_lancamento_descoberto_por_titulo` —
    que grava o cache negativo (`lancamento_atualizado_em`) mesmo quando o
    provedor respondeu sem achar (`metadados is None`).

    `anilist_id` só é persistido sob corroboração de slug (D4 do plano): o id é
    `unique`, grudento e sem UI de correção — um id errado bloqueia o anime
    certo. O bloco de lançamento errado, ao contrário, se autocorrige no próximo
    refresh.

    Toda exceção esperada vira `warning` e NÃO carimba (mesma filosofia de
    `sondagem._sondar_e_persistir`: só o sucesso carimba); `CancelledError` e
    erros inesperados propagam de propósito.
    """
    termo = _termo_de_busca(titulo)
    try:
        metadados = await asyncio.wait_for(
            servico.buscar_por_titulo(termo), timeout=_TETO_ENRIQUECIMENTO_S
        )
        await aplicar_lancamento_descoberto_por_titulo(
            sessionmaker,
            anime_id,
            anilist_id=_anilist_id_corroborado(termo, metadados),
            lancamento=metadados.lancamento if metadados is not None else None,
        )
    except (FalhaDeMetadados, TimeoutError, SQLAlchemyError) as excecao:
        logger.warning(
            "aquecimento de lançamento por título falhou para anime_id=%s termo=%r: %s",
            anime_id,
            termo,
            excecao,
        )


def _anilist_id_corroborado(termo: str, metadados: MetadadosDeAnime | None) -> int | None:
    """D4 do plano: só devolve o `anilist_id` do provedor se o slug do `termo`
    de busca casar com o slug do `titulo_romaji` OU do `titulo_ingles`
    retornado. Sem corroboração o id fica `None` (grava-se só o bloco de
    lançamento) — um `anilist_id` errado é `unique` e sem tela de correção."""
    if metadados is None or metadados.anilist_id is None:
        return None
    slug_termo = slugificar(termo)
    slugs_provedor = {
        slugificar(t) for t in (metadados.titulo_romaji, metadados.titulo_ingles) if t
    }
    if slug_termo in slugs_provedor:
        return metadados.anilist_id
    logger.info(
        "anilist_id=%s não corroborado: termo=%r vs romaji=%r / ingles=%r — grava só o bloco",
        metadados.anilist_id,
        termo,
        metadados.titulo_romaji,
        metadados.titulo_ingles,
    )
    return None


def _termo_de_busca(titulo: str) -> str:
    """Normaliza o título local antes da busca de metadados. Os sites de
    extração marcam versão de duas formas: entre parênteses ("Nome (Dublado)")
    e como token solto ("Nome Dublado"). A primeira fica FORA da fronteira de
    token de `remover_marcador_de_versao`, então os segmentos entre `()`/`[]`
    são removidos inteiros aqui (sem desembrulhar — "(Ko)" viraria "ko" solto e
    pioraria o match); `remover_marcador_de_versao` cuida das formas sem
    parênteses. Título que ficaria vazio volta cru.

    `remover_marcador_de_versao` é domínio puro de `extractors/versao.py` (sem
    HTTP/framework) — reuso pontual da regra de fronteira de token, não a
    mistura de famílias de adapter que o CLAUDE.md §1 proíbe (`api/servicos/
    sondagem.py` importa de `extractors/` pelo mesmo motivo).
    """
    sem_parenteses = _REGEX_SEGMENTO_PARENTETICO.sub(" ", titulo)
    termo = remover_marcador_de_versao(sem_parenteses)
    return termo or titulo


async def enriquecer_anime_criado(
    sessionmaker: _SessionMaker,
    anime_id: int,
    titulo: str,
    *,
    anilist_id: int | None,
    kitsu_id: int | None,
    capa_url: str | None,
    sinopse: str | None,
    banner_url: str | None,
    capa_cor: str | None,
    generos: list[str] | None,
    titulo_ingles: str | None = None,
    formato: str | None = None,
) -> None:
    """Preenche metadados do anime recém-obtido/criado (`POST
    /api/admin/animes`). Se o request já trouxe algum campo, persiste direto
    — evita rebuscar um provedor externo por um dado que já veio no payload
    (importa pro rate limit do AniList/Kitsu). Senão, tenta enriquecer por
    título em best-effort: falha do provedor vira warning, nunca bloqueia a
    criação do anime (que já aconteceu antes desta chamada).

    `formato` (`format` cru da AniList, já persistido em `Anime.formato_midia`
    por `db.catalogo.obter_ou_criar_anime_id` na criação) decide o walk de
    franquia em `_resolver_e_aplicar_serie`: `None`/TV segue o walk normal
    (`numero_temporada`+`serie_ancora`); filme/OVA/ONA/especial usa a
    resolução por série-mãe (só `serie_ancora`). Não é conhecido no caminho
    de enriquecimento por título abaixo (`buscar_por_titulo` não devolve
    `format`) — fica `None` nesse caminho, tratado como série normal."""
    algum_campo_veio_no_payload = (
        anilist_id is not None
        or kitsu_id is not None
        or capa_url is not None
        or sinopse is not None
        or banner_url is not None
        or capa_cor is not None
        or generos is not None
        or titulo_ingles is not None
    )
    if algum_campo_veio_no_payload:
        metadados = MetadadosDeAnime(
            capa_url=capa_url,
            sinopse=sinopse,
            anilist_id=anilist_id,
            kitsu_id=kitsu_id,
            banner_url=banner_url,
            capa_cor=capa_cor,
            generos=generos,
            titulo_ingles=titulo_ingles,
        )
        await aplicar_metadados(sessionmaker, anime_id, metadados)
        await _resolver_e_aplicar_serie(
            sessionmaker, anime_id, titulo, anilist_id, formato=formato
        )
        return

    try:
        metadados = await asyncio.wait_for(
            servico.buscar_por_titulo(titulo), timeout=_TETO_ENRIQUECIMENTO_S
        )
    except (FalhaDeMetadados, TimeoutError) as excecao:
        logger.warning(
            "enriquecimento de metadados best-effort falhou para anime_id=%s titulo=%r: %s",
            anime_id,
            titulo,
            excecao,
        )
        return

    if metadados is not None:
        await aplicar_metadados(sessionmaker, anime_id, metadados)
        await _resolver_e_aplicar_serie(
            sessionmaker, anime_id, titulo, metadados.anilist_id
        )


async def _resolver_e_aplicar_serie(
    sessionmaker: _SessionMaker,
    anime_id: int,
    titulo: str,
    anilist_id: int | None,
    *,
    formato: str | None = None,
) -> None:
    """Preenche `numero_temporada` (ordinal narrativo) e `serie_ancora` do anime
    recém-criado: anda o grafo de `relations` da AniList
    (`servico.resolver_serie`, D1) e concilia o ordinal do grafo com o marcador
    do título (`separar_temporada`/`conciliar_posicao`, D2). Grava via
    `aplicar_posicao_na_serie` (só-quando-NULL — o marcador do título gravado na
    criação nunca é sobrescrito).

    `formato` não-nulo (`Anime.formato_midia` — filme/OVA/ONA/especial) desvia
    pra `_aplicar_ancora_de_midia`: esses formatos quase nunca têm aresta
    `PREQUEL` de volta pra série TV (o walk normal ficaria ancorado neles
    mesmos), então só `serie_ancora` é resolvido (via série-mãe), nunca
    `numero_temporada` — não têm posição narrativa numerada.

    Best-effort de ponta a ponta, mesma filosofia de `_resolver_titulos_
    canonicos`: sem `anilist_id` não há grafo para andar; qualquer falha
    (provedor, timeout de `_TETO_SERIE_S`, banco) vira `warning` e retorna — a
    criação do anime já aconteceu. A divergência marcador×grafo (D2) é logada em
    `info` para diagnóstico da Fase 6.

    NÃO é chamada no refresh de lançamento em lote
    (`_refrescar_lancamentos_do_cruzamento`): a estrutura de franquia não muda e
    o refresh varre o catálogo inteiro. O backfill do catálogo já existente é
    `scripts/backfill_serie.py`.
    """
    if anilist_id is None:
        return
    if formato is not None:
        await _aplicar_ancora_de_midia(sessionmaker, anime_id, anilist_id)
        return
    try:
        serie = await asyncio.wait_for(
            servico.resolver_serie(anilist_id), timeout=_TETO_SERIE_S
        )
        marcador = separar_temporada(titulo)[1]
        ordinal_do_grafo = serie.ordinal if serie is not None else None
        ancora_do_grafo = serie.ancora if serie is not None else None
        if (
            marcador is not None
            and ordinal_do_grafo is not None
            and marcador != ordinal_do_grafo
        ):
            logger.info(
                "posição na série: divergência para anime_id=%s anilist_id=%s — "
                "marcador=%s, ordinal_do_grafo=%s (fica o marcador)",
                anime_id,
                anilist_id,
                marcador,
                ordinal_do_grafo,
            )
        posicao = conciliar_posicao(
            marcador=marcador,
            ordinal_do_grafo=ordinal_do_grafo,
            ancora_do_grafo=ancora_do_grafo,
            anilist_id=anilist_id,
        )
        await aplicar_posicao_na_serie(sessionmaker, anime_id, posicao)
    except Exception as excecao:
        logger.warning(
            "resolução de posição na série best-effort falhou para anime_id=%s "
            "anilist_id=%s: %s",
            anime_id,
            anilist_id,
            excecao,
        )


async def _aplicar_ancora_de_midia(
    sessionmaker: _SessionMaker, anime_id: int, anilist_id: int
) -> None:
    """Ramo de `_resolver_e_aplicar_serie` para `Anime.formato_midia` não-nulo
    (filme/OVA/ONA/especial): resolve só `serie_ancora`
    (`servico.resolver_ancora_de_midia`, via série-mãe — nunca o walk
    `PREQUEL` normal, que ancoraria o item nele mesmo). `numero_temporada`
    nunca é tocado aqui — esses formatos não têm posição narrativa numerada.

    Best-effort, mesma filosofia do ramo TV: qualquer falha (provedor, timeout,
    banco) vira `warning` e retorna — a criação do anime já aconteceu."""
    try:
        ancora = await asyncio.wait_for(
            servico.resolver_ancora_de_midia(anilist_id), timeout=_TETO_SERIE_S
        )
        if ancora is not None:
            await aplicar_posicao_na_serie(
                sessionmaker, anime_id, PosicaoNaSerie(numero_temporada=None, serie_ancora=ancora)
            )
    except Exception as excecao:
        logger.warning(
            "resolução de âncora de mídia relacionada best-effort falhou para "
            "anime_id=%s anilist_id=%s: %s",
            anime_id,
            anilist_id,
            excecao,
        )

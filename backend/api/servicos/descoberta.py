"""Orquestração de metadados externos (`integrations/`) com o catálogo local
— mesmo papel de `api/servicos/fontes.py`, mas para `integrations/servico.py`
em vez de `fontes/`. Não importa `fastapi` nem Pydantic (regra de
dependência da Clean Architecture, CLAUDE.md §1); `api/rotas/animes.py`
traduz para schemas.
"""

import asyncio
import logging
import re
import time
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.servicos.catalogo import banner_da_temporada_ou_franquia
from core.ciclo_de_vida import RetratoDoAnime, deve_atualizar_status
from core.conteudo_adulto import eh_conteudo_adulto
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
    obter_ou_criar_anime_id,
    preencher_banner_visual_em_lote,
    promover_a_serie,
    rebaixar_a_extra,
    sincronizar_capas_em_lote,
    sobrescrever_arte,
)
from db.franquias import agrupar_franquias
from fontes.adaptadores.versao import remover_marcador_de_versao
from integrations import servico
from integrations.base import AnimeEmAlta, ArteDeAnime, MetadadosDeAnime, NoDeSerie
from models.anime import Anime

logger = logging.getLogger(__name__)

_SessionMaker = async_sessionmaker[AsyncSession]

# F4/F14 — atualização do estado de lançamento, sem scheduler próprio. O dado
# se renova em dois momentos:
#   1. o cruzamento do feed "em alta" (F4a, de graça: o feed já traz o bloco
#      fresco da AniList);
#   2. a passada do zelador (`api/servicos/zelador.py` → `agendar_refreshs_do_catalogo`),
#      para animes com dado mais velho que este TTL — COM `anilist_id` por busca lazy
#      por id (`servico.buscar_lancamento_por_anilist_id`), SEM por TÍTULO
#      (`servico.buscar_por_titulo`, cadeia AniList→Kitsu; sem isso `status_lancamento`
#      ficaria NULL para sempre e o badge de "episódios novos" nunca dispararia).
_TTL_LANCAMENTO_S = 6 * 3600

# Referência forte às buscas lazy em andamento: (1) deduplica passadas
# concorrentes sobre o mesmo anime e (2) impede o GC de
# coletar uma `Task` fire-and-forget antes de ela terminar. A entrada sai no
# `add_done_callback`. Compartilhado pelos dois caminhos de
# `agendar_refreshs_do_catalogo` — as listas de candidatos de cada um são
# disjuntas (um anime tem OU não tem `anilist_id`).
_refreshs_de_lancamento_em_voo: dict[int, asyncio.Task] = {}

# F14 — teto de animes por listagem de catálogo que disparam busca à AniList
# para aquecer o `status_lancamento`. Segura o rate limit num catálogo grande;
# em poucas visitas o catálogo inteiro esquenta.
_MAX_REFRESHS_DE_LANCAMENTO_POR_LOTE = 5

# F14 — teto próprio (e menor) das buscas por TÍTULO por listagem: cada uma
# custa até 2 round-trips (AniList + fallback Kitsu) contra 1 da busca por id,
# então tem orçamento independente. Pior caso por listagem: 5 (id) + 2 (título).
_MAX_BUSCAS_POR_TITULO_POR_LOTE = 2

# Reparo automático de classificação/posição na série (`agendar_reparos_de_
# classificacao`). Teto próprio por listagem: cada reparo custa ~4-8 chamadas à
# AniList (classificação + walk + franquia) contra ~30/min de limite medido em
# 2026-10-04 — 2 por visita deixa folga mesmo somado aos refreshs acima.
_MAX_REPAROS_DE_CLASSIFICACAO_POR_LOTE = 2
# Cooldown por anime e por processo, contado da TENTATIVA (não do sucesso): série
# cujo walk nunca resolve (ciclo, prequel ambíguo) ficaria retentando a cada
# passada do zelador pra sempre. Em memória de propósito — reiniciar o processo
# zera, que é exatamente quando vale tentar de novo.
_COOLDOWN_REPARO_DE_CLASSIFICACAO_S = 3600
_reparos_de_classificacao_em_voo: dict[int, asyncio.Task] = {}
_reparos_de_classificacao_recentes: dict[int, float] = {}

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
# caminhada depois da primeira. Best-effort como `resolver_titulos_canonicos`
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
    await _sincronizar_capa_do_cruzamento(sessionmaker, pares)
    return await _aplicar_banner_do_catalogo(sessionmaker, pares)


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
    await _sincronizar_capa_do_cruzamento(sessionmaker, pares)
    return await _aplicar_banner_do_catalogo(sessionmaker, pares)


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
        # Filtra antes de achatar: `tamanhos` precisa bater com o que
        # `_cruzar_com_catalogo` devolve, que também descarta conteúdo adulto.
        itens = [item for item in itens if not eh_conteudo_adulto(item.generos)]
        achatados.extend(itens)
        tamanhos.append((chave, len(itens)))

    pares_achatados = await _cruzar_com_catalogo(sessionmaker, achatados)
    pares_achatados = await _aplicar_banner_do_catalogo(sessionmaker, pares_achatados)

    resultado = []
    cursor = 0
    for chave, tamanho in tamanhos:
        resultado.append((chave, pares_achatados[cursor : cursor + tamanho]))
        cursor += tamanho
    return resultado


async def listar_descoberta_com_catalogo(
    sessionmaker: _SessionMaker, genero: str | None, pagina: int
) -> tuple[list[tuple[AnimeEmAlta, int | None]], bool]:
    """Uma página da Descobrir (`integrations.servico.listar_descoberta`) pareada
    com `Anime.id` local, mais se há página seguinte. Propaga `FalhaDeMetadados`
    (a rota devolve 502, nunca uma página vazia no lugar de "provedor fora do ar")
    e `ValueError` (gênero fora da lista aceita).

    Só o cruzamento com o catálogo, como na busca livre: sem refresh oportunista
    de lançamento nem troca de banner — a grade só exibe a capa, e popularidade
    histórica não tem a correlação com "em lançamento" que justifica o refresh do
    feed "em alta"."""
    pagina_de_animes = await servico.listar_descoberta(genero, pagina)
    pares = await _cruzar_com_catalogo(sessionmaker, pagina_de_animes.itens)
    return pares, pagina_de_animes.tem_mais


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
    bloco de lançamento de um título não-lançado muda pouco. Já a capa é
    sincronizada (`_sincronizar_capa_do_cruzamento`): é aqui que a AniList mais
    troca o placeholder pela arte oficial."""
    itens = await servico.listar_proxima_temporada()
    pares = await _cruzar_com_catalogo(sessionmaker, itens)
    await _sincronizar_capa_do_cruzamento(sessionmaker, pares)
    return await _aplicar_banner_do_catalogo(sessionmaker, pares)


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
    (provedor de fallback) não carrega `anilist_id`.

    Ponto único do filtro de conteúdo adulto para feeds/busca/relacionados:
    também cobre feed restaurado do cache persistido, que pode ter sido gravado
    antes do filtro existir."""
    itens = [item for item in itens if not eh_conteudo_adulto(item.generos)]
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


async def _sincronizar_capa_do_cruzamento(
    sessionmaker: _SessionMaker, pares: list[tuple[AnimeEmAlta, int | None]]
) -> None:
    """Mantém `Anime.capa_path`/`capa_cor` iguais à capa que a AniList serve AGORA:
    para cada item do feed cruzado com um anime catalogado cuja capa gravada
    diverge da do feed, sobrescreve. Sem isso a Galeria (lê o catálogo) e a Home
    (lê o feed) mostram capas diferentes, principalmente em anime não lançado, em
    que a AniList troca o placeholder pela arte oficial. Nenhuma chamada de rede
    extra — o item já veio no feed.

    Best-effort de ponta a ponta: falha de leitura ou de escrita vira `warning` e
    nunca derruba o feed (o cruzamento já foi montado)."""
    do_feed = {
        anime_id: item
        for item, anime_id in pares
        if anime_id is not None and item.capa_url
    }
    if not do_feed:
        return

    try:
        async with sessionmaker() as sessao:
            resultado = await sessao.execute(
                select(Anime.id, Anime.capa_path).where(Anime.id.in_(list(do_feed)))
            )
            gravadas = resultado.all()

        divergentes = {
            anime_id: (do_feed[anime_id].capa_url, do_feed[anime_id].capa_cor)
            for anime_id, capa_gravada in gravadas
            if capa_gravada != do_feed[anime_id].capa_url
        }
        await sincronizar_capas_em_lote(sessionmaker, divergentes)
    except SQLAlchemyError as excecao:
        logger.warning(
            "sincronização de capa no cruzamento do feed falhou (%d candidato(s)): %s",
            len(do_feed),
            excecao,
        )


async def _aplicar_banner_do_catalogo(
    sessionmaker: _SessionMaker, pares: list[tuple[AnimeEmAlta, int | None]]
) -> list[tuple[AnimeEmAlta, int | None]]:
    """Troca o `banner_url` do item catalogado pelo banner do catálogo
    (`banner_da_temporada_ou_franquia`: a escolha do usuário, senão o da própria
    temporada, senão o da primeira temporada da franquia com banner) — o MESMO que
    a página do anime exibe, pro carrossel não mostrar a arte do provedor enquanto
    a página mostra outra. Item sem banner no catálogo mantém o do provedor. Roda
    DEPOIS do backfill de `_preencher_banner_do_cruzamento`: se rodasse antes, o
    backfill copiaria a escolha para `banner_path` e limpar a escolha deixaria o
    resíduo. O cache do feed fica só com dado de provedor, então nada a invalidar.

    Best-effort: falha de leitura vira `warning` e devolve os pares do provedor."""
    if all(anime_id is None for _, anime_id in pares):
        return pares
    try:
        async with sessionmaker() as sessao:
            grupos = await agrupar_franquias(sessao)
    except SQLAlchemyError as excecao:
        logger.warning("leitura do banner do catálogo no feed falhou: %s", excecao)
        return pares

    resultado = []
    for item, anime_id in pares:
        grupo = grupos.get(anime_id) if anime_id is not None else None
        proprio = next((linha.banner_path for linha in grupo or [] if linha.id == anime_id), None)
        banner = banner_da_temporada_ou_franquia(grupo, proprio) if grupo else None
        resultado.append((replace(item, banner_url=banner) if banner else item, anime_id))
    return resultado


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
    if not deve_atualizar_status(RetratoDoAnime.de(anime), date.today()):
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


async def _aplicar_metadados_por_anilist_id(
    sessionmaker: _SessionMaker, anime_id: int, anilist_id: int, banner_pendente: bool
) -> None:
    """Busca a ficha completa da AniList por `anilist_id` e aplica o que ainda
    estiver faltando (`aplicar_metadados` é só-quando-nulo). Corpo
    compartilhado por `agendar_enriquecimento_de_metadados` (fire-and-forget,
    disparado na abertura da página) e por `enriquecer_anime_criado`
    (síncrono, na própria criação) — mesma chamada, cada lado decide seu
    próprio teto/captura de erro."""
    metadados = await servico.buscar_metadados_por_anilist_id(anilist_id)
    if metadados is None:
        return
    await aplicar_metadados(sessionmaker, anime_id, metadados)
    # `aplicar_metadados` é só-quando-nulo: nunca troca um banner já
    # gravado, mesmo sendo o fallback cru da AniList que nunca recebeu o
    # overlay TMDB. Sobrescrita explícita só nesse caso — mesma escrita
    # de `scripts/rerresolver_banners.py`, só que em resposta a uma
    # abertura/criação de página em vez de um lote manual; `sobrescrever_arte`
    # já não apaga banner existente quando o TMDB não devolve nada.
    if banner_pendente and metadados.banner_url is not None:
        await sobrescrever_arte(
            sessionmaker, anime_id, ArteDeAnime(banner_url=metadados.banner_url)
        )


async def _buscar_metadados_e_persistir(
    sessionmaker: _SessionMaker, anime_id: int, anilist_id: int, banner_pendente: bool
) -> None:
    """Corpo da `Task` fire-and-forget de `agendar_enriquecimento_de_metadados`.
    Mesma filosofia de `_buscar_e_persistir_lancamento`: toda exceção esperada
    vira `warning` e morre aqui; `CancelledError` e erros inesperados
    propagam de propósito."""
    try:
        await _aplicar_metadados_por_anilist_id(
            sessionmaker, anime_id, anilist_id, banner_pendente
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

    Por fim, `agendar_reparos_de_classificacao` (orçamento próprio) refaz a
    posição/classificação de série criada sem âncora.
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

    agendar_reparos_de_classificacao(sessionmaker, animes)


def _reparo_de_classificacao_em_cooldown(anime_id: int, agora: float) -> bool:
    ultima_tentativa = _reparos_de_classificacao_recentes.get(anime_id)
    return (
        ultima_tentativa is not None
        and agora - ultima_tentativa < _COOLDOWN_REPARO_DE_CLASSIFICACAO_S
    )


def agendar_reparos_de_classificacao(sessionmaker: _SessionMaker, animes: list[Anime]) -> None:
    """Reparo automático (fire-and-forget) de anime criado como série que ficou
    sem posição: `formato_midia` nulo + `anilist_id` + `serie_ancora` nulo. Toda
    criação bem-sucedida grava a âncora (`_resolver_e_aplicar_serie`); âncora nula
    é a assinatura de que a AniList falhou no meio (429, timeout) — inclusive no
    2º estágio da classificação, o que deixaria um ONA com `PARENT` como série.

    Refaz `_resolver_e_aplicar_serie` (classifica COM relações; extra é rebaixado
    e ancorado, série ganha posição e franquia). Não cobre o que já tem âncora
    mas dado velho (ex. `PARENT` adicionado depois na AniList):
    `scripts/reclassificar_midia.py`.

    No-op silencioso quando não há candidato, o anime já tem reparo em voo ou
    tentativa dentro do cooldown, ou não há event loop rodando."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    agora = time.monotonic()
    candidatos = [
        anime
        for anime in animes
        if anime.anilist_id is not None
        and anime.formato_midia is None
        and anime.serie_ancora is None
        and anime.id not in _reparos_de_classificacao_em_voo
        and not _reparo_de_classificacao_em_cooldown(anime.id, agora)
    ]
    for anime in candidatos[:_MAX_REPAROS_DE_CLASSIFICACAO_POR_LOTE]:
        anime_id = anime.id
        _reparos_de_classificacao_recentes[anime_id] = agora
        tarefa = loop.create_task(
            _resolver_e_aplicar_serie(sessionmaker, anime_id, anime.titulo, anime.anilist_id)
        )
        _reparos_de_classificacao_em_voo[anime_id] = tarefa
        tarefa.add_done_callback(
            lambda _tarefa, aid=anime_id: _reparos_de_classificacao_em_voo.pop(aid, None)
        )


def _elegivel_para_aquecimento(anime: Anime, limite: datetime) -> bool:
    """Gate comum aos dois caminhos de `agendar_refreshs_do_catalogo`: a política
    de ciclo de vida pede status novo (`core.ciclo_de_vida.deve_atualizar_status`)
    e o carimbo é mais velho que `limite` (ou ausente)."""
    return deve_atualizar_status(
        RetratoDoAnime.de(anime), date.today()
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

    `remover_marcador_de_versao` é domínio puro de `fontes/adaptadores/versao.py` (sem
    HTTP/framework) — reuso pontual da regra de fronteira de token, não a
    mistura de famílias de adapter que o CLAUDE.md §1 proíbe (`api/servicos/
    sondagem.py` importa de `fontes/` pelo mesmo motivo).
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
        if anilist_id is not None and sinopse is None:
            # Resultado de busca da biblioteca nunca traz sinopse no payload
            # (só o feed "em alta" a traz — ver `AnimeEmAlta.sinopse`) nem
            # `ano` (nenhum caminho do frontend manda `ano` na criação). Sem
            # isto, a página do anime recém-criado nascia incompleta
            # (sinopse/ano/overlay TMDB de banner ausentes) até a Task
            # fire-and-forget de `agendar_enriquecimento_de_metadados`
            # terminar — e nada avisa o front quando isso acontece (sem
            # WebSocket/polling): a única forma de ver o resultado era
            # recarregar a página na mão (achado do usuário testando o
            # clique num item de busca, 2026-09-23). Busca síncrona aqui,
            # best-effort com o mesmo teto/captura do enriquecimento por
            # título abaixo — a criação nunca fica bloqueada por uma AniList
            # fora do ar. Gate em `sinopse is None` (não em todo `anilist_id`
            # presente) pra não gastar uma chamada AniList extra no caminho
            # comum do feed "em alta", que já traz tudo no payload.
            try:
                await asyncio.wait_for(
                    _aplicar_metadados_por_anilist_id(
                        sessionmaker,
                        anime_id,
                        anilist_id,
                        banner_pendente=_banner_e_fallback_anilist(banner_url),
                    ),
                    timeout=_TETO_ENRIQUECIMENTO_S,
                )
            except (FalhaDeMetadados, TimeoutError, SQLAlchemyError) as excecao:
                logger.warning(
                    "completar metadados por anilist_id best-effort falhou na criação"
                    " para anime_id=%s anilist_id=%s: %s",
                    anime_id,
                    anilist_id,
                    excecao,
                )
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

    `formato` não-nulo (`Anime.formato_midia` — EXTRA: filme/OVA curto/especial/
    ONA-extra) desvia pra `_aplicar_ancora_de_midia`: extras quase nunca têm
    aresta `PREQUEL` de volta pra série (o walk normal ficaria ancorado neles
    mesmos), então só `serie_ancora` é resolvido (via série-mãe), nunca
    `numero_temporada` — não têm posição narrativa numerada. `formato` `None`
    ainda passa por `_formato_se_extra_declarado` (feed sem relações deixa
    ONA/OVA longo com `PARENT` passar como série); ver `integrations/
    classificacao.py`.

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
    if formato is None:
        formato = await _formato_se_extra_declarado(sessionmaker, anime_id, anilist_id)
    if formato is not None:
        await _aplicar_ancora_de_midia(sessionmaker, anime_id, anilist_id, formato)
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

        if serie is not None:
            franquia = await asyncio.wait_for(
                servico.resolver_franquia(anilist_id), timeout=_TETO_SERIE_S
            )
            if franquia:
                await _materializar_temporadas_irmas(sessionmaker, anilist_id, franquia)
    except Exception as excecao:
        logger.warning(
            "resolução de posição na série best-effort falhou para anime_id=%s "
            "anilist_id=%s: %s",
            anime_id,
            anilist_id,
            excecao,
        )


async def _materializar_temporadas_irmas(
    sessionmaker: _SessionMaker, anilist_id_clicado: int, franquia: list[NoDeSerie]
) -> None:
    """Materializa (metadados apenas, sem tocar `fontes/`) toda temporada
    da `franquia` (`servico.resolver_franquia`, lista ordenada T1..Tn) que
    ainda não está no catálogo local — o pedido do usuário de agrupar a
    franquia inteira ao clicar em qualquer uma das temporadas.

    A posição (`numero_temporada`/`serie_ancora`) de cada irmã já é conhecida
    pela POSIÇÃO da irmã dentro de `franquia` — não rechama `resolver_serie`
    por irmã (o walk já é 1 caminhada para a franquia inteira, ver docstring
    de `resolver_franquia`). Mesma conciliação marcador×grafo de
    `_resolver_e_aplicar_serie` (o marcador do título sempre vence).

    Best-effort por item: uma irmã sem metadados resolvidos (provedor sem
    ficha, ou instável) é logada e pulada — nunca cria linha só com título/slug
    (diferente do cadastro manual, aqui não há confirmação do usuário sobre
    aquele título). Uma falha numa irmã não impede as demais.
    """
    ancora = franquia[0].anilist_id
    async with sessionmaker() as sessao:
        ja_catalogados = {
            row[0]
            for row in (
                await sessao.execute(
                    select(Anime.anilist_id).where(
                        Anime.anilist_id.in_([no.anilist_id for no in franquia])
                    )
                )
            ).all()
        }

    for ordinal, no in enumerate(franquia, start=1):
        if no.anilist_id == anilist_id_clicado or no.anilist_id in ja_catalogados:
            continue
        try:
            metadados = await asyncio.wait_for(
                servico.buscar_metadados_por_anilist_id(no.anilist_id),
                timeout=_TETO_SERIE_S,
            )
            if metadados is None:
                logger.info(
                    "agrupamento de franquia: sem metadados para anilist_id=%s "
                    "(%r, T%d da franquia âncora=%s) — não materializada",
                    no.anilist_id,
                    no.titulo,
                    ordinal,
                    ancora,
                )
                continue

            titulo = metadados.titulo_romaji or no.titulo
            anime_id_irma = await obter_ou_criar_anime_id(
                sessionmaker, titulo, metadados.ano, anilist_id=no.anilist_id
            )
            await aplicar_metadados(sessionmaker, anime_id_irma, metadados)

            marcador = separar_temporada(titulo)[1]
            posicao = conciliar_posicao(
                marcador=marcador,
                ordinal_do_grafo=ordinal,
                ancora_do_grafo=ancora,
                anilist_id=no.anilist_id,
            )
            await aplicar_posicao_na_serie(sessionmaker, anime_id_irma, posicao)
        except (FalhaDeMetadados, TimeoutError, SQLAlchemyError) as excecao:
            logger.warning(
                "agrupamento de franquia: falha ao materializar anilist_id=%s "
                "(T%d da franquia âncora=%s): %s",
                no.anilist_id,
                ordinal,
                ancora,
                excecao,
            )


async def _formato_se_extra_declarado(
    sessionmaker: _SessionMaker, anime_id: int, anilist_id: int
) -> str | None:
    """Segundo estágio da classificação série×extra: o feed (sem relações)
    deixou passar como série; aqui `servico.formato_se_extra` aplica a regra com
    a aresta `PARENT`. Se for extra, grava `formato_midia` e devolve o `format`
    pra `_resolver_e_aplicar_serie` desviar pro ramo de âncora. Best-effort:
    qualquer falha vira `warning` e `None` (segue como série — o erro barato)."""
    try:
        formato = await asyncio.wait_for(
            servico.formato_se_extra(anilist_id), timeout=_TETO_SERIE_S
        )
        if formato is not None:
            await rebaixar_a_extra(sessionmaker, anime_id, formato)
        return formato
    except Exception as excecao:
        logger.warning(
            "classificação série×extra best-effort falhou para anime_id=%s anilist_id=%s: %s",
            anime_id,
            anilist_id,
            excecao,
        )
        return None


async def _aplicar_ancora_de_midia(
    sessionmaker: _SessionMaker, anime_id: int, anilist_id: int, formato: str
) -> None:
    """Ramo de `_resolver_e_aplicar_serie` para `Anime.formato_midia` não-nulo
    (extra: filme/OVA curto/especial/ONA-extra): resolve só `serie_ancora`
    (`servico.resolver_ancora_de_midia`, via série-mãe — nunca o walk
    `PREQUEL` normal, que ancoraria o item nele mesmo). `numero_temporada`
    nunca é tocado aqui — extra não tem posição narrativa numerada. Não puxa a
    série-mãe pro catálogo: o usuário clicou num extra, não na série (a
    Crunchyroll também não materializa).

    `formato` só entra no log. Best-effort, mesma filosofia do ramo TV:
    qualquer falha (provedor, timeout, banco) vira `warning` e retorna — a
    criação do anime já aconteceu."""
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
            "anime_id=%s anilist_id=%s formato=%s: %s",
            anime_id,
            anilist_id,
            formato,
            excecao,
        )


async def reclassificar_midia(
    sessionmaker: _SessionMaker,
    anime_id: int,
    titulo: str,
    anilist_id: int,
    *,
    formato_atual: str | None,
    formato: str,
    serie: bool,
) -> str | None:
    """Aplica a classificação (`servico.classificar_midia`) a um anime JÁ
    catalogado — `scripts/reclassificar_midia.py`. Devolve `"promovido"` (era
    extra, a regra atual diz série: refaz posição e agrupa a franquia como numa
    criação), `"rebaixado"` (era série, a regra diz extra: ancora na série-mãe)
    ou `None` quando nada muda. Idempotente: roda de novo e não faz nada."""
    if serie and formato_atual is not None:
        await promover_a_serie(sessionmaker, anime_id)
        await _resolver_e_aplicar_serie(sessionmaker, anime_id, titulo, anilist_id)
        return "promovido"
    if not serie and formato_atual is None:
        await rebaixar_a_extra(sessionmaker, anime_id, formato)
        await _aplicar_ancora_de_midia(sessionmaker, anime_id, anilist_id, formato)
        return "rebaixado"
    return None

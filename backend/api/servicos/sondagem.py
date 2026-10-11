"""Sondagem da fonte real (site) de um anime para contar episódios disponíveis.

Orquestra `extractors/` — via `api/servicos/fontes.py::resolver_e_listar`
(sem o overlay de still da exibição, que a sondagem descartaria) — e grava a
contagem em `Anime.episodios_na_fonte`/`fonte_verificada_*`
(`db.catalogo.atualizar_contagem_na_fonte`). Família de adapter distinta da de
`api/servicos/descoberta.py`, que orquestra `integrations/` (metadados de
provedor externo por API JSON pública): aqui é scraping de site com bypass
anti-bot, custo real por anime — daí o TTL longo, o teto por lote e o semáforo
global que serializa os scrapes.

Mesmo padrão de refresh oportunista de F4b
(`descoberta.agendar_refresh_de_lancamento`): `agendar_sondagens` é síncrona e
fire-and-forget, dispara `Task`s que rodam à margem da request e cujo resultado
entra no banco para a PRÓXIMA leitura do catálogo, não para esta. Não importa
`fastapi` nem Pydantic (regra de dependência da Clean Architecture, CLAUDE.md
§1) — `api/rotas/animes.py` é quem traduz para os esquemas de saída.
"""

import asyncio
import logging
import time
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.servicos import descoberta
from api.servicos.fontes import resolver_e_listar
from api.servicos.jobs import versao_episodio_da_fonte
from core.enums import StatusLancamento, TipoEpisodio, VersaoDeFonte, VersaoEpisodio
from core.erros import FalhaDeExtracao, FonteAmbigua, VersaoIndisponivelError
from db.catalogo import atualizar_contagem_na_fonte
from extractors.servico import filtrar_por_versao
from models.anime import Anime
from models.episodio import Episodio
from models.fonte_anime import FonteAnime

logger = logging.getLogger(__name__)

_SessionMaker = async_sessionmaker[AsyncSession]

# Sondagem é scraping de site (caro: bypass anti-bot, uma requisição por anime).
# TTL de 6h entre sondagens do mesmo anime — sem scheduler, só carona na leitura
# do catálogo (mesma filosofia de `descoberta._TTL_LANCAMENTO_S`).
_TTL_SONDAGEM_S = 6 * 3600

# Teto de sondagens disparadas por uma única passada de `agendar_sondagens` —
# abrir o catálogo não pode enfileirar um scrape por anime em lançamento.
_MAX_SONDAGENS_POR_LOTE = 8

# Nunca dois scrapes simultâneos, nem em sites diferentes: serializa o custo de
# rede/CPU do bypass anti-bot e, de brinde, garante ordem por domínio sem
# precisar de lock por site.
_semaforo_de_sondagem = asyncio.Semaphore(1)

# Referência forte às `Task` de sondagem em voo: (1) deduplica passadas
# concorrentes de `agendar_sondagens` para o mesmo anime e (2) impede o GC de
# coletar uma `Task` fire-and-forget antes de ela terminar. A entrada sai no
# `add_done_callback`.
_sondagens_em_voo: dict[int, asyncio.Task] = {}

# Cooldown de reparo de fonte perdida que falhou (`versoes_para_reresolver_
# fonte_perdida`, 2026-09-19): sem NENHUMA `FonteAnime` mapeada, a resolução
# varre TODOS os extratores com várias variantes de título — bem mais cara que
# uma sondagem normal (que reusa o site já mapeado e falha rápido se ele
# estiver fora do ar). Sem este cooldown, um anime que não é encontrado em
# lugar nenhum (ex.: site descontinuou o título) repetia essa varredura
# inteira a cada `?aquecer=true` — inclusive o `recarregar()` que a própria
# Galeria dispara ao terminar de esperar o aquecimento anterior. Em memória de
# processo (mesmo padrão de `_sondagens_em_voo`): reinicia com o processo, o
# que é aceitável — o pior caso é uma nova tentativa após um restart, não um
# vazamento permanente.
_TTL_FALHA_REPARO_DE_FONTE_S = 3600
_falhas_de_reparo_de_fonte: dict[int, float] = {}


def _reparo_de_fonte_em_cooldown(anime_id: int) -> bool:
    expira_em = _falhas_de_reparo_de_fonte.get(anime_id)
    return expira_em is not None and time.monotonic() < expira_em


def ids_fora_de_cooldown_de_reparo(ids: Iterable[int]) -> list[int]:
    """Filtra `ids` removendo os que tiveram uma tentativa de reparo de fonte
    perdida sem sucesso há menos de `_TTL_FALHA_REPARO_DE_FONTE_S` — chamado
    por `api/rotas/animes.py::listar_animes` ANTES de derivar palpites de
    versão (`versoes_para_reresolver_fonte_perdida`), pra nem gastar a query
    de episódios com um anime que está de cooldown."""
    return [anime_id for anime_id in ids if not _reparo_de_fonte_em_cooldown(anime_id)]


# `VersaoDeFonte` (estado do mapeamento) -> `VersaoEpisodio` pedível a
# `extractors.resolucao.resolver_fonte_do_anime`. NUNCA `DESCONHECIDA`:
# `resolver_fonte_do_anime` levanta `ValueError` com ela. `NAO_DIFERENCIADA` ->
# `LEGENDADO` é seguro — a resolução aceita a linha `NAO_DIFERENCIADA` e
# `extractors.servico.filtrar_por_versao` devolve a lista inteira quando nenhum
# episódio da fonte traz rótulo de versão.
_MAPA_VERSAO: dict[VersaoDeFonte, VersaoEpisodio] = {
    VersaoDeFonte.LEGENDADO: VersaoEpisodio.LEGENDADO,
    VersaoDeFonte.DUBLADO: VersaoEpisodio.DUBLADO,
    VersaoDeFonte.NAO_DIFERENCIADA: VersaoEpisodio.LEGENDADO,
}


def versao_de_sondagem(versao_de_fonte: VersaoDeFonte) -> VersaoEpisodio:
    """Traduz UMA `VersaoDeFonte` (estado do mapeamento de `FonteAnime`) para a
    `VersaoEpisodio` a pedir na sondagem — `NAO_DIFERENCIADA -> LEGENDADO`,
    NUNCA `DESCONHECIDA` (que faria `resolver_fonte_do_anime` levantar
    `ValueError`). Ver `_MAPA_VERSAO`.

    `versoes_de_sondagem_por_anime` aplica o mesmo mapa em lote; `obter_anime`
    usa esta função para a linha de `FonteAnime` única que já leu, sem abrir
    outra query.
    """
    return _MAPA_VERSAO[versao_de_fonte]


# Sentinel para ordenar animes sem `fonte_verificada_em` antes dos demais —
# *aware* (UTC) para nunca colidir com "naive vs aware" na comparação de tupla.
_CARIMBO_MINIMO = datetime.min.replace(tzinfo=UTC)


async def _escolha_de_fonte_mais_recente_por_anime(
    sessao: AsyncSession, ids: Iterable[int]
) -> dict[int, VersaoDeFonte]:
    """`{anime_id: VersaoDeFonte da linha de maior resolvido_em}` para os `ids`
    com ao menos uma linha em `FonteAnime` — a última escolha manual de fonte do
    usuário, a mesma que uma captura usaria
    (`extractors.resolucao._resolver_em_mapeadas`). Query única, roda na sessão
    da request. Anime sem linha em `FonteAnime` não aparece no resultado.

    Base compartilhada por `versoes_de_sondagem_por_anime` (traduz pra "o que
    sondar", NUNCA `DESCONHECIDA`) e `versoes_confirmadas_mais_recentes_por_anime`
    (traduz pra "o que exibir no catálogo", `DESCONHECIDA` quando a fonte não
    diferencia) — mesma query, tradução final diferente."""
    lista_ids = list(ids)
    if not lista_ids:
        return {}

    resultado = await sessao.execute(
        select(FonteAnime.anime_id, FonteAnime.versao, FonteAnime.resolvido_em).where(
            FonteAnime.anime_id.in_(lista_ids)
        )
    )

    escolha_por_anime: dict[int, tuple[datetime, VersaoDeFonte]] = {}
    for anime_id, versao, resolvido_em in resultado.all():
        anterior = escolha_por_anime.get(anime_id)
        if anterior is None or resolvido_em > anterior[0]:
            escolha_por_anime[anime_id] = (resolvido_em, versao)

    return {anime_id: versao for anime_id, (_, versao) in escolha_por_anime.items()}


async def versoes_de_sondagem_por_anime(
    sessao: AsyncSession, ids: Iterable[int]
) -> dict[int, VersaoEpisodio]:
    """`{anime_id: versão a sondar}` — ver `_escolha_de_fonte_mais_recente_por_anime`.
    `agendar_sondagens` consome o dict pronto, sem I/O."""
    escolha = await _escolha_de_fonte_mais_recente_por_anime(sessao, ids)
    return {anime_id: versao_de_sondagem(versao) for anime_id, versao in escolha.items()}


async def versoes_confirmadas_mais_recentes_por_anime(
    sessao: AsyncSession, ids: Iterable[int]
) -> dict[int, VersaoEpisodio]:
    """`{anime_id: versão a exibir no catálogo}` — mesma escolha de
    `versoes_de_sondagem_por_anime` (ver `_escolha_de_fonte_mais_recente_por_anime`),
    mas traduzida com `jobs.versao_episodio_da_fonte`: `NAO_DIFERENCIADA` vira
    `DESCONHECIDA` (sem badge), não `LEGENDADO` — usar a tradução de sondagem
    aqui mostraria "Legendado" em fonte que não confirma nada. Alimenta
    `AnimeSaida.versao_confirmada_mais_recente` (badge "Dublado"/"Legendado" do
    card, `components/AnimeCard.jsx`) via `api/rotas/animes.py::listar_animes`;
    `obter_anime` já tem a linha via outra query e resolve inline sem chamar
    esta."""
    escolha = await _escolha_de_fonte_mais_recente_por_anime(sessao, ids)
    return {anime_id: versao_episodio_da_fonte(versao) for anime_id, versao in escolha.items()}


async def versoes_para_reresolver_fonte_perdida(
    sessao: AsyncSession, ids: Iterable[int]
) -> dict[int, VersaoEpisodio]:
    """`{anime_id: versão a PEDIR}` pra animes com `Episodio` capturado mas
    ZERO linha em `FonteAnime` — caso real (2026-09-15, migração
    `26791d90cb31_invalida_fonte_anime_do_animefire_one`): o domínio antigo do
    AnimeFire saiu do ar e a migração apagou em lote as linhas de `fonte_anime`
    que apontavam pra ele, esperando que a resolução rodasse nova ao vivo "na
    próxima tentativa". Só que sem NENHUMA fonte mapeada pra consultar,
    `versoes_de_sondagem_por_anime` nunca tem entrada pra esses animes, e
    `agendar_sondagens` os pula (`anime.id not in versoes`) pra sempre — a
    única forma de reparar era abrir a página do anime manualmente. `ids`
    aqui já vem filtrado por quem chama (`api/rotas/animes.py::listar_animes`)
    pros que TÊM episódio mas não têm entrada em `versoes_de_sondagem_por_anime`.

    Deriva a versão a pedir do `Episodio.versao` mais recente já capturado
    (mesmo mapa de `versao_de_sondagem`: `DESCONHECIDA`/`NAO_DIFERENCIADA`
    nunca é pedível, vira `LEGENDADO`) — é só um palpite pra dar à busca ao
    vivo um ponto de partida; `resolver_fonte_do_anime` ainda pode confirmar
    a versão real assim que reencontrar o anime num site."""
    lista_ids = list(ids)
    if not lista_ids:
        return {}

    resultado = await sessao.execute(
        select(Episodio.anime_id, Episodio.versao, Episodio.criado_em).where(
            Episodio.anime_id.in_(lista_ids), Episodio.tipo == TipoEpisodio.REGULAR
        )
    )
    mais_recente_por_anime: dict[int, tuple[datetime, VersaoEpisodio]] = {}
    for anime_id, versao, criado_em in resultado.all():
        anterior = mais_recente_por_anime.get(anime_id)
        if anterior is None or criado_em > anterior[0]:
            mais_recente_por_anime[anime_id] = (criado_em, versao)

    pedivel = (VersaoEpisodio.LEGENDADO, VersaoEpisodio.DUBLADO)
    return {
        anime_id: (versao if versao in pedivel else VersaoEpisodio.LEGENDADO)
        for anime_id, (_, versao) in mais_recente_por_anime.items()
    }


async def versoes_de_reparo_de_temporadas_novas(
    sessao: AsyncSession,
    novas: dict[int, int],
    versoes_existentes: dict[int, VersaoEpisodio],
) -> dict[int, VersaoEpisodio]:
    """`{anime_id da temporada nova: versão a PEDIR}` pras temporadas de
    `lancamentos.temporadas_novas` que ainda não têm `FonteAnime` (temporada
    nunca capturada → nunca resolveu fonte → `agendar_sondagens` a pularia pra
    sempre e o badge/prateleira nunca saberiam que ela já estreou). O palpite
    de versão herda a da temporada anterior (`versoes_para_reresolver_fonte_
    perdida` sobre ela); mesma semântica de reparo — varredura cara, por isso
    respeita `ids_fora_de_cooldown_de_reparo` e quem chama passa o resultado em
    `ignorar_gate_de_status`."""
    sem_fonte = ids_fora_de_cooldown_de_reparo(
        anime_id for anime_id in novas if anime_id not in versoes_existentes
    )
    palpites = await versoes_para_reresolver_fonte_perdida(
        sessao, {novas[anime_id] for anime_id in sem_fonte}
    )
    return {
        anime_id: palpites[novas[anime_id]]
        for anime_id in sem_fonte
        if novas[anime_id] in palpites
    }


def agendar_sondagens(
    sessionmaker: _SessionMaker,
    animes: list[Anime],
    versoes: dict[int, VersaoEpisodio],
    *,
    ignorar_gate_de_status: frozenset[int] = frozenset(),
) -> None:
    """Dispara, sem bloquear, a sondagem da fonte real dos animes em lançamento
    cuja contagem está velha (> `_TTL_SONDAGEM_S`) ou ausente — no máximo
    `_MAX_SONDAGENS_POR_LOTE` por passada, os de carimbo mais antigo primeiro.
    Fire-and-forget: o resultado entra no banco para a próxima leitura do
    catálogo, não para esta (mesmo padrão de
    `descoberta.agendar_refresh_de_lancamento`).

    `ignorar_gate_de_status`: ids que pulam o gate de status de lançamento por
    completo — uso exclusivo do reparo de `versoes_para_reresolver_fonte_perdida`
    (`api/rotas/animes.py::listar_animes`): um anime `FINALIZADO` sem NENHUMA
    `FonteAnime` mapeada também precisa ser tentado (a resolução persiste a
    fonte perdida como efeito colateral, ver `_sondar_e_persistir`), não só o
    caso "FINALIZADO mas incompleto" de `_finalizado_incompleto`. Autolimitado
    igual ao resto: uma vez resolvido, o anime ganha uma `FonteAnime` e some
    do conjunto de candidatos na próxima passada (`versoes_de_sondagem_por_anime`
    já cobre ele normalmente dali em diante).

    100% síncrona, zero I/O. No-op silencioso (nenhuma destas condições é
    anormal, então sem log) quando não há event loop rodando, ou para cada anime
    cujo: status de lançamento não é `EM_LANCAMENTO`/nulo E não é o caso
    `FINALIZADO` incompleto de `_finalizado_incompleto` (ver ali) E não está em
    `ignorar_gate_de_status`; não tem fonte mapeada nem palpite de versão
    (`anime.id not in versoes`); contagem ainda dentro do TTL; ou já tem uma
    sondagem em voo.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    limite = datetime.now(UTC) - timedelta(seconds=_TTL_SONDAGEM_S)
    candidatos = sorted(animes, key=_ordem_de_sondagem)

    agendadas = 0
    for anime in candidatos:
        if agendadas >= _MAX_SONDAGENS_POR_LOTE:
            break
        if (
            anime.status_lancamento not in (StatusLancamento.EM_LANCAMENTO, None)
            and not _finalizado_incompleto(anime)
            and anime.id not in ignorar_gate_de_status
        ):
            continue
        if anime.id not in versoes:
            continue
        if not descoberta.carimbo_esta_velho(anime.fonte_verificada_em, limite):
            continue
        if anime.id in _sondagens_em_voo:
            continue

        tarefa = loop.create_task(
            _sondar_e_persistir(
                sessionmaker,
                anime.id,
                versoes[anime.id],
                eh_reparo_de_fonte_perdida=anime.id in ignorar_gate_de_status,
            )
        )
        _sondagens_em_voo[anime.id] = tarefa
        tarefa.add_done_callback(
            lambda _tarefa, aid=anime.id: _sondagens_em_voo.pop(aid, None)
        )
        agendadas += 1


def sondagem_em_andamento(ids: Iterable[int]) -> bool:
    """`True` se algum dos `ids` tem uma sondagem em voo agora (peek em
    `_sondagens_em_voo`, sem I/O) — usado por `api/servicos/progresso.py` pra
    sinalizar ao frontend que vale reconsultar a prateleira "Continuar
    assistindo" em alguns segundos em vez de esperar F5 (mesmo padrão de
    `ItemContinuarAssistindo.still_pendente`). Chamar DEPOIS de
    `agendar_sondagens` na mesma passada: cobre tanto a sondagem que acabou de
    ser agendada agora quanto uma já em voo de uma passada anterior."""
    return any(anime_id in _sondagens_em_voo for anime_id in ids)


def _finalizado_incompleto(anime: Anime) -> bool:
    """`True` quando a AniList já marcou o anime `FINALIZADO`, mas a contagem
    da fonte real ainda não alcançou o total que ela declara — caso real
    observado (2026-09-19): o fansub sobe o(s) último(s) episódio(s) depois
    de a AniList fechar o status, e sem esta exceção `agendar_sondagens`
    parava de checar aquele anime PARA SEMPRE assim que ele virava
    `FINALIZADO` (gate original: só `EM_LANCAMENTO`/`None`) — o episódio final
    nunca mais era descoberto, e o anime sumia de "Continuar assistindo"
    (`api/servicos/progresso.py`) sem card nenhum pra ele, mesmo com o
    episódio disponível na fonte.

    Autolimitado: assim que `episodios_na_fonte` alcança
    `total_episodios_anilist`, esta função volta a `False` e o anime para de
    ser re-sondado — não reabre sondagem indefinida pra show genuinamente
    completo. `total_episodios_anilist` ausente (AniList nunca fechou a
    contagem) não é motivo de reabertura: sem total pra comparar, não dá pra
    saber se falta episódio."""
    return (
        anime.status_lancamento == StatusLancamento.FINALIZADO
        and anime.total_episodios_anilist is not None
        and (anime.episodios_na_fonte or 0) < anime.total_episodios_anilist
    )


def _ordem_de_sondagem(anime: Anime) -> tuple[bool, datetime]:
    """Chave de ordenação de `agendar_sondagens`: `fonte_verificada_em` nulo
    primeiro, depois o mais antigo — quem está há mais tempo sem contagem
    confiável tem prioridade no orçamento do lote."""
    carimbo = anime.fonte_verificada_em
    return (carimbo is not None, carimbo or _CARIMBO_MINIMO)


async def _sondar_e_persistir(
    sessionmaker: _SessionMaker,
    anime_id: int,
    versao: VersaoEpisodio,
    *,
    eh_reparo_de_fonte_perdida: bool = False,
) -> None:
    """Corpo da `Task` fire-and-forget de sondagem. Toda exceção esperada (fonte
    fora do ar, ambígua, versão indisponível, timeout, erro de banco) vira
    `warning` e morre aqui — nunca propaga para o event loop. `CancelledError` e
    erros inesperados propagam de propósito.

    Só o caminho de sucesso carimba: `Anime.fonte_verificada_em` é escrito apenas
    por `atualizar_contagem_na_fonte`. Uma sondagem que falhou não mexe em coluna
    nenhuma — a próxima passada continua vendo o carimbo antigo/nulo e tenta de
    novo (barato: reusa o site já mapeado). `eh_reparo_de_fonte_perdida=True`
    (vindo de `ignorar_gate_de_status` em `agendar_sondagens`) é o caso caro —
    SEM fonte mapeada, a busca varre todos os extratores — e sua falha grava um
    cooldown próprio (`_registrar_falha_de_reparo_de_fonte`), já que não há
    carimbo de coluna pra segurar o reintento por si só.

    `total` conta apenas números REGULAR distintos (`ep.numero is not None`,
    deduplicado): mesmo recorte `tipo == REGULAR` de
    `lancamentos.maior_numero_capturado_por_anime` (o outro lado do cálculo do
    badge) — rótulos não-numéricos ("Especial", "OVA 2") e o mesmo número
    repetido ("7"/"07") inflariam a contagem da fonte, e com ela o badge, de
    forma permanente.
    """
    try:
        async with sessionmaker() as sessao:
            anime = await sessao.get(Anime, anime_id)
        if anime is None:
            return
        async with _semaforo_de_sondagem:
            fonte = await resolver_e_listar(
                sessionmaker, anime, versao, resolver_canonico=True
            )
        episodios = filtrar_por_versao(fonte.episodios, versao)
        total = len({ep.numero for ep in episodios if ep.numero is not None})
        await atualizar_contagem_na_fonte(
            sessionmaker, anime_id, total=total, dominio=fonte.dominio
        )
    except (
        FalhaDeExtracao,
        FonteAmbigua,
        VersaoIndisponivelError,
        TimeoutError,
        SQLAlchemyError,
    ) as excecao:
        logger.warning("sondagem de fonte falhou para anime_id=%s: %s", anime_id, excecao)
        if eh_reparo_de_fonte_perdida:
            _falhas_de_reparo_de_fonte[anime_id] = time.monotonic() + _TTL_FALHA_REPARO_DE_FONTE_S

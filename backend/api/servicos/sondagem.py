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
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.servicos import descoberta
from api.servicos.fontes import resolver_e_listar
from api.servicos.jobs import versao_episodio_da_fonte
from core.ciclo_de_vida import INTERVALO_APOS_SUCESSO, RetratoDoAnime, deve_sondar_fonte
from core.enums import (
    ResultadoDeVerificacao,
    TarefaDeVerificacao,
    TipoEpisodio,
    VersaoDeFonte,
    VersaoEpisodio,
)
from core.erros import (
    FalhaDeExtracao,
    FonteAmbigua,
    FonteNaoEncontrada,
    SessaoRejeitada,
    SiteEmCooldown,
    VersaoIndisponivelError,
)
from db import verificacao
from db.catalogo import atualizar_contagem_na_fonte
from extractors.resiliencia import em_segundo_plano
from extractors.servico import filtrar_por_versao
from models.anime import Anime
from models.episodio import Episodio
from models.fonte_anime import FonteAnime

logger = logging.getLogger(__name__)

_SessionMaker = async_sessionmaker[AsyncSession]

# Sondagem é scraping de site (caro: bypass anti-bot, uma requisição por anime).
# TTL de 6h entre sondagens do mesmo anime — sem scheduler, só carona na leitura
# do catálogo (mesma filosofia de `descoberta._TTL_LANCAMENTO_S`).
_TTL_SONDAGEM_S = int(INTERVALO_APOS_SUCESSO.total_seconds())

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


async def ids_em_espera(sessao: AsyncSession, ids: Iterable[int]) -> frozenset[int]:
    """`anime_id`s dentre `ids` em backoff de sondagem (falha recente, persistida
    em `verificacao_de_anime`). Quem chama passa o resultado a `agendar_sondagens`
    (`em_espera`) e ao reparo de fonte perdida: sem isto, um anime que falha
    (ex. Cloudflare rejeitando a sessão) seria retentado a cada abertura da
    Galeria e ocuparia vaga do teto por lote sem nunca ceder lugar. Cobre também
    a varredura cara de reparo (sem `FonteAnime` mapeada), que antes tinha um
    cooldown em memória próprio."""
    return await verificacao.ids_em_espera(sessao, ids, TarefaDeVerificacao.FONTE)


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
    pula quem está em backoff (`ids_em_espera`) e quem chama passa o resultado
    em `ignorar_gate_de_status`."""
    em_espera = await ids_em_espera(sessao, novas)
    sem_fonte = [
        anime_id
        for anime_id in novas
        if anime_id not in versoes_existentes and anime_id not in em_espera
    ]
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
    em_espera: frozenset[int] = frozenset(),
) -> None:
    """Dispara, sem bloquear, a sondagem da fonte real dos animes em lançamento
    cuja contagem está velha (> `_TTL_SONDAGEM_S`) ou ausente — no máximo
    `_MAX_SONDAGENS_POR_LOTE` por passada, os de carimbo mais antigo primeiro.
    Fire-and-forget: o resultado entra no banco para a próxima leitura do
    catálogo, não para esta (mesmo padrão de
    `descoberta.agendar_refresh_de_lancamento`).

    `em_espera`: ids em backoff por falha recente (`ids_em_espera`) — pulados
    ANTES do teto por lote, senão os mesmos animes presos ocupariam as vagas.

    `ignorar_gate_de_status`: ids que pulam o gate de status de lançamento por
    completo — uso exclusivo do reparo de `versoes_para_reresolver_fonte_perdida`
    (`api/rotas/animes.py::listar_animes`): um anime `FINALIZADO` sem NENHUMA
    `FonteAnime` mapeada também precisa ser tentado (a resolução persiste a
    fonte perdida como efeito colateral, ver `_sondar_e_persistir`), não só a
    janela pós-fim de `core.ciclo_de_vida`. Autolimitado
    igual ao resto: uma vez resolvido, o anime ganha uma `FonteAnime` e some
    do conjunto de candidatos na próxima passada (`versoes_de_sondagem_por_anime`
    já cobre ele normalmente dali em diante).

    100% síncrona, zero I/O. No-op silencioso (nenhuma destas condições é
    anormal, então sem log) quando não há event loop rodando, ou para cada anime
    cuja fase (`core.ciclo_de_vida.deve_sondar_fonte`) não pede sondagem E que não
    está em `ignorar_gate_de_status`; não tem fonte mapeada nem palpite de versão
    (`anime.id not in versoes`); contagem ainda dentro do TTL; ou já tem uma
    sondagem em voo.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    limite = datetime.now(UTC) - timedelta(seconds=_TTL_SONDAGEM_S)
    hoje = date.today()
    candidatos = sorted(animes, key=_ordem_de_sondagem)

    agendadas = 0
    for anime in candidatos:
        if agendadas >= _MAX_SONDAGENS_POR_LOTE:
            break
        if anime.id not in ignorar_gate_de_status and not deve_sondar_fonte(
            RetratoDoAnime.de(anime), hoje
        ):
            continue
        if anime.id not in versoes or anime.id in em_espera:
            continue
        if not descoberta.carimbo_esta_velho(anime.fonte_verificada_em, limite):
            continue
        if anime.id in _sondagens_em_voo:
            continue

        tarefa = loop.create_task(
            _sondar_e_persistir(sessionmaker, anime.id, versoes[anime.id])
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


def _ordem_de_sondagem(anime: Anime) -> tuple[bool, datetime]:
    """Chave de ordenação de `agendar_sondagens`: `fonte_verificada_em` nulo
    primeiro, depois o mais antigo — quem está há mais tempo sem contagem
    confiável tem prioridade no orçamento do lote."""
    carimbo = anime.fonte_verificada_em
    return (carimbo is not None, carimbo or _CARIMBO_MINIMO)


def _resultado_da_excecao(excecao: Exception) -> ResultadoDeVerificacao:
    if isinstance(excecao, SiteEmCooldown):
        return ResultadoDeVerificacao.SITE_INDISPONIVEL
    if isinstance(excecao, SessaoRejeitada):
        return ResultadoDeVerificacao.PRECISA_SESSAO
    if isinstance(excecao, FonteNaoEncontrada | VersaoIndisponivelError):
        return ResultadoDeVerificacao.NAO_ENCONTRADO
    if isinstance(excecao, FonteAmbigua):
        return ResultadoDeVerificacao.AMBIGUO
    return ResultadoDeVerificacao.ERRO


async def _registrar(
    sessionmaker: _SessionMaker,
    anime_id: int,
    resultado: ResultadoDeVerificacao,
    detalhe: str | None = None,
) -> None:
    """Grava o desfecho sem deixar um erro de banco esconder o da sondagem."""
    try:
        await verificacao.registrar_resultado(
            sessionmaker, anime_id, TarefaDeVerificacao.FONTE, resultado, detalhe=detalhe
        )
    except SQLAlchemyError as excecao:
        logger.warning("registro da verificação falhou para anime_id=%s: %s", anime_id, excecao)


async def _sondar_e_persistir(
    sessionmaker: _SessionMaker, anime_id: int, versao: VersaoEpisodio
) -> None:
    """Corpo da `Task` fire-and-forget de sondagem. Toda exceção esperada (fonte
    fora do ar, ambígua, versão indisponível, timeout, erro de banco) vira
    `warning` e morre aqui — nunca propaga para o event loop. `CancelledError` e
    erros inesperados propagam de propósito.

    Todo desfecho é registrado em `verificacao_de_anime` (`_registrar`): o
    backoff persistido segura o reintento de quem falha, inclusive a varredura
    cara de reparo (SEM fonte mapeada, a busca varre todos os extratores).
    `Anime.fonte_verificada_em` continua sendo escrito só pelo sucesso, por
    `atualizar_contagem_na_fonte`.

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
            with em_segundo_plano():
                fonte = await resolver_e_listar(
                    sessionmaker,
                    anime,
                    versao,
                    resolver_canonico=True,
                    tentar_fontes_alternativas=True,
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
        await _registrar(sessionmaker, anime_id, _resultado_da_excecao(excecao), str(excecao))
    else:
        await _registrar(sessionmaker, anime_id, ResultadoDeVerificacao.OK)

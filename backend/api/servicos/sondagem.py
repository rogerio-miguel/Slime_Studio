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
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.servicos import descoberta
from api.servicos.fontes import resolver_e_listar
from api.servicos.jobs import versao_episodio_da_fonte
from core.enums import StatusLancamento, VersaoDeFonte, VersaoEpisodio
from core.erros import FalhaDeExtracao, FonteAmbigua, VersaoIndisponivelError
from db.catalogo import atualizar_contagem_na_fonte
from extractors.servico import filtrar_por_versao
from models.anime import Anime
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


def agendar_sondagens(
    sessionmaker: _SessionMaker,
    animes: list[Anime],
    versoes: dict[int, VersaoEpisodio],
) -> None:
    """Dispara, sem bloquear, a sondagem da fonte real dos animes em lançamento
    cuja contagem está velha (> `_TTL_SONDAGEM_S`) ou ausente — no máximo
    `_MAX_SONDAGENS_POR_LOTE` por passada, os de carimbo mais antigo primeiro.
    Fire-and-forget: o resultado entra no banco para a próxima leitura do
    catálogo, não para esta (mesmo padrão de
    `descoberta.agendar_refresh_de_lancamento`).

    100% síncrona, zero I/O. No-op silencioso (nenhuma destas condições é
    anormal, então sem log) quando não há event loop rodando, ou para cada anime
    cujo: status de lançamento não é `EM_LANCAMENTO` nem nulo; não tem fonte
    mapeada (`anime.id not in versoes`); contagem ainda dentro do TTL; ou já tem
    uma sondagem em voo.
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
        if anime.status_lancamento not in (StatusLancamento.EM_LANCAMENTO, None):
            continue
        if anime.id not in versoes:
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


async def _sondar_e_persistir(
    sessionmaker: _SessionMaker, anime_id: int, versao: VersaoEpisodio
) -> None:
    """Corpo da `Task` fire-and-forget de sondagem. Toda exceção esperada (fonte
    fora do ar, ambígua, versão indisponível, timeout, erro de banco) vira
    `warning` e morre aqui — nunca propaga para o event loop. `CancelledError` e
    erros inesperados propagam de propósito.

    Só o caminho de sucesso carimba: `Anime.fonte_verificada_em` é escrito apenas
    por `atualizar_contagem_na_fonte`. Uma sondagem que falhou não mexe em coluna
    nenhuma — a próxima passada continua vendo o carimbo antigo/nulo e tenta de
    novo.

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

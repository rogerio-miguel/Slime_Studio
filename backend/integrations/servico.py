"""Serviço de metadados externos: cadeia de fallback AniList -> Kitsu com
timeout por provedor (só AniList em `buscar_titulos` — ver `PROVEDORES_DE_TITULO`
em `registro.py`; o fallback para o Kitsu continua valendo em
`buscar_por_titulo` e nas buscas por id), e cache em memória de processo do
feed "em alta".

Também orquestra o overlay de banner de TMDB por cima do resultado de
metadados/feed, ANTES de gravar qualquer cache — ver a seção "overlay de
banner" no fim do arquivo e `PLANO_ARTE_TMDB.md` (D4) para o racional
completo (memo próprio, latch de autenticação, mecânica de lote). Capa
(pôster) NÃO passa por este overlay — é responsabilidade exclusiva da cadeia
normal de `ProvedorDeMetadados` (AniList/Kitsu) acima. A
seção "overlay de still de episódio" logo depois (Fatia 5/6 do mesmo plano)
expõe `buscar_info_de_episodio` (still/nome/sinopse), consumido por
`api/servicos/fontes.py::listar_episodios_remotos` — não um dos 5 pontos de
montagem acima, é chamado por episódio, não por registro de metadados/feed.

Único lugar de `integrations/` com `asyncio.to_thread`/`asyncio.wait_for`
(mesma separação de `extractors/resiliencia.py` para os extratores de site).
`_chamar` é também o único ponto que lê/escreve o cooldown de provedor
(`_cooldown_por_provedor`, circuit breaker "lite" em memória de processo — ver
o comentário da seção logo abaixo de `_ERROS_DE_PROVEDOR`).

Cache do feed "em alta": sem precedente de cache em memória no projeto — os
dois candidatos óbvios (`extractors/circuit_breaker.py`,
`extractors/sessao_cache.py`) são ambos persistidos em SQLite, o que não se
aplica aqui (não há necessidade de sobreviver a restart de processo para um
cache de 1h de um feed público). Uma variável de módulo com timestamp resolve
sem introduzir Redis nem um novo padrão de infraestrutura.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass, replace

import requests

from core.erros import FalhaDeMetadados
from core.sinopse import eh_primeira_temporada, escolher_sinopse
from core.temporada import separar_temporada
from core.texto import slugificar
from integrations.base import (
    AnimeEmAlta,
    ArteDeAnime,
    FileiraTematica,
    InfoDeEpisodio,
    LancamentoDeAnime,
    MetadadosDeAnime,
    NoDeSerie,
    ProvedorComFileirasTematicas,
    ProvedorComLancamento,
    ProvedorComRecomendacoes,
    ProvedorComRelacoes,
    ProvedorDeArte,
    ProvedorDeMetadados,
    RelacoesDeAnime,
    TitulosDeAnime,
)
from integrations.registro import (
    FILEIRAS_TEMATICAS,
    PROVEDORES,
    PROVEDORES_DE_FEED,
    PROVEDORES_DE_TITULO,
    provedores_de_arte,
)
from integrations.tmdb import (
    TabelaDeTemporadas,
    TmdbNaoAutorizado,
    TmdbProvider,
    localizar_temporada,
)

logger = logging.getLogger(__name__)

# Teto curto por provedor: estas são APIs JSON públicas sem bypass (ao
# contrário de `extractors/resiliencia.py::_TETO_ESPERA_S`, que cobre até 2
# chamadas HTTP sequenciais de um adapter com bypass) — uma falha aqui deve
# liberar o próximo provedor da cadeia rápido.
#
# Precisa ser ESTRITAMENTE MAIOR que o timeout interno do `requests` de cada
# adapter (`integrations/anilist.py::_TIMEOUT_S` / `integrations/kitsu.py::
# _TIMEOUT_S`, hoje 6s): assim, quando um provedor só está lento (não erra),
# é a própria chamada `requests` que estoura primeiro — a thread do
# `to_thread` termina normalmente dentro da janela deste `wait_for` em vez de
# ficar órfã rodando no thread pool até o timeout dela mesma (`to_thread` não
# é cancelável pelo `wait_for`).
_TIMEOUT_POR_PROVEDOR_S: float = 8
_TTL_EM_ALTA_S = 3600
# Agenda de exibição muda tão rápido quanto "em alta" (episódio novo a
# qualquer hora) — mesmo TTL.
_TTL_NOVOS_LANCAMENTOS_S = 3600
# Roster de temporada muda devagar (estreias/adiamentos, não trending diário) —
# TTL mais folgado que o de "em alta".
_TTL_PROXIMA_TEMPORADA_S = 6 * 3600
# Popularidade por tag muda mais devagar ainda que o roster de temporada (não é
# lançamento/estreia, é ranking de trending histórico por tag) — TTL mais
# folgado que os dois acima.
_TTL_FILEIRA_TEMATICA_S = 12 * 3600
# Teto de requisições simultâneas à AniList ao buscar as 10 `FILEIRAS_TEMATICAS`
# de uma vez (`listar_fileiras_tematicas`): nem sequencial (lento demais para a
# Home), nem as 10 em paralelo (risco de rate limit — mesma preocupação do
# comentário de `PROVEDORES_DE_FEED` em `registro.py`).
_CONCORRENCIA_FILEIRAS_TEMATICAS = 3

# Overlay de arte (TMDB, PLANO_ARTE_TMDB.md D4) — TTL do memo >= o maior TTL de
# feed acima (`_TTL_FILEIRA_TEMATICA_S`, 12h): um feed já cacheado nunca
# re-pergunta ao TMDB dentro da própria vida.
_TTL_ARTE_S = 12 * 3600
# 3 fileiras simultâneas (`_CONCORRENCIA_FILEIRAS_TEMATICAS`) × 6 = 18 req/s de
# pico, folgado no teto do TMDB.
_CONCORRENCIA_ARTE = 6
_TETO_LOTE_ARTE_S = 20
_LIMITE_MEMO_ARTE = 4000

# Exceções esperadas de um provedor (rede, HTTP >=400 incluindo 429, timeout
# de `wait_for`, ou formato de resposta inesperado que o adapter sinaliza com
# `RuntimeError`) — qualquer outra exceção é bug do adapter, não "provedor
# fora do ar", e deve propagar em vez de ser engolida pela cadeia de fallback.
_ERROS_DE_PROVEDOR: tuple[type[Exception], ...] = (
    requests.RequestException,
    RuntimeError,
    TimeoutError,
)

# --- cooldown de provedor (circuit breaker "lite", em memória de processo) ---
#
# Depois de N falhas de rede/timeout CONSECUTIVAS de um provedor, as chamadas
# seguintes a ele curto-circuitam na hora (sem tocar a rede) por uma janela
# crescente, até uma sonda de meio-aberto (a 1ª chamada depois de o cooldown
# expirar) reabrir. Existe porque cada chamada a um provedor degradado custa
# 6-8s de timeout (`_TIMEOUT_POR_PROVEDOR_S` + timeout interno do `requests` de
# cada adapter), e caminhos como a Home disparam ~13 queries AniList quase
# simultâneas.
#
# Em memória de processo (dict de módulo, relógio `time.monotonic`) — MESMA
# justificativa do `_cache_em_alta` abaixo (API JSON pública, sem necessidade de
# sobreviver a restart). NÃO reusa `extractors/circuit_breaker.py`: aquele é
# SQLite e acoplado a `EstadoSite`/domínio de site com bypass anti-bot
# (CLAUDE.md §1 — as duas famílias de adapter não se cruzam). Espelha só o
# vocabulário: `falhas_consecutivas`, backoff crescente + cooldown cheio, estado
# DERIVADO de `cooldown_ate > agora` (nunca um bool próprio).
#
# Backoff suave (decisão do usuário; vs. `(30, 120, 600)` + 3600s do breaker de
# sites): 1ª falha 15s, 2ª 60s, 3ª 300s, 4ª em diante 900s (cooldown cheio).
# Uma onda concorrente de falhas conta como UMA (ver `_registrar_falha_de_provedor`):
# o degrau só aprofunda na sonda de meio-aberto após o cooldown expirar.
_BACKOFF_DE_COOLDOWN_S: tuple[int, ...] = (15, 60, 300)
_LIMITE_PARA_COOLDOWN_CHEIO = len(_BACKOFF_DE_COOLDOWN_S)
_COOLDOWN_CHEIO_S = 900


class ProvedorEmCooldown(RuntimeError):
    """Curto-circuito: o provedor acumulou `falhas_consecutivas` e está em
    cooldown — a chamada falha na hora, sem tocar a rede. Subclasse de
    `RuntimeError` (já em `_ERROS_DE_PROVEDOR`), então `_buscar_em_cadeia`, os
    loops de feed e as buscas por id já a tratam como "provedor falhou": caem
    para o próximo provedor / marcam falho / levantam `FalhaDeMetadados` se
    todos falharam. Não conta como falha nova (não incrementa o contador)."""


# `nome do provedor -> (falhas_consecutivas, cooldown_ate em time.monotonic())`.
# Lido e escrito SÓ no contexto async de `_chamar` (antes/depois do
# `await asyncio.to_thread(...)`), NUNCA dentro da thread — o event loop é
# single-thread, então não há corrida e nenhum lock é necessário (mesma garantia
# de `_arte_desabilitada_por_auth`). `tests/conftest.py::_isola_cooldown_de_provedor`
# (autouse) zera este dict entre testes (estado de módulo).
_cooldown_por_provedor: dict[str, tuple[int, float]] = {}


def _nivel_de_log_de_falha(excecao: BaseException | None) -> int:
    """`DEBUG` quando a falha é um curto-circuito de cooldown já anunciado uma
    vez por `_registrar_falha_de_provedor` (`ProvedorEmCooldown`, direto ou como
    `__cause__` de um `FalhaDeMetadados`) — logar cada chamada curto-circuitada
    em `WARNING` repoluiria o log, que é o que o cooldown existe pra consertar.
    `WARNING` para qualquer falha real de provedor (comportamento inalterado —
    `ProvedorEmCooldown` é um tipo novo, então isto é no-op pro que já existia)."""
    return logging.DEBUG if isinstance(excecao, ProvedorEmCooldown) else logging.WARNING


# `(expira_em_monotonic, itens)` — `None` até o primeiro sucesso.
_cache_em_alta: tuple[float, list[AnimeEmAlta]] | None = None

# Guarda a seção "checar cache -> buscar se expirado -> gravar cache" de
# `listar_em_alta` contra rajada concorrente (thundering herd): sem isto, N
# requisições simultâneas durante uma janela de cache-miss disparariam N
# buscas reais aos provedores em paralelo, agravando o risco de rate-limit
# do AniList (§9 do documento de especificação).
_lock_em_alta = asyncio.Lock()

# `(expira_em_monotonic, itens)` — `None` até o primeiro sucesso. Cache/lock
# próprios (independentes dos de "em alta"): é outro feed, outro TTL.
_cache_novos_lancamentos: tuple[float, list[AnimeEmAlta]] | None = None
_lock_novos_lancamentos = asyncio.Lock()

# `(expira_em_monotonic, itens)` — `None` até o primeiro sucesso. Cache/lock
# próprios (independentes dos de "em alta"): é outro feed, outro TTL.
_cache_proxima_temporada: tuple[float, list[AnimeEmAlta]] | None = None
_lock_proxima_temporada = asyncio.Lock()

# Cache/lock POR FILEIRA (não um par global como acima): cada uma das 10
# `FILEIRAS_TEMATICAS` é buscada e expira de forma independente — um lock
# global serializaria a busca de todas as fileiras entre si, e uma fileira
# lenta ou em cache-miss bloquearia as outras 9 sem necessidade. Chaves e locks
# pré-criados a partir de `FILEIRAS_TEMATICAS` (fixa, definida em
# `registro.py`) — sem criação preguiçosa de lock por chave, que exigiria sua
# própria proteção contra corrida.
_cache_fileiras_tematicas: dict[str, tuple[float, list[AnimeEmAlta]]] = {}
_locks_fileiras_tematicas: dict[str, asyncio.Lock] = {
    fileira.chave: asyncio.Lock() for fileira in FILEIRAS_TEMATICAS
}
_fileiras_por_chave: dict[str, FileiraTematica] = {
    fileira.chave: fileira for fileira in FILEIRAS_TEMATICAS
}

# Referência FORTE às tasks de revalidação em segundo plano (stale-while-
# revalidate, ver `_servir_feed_com_stale_revalidate` abaixo) — o loop do
# asyncio só guarda referência FRACA de uma task (`asyncio.create_task`),
# então sem isto ela pode ser coletada pelo GC no meio da execução (armadilha
# documentada da stdlib). `add_done_callback` remove sozinho ao terminar.
_tarefas_de_revalidacao_em_segundo_plano: set[asyncio.Task] = set()


def _agendar_revalidacao_em_segundo_plano(corrotina: Coroutine[None, None, None]) -> None:
    tarefa = asyncio.create_task(corrotina)
    _tarefas_de_revalidacao_em_segundo_plano.add(tarefa)
    tarefa.add_done_callback(_tarefas_de_revalidacao_em_segundo_plano.discard)


# --- persistência dos feeds entre reinícios ---
#
# Os 4 feeds acima vivem só na memória do processo: depois de um restart da API
# a 1ª abertura da Home é cache-miss em tudo e espera a busca AniList + overlay
# TMDB por item (dezenas de segundos medidos, 2026-10-02). `integrations/` não
# conhece banco (domínio puro) — quem persiste é injetado pela API no lifespan,
# como `instalar_provedores_de_arte`. Sem instalar, nada muda (testes, scripts).
_CHAVE_EM_ALTA = "em-alta"
_CHAVE_NOVOS_LANCAMENTOS = "novos-lancamentos"
_CHAVE_PROXIMA_TEMPORADA = "proxima-temporada"
_PREFIXO_CHAVE_FILEIRA = "fileira:"

_persistir_feed: Callable[[str, list[AnimeEmAlta]], Awaitable[None]] | None = None


def instalar_persistencia_de_feeds(
    persistir: Callable[[str, list[AnimeEmAlta]], Awaitable[None]],
) -> None:
    global _persistir_feed
    _persistir_feed = persistir


def restaurar_feeds_persistidos(feeds: dict[str, list[AnimeEmAlta]]) -> None:
    """Semeia os caches de memória com o que foi persistido, já EXPIRADO
    (`expira_em=0.0`): a 1ª requisição serve esse dado na hora como "velho" e
    `_servir_feed_com_stale_revalidate` dispara a revalidação em segundo plano —
    o usuário nunca espera a busca real. Não sobrescreve cache já preenchido.
    Chave desconhecida (fileira removida de `FILEIRAS_TEMATICAS`) é ignorada."""
    global _cache_em_alta, _cache_novos_lancamentos, _cache_proxima_temporada
    for chave, itens in feeds.items():
        if chave == _CHAVE_EM_ALTA and _cache_em_alta is None:
            _cache_em_alta = (0.0, itens)
        elif chave == _CHAVE_NOVOS_LANCAMENTOS and _cache_novos_lancamentos is None:
            _cache_novos_lancamentos = (0.0, itens)
        elif chave == _CHAVE_PROXIMA_TEMPORADA and _cache_proxima_temporada is None:
            _cache_proxima_temporada = (0.0, itens)
        elif chave.startswith(_PREFIXO_CHAVE_FILEIRA):
            fileira = chave.removeprefix(_PREFIXO_CHAVE_FILEIRA)
            if fileira in _fileiras_por_chave:
                _cache_fileiras_tematicas.setdefault(fileira, (0.0, itens))


async def _persistir_em_segundo_plano(chave: str, itens: list[AnimeEmAlta]) -> None:
    if _persistir_feed is None:
        return
    try:
        await _persistir_feed(chave, itens)
    except Exception as excecao:  # noqa: BLE001
        # Best-effort: o cache de memória já foi gravado; falhar em persistir
        # (tabela ainda não migrada, banco ocupado) nunca derruba nem atrasa o feed.
        logger.warning("não foi possível persistir o feed %r: %s", chave, excecao)

# Memo de processo do overlay de banner (D4): `(slug do título base, ano) ->
# (expira_em_monotonic, ArteDeAnime | None)`. Com cache negativo — título que
# o TMDB não achou não é re-perguntado dentro do TTL. Ao ultrapassar
# `_LIMITE_MEMO_ARTE`, `_gravar_memo_arte` limpa o dict inteiro (política
# simples e correta, sem LRU).
# `tests/test_integrations_metadados.py` tem fixture autouse que zera isto
# entre testes (estado de módulo).
_memo_arte: dict[tuple[str, int | None], tuple[float, ArteDeAnime | None]] = {}

# Memo de processo de `buscar_titulos` (títulos canônicos AniList) — chave é o
# slug do título cadastrado. Mesma política/TTL de `_memo_arte` (cache
# negativo incluído, limpa o dict inteiro ao estourar `_LIMITE_MEMO_ARTE`):
# sem isto, toda visita a `PaginaDoAnime.jsx` paga uma chamada AniList nova
# pro MESMO anime (`api/servicos/fontes.py::resolver_e_listar` chama
# `buscar_titulos` a cada requisição, sem cache próprio) — títulos canônicos
# não mudam na frequência de navegação do usuário.
_memo_titulos: dict[str, tuple[float, TitulosDeAnime | None]] = {}

# Memo de processo de `listar_relacionados` (seção "Relacionados" da página do
# anime) — chave é `anilist_id`. Mesma política de `_memo_titulos` (TTL frouxo,
# sem lock: 1 página de detalhe por vez, sem o tráfego concorrente da Home que
# justifica o double-checked locking de `listar_em_alta`); TTL igual ao de
# `_memo_arte` (12h) — recomendação/relação da AniList não muda na frequência
# de navegação do usuário. `tests/test_integrations_metadados.py` tem fixture
# autouse que zera este memo entre testes junto dos demais.
_memo_relacionados: dict[int, tuple[float, list[AnimeEmAlta]]] = {}

# Memo do overlay de still/nome/sinopse de episódio (PLANO_ARTE_TMDB.md
# Fatia 5/6). Chave de `_memo_info_episodio`: `(slug do título, ano,
# temporada, numero)`, onde `temporada` é `int` quando o chamador sabe o `n`
# da temporada (`Anime.numero_temporada`, Fase 3) e `numero` é o episódio
# DENTRO dela; ou `None` (caminho legado) e `numero` é a numeração absoluta
# sobre a série inteira. Os dois caminhos nunca colidem (o `None` no 3º
# elemento os separa). A primeira consulta de QUALQUER episódio de uma
# temporada popula a info de TODOS os episódios dela de uma vez
# (`TmdbProvider.info_da_temporada` devolve a temporada inteira), então uma
# página com N episódios da mesma temporada paga só 1 `GET /tv/{id}/season/{n}`.
#
# `_memo_temporadas` cacheia a `TabelaDeTemporadas` (id da série + primeiro
# episódio absoluto por temporada) por `(slug, ano)` — usado SÓ no caminho
# legado (`temporada is None`), pra não repetir `_resolver_serie`+`GET /tv/{id}`
# por episódio. Com `temporada` conhecida esse passo não existe.
#
# Mesmo TTL (`_TTL_ARTE_S`) e política de limite (`_LIMITE_MEMO_ARTE`) do memo
# de arte acima. `tests/test_integrations_metadados.py` tem fixture autouse que
# zera os três memos entre testes.
_memo_temporadas: dict[tuple[str, int | None], tuple[float, TabelaDeTemporadas | None]] = {}
_memo_info_episodio: dict[
    tuple[str, int | None, int | None, int], tuple[float, InfoDeEpisodio | None]
] = {}

# Latch: liga na primeira `TmdbNaoAutorizado` (token errado/revogado) e nunca
# desliga sozinho — um token ruim não muda em runtime, só reiniciando o
# processo com um token corrigido. Evita dezenas de warnings por feed quando a
# má configuração já foi identificada uma vez (loga em ERROR só na virada).
_arte_desabilitada_por_auth = False

# --- walk de série (grafo `relations` da AniList, Fase 3) ---
#
# `resolver_serie` anda o grafo de `relations` SÓ PARA TRÁS (arestas PREQUEL de
# temporada de TV) até o nó sem prequel — a temporada 1 da franquia. Ir para
# frente (SEQUEL) responderia a mesma pergunta pelo dobro do custo. Cada hop é
# uma chamada AniList sob `_chamar` (teto + cooldown de provedor); memo de
# processo por `anilist_id` amortiza a franquia inteira (a caminhada grava a
# posição de todos os nós do caminho, não só a do alvo). Mesma justificativa de
# memo em memória do `_memo_arte`; mesma política de limpeza (limpa o dict
# inteiro ao estourar o limite, sem LRU). `test_integrations_metadados.py` tem
# fixture autouse que zera este memo entre testes.


@dataclass(frozen=True, slots=True)
class SerieResolvida:
    ancora: int  # `anilist_id` da temporada 1 (== o próprio id quando não há prequel de TV)
    ordinal: int  # posição narrativa na franquia, 1-based


_MAX_HOPS_DE_SERIE = 12
_TTL_SERIE_S = 24 * 3600
_LIMITE_MEMO_SERIE = 4000
_memo_serie: dict[int, tuple[float, SerieResolvida]] = {}


class _SerieAmbigua(Exception):
    """Um nó tem mais de um prequel de TV e as datas não bastam para desempatar
    — o walk para sem âncora (a correção manual desses casos é a Fase 6)."""


async def buscar_por_titulo(titulo: str) -> MetadadosDeAnime | None:
    """Tenta cada provedor de `PROVEDORES` em ordem até achar metadados para
    `titulo`; ver `_buscar_em_cadeia` para a semântica de fallback. Overlay de
    arte (TMDB) sobreposto antes de devolver — ver `_com_arte`/D4."""
    resultado = await _buscar_em_cadeia(
        lambda provedor: provedor.buscar_por_titulo, titulo, descricao="busca por título"
    )
    if resultado is None:
        return resultado
    titulo_arte = resultado.titulo_ingles or resultado.titulo_romaji or titulo
    return await _com_arte(resultado, titulo=titulo_arte, ano=resultado.ano)


def _gravar_memo_titulos(slug: str, titulos: TitulosDeAnime | None) -> None:
    """Mesma política de `_gravar_memo_arte`: grava inclusive `None` (cache
    negativo), limpa o dict inteiro ao estourar `_LIMITE_MEMO_ARTE`."""
    if len(_memo_titulos) >= _LIMITE_MEMO_ARTE:
        _memo_titulos.clear()
    _memo_titulos[slug] = (time.monotonic() + _TTL_ARTE_S, titulos)


async def buscar_titulos(titulo: str) -> TitulosDeAnime | None:
    """Tenta cada provedor de `PROVEDORES_DE_TITULO` (só a AniList — ver o
    comentário da tupla em `registro.py`) em ordem até achar títulos
    alternativos (romaji/inglês/nativo/sinônimos) para `titulo` — usado por
    `api/servicos/busca.py::_resolver_titulos_canonicos` como base da escada de
    termos e das referências de validação da busca em fontes.

    Ao contrário de `buscar_por_titulo`, NÃO cai para o Kitsu: a resolução do
    título canônico é enriquecimento best-effort sob teto curto, e a AniList
    fora do ar deve degradar direto (`FalhaDeMetadados` → o chamador segue só
    com o título digitado), sem pagar a latência de timeout do Kitsu instável.
    Ver `_buscar_em_cadeia` para a semântica de fallback dentro da tupla.

    Cacheado em processo por `_memo_titulos` (TTL `_TTL_ARTE_S`, cache
    negativo incluído) — chamador típico (`api/servicos/fontes.py::
    resolver_e_listar`) invoca isto em TODA visita à página do anime; sem o
    memo, cada visita pagaria uma chamada AniList nova para o mesmo anime.
    Grava só no caminho de sucesso: uma `FalhaDeMetadados` (todos os
    provedores fora do ar) propaga sem tocar o memo, deixando a próxima
    chamada tentar de novo em vez de fixar a falha pelo TTL inteiro."""
    slug = slugificar(titulo)
    memo = _memo_titulos.get(slug)
    if memo is not None:
        expira_em, titulos_cacheados = memo
        if time.monotonic() < expira_em:
            return titulos_cacheados

    resultado = await _buscar_em_cadeia(
        lambda provedor: provedor.buscar_titulos,
        titulo,
        descricao="busca de títulos",
        provedores=PROVEDORES_DE_TITULO,
    )
    _gravar_memo_titulos(slug, resultado)
    return resultado


def _gravar_memo_relacionados(anilist_id: int, itens: list[AnimeEmAlta]) -> None:
    """Mesma política de `_gravar_memo_arte`: limpa o dict inteiro ao estourar
    `_LIMITE_MEMO_ARTE` (sem cache negativo aqui — `[]` já É a resposta normal
    de "sem sugestão", não precisa de tratamento à parte)."""
    if len(_memo_relacionados) >= _LIMITE_MEMO_ARTE:
        _memo_relacionados.clear()
    _memo_relacionados[anilist_id] = (time.monotonic() + _TTL_ARTE_S, itens)


async def listar_relacionados(anilist_id: int) -> list[AnimeEmAlta]:
    """"Relacionados" da página do anime (`GET /api/animes/{id}/relacionados`):
    recomendações da comunidade + relações de franquia não sequenciais
    (`ProvedorComRecomendacoes.buscar_relacionados`). Best-effort de ponta a
    ponta — ao contrário de `_buscar_em_cadeia`/`listar_em_alta`, uma falha
    (provedor fora do ar, cooldown, ou nenhum provedor com a capability)
    degrada para `[]` em vez de propagar `FalhaDeMetadados`: esta seção é
    conteúdo suplementar da página do anime, que já teve seu conteúdo
    principal carregado por `obter_anime` — não pode derrubar a página por
    causa dela (CLAUDE.md: erro nunca silencioso É pra falha inesperada, não
    pra "sem sinal"; aqui `[]` É o resultado normal tanto pra "sem sugestão"
    quanto pra "provedor fora do ar", e o warning abaixo cobre o segundo caso
    no log).

    Overlay de arte (TMDB) sobreposto antes de cachear — mesmo padrão de
    `listar_em_alta`/`_buscar_fileira_tematica_sem_cache`. Cacheado por
    `_memo_relacionados` (TTL `_TTL_ARTE_S`, sem lock — ver docstring do
    dict)."""
    memo = _memo_relacionados.get(anilist_id)
    if memo is not None:
        expira_em, itens = memo
        if time.monotonic() < expira_em:
            return itens

    capazes = [p for p in PROVEDORES if isinstance(p, ProvedorComRecomendacoes)]
    for provedor in capazes:
        try:
            itens = await _chamar(provedor, provedor.buscar_relacionados, anilist_id)
        except _ERROS_DE_PROVEDOR as excecao:
            logger.log(
                _nivel_de_log_de_falha(excecao),
                "provedor de metadados %r falhou ao buscar relacionados de anilist_id=%s: %s",
                provedor.nome,
                anilist_id,
                excecao,
            )
            continue

        itens = await _sobrepor_arte_em_lote(itens)
        _gravar_memo_relacionados(anilist_id, itens)
        return itens

    return []


async def listar_por_busca(titulo: str) -> list[AnimeEmAlta]:
    """Candidatos de uma busca livre por `titulo` — alimenta a busca da Home
    (`GET /api/animes/buscar`). Só `PROVEDORES_DE_TITULO` (a AniList; o Kitsu
    não expõe busca em lista).

    Best-effort e SEM cache: é termo do usuário, baixa repetição, e a busca da
    Home não pode quebrar por AniList fora do ar. Qualquer erro de provedor
    (`_ERROS_DE_PROVEDOR` — rede, timeout, cooldown, formato inesperado)
    degrada para `[]` com `logger.warning` (CLAUDE.md §4 — degrada explícito,
    não silencioso)."""
    for provedor in PROVEDORES_DE_TITULO:
        try:
            return await _chamar(provedor, provedor.listar_por_busca, titulo)
        except _ERROS_DE_PROVEDOR as excecao:
            logger.warning(
                "provedor de metadados %r falhou na busca em lista de %r: %s",
                provedor.nome,
                titulo,
                excecao,
            )
    return []


async def buscar_lancamento_por_anilist_id(anilist_id: int) -> LancamentoDeAnime | None:
    """Estado de lançamento (status/próximo episódio) de um anime pelo seu id
    AniList. Só provedores que implementam `ProvedorComLancamento` entram na
    cadeia (hoje só o AniList — Kitsu não expõe next-airing).

    Mesma semântica de fallback de `_buscar_em_cadeia`: primeira resposta
    não-`None` vence; um provedor que levanta é logado e a cadeia segue para o
    próximo; só levanta `FalhaDeMetadados` se todos os provedores capazes
    falharem de fato. Se nenhum provedor é capaz, devolve `None` (condição
    estrutural, não "provedores fora do ar"). Sem cache — a frequência do
    refresh oportunista (F4) é controlada por quem chama.
    """
    capazes = [p for p in PROVEDORES if isinstance(p, ProvedorComLancamento)]
    if not capazes:
        return None

    algum_respondeu = False
    ultimo_erro: Exception | None = None
    for provedor in capazes:
        try:
            resultado = await _chamar(
                provedor, provedor.buscar_lancamento_por_anilist_id, anilist_id
            )
        except _ERROS_DE_PROVEDOR as excecao:
            logger.log(
                _nivel_de_log_de_falha(excecao),
                "provedor de metadados %r falhou ao buscar lançamento de anilist_id=%s: %s",
                provedor.nome,
                anilist_id,
                excecao,
            )
            ultimo_erro = excecao
            continue

        algum_respondeu = True
        if resultado is not None:
            return resultado

    if algum_respondeu:
        return None
    raise FalhaDeMetadados(
        f"todos os provedores falharam ao buscar lançamento de anilist_id={anilist_id}"
    ) from ultimo_erro


async def buscar_metadados_por_anilist_id(anilist_id: int) -> MetadadosDeAnime | None:
    """Metadados completos (capa, banner, cor dominante da capa, sinopse) de um
    anime pelo seu id AniList — usado pelo backfill de arte visual
    (`scripts/backfill_metadados_visuais.py`).

    Mesma semântica de fallback de `buscar_lancamento_por_anilist_id`: primeira
    resposta não-`None` vence; um provedor que levanta é logado e a cadeia segue
    para o próximo; só levanta `FalhaDeMetadados` se TODOS os provedores falharem
    de fato (rede/HTTP/timeout). Provedores que não conhecem id AniList (Kitsu)
    devolvem `None` pela implementação padrão de `ProvedorDeMetadados` e a cadeia
    segue — se ninguém resolve, devolve `None` em vez de exceção. Sem cache (o
    cache TTL de `servico.py` é só para os feeds sazonais). Overlay de arte
    (TMDB) sobreposto antes de devolver — ver `_com_arte`/D4.
    """
    algum_respondeu = False
    ultimo_erro: Exception | None = None
    for provedor in PROVEDORES:
        try:
            resultado = await _chamar(
                provedor, provedor.buscar_metadados_por_anilist_id, anilist_id
            )
        except _ERROS_DE_PROVEDOR as excecao:
            logger.log(
                _nivel_de_log_de_falha(excecao),
                "provedor de metadados %r falhou ao buscar metadados de anilist_id=%s: %s",
                provedor.nome,
                anilist_id,
                excecao,
            )
            ultimo_erro = excecao
            continue

        algum_respondeu = True
        if resultado is not None:
            titulo_arte = resultado.titulo_ingles or resultado.titulo_romaji
            return await _com_arte(resultado, titulo=titulo_arte, ano=resultado.ano)

    if algum_respondeu:
        return None
    raise FalhaDeMetadados(
        f"todos os provedores falharam ao buscar metadados de anilist_id={anilist_id}"
    ) from ultimo_erro


async def _buscar_em_cadeia[T](
    operacao: Callable[[ProvedorDeMetadados], Callable[[str], T | None]],
    titulo: str,
    *,
    descricao: str,
    provedores: tuple[ProvedorDeMetadados, ...] | None = None,
) -> T | None:
    """Tenta cada provedor de `provedores` em ordem, chamando `operacao(provedor)`
    com `titulo`. `provedores=None` (padrão) usa a cadeia completa `PROVEDORES`
    — resolvida a cada chamada, para os testes poderem monkeypatchar
    `servico.PROVEDORES`; `buscar_titulos` passa `PROVEDORES_DE_TITULO` (só
    AniList). Um provedor que responde mas não encontra o título (`None`) não é
    falha — cai para o próximo provedor tentar, mesma filosofia de
    `extractors/resolucao.py` (busca vazia não é erro). Só levanta
    `FalhaDeMetadados` se todos os provedores falharem de fato (rede/HTTP/
    timeout); se todos responderem sem encontrar, devolve `None` (título não
    existe em nenhum provedor conhecido). `descricao` entra na mensagem de
    log/erro para diferenciar qual operação falhou.
    """
    cadeia = provedores if provedores is not None else PROVEDORES
    algum_respondeu = False
    ultimo_erro: Exception | None = None

    for provedor in cadeia:
        try:
            resultado = await _chamar(provedor, operacao(provedor), titulo)
        except _ERROS_DE_PROVEDOR as excecao:
            logger.log(
                _nivel_de_log_de_falha(excecao),
                "provedor de metadados %r falhou em %s de %r: %s",
                provedor.nome,
                descricao,
                titulo,
                excecao,
            )
            ultimo_erro = excecao
            continue

        algum_respondeu = True
        if resultado is not None:
            return resultado

    if algum_respondeu:
        return None
    raise FalhaDeMetadados(
        f"todos os provedores de metadados falharam em {descricao} de {titulo!r}"
    ) from ultimo_erro


# --- stale-while-revalidate genérico dos 4 feeds cacheados da Home ---
#
# Antes (double-checked locking puro): cache expirado bloqueava a requisição
# que calhasse de chegar naquele instante até a busca real terminar — na
# fileira temática (10 queries AniList + overlay TMDB por item) isso podia
# ser bem lento numa cache fria. Agora: cache expirado devolve o dado ANTIGO
# na hora e dispara UMA revalidação em segundo plano (guardada pelo próprio
# lock — `lock.locked()` evita empilhar tasks quando várias requisições
# chegam juntas logo após o TTL vencer); ninguém mais paga a latência da
# AniList/TMDB só por calhar de bater a rota nesse instante. Cache-MISS (1ª
# busca de sempre, sem dado velho pra servir) segue bloqueante — não tem
# alternativa.
#
# Cada um dos 4 feeds mantém seu PRÓPRIO armazenamento (tupla de módulo para
# em-alta/novos-lançamentos/próxima-temporada, dict por chave para fileiras
# temáticas — decisão anterior já documentada acima, não migrada pra um cache
# único); só a MECÂNICA de revalidação é compartilhada aqui via `obter_cache`/
# `gravar_cache` (closures de quem chama).
async def _servir_feed_com_stale_revalidate(
    obter_cache: Callable[[], tuple[float, list[AnimeEmAlta]] | None],
    gravar_cache: Callable[[list[AnimeEmAlta]], None],
    lock: asyncio.Lock,
    buscar_sem_cache: Callable[[], Awaitable[list[AnimeEmAlta]]],
    descricao: str,
    chave_persistida: str,
) -> list[AnimeEmAlta]:
    entrada = obter_cache()
    if entrada is not None:
        expira_em, itens = entrada
        if time.monotonic() < expira_em:
            return itens
        if not lock.locked():
            _agendar_revalidacao_em_segundo_plano(
                _revalidar_em_segundo_plano(
                    obter_cache, gravar_cache, lock, buscar_sem_cache, descricao, chave_persistida
                )
            )
        return itens

    async with lock:
        entrada = obter_cache()
        if entrada is not None and time.monotonic() < entrada[0]:
            return entrada[1]
        itens = await buscar_sem_cache()
        gravar_cache(itens)
        if _persistir_feed is not None:
            _agendar_revalidacao_em_segundo_plano(
                _persistir_em_segundo_plano(chave_persistida, itens)
            )
        return itens


async def _revalidar_em_segundo_plano(
    obter_cache: Callable[[], tuple[float, list[AnimeEmAlta]] | None],
    gravar_cache: Callable[[list[AnimeEmAlta]], None],
    lock: asyncio.Lock,
    buscar_sem_cache: Callable[[], Awaitable[list[AnimeEmAlta]]],
    descricao: str,
    chave_persistida: str,
) -> None:
    async with lock:
        # Outra revalidação (ou a busca bloqueante de cache-miss) pode ter
        # corrido enquanto esperávamos o lock — não bate na AniList à toa se
        # já resolveu.
        entrada = obter_cache()
        if entrada is not None and time.monotonic() < entrada[0]:
            return
        try:
            itens = await buscar_sem_cache()
        except FalhaDeMetadados as excecao:
            # Falha aqui NUNCA propaga: ninguém está esperando por esta task
            # (o chamador original já recebeu o dado stale). Mantém o cache
            # antigo servindo até a próxima tentativa.
            logger.warning(
                "revalidação em segundo plano de %r falhou, mantendo cache antigo: %s",
                descricao,
                excecao,
            )
            return
        gravar_cache(itens)
        await _persistir_em_segundo_plano(chave_persistida, itens)


async def _buscar_em_alta_sem_cache() -> list[AnimeEmAlta]:
    ultimo_erro: Exception | None = None
    for provedor in PROVEDORES_DE_FEED:
        try:
            itens = await _chamar(provedor, provedor.listar_em_alta)
        except _ERROS_DE_PROVEDOR as excecao:
            logger.log(
                _nivel_de_log_de_falha(excecao),
                "provedor de metadados %r falhou ao listar 'em alta': %s",
                provedor.nome,
                excecao,
            )
            ultimo_erro = excecao
            continue
        return await _sobrepor_arte_em_lote(itens)

    raise FalhaDeMetadados(
        "todos os provedores de metadados falharam ao listar 'em alta'"
    ) from ultimo_erro


async def listar_em_alta() -> list[AnimeEmAlta]:
    """Feed "lançamentos em alta", cacheado em memória por `_TTL_EM_ALTA_S`
    com stale-while-revalidate (ver `_servir_feed_com_stale_revalidate`
    acima). Percorre só `PROVEDORES_DE_FEED` (AniList; Kitsu de fora — ver o
    comentário da tupla em `registro.py`). Propaga `FalhaDeMetadados` só no
    cache-miss (1ª busca) se todos os provedores falharem — nunca devolve
    `[]` silenciosamente para não confundir "sem lançamentos" com
    "provedores fora do ar" (CLAUDE.md: erro nunca silencioso)."""

    def _obter() -> tuple[float, list[AnimeEmAlta]] | None:
        return _cache_em_alta

    def _gravar(itens: list[AnimeEmAlta]) -> None:
        global _cache_em_alta
        _cache_em_alta = (time.monotonic() + _TTL_EM_ALTA_S, itens)

    return await _servir_feed_com_stale_revalidate(
        _obter,
        _gravar,
        _lock_em_alta,
        _buscar_em_alta_sem_cache,
        "em alta",
        _CHAVE_EM_ALTA,
    )


async def _buscar_novos_lancamentos_sem_cache() -> list[AnimeEmAlta]:
    ultimo_erro: Exception | None = None
    for provedor in PROVEDORES_DE_FEED:
        try:
            itens = await _chamar(provedor, provedor.listar_novos_lancamentos)
        except _ERROS_DE_PROVEDOR as excecao:
            logger.log(
                _nivel_de_log_de_falha(excecao),
                "provedor de metadados %r falhou ao listar 'novos lançamentos': %s",
                provedor.nome,
                excecao,
            )
            ultimo_erro = excecao
            continue
        return await _sobrepor_arte_em_lote(itens)

    raise FalhaDeMetadados(
        "todos os provedores de metadados falharam ao listar 'novos lançamentos'"
    ) from ultimo_erro


async def listar_novos_lancamentos() -> list[AnimeEmAlta]:
    """Feed "novos lançamentos" (um anime por card, o mais recente primeiro),
    cacheado em memória por `_TTL_NOVOS_LANCAMENTOS_S` com stale-while-
    revalidate (ver `_servir_feed_com_stale_revalidate`). Propaga
    `FalhaDeMetadados` só no cache-miss (1ª busca) se todos falharem — nunca
    devolve `[]` silenciosamente para não confundir "nada saiu ainda" com
    "provedores fora do ar" (CLAUDE.md: erro nunca silencioso)."""

    def _obter() -> tuple[float, list[AnimeEmAlta]] | None:
        return _cache_novos_lancamentos

    def _gravar(itens: list[AnimeEmAlta]) -> None:
        global _cache_novos_lancamentos
        _cache_novos_lancamentos = (time.monotonic() + _TTL_NOVOS_LANCAMENTOS_S, itens)

    return await _servir_feed_com_stale_revalidate(
        _obter,
        _gravar,
        _lock_novos_lancamentos,
        _buscar_novos_lancamentos_sem_cache,
        "novos lançamentos",
        _CHAVE_NOVOS_LANCAMENTOS,
    )


async def _buscar_proxima_temporada_sem_cache() -> list[AnimeEmAlta]:
    ultimo_erro: Exception | None = None
    for provedor in PROVEDORES_DE_FEED:
        try:
            itens = await _chamar(provedor, provedor.listar_proxima_temporada)
        except _ERROS_DE_PROVEDOR as excecao:
            logger.log(
                _nivel_de_log_de_falha(excecao),
                "provedor de metadados %r falhou ao listar 'próxima temporada': %s",
                provedor.nome,
                excecao,
            )
            ultimo_erro = excecao
            continue
        return await _sobrepor_arte_em_lote(itens)

    raise FalhaDeMetadados(
        "todos os provedores de metadados falharam ao listar 'próxima temporada'"
    ) from ultimo_erro


async def listar_proxima_temporada() -> list[AnimeEmAlta]:
    """Feed "próxima temporada", cacheado em memória por
    `_TTL_PROXIMA_TEMPORADA_S` com stale-while-revalidate (ver
    `_servir_feed_com_stale_revalidate`). Propaga `FalhaDeMetadados` só no
    cache-miss (1ª busca) se todos falharem — nunca devolve `[]`
    silenciosamente para não confundir "temporada ainda sem anúncios" com
    "provedores fora do ar" (CLAUDE.md: erro nunca silencioso)."""

    def _obter() -> tuple[float, list[AnimeEmAlta]] | None:
        return _cache_proxima_temporada

    def _gravar(itens: list[AnimeEmAlta]) -> None:
        global _cache_proxima_temporada
        _cache_proxima_temporada = (time.monotonic() + _TTL_PROXIMA_TEMPORADA_S, itens)

    return await _servir_feed_com_stale_revalidate(
        _obter,
        _gravar,
        _lock_proxima_temporada,
        _buscar_proxima_temporada_sem_cache,
        "próxima temporada",
        _CHAVE_PROXIMA_TEMPORADA,
    )


async def listar_fileira_tematica(chave: str) -> list[AnimeEmAlta]:
    """Uma fileira temática específica (`FILEIRAS_TEMATICAS` em `registro.py`),
    cacheada em memória por `_TTL_FILEIRA_TEMATICA_S` via `_listar_com_cache`.
    Levanta `ValueError` se `chave` não corresponde a nenhuma fileira
    conhecida, e propaga `FalhaDeMetadados` se a busca falhar (ver
    `_buscar_fileira_tematica_sem_cache`) — ao contrário de
    `listar_fileiras_tematicas`, aqui não há "fileiras irmãs" para absorver a
    falha, então a exceção sobe para quem chamou."""
    fileira = _fileiras_por_chave.get(chave)
    if fileira is None:
        raise ValueError(f"fileira temática desconhecida: {chave!r}")

    return await _listar_com_cache(chave, lambda: _buscar_fileira_tematica_sem_cache(fileira))


async def listar_fileiras_tematicas() -> dict[str, list[AnimeEmAlta]]:
    """Todas as `FILEIRAS_TEMATICAS`, cada uma com seu cache/TTL próprio (ver
    `listar_fileira_tematica`), buscadas com no máximo
    `_CONCORRENCIA_FILEIRAS_TEMATICAS` requisições simultâneas à AniList.

    Uma fileira que falha (exceção, timeout, resposta malformada — tudo que
    `_buscar_fileira_tematica_sem_cache` já traduz em `FalhaDeMetadados`) é
    logada e OMITIDA do dict resultado; as demais seguem normalmente. Só
    levanta `FalhaDeMetadados` se TODAS as fileiras falharem — nunca devolve
    `{}` silenciosamente, para não confundir "todas sem resultado" com
    "provedor fora do ar" (CLAUDE.md: erro nunca silencioso).
    """
    semaforo = asyncio.Semaphore(_CONCORRENCIA_FILEIRAS_TEMATICAS)

    async def _buscar_uma(fileira: FileiraTematica) -> tuple[str, list[AnimeEmAlta] | None]:
        async with semaforo:
            try:
                return fileira.chave, await listar_fileira_tematica(fileira.chave)
            except FalhaDeMetadados as excecao:
                # `__cause__` é o erro do provedor por baixo do `FalhaDeMetadados`
                # — `DEBUG` quando foi só um curto-circuito de cooldown.
                logger.log(
                    _nivel_de_log_de_falha(excecao.__cause__),
                    "fileira temática %r omitida do agregado: %s",
                    fileira.chave,
                    excecao,
                )
                return fileira.chave, None

    resultados = await asyncio.gather(*(_buscar_uma(fileira) for fileira in FILEIRAS_TEMATICAS))

    fileiras = {chave: itens for chave, itens in resultados if itens is not None}
    if not fileiras:
        raise FalhaDeMetadados("todas as fileiras temáticas falharam ao listar")
    return fileiras


async def _buscar_fileira_tematica_sem_cache(fileira: FileiraTematica) -> list[AnimeEmAlta]:
    """Busca `fileira` sem cache, entre os provedores que implementam
    `ProvedorComFileirasTematicas` (hoje só a AniList). Kitsu não entra aqui
    mesmo como fallback — decisão de produto fechada, taxonomia de tags
    incompatível entre provedores (ver `registro.py`) — e nem precisaria de
    filtro especial: ele simplesmente não implementa a capability. Levanta
    `FalhaDeMetadados` se todos os provedores capazes falharem."""
    capazes = [p for p in PROVEDORES if isinstance(p, ProvedorComFileirasTematicas)]

    ultimo_erro: Exception | None = None
    for provedor in capazes:
        try:
            itens = await _chamar(provedor, provedor.listar_fileira_tematica, fileira)
        except _ERROS_DE_PROVEDOR as excecao:
            logger.log(
                _nivel_de_log_de_falha(excecao),
                "provedor de metadados %r falhou ao listar fileira temática %r: %s",
                provedor.nome,
                fileira.chave,
                excecao,
            )
            ultimo_erro = excecao
            continue

        return await _sobrepor_arte_em_lote(itens)

    raise FalhaDeMetadados(
        f"todos os provedores falharam ao listar fileira temática {fileira.chave!r}"
    ) from ultimo_erro


async def _listar_com_cache(
    chave: str, buscar: Callable[[], Awaitable[list[AnimeEmAlta]]]
) -> list[AnimeEmAlta]:
    """Cache-com-TTL genérico por chave, usado SÓ pelas fileiras temáticas
    (`_cache_fileiras_tematicas`/`_locks_fileiras_tematicas`/
    `_TTL_FILEIRA_TEMATICA_S`) — mesma mecânica de stale-while-revalidate de
    `_servir_feed_com_stale_revalidate` (em-alta/novos-lançamentos/próxima-
    temporada usam a mesma função diretamente; aqui é via este wrapper porque
    o armazenamento é POR `chave`, não uma tupla de módulo — lock também é
    por `chave`, então um cache-miss numa fileira nunca bloqueia a busca de
    outra)."""

    def _obter() -> tuple[float, list[AnimeEmAlta]] | None:
        return _cache_fileiras_tematicas.get(chave)

    def _gravar(itens: list[AnimeEmAlta]) -> None:
        _cache_fileiras_tematicas[chave] = (time.monotonic() + _TTL_FILEIRA_TEMATICA_S, itens)

    return await _servir_feed_com_stale_revalidate(
        _obter,
        _gravar,
        _locks_fileiras_tematicas[chave],
        buscar,
        f"fileira temática {chave!r}",
        f"{_PREFIXO_CHAVE_FILEIRA}{chave}",
    )


# --- overlay de arte (TMDB, PLANO_ARTE_TMDB.md D4) ---


def _gravar_memo_arte(chave: tuple[str, int | None], arte: ArteDeAnime | None) -> None:
    """Grava só em caminho de sucesso (chamador decide quando), inclusive
    `None` (cache negativo). Ao ultrapassar `_LIMITE_MEMO_ARTE`, limpa o dict
    inteiro — política simples e correta, sem LRU."""
    if len(_memo_arte) >= _LIMITE_MEMO_ARTE:
        _memo_arte.clear()
    _memo_arte[chave] = (time.monotonic() + _TTL_ARTE_S, arte)


def _desabilitar_arte_por_auth(provedor: ProvedorDeArte, excecao: TmdbNaoAutorizado) -> None:
    """Liga o latch de auth e loga em `ERROR` **só na primeira vez**. Sem
    `await` entre o check e o set, é atômico sob o scheduler cooperativo do
    asyncio — mas `buscar_arte_por_titulo`/`buscar_info_de_episodio` já podem ter
    disparado várias chamadas concorrentes (`_CONCORRENCIA_ARTE`, até 3 lotes
    em paralelo) antes de a primeira falha chegar aqui; sem esse guard, cada
    uma delas loga de novo ao resolver o próprio 401 — dezenas de linhas em
    vez de uma, exatamente o ruído que o latch existe pra evitar."""
    global _arte_desabilitada_por_auth
    if _arte_desabilitada_por_auth:
        return
    _arte_desabilitada_por_auth = True
    logger.error(
        "provedor de arte %r rejeitou o token — desabilitando overlay de arte "
        "pro resto do processo: %s",
        provedor.nome,
        excecao,
    )


async def buscar_arte_por_titulo(titulo: str, ano: int | None) -> ArteDeAnime | None:
    """Busca só banner nos `provedores_de_arte()` instalados (hoje só TMDB),
    com memo de processo por `(slug do título base, ano)` — TTL `_TTL_ARTE_S`,
    com cache negativo: sem isso, aquecer `listar_fileiras_tematicas` do zero
    custaria ~500 chamadas TMDB (10 fileiras × 50 itens, repetição alta de
    anime entre fileiras).

    O título é reduzido ao título BASE via `separar_temporada` (ex. "Slime
    Season 4" -> "Slime") antes de ir ao provedor — melhora o match de busca
    de série no TMDB mesmo só para banner, já que o TMDB modela a série
    inteira, não a temporada (D3); o número de temporada derivado não
    alimenta mais nada além disso (capa não é mais resolvida aqui).

    Pública (não `_`-prefixada) porque, além do overlay interno via
    `_com_arte`, é chamada direto por scripts de backfill pra re-resolver
    banner de anime já catalogado, sem passar pelo fluxo completo de
    metadados.

    Erro de provedor (`_ERROS_DE_PROVEDOR`) NUNCA grava no memo — congelar 12h
    de "sem arte" por causa de uma falha transitória de rede seria pior que
    tentar de novo na próxima chamada; a busca simplesmente segue para o
    próximo provedor da tupla (hoje só há um, TMDB — o loop é preparado para
    mais). `TmdbNaoAutorizado` (token errado/revogado) é tratada à parte: liga
    o latch de módulo e loga uma vez em `ERROR` — sem isso um token errado
    geraria dezenas de warnings por feed e a má configuração ficaria
    invisível; a partir daí, devolve `None` de imediato sem tentar de novo.
    """
    if _arte_desabilitada_por_auth:
        return None

    titulo_base, _derivado = separar_temporada(titulo)

    chave = (slugificar(titulo_base), ano)
    memo = _memo_arte.get(chave)
    if memo is not None:
        expira_em, arte = memo
        if time.monotonic() < expira_em:
            return arte

    for provedor in provedores_de_arte():
        try:
            arte = await _chamar(provedor, provedor.buscar_arte_por_titulo, titulo_base, ano)
        except TmdbNaoAutorizado as excecao:
            _desabilitar_arte_por_auth(provedor, excecao)
            return None
        except _ERROS_DE_PROVEDOR as excecao:
            logger.log(
                _nivel_de_log_de_falha(excecao),
                "provedor de arte %r falhou ao buscar arte de %r: %s",
                provedor.nome,
                titulo,
                excecao,
            )
            continue

        _gravar_memo_arte(chave, arte)
        if arte is not None:
            return arte

    return None


async def buscar_sinopse_da_temporada(titulo: str, ano: int | None, temporada: int) -> str | None:
    """Sinopse pt-BR da temporada no TMDB — só o backfill de sinopse usa (a
    maioria das temporadas não tem tradução própria). Best-effort: erro de
    provedor vira `None` com log; sem memo (uso pontual)."""
    if _arte_desabilitada_por_auth:
        return None
    titulo_base, _derivado = separar_temporada(titulo)
    for provedor in provedores_de_arte():
        if not isinstance(provedor, TmdbProvider):
            continue
        try:
            return await _chamar(
                provedor, provedor.sinopse_da_temporada, titulo_base, ano, temporada
            )
        except TmdbNaoAutorizado as excecao:
            _desabilitar_arte_por_auth(provedor, excecao)
            return None
        except _ERROS_DE_PROVEDOR as excecao:
            logger.log(
                _nivel_de_log_de_falha(excecao),
                "provedor de arte %r falhou ao buscar sinopse da temporada %s de %r: %s",
                provedor.nome,
                temporada,
                titulo,
                excecao,
            )
    return None


# --- overlay de still/nome/sinopse de episódio (TMDB, Fatia 5/6 do PLANO_ARTE_TMDB.md) ---
#
# `buscar_info_de_episodio` tem dois caminhos: com `temporada` (o `n` da
# temporada, `Anime.numero_temporada`) vai direto a `GET /tv/{id}/season/{n}`
# e `numero` é o episódio dentro dela; sem `temporada` (legado, quando
# `numero_temporada` é desconhecido) `numero` é a numeração absoluta e a
# temporada é resolvida por `TabelaDeTemporadas`/`localizar_temporada`.


def _gravar_memo_temporadas(
    chave: tuple[str, int | None], tabela: TabelaDeTemporadas | None
) -> None:
    """Mesma política de `_gravar_memo_arte`: grava inclusive `None` (cache
    negativo), limpa o dict inteiro ao estourar `_LIMITE_MEMO_ARTE`."""
    if len(_memo_temporadas) >= _LIMITE_MEMO_ARTE:
        _memo_temporadas.clear()
    _memo_temporadas[chave] = (time.monotonic() + _TTL_ARTE_S, tabela)


def _gravar_memo_info_episodio(
    chave: tuple[str, int | None, int | None, int], info: InfoDeEpisodio | None
) -> None:
    """Mesma política de `_gravar_memo_arte`: grava inclusive `None` (cache
    negativo), limpa o dict inteiro ao estourar `_LIMITE_MEMO_ARTE`."""
    if len(_memo_info_episodio) >= _LIMITE_MEMO_ARTE:
        _memo_info_episodio.clear()
    _memo_info_episodio[chave] = (time.monotonic() + _TTL_ARTE_S, info)


async def buscar_info_de_episodio(
    titulo: str, ano: int | None, numero: int, temporada: int | None
) -> InfoDeEpisodio | None:
    """Still/nome/sinopse TMDB do episódio `numero` de `titulo`/`ano` —
    overlay best-effort consumido por `api/servicos/fontes.py::
    listar_episodios_remotos` sobre `EpisodioRemoto` (`thumb_url`/`titulo`/
    `sinopse`). Com `temporada` dada, `numero` é o episódio dentro da
    temporada; sem ela, `numero` é a numeração absoluta local. `None` sempre
    que não achar ou o provedor falhar — quem chama decide o fallback (a arte
    do anime pro still; título/sinopse simplesmente ficam vazios). Compartilha
    o latch de autenticação (`_arte_desabilitada_por_auth`) com
    `buscar_arte_por_titulo`: um token rejeitado desabilita os dois overlays
    de uma vez, não só o de banner.
    """
    if _arte_desabilitada_por_auth:
        return None

    chave_info = (slugificar(titulo), ano, temporada, numero)
    memo = _memo_info_episodio.get(chave_info)
    if memo is not None:
        expira_em, info = memo
        if time.monotonic() < expira_em:
            return info

    for provedor in provedores_de_arte():
        try:
            info = await _buscar_info_de_um_provedor(provedor, titulo, ano, numero, temporada)
        except TmdbNaoAutorizado as excecao:
            _desabilitar_arte_por_auth(provedor, excecao)
            return None
        except _ERROS_DE_PROVEDOR as excecao:
            logger.log(
                _nivel_de_log_de_falha(excecao),
                "provedor de arte %r falhou ao buscar info do episódio %s (temporada %s) "
                "de %r: %s",
                provedor.nome,
                numero,
                temporada,
                titulo,
                excecao,
            )
            continue

        if info is not None:
            return info

    return None


async def _buscar_info_de_um_provedor(
    provedor: ProvedorDeArte, titulo: str, ano: int | None, numero: int, temporada: int | None
) -> InfoDeEpisodio | None:
    """`TmdbProvider` (hoje o único `ProvedorDeArte`) busca a info de TODA a
    temporada de uma vez (`TmdbProvider.info_da_temporada`) e popula
    `_memo_info_episodio` pros outros episódios dela, não só o pedido:

    - com `temporada` conhecida, vai direto (`info_da_temporada_por_titulo`),
      sem `TabelaDeTemporadas`;
    - sem ela (legado), resolve/reusa a `TabelaDeTemporadas` via
      `_memo_temporadas` pra achar a temporada de `numero` (absoluto).

    Qualquer outro `ProvedorDeArte` hipotético cai na chamada direta e simples
    do método da ABC, sem o bônus de cache por temporada."""
    slug = slugificar(titulo)

    if not isinstance(provedor, TmdbProvider):
        info = await _chamar(
            provedor, provedor.buscar_info_de_episodio, titulo, ano, numero, temporada
        )
        _gravar_memo_info_episodio((slug, ano, temporada, numero), info)
        return info

    if temporada is not None:
        info_da_temporada = await _chamar(
            provedor, provedor.info_da_temporada_por_titulo, titulo, ano, temporada
        )
        if info_da_temporada is None:
            _gravar_memo_info_episodio((slug, ano, temporada, numero), None)
            return None
        for numero_local, info_local in info_da_temporada.items():
            _gravar_memo_info_episodio((slug, ano, temporada, numero_local), info_local)
        return info_da_temporada.get(numero)

    chave_temporada = (slug, ano)
    memo_tabela = _memo_temporadas.get(chave_temporada)
    if memo_tabela is not None and time.monotonic() < memo_tabela[0]:
        tabela = memo_tabela[1]
    else:
        tabela = await _chamar(provedor, provedor.tabela_de_temporadas, titulo, ano)
        _gravar_memo_temporadas(chave_temporada, tabela)

    if tabela is None:
        return None

    localizacao = localizar_temporada(tabela.temporadas, numero)
    if localizacao is None:
        return None
    numero_da_temporada, numero_na_temporada = localizacao

    info_da_temporada = await _chamar(
        provedor, provedor.info_da_temporada, tabela.id_da_serie, numero_da_temporada
    )
    if info_da_temporada is None:
        # Negativo só do episódio pedido (não dá pra "fatiar" uma temporada
        # que não veio) — evita repescar esta mesma temporada só por causa
        # deste episódio específico dentro do TTL.
        _gravar_memo_info_episodio((slug, ano, None, numero), None)
        return None

    # Popula a info de TODOS os episódios da temporada de uma vez — não só o
    # pedido — evitando repescar `/tv/{id}/season/{n}` pros próximos episódios
    # da mesma temporada.
    primeiro_absoluto = next(
        primeiro
        for numero_temp, primeiro, _contagem in tabela.temporadas
        if numero_temp == numero_da_temporada
    )
    for numero_local, info_local in info_da_temporada.items():
        chave = (slug, ano, None, primeiro_absoluto + numero_local - 1)
        _gravar_memo_info_episodio(chave, info_local)

    return info_da_temporada.get(numero_na_temporada)


async def _com_arte[T](registro: T, *, titulo: str | None, ano: int | None) -> T:
    """Sobrepõe banner e sinopse pt-BR de TMDB num `MetadadosDeAnime` ou
    `AnimeEmAlta` — genérico porque os dois compartilham `banner_url`/`sinopse`.
    A sinopse segue `core/sinopse.py::escolher_sinopse` (só troca uma sinopse que
    já existe, nunca cria) e o TMDB sem tradução pt-BR a deixa como está.
    `titulo=None` devolve `registro` intacto (nada para buscar). Banner nulo
    do TMDB PRESERVA o valor anterior — nunca zera o `bannerImage` já
    resolvido pela AniList. `capa_url` de `registro` nunca é tocado aqui:
    capa é responsabilidade exclusiva da cadeia normal de
    `ProvedorDeMetadados` (AniList/Kitsu), não deste overlay. Qualquer falha
    do overlay (`_ERROS_DE_PROVEDOR`) vira warning e devolve `registro`
    intacto: arte é sempre best-effort, nunca derruba o registro base.
    """
    if titulo is None:
        return registro

    try:
        arte = await buscar_arte_por_titulo(titulo, ano)
    except _ERROS_DE_PROVEDOR as excecao:
        logger.log(
            _nivel_de_log_de_falha(excecao), "overlay de arte falhou para %r: %s", titulo, excecao
        )
        return registro

    if arte is None:
        return registro

    return replace(
        registro,
        banner_url=arte.banner_url if arte.banner_url is not None else registro.banner_url,
        sinopse=escolher_sinopse(
            registro.sinopse,
            serie_ptbr=arte.sinopse_serie,
            primeira_temporada=eh_primeira_temporada(arte.ano_da_serie, ano),
        ),
    )


async def _sobrepor_arte_em_lote(itens: list[AnimeEmAlta]) -> list[AnimeEmAlta]:
    """Sobrepõe arte de TMDB em cada item de um feed, ANTES de gravar no
    cache do feed (D4) — o custo de N chamadas TMDB só é pago 1x por janela
    de TTL do feed, não por request de Home. Mesma mecânica de
    concorrência/deadline de `api/servicos/capas.py::_consultar_capas`: item
    que não resolveu a tempo mantém a arte da AniList (a *task* pendente é
    cancelada — não a chamada HTTP síncrona em voo, mesma limitação
    documentada lá).

    Guarda `not itens` explícita: `asyncio.wait` levanta `ValueError` para uma
    lista vazia de tarefas — diferente de `api/servicos/capas.py::_consultar_capas`,
    aqui o guard mora dentro da função (5 pontos de chamada, nenhum precisa
    lembrar de checar antes)."""
    if not itens:
        return itens

    semaforo = asyncio.Semaphore(_CONCORRENCIA_ARTE)

    async def _sobrepor_um(indice: int, item: AnimeEmAlta) -> tuple[int, AnimeEmAlta]:
        async with semaforo:
            titulo = item.titulo_ingles or item.titulo_romaji
            item_com_arte = await _com_arte(item, titulo=titulo, ano=item.ano_estreia)
            return indice, item_com_arte

    tasks = [asyncio.ensure_future(_sobrepor_um(i, item)) for i, item in enumerate(itens)]
    concluidas, pendentes = await asyncio.wait(tasks, timeout=_TETO_LOTE_ARTE_S)
    if pendentes:
        for tarefa in pendentes:
            tarefa.cancel()
        # Aguarda a cancelação assentar antes de devolver — mesma razão de
        # `api/servicos/capas.py::_consultar_capas` (a *task* asyncio não pode
        # ficar solta, mesmo que a thread do OS por trás dela rode até o fim).
        await asyncio.gather(*pendentes, return_exceptions=True)

    resultado = list(itens)
    for tarefa in concluidas:
        indice, item_com_arte = tarefa.result()
        resultado[indice] = item_com_arte
    return resultado


# --- walk de série (grafo `relations`, Fase 3) ---


def _gravar_memo_serie(caminho: list[NoDeSerie]) -> None:
    """`caminho` vai do alvo (índice 0) até a âncora (último item, sem prequel).
    Grava a posição de CADA nó do caminho — a âncora fica `ordinal=1`, o alvo
    `ordinal=len(caminho)` — para que uma franquia de N temporadas custe ~1
    caminhada, não N. Limpa o dict inteiro ao estourar `_LIMITE_MEMO_SERIE`
    (política de `_gravar_memo_arte`, sem LRU)."""
    if len(_memo_serie) >= _LIMITE_MEMO_SERIE:
        _memo_serie.clear()
    ancora = caminho[-1].anilist_id
    total = len(caminho)
    expira_em = time.monotonic() + _TTL_SERIE_S
    for indice, no in enumerate(caminho):
        serie = SerieResolvida(ancora=ancora, ordinal=total - indice)
        _memo_serie[no.anilist_id] = (expira_em, serie)


def _chave_de_data(no: NoDeSerie) -> tuple[int, int]:
    """`(ano, mes)` de `no` para ordenação — só chamado depois de garantir
    `no.ano is not None`; `mes` ausente vira 0 (ordena antes de qualquer mês
    conhecido do mesmo ano)."""
    return (no.ano, no.mes or 0)


def _escolher_prequel(relacoes: RelacoesDeAnime) -> NoDeSerie | None:
    """Próximo nó do walk (para trás): `None` quando `relacoes.no` não tem
    prequel de TV (é a âncora). Com mais de um prequel, escolhe o mais recente
    ainda anterior ao nó atual; sem nenhum anterior, o mais recente no geral.
    Levanta `_SerieAmbigua` quando nenhum candidato tem data — não há como
    ordenar."""
    prequels = relacoes.prequels
    if not prequels:
        return None
    if len(prequels) == 1:
        return prequels[0]

    com_data = [p for p in prequels if p.ano is not None]
    if not com_data:
        raise _SerieAmbigua

    if relacoes.no.ano is not None:
        limite = (relacoes.no.ano, relacoes.no.mes or 0)
        anteriores = [p for p in com_data if _chave_de_data(p) < limite]
        if anteriores:
            return max(anteriores, key=_chave_de_data)
    return max(com_data, key=_chave_de_data)


def _escolher_sequel(relacoes: RelacoesDeAnime) -> NoDeSerie | None:
    """Próximo nó do walk PARA FRENTE (espelho de `_escolher_prequel`): `None`
    quando `relacoes.no` não tem sequel de TV (é a última temporada conhecida).
    Com mais de um sequel, escolhe o mais antigo ainda posterior ao nó atual
    (o sequel mais próximo cronologicamente, não o mais distante); sem nenhum
    posterior, o mais antigo no geral. Levanta `_SerieAmbigua` quando nenhum
    candidato tem data — mesma degradação de `_escolher_prequel`."""
    sequels = relacoes.sequels
    if not sequels:
        return None
    if len(sequels) == 1:
        return sequels[0]

    com_data = [s for s in sequels if s.ano is not None]
    if not com_data:
        raise _SerieAmbigua

    if relacoes.no.ano is not None:
        limite = (relacoes.no.ano, relacoes.no.mes or 0)
        posteriores = [s for s in com_data if _chave_de_data(s) > limite]
        if posteriores:
            return min(posteriores, key=_chave_de_data)
    return min(com_data, key=_chave_de_data)


async def resolver_franquia(anilist_id: int) -> list[NoDeSerie] | None:
    """Lista ordenada `[T1, T2, ..., Tn]` de TODA a franquia de `anilist_id`
    (temporadas de TV/TV_SHORT), usada pela materialização em lote da franquia
    ao clicar em qualquer uma delas (`api/servicos/descoberta.py::
    _materializar_temporadas_irmas`).

    Primeiro reusa `resolver_serie` (walk PREQUEL, já memoizado) para achar a
    âncora (T1); depois anda SEQUEL para frente a partir dela, mesmo teto
    `_MAX_HOPS_DE_SERIE` e mesma degradação do walk para trás — mas aqui parar
    no meio do caminho (provedor falhou, ciclo, ambiguidade) devolve o que já
    foi encontrado até ali em vez de `None`: é enumeração best-effort de
    VÁRIAS temporadas, não resolução de UMA. `None` só quando nem a âncora foi
    resolvida (sem grafo para andar).

    Sem memo próprio (ao contrário de `resolver_serie`): chamado só no fluxo
    raro de materialização por clique, não em hot path como os feeds da Home.
    """
    serie = await resolver_serie(anilist_id)
    if serie is None:
        return None

    capazes = [p for p in PROVEDORES if isinstance(p, ProvedorComRelacoes)]
    if not capazes:
        return None

    caminho: list[NoDeSerie] = []
    visitados: set[int] = set()
    id_atual = serie.ancora
    for _ in range(_MAX_HOPS_DE_SERIE + 1):
        if id_atual in visitados:
            logger.warning(
                "walk de franquia: ciclo em anilist_id=%s (a partir da âncora %s) — "
                "parando com %d temporada(s) encontrada(s)",
                anilist_id,
                serie.ancora,
                len(caminho),
            )
            break
        visitados.add(id_atual)

        relacoes = await _buscar_relacoes_em_cadeia(capazes, id_atual)
        if relacoes is None:
            break
        caminho.append(relacoes.no)

        try:
            proximo = _escolher_sequel(relacoes)
        except _SerieAmbigua:
            logger.warning(
                "walk de franquia: anilist_id=%s tem %d sequels de TV e datas "
                "insuficientes para desempate — parando com %d temporada(s) encontrada(s)",
                id_atual,
                len(relacoes.sequels),
                len(caminho),
            )
            break

        if proximo is None:
            break
        id_atual = proximo.anilist_id
    else:
        logger.warning(
            "walk de franquia: anilist_id=%s excedeu %d hops a partir da âncora %s — "
            "parando com %d temporada(s) encontrada(s)",
            anilist_id,
            _MAX_HOPS_DE_SERIE,
            serie.ancora,
            len(caminho),
        )

    return caminho


async def _buscar_relacoes_em_cadeia(
    capazes: list[ProvedorComRelacoes], anilist_id: int
) -> RelacoesDeAnime | None:
    """Primeiro provedor capaz que responde vence; falha de provedor
    (`_ERROS_DE_PROVEDOR` — rede, timeout, cooldown, formato inesperado) é
    logada e a cadeia segue. `None` quando todos falharam OU nenhum conhece o
    id — o walk trata os dois igual ("pare, sem âncora")."""
    for provedor in capazes:
        try:
            return await _chamar(provedor, provedor.buscar_relacoes, anilist_id)
        except _ERROS_DE_PROVEDOR as excecao:
            logger.log(
                _nivel_de_log_de_falha(excecao),
                "provedor de metadados %r falhou ao buscar relações de anilist_id=%s: %s",
                provedor.nome,
                anilist_id,
                excecao,
            )
    return None


async def _buscar_serie_pai_em_cadeia(
    capazes: list[ProvedorComRelacoes], anilist_id: int
) -> NoDeSerie | None:
    """Mesma semântica de `_buscar_relacoes_em_cadeia` (definida mais abaixo,
    reaproveitada por `resolver_ancora_de_midia`): primeiro provedor capaz que
    responde vence, falha de provedor é logada e a cadeia segue."""
    for provedor in capazes:
        try:
            return await _chamar(provedor, provedor.buscar_serie_pai, anilist_id)
        except _ERROS_DE_PROVEDOR as excecao:
            logger.log(
                _nivel_de_log_de_falha(excecao),
                "provedor de metadados %r falhou ao buscar série-mãe de anilist_id=%s: %s",
                provedor.nome,
                anilist_id,
                excecao,
            )
    return None


async def resolver_ancora_de_midia(anilist_id: int) -> int | None:
    """`serie_ancora` de um filme/OVA/ONA/especial (`Anime.formato_midia` não
    nulo) — o COMPLEMENTO de `resolver_serie`, que só anda o walk `PREQUEL`
    entre `Media` TV/TV_SHORT e por isso não serve pra esses formatos (a
    aresta de volta pra série-mãe quase nunca é `PREQUEL`, ver `buscar_
    serie_pai`).

    Acha o primeiro nó TV/TV_SHORT relacionado (`buscar_serie_pai`) e devolve
    a ÂNCORA DELE (`resolver_serie` nesse nó — que pode ser ele mesmo, se for
    a T1, ou subir a cadeia de prequels se não for). `None` quando não há nó
    TV relacionado, ou o walk a partir dele falha — nunca ancora o filme nele
    mesmo (isso o transformaria num card de franquia próprio, o problema que
    esta função existe para evitar).

    Sem cache próprio: `resolver_serie` (chamado aqui) já cacheia por
    `anilist_id` via `_memo_serie`; esta função só roda uma vez, no
    enriquecimento best-effort pós-criação (`api/servicos/descoberta.py::
    _resolver_e_aplicar_serie`), não a cada carregamento de página."""
    capazes = [p for p in PROVEDORES if isinstance(p, ProvedorComRelacoes)]
    if not capazes:
        return None
    pai = await _buscar_serie_pai_em_cadeia(capazes, anilist_id)
    if pai is None:
        return None
    serie = await resolver_serie(pai.anilist_id)
    return serie.ancora if serie is not None else None


async def resolver_serie(anilist_id: int) -> SerieResolvida | None:
    """`(ancora, ordinal)` de `anilist_id` — a âncora é o `anilist_id` da
    temporada 1 da franquia (== `anilist_id` quando o próprio anime não tem
    prequel de TV), o ordinal é a posição narrativa 1-based.

    Anda o grafo de `relations` da AniList SÓ PARA TRÁS (arestas PREQUEL de
    `Media` ANIME em formato `TV`/`TV_SHORT` — o adapter já filtra). Best-effort:
    devolve `None` (nunca um ordinal parcial) diante de qualquer falha de
    provedor, ciclo no grafo, teto de `_MAX_HOPS_DE_SERIE` hops ou desempate
    impossível entre prequels. Só sucesso é cacheado (falha por cooldown é
    transitória); o memo é populado para todos os nós do caminho.
    """
    memo = _memo_serie.get(anilist_id)
    if memo is not None:
        expira_em, serie = memo
        if time.monotonic() < expira_em:
            return serie

    capazes = [p for p in PROVEDORES if isinstance(p, ProvedorComRelacoes)]
    if not capazes:
        return None

    caminho: list[NoDeSerie] = []
    visitados: set[int] = set()
    id_atual = anilist_id
    for _ in range(_MAX_HOPS_DE_SERIE + 1):
        if id_atual in visitados:
            logger.warning("walk de série: ciclo em anilist_id=%s — parando sem âncora", anilist_id)
            return None
        visitados.add(id_atual)

        relacoes = await _buscar_relacoes_em_cadeia(capazes, id_atual)
        if relacoes is None:
            return None
        caminho.append(relacoes.no)

        try:
            proximo = _escolher_prequel(relacoes)
        except _SerieAmbigua:
            logger.warning(
                "walk de série: anilist_id=%s tem %d prequels de TV e datas insuficientes "
                "para desempate — parando sem âncora",
                id_atual,
                len(relacoes.prequels),
            )
            return None

        if proximo is None:
            _gravar_memo_serie(caminho)
            return SerieResolvida(ancora=caminho[-1].anilist_id, ordinal=len(caminho))
        id_atual = proximo.anilist_id

    logger.warning(
        "walk de série: anilist_id=%s excedeu %d hops — cadeia anômala, parando sem âncora",
        anilist_id,
        _MAX_HOPS_DE_SERIE,
    )
    return None


def _http_indica_provedor_fora_do_ar(excecao: requests.HTTPError) -> bool:
    """`True` só para 429 e 5xx — provedor sobrecarregado ou fora do ar, conta
    como falha do cooldown. Os demais 4xx significam "requisição recusada", não
    "provedor caiu": não mexem no cooldown (o `raise_for_status()` real dos
    adapters sempre anexa `.response`; um `HTTPError` sem status vira "não é
    indisponibilidade")."""
    codigo = getattr(getattr(excecao, "response", None), "status_code", None)
    return codigo == 429 or (codigo is not None and 500 <= codigo < 600)


def _cooldown_ate(nome: str) -> float | None:
    """`cooldown_ate` (relógio `time.monotonic`) se `nome` está em cooldown
    AGORA, senão `None`. Estado DERIVADO de `cooldown_ate > agora` — nunca um
    bool armazenado (mesma decisão de `extractors/circuit_breaker.py`)."""
    estado = _cooldown_por_provedor.get(nome)
    if estado is None:
        return None
    _falhas, cooldown_ate = estado
    return cooldown_ate if time.monotonic() < cooldown_ate else None


def _abortar_se_em_cooldown(nome: str) -> None:
    """Levanta `ProvedorEmCooldown` na hora se `nome` está em cooldown — sem
    tocar a rede e sem contar como falha nova. `logger.debug` no máximo: a
    degradação já saiu em `WARNING` uma vez em `_registrar_falha_de_provedor`."""
    cooldown_ate = _cooldown_ate(nome)
    if cooldown_ate is None:
        return
    restante = cooldown_ate - time.monotonic()
    logger.debug("provedor %r em cooldown (faltam %.0fs) — curto-circuito", nome, restante)
    raise ProvedorEmCooldown(
        f"{nome} em cooldown do circuit breaker (faltam {restante:.0f}s)"
    )


def _registrar_sucesso_de_provedor(nome: str) -> None:
    """Zera `falhas_consecutivas` e fecha o cooldown de `nome`. Sem registro
    prévio não há o que zerar. Só uma resposta bem-sucedida chama isto — uma
    resposta-com-erro que não é indisponibilidade (4xx não-429, `RuntimeError`
    de formato inesperado) apenas propaga, sem mexer no contador."""
    _cooldown_por_provedor.pop(nome, None)


def _registrar_falha_de_provedor(nome: str, erro: Exception) -> None:
    """Incrementa `falhas_consecutivas` e reprograma `cooldown_ate` no degrau de
    backoff correspondente. Um `logger.warning` por falha REAL (a transição para
    — ou o aprofundamento do — cooldown), nunca por chamada curto-circuitada.

    Falha que chega com o provedor JÁ em cooldown ativo é ignorada: pertence à
    mesma onda concorrente que acabou de abrir o breaker (um caminho como a Home
    dispara N chamadas quase simultâneas — todas passam `_abortar_se_em_cooldown`
    antes de a primeira registrar a falha, e sem este guard as N incrementariam
    o contador em sequência, pulando os degraus 15s→60s→300s direto pro cooldown
    cheio de 900s). O aprofundamento real do degrau vem da sonda de meio-aberto
    (a 1ª chamada depois de o cooldown expirar), quando não há cooldown ativo."""
    if _cooldown_ate(nome) is not None:
        return
    falhas = _cooldown_por_provedor.get(nome, (0, 0.0))[0] + 1
    espera = _backoff_de_cooldown_s(falhas)
    _cooldown_por_provedor[nome] = (falhas, time.monotonic() + espera)
    logger.warning(
        "provedor de metadados %r degradado (%sª falha consecutiva: %s) — "
        "curto-circuitando chamadas pelos próximos %ss",
        nome,
        falhas,
        erro,
        espera,
    )


def _backoff_de_cooldown_s(falhas_consecutivas: int) -> int:
    if falhas_consecutivas > _LIMITE_PARA_COOLDOWN_CHEIO:
        return _COOLDOWN_CHEIO_S
    return _BACKOFF_DE_COOLDOWN_S[falhas_consecutivas - 1]


async def _chamar[T](
    provedor: ProvedorDeMetadados | ProvedorDeArte, operacao: Callable[..., T], *args: object
) -> T:
    """Wrapper único de `integrations/` para `asyncio.to_thread` + `wait_for` — e
    único ponto onde o cooldown de provedor (`_cooldown_por_provedor`) é lido e
    escrito, sempre no event loop (antes/depois do `await`), nunca dentro da
    thread (ver o comentário de `_cooldown_por_provedor`).

    Curto-circuita com `ProvedorEmCooldown` quando o provedor está degradado.
    Só falha de indisponibilidade (timeout do `wait_for`, `ConnectionError` /
    `Timeout` do `requests`, HTTP 429/5xx) alimenta o cooldown; só uma resposta
    bem-sucedida o zera. Todo o resto (4xx não-429, `RuntimeError` de formato
    inesperado, `TmdbNaoAutorizado`) apenas propaga — o provedor respondeu, não
    é "fora do ar", e não é recuperação confirmada tampouco.
    """
    # ANTES do `try`: um curto-circuito não deve passar pelo tratamento de
    # falha abaixo (não conta como falha nova, não chama `registrar_sucesso`).
    _abortar_se_em_cooldown(provedor.nome)

    try:
        resultado = await asyncio.wait_for(
            asyncio.to_thread(operacao, *args), timeout=_TIMEOUT_POR_PROVEDOR_S
        )
    except TimeoutError as excecao:
        _registrar_falha_de_provedor(provedor.nome, excecao)
        raise TimeoutError(
            f"{provedor.nome} excedeu o teto de {_TIMEOUT_POR_PROVEDOR_S}s"
        ) from excecao
    except (requests.ConnectionError, requests.Timeout) as excecao:
        _registrar_falha_de_provedor(provedor.nome, excecao)
        raise
    except requests.HTTPError as excecao:
        if _http_indica_provedor_fora_do_ar(excecao):
            _registrar_falha_de_provedor(provedor.nome, excecao)
        raise

    _registrar_sucesso_de_provedor(provedor.nome)
    return resultado

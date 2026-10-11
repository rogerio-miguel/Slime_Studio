"""Feature "continuar assistindo" — leitura da prateleira da Inicio. Não
importa `fastapi` nem Pydantic (regra de dependência da Clean Architecture,
CLAUDE.md §1); `api/rotas/episodios.py` traduz o resultado para
`ContinuarAssistindoSaida`.

Um item por ANIME (não por episódio) — extensão do catálogo/página do anime
pedida pelo usuário: a prateleira decide, por anime com atividade recente, um
único "próximo passo" e delega a renderização pro MESMO componente que a
página do anime já usa (`LinhaDeEpisodio.jsx`), então as variantes abaixo
espelham os próprios ramos daquele componente, não um vocabulário novo.

Escolha do slot por anime (`_escolher_slot`), em ordem:
1. episódio `PRONTO` com progresso salvo e ainda abaixo de `_LIMIAR_CONCLUSAO`
   → variante `pronto` (o mesmo card de hoje, com barra).
2. senão, fronteira = maior número "resolvido" (assistido de fato, OU `PRONTO`
   com progresso >= `_LIMIAR_CONCLUSAO` mas ainda sem `assistido_em` — cobre o
   mesmo race do listener de saída que o auto-limpa de `_LIMIAR_CONCLUSAO` já
   documentava aqui) + 1 = próximo número:
   - já existe `Episodio` pra esse número → variante `pronto` (sem barra, é
     largada nova), `capturavel` (`LIBERADO`/`FALHOU`, mesmos dois status que
     `LinhaDeEpisodio.jsx::permiteRecaptura` já trata como recaptura) ou
     `processando` (qualquer outro status — pipeline em curso ou parado);
   - não existe ainda: `episodios_na_fonte` (sondagem real do site,
     `api/servicos/sondagem.py`) precisa cobrir esse número E a fonte do anime
     precisa estar confirmada (`versao_confirmada_mais_recente` — sem isso não
     dá pra montar o pedido de captura) → variante `capturavel`.
3. nenhum dos dois → anime não aparece (terminou tudo, sem lançamento novo).

Quem entra (2026-09-30): toda temporada com QUALQUER episódio regular local
(não só quem já tem progresso) — a prateleira é a extensão da página do anime,
então captura concluída e ainda não assistida já aparece. Sem nada assistido
ainda, o slot é o menor número não-`LIBERADO` (`pronto`/`processando`/
`capturavel` por falha). Além disso, `lancamentos.temporadas_novas`: temporada
do catálogo SEM episódio local cuja anterior na franquia o usuário terminou vira
o slot 1 `capturavel` (`_slot_de_temporada_nova`), com badge "Novo ep" enquanto
`EM_LANCAMENTO`, mesmo que a fonte já tenha mais de um episódio (é início de
temporada, não atraso). Mesmo slot pra `lancamentos.primeiras_em_lancamento`:
primeira temporada `EM_LANCAMENTO` sem episódio local (anime recém-estreado,
sem anterior na franquia) — entra assim que a fonte é resolvida (abrir a página
do anime) e a sondagem preenche `episodios_na_fonte`. Já a temporada nova de
franquia, sem `FonteAnime` ainda, só vira card depois que a sondagem de reparo
(`sondagem.versoes_para_resolver_fonte`) resolver a fonte em segundo
plano.

`episodio_novo` (badge "Novo ep", `components/CartaoContinuarAssistindo.jsx::
BadgeNovo`) é `capturavel` + episódio nunca existiu + anime `EM_LANCAMENTO` +
`numero == episodios_na_fonte` — as três primeiras são o mesmo gate de
`api/servicos/lancamentos.py::episodios_novos`, só que por anime em vez de
contagem (um anime encerrado que o usuário só não terminou de acompanhar cai
no mesmo `capturavel`, sem a badge). A quarta condição é exclusiva daqui
(2026-09-19): como só existe UM slot por anime (o próximo buraco, não uma
contagem), sem ela um anime muito atrasado (visto até o 8, fonte já no 11)
acendia a badge no 9 — que não é "novo", é só o próximo item do atraso.
`numero == episodios_na_fonte` restringe a badge a quando o slot mostrado É de
fato o episódio mais recente que a fonte tem; badge só volta a acender quando
o usuário alcançar essa fronteira de novo.

Still/título/sinopse do slot `capturavel` sem episódio (nunca capturado, não
tem `Episodio.capa_path` ainda) vêm de `api/servicos/fontes.py::
info_de_episodio` — mesma consulta pontual ao TMDB que a captura já faz pra
gravar essas colunas, só antecipada pra exibição. **Nunca ao vivo dentro da
resposta** (2026-09-19 — a versão anterior dava `await` nesse lookup pra cada
slot antes de responder, e um TMDB lento/com timeout de 9s por episódio
deixava a Home inteira lenta pra abrir): cache-hit usa na hora, cache-miss cai
no fallback de arte do anime pra ESTA leitura e agenda a busca em segundo
plano (fire-and-forget, mesmo padrão de `api/servicos/descoberta.py::
agendar_refresh_de_lancamento` — dict de `Task` como referência forte pra não
perder o fire-and-forget pro GC, dedupe por chave). A leitura seguinte da
prateleira (poll/reload) já vem com a still certa. Nunca scraping/anti-bot —
`FonteAnime` já resolvida é pré-requisito do próprio slot.

`ItemContinuarAssistindo.still_pendente` sinaliza pro frontend quando esta
leitura caiu no cache-miss acima (2026-09-19): sem isso o usuário só via a
still/título certos depois de um F5 manual. `paginas/Inicio.jsx` usa a flag
pra decidir se vale reconsultar a prateleira de novo em alguns segundos.

`listar_continuar_assistindo` também dispara `sondagem.agendar_sondagens`
(2026-09-19) — mas só para os animes JÁ nesta prateleira (`ids_ativos`), não o
catálogo inteiro; isso era exclusivo da Galeria (`?aquecer=true`) e da página
do anime, que continuam existindo (cobrem quem nunca foi assistido, fora do
escopo daqui). Mesmo problema do still: episódio novo na fonte só aparece
aqui depois que a sondagem em segundo plano atualiza `episodios_na_fonte` —
mas como um anime sem `Episodio` pro próximo número some de `itens` por
inteiro (`_escolher_slot` devolve `None`), não dá pra pendurar uma flag por
item. `ResultadoContinuarAssistindo.sondagem_em_andamento` cobre isso: um
booleano no nível da resposta (peek em `sondagem._sondagens_em_voo`,
`sondagem.sondagem_em_andamento`), que `Inicio.jsx` usa pra decidir se vale
reconsultar a prateleira inteira de novo.
"""

import asyncio
import time
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.servicos import catalogo as servico_catalogo
from api.servicos import lancamentos as servico_lancamentos
from api.servicos import sondagem as servico_sondagem
from api.servicos.fontes import info_de_episodio
from core.enums import StatusEpisodio, StatusLancamento, TipoEpisodio, VersaoEpisodio
from integrations.base import InfoDeEpisodio
from models.anime import Anime
from models.episodio import Episodio

_SessionMaker = async_sessionmaker[AsyncSession]

_LIMITE_PADRAO = 20
# Mesmo limiar de "assistido" usado no player (`usePontoDeAssistido.js`) — um
# episódio que já passou disso deveria ter sido liberado (`liberar_episodio`)
# em vez de continuar aparecendo como "em progresso"; serve duplamente aqui
# como piso da fronteira (`_escolher_slot`) pro caso de o usuário ter fechado
# a aba antes do listener de saída marcar `assistido_em`.
_LIMIAR_CONCLUSAO = 0.9

# Cache em memória de processo (mesma ideia de `integrations/servico.py`,
# ex. `_memo_arte`): a still/título/sinopse TMDB de um episódio não muda
# depois de resolvida, então um slot já visto não precisa perguntar de novo a
# cada leitura da prateleira dentro do TTL. `None` também é cacheado (TMDB não
# achou) — sem isso um episódio sem still ficaria reagendando a busca em todo
# request. Chave `(anime_id, numero)`, valor `(expira_em_monotonic, info)`.
_TTL_CACHE_STILL_S = 12 * 3600
_cache_still: dict[tuple[int, int], tuple[float, InfoDeEpisodio | None]] = {}
_SEM_CACHE = object()

# Referência forte às buscas de still em voo — mesmo padrão de
# `api/servicos/descoberta.py::_refreshs_de_lancamento_em_voo` (dict de
# `Task`, pop no `done_callback`): sem isso o `asyncio.create_task` fire-and-
# forget pode ser coletado pelo GC no meio do caminho. Dedupe: duas leituras
# concorrentes da prateleira não disparam duas buscas pro mesmo slot.
_stills_em_voo: dict[tuple[int, int], asyncio.Task] = {}


@dataclass(slots=True)
class ItemContinuarAssistindo:
    """Um card da prateleira — `api/rotas/episodios.py` traduz pra
    `ContinuarAssistindoSaida`. `episodio_id`/`status`/`progresso_s`/
    `duracao_s` vêm nulos quando `variante == 'capturavel'` e o episódio nunca
    existiu (slot puramente da fonte, ainda sem `Episodio`)."""

    anime_id: int
    anime_titulo: str
    numero_temporada: int | None
    numero: int
    variante: str
    episodio_id: int | None
    status: str | None
    progresso_s: int | None
    duracao_s: int | None
    thumb: str | None
    titulo: str | None
    sinopse: str | None
    versao: str | None
    episodio_novo: bool
    still_pendente: bool


@dataclass(slots=True)
class ResultadoContinuarAssistindo:
    """Corpo de `GET /api/episodios/continuar-assistindo` — `sondagem_em_
    andamento` cobre o caso que nenhuma flag por item resolve: um anime cujo
    próximo episódio ainda não existe (`_escolher_slot` devolve `None` pra ele
    quando `episodios_na_fonte` está desatualizado) simplesmente NÃO aparece em
    `itens` até a sondagem atualizar a contagem — não dá pra pendurar uma flag
    num item que não existe ainda. `paginas/Inicio.jsx` usa esta flag (em vez
    de `still_pendente`, item a item) pra saber se vale reconsultar a
    prateleira inteira de novo."""

    itens: list["ItemContinuarAssistindo"]
    sondagem_em_andamento: bool


@dataclass(slots=True)
class _Candidato:
    """Estado intermediário de um anime antes do overlay de still — `anime` e
    `episodio` (a linha real, quando existe) ficam disponíveis pra
    `_aplicar_still_capturavel` sem reconsultar o banco."""

    anime: Anime
    numero: int
    episodio: Episodio | None
    variante: str
    atividade_em: datetime
    versao: str | None
    thumb: str | None = None
    titulo: str | None = None
    sinopse: str | None = None
    still_pendente: bool = False
    temporada_nova: bool = False


def _preferir_versao(candidatos: list[Episodio], versao_ativa: str | None) -> Episodio:
    """Mais de uma linha pode existir no mesmo número (legendado + dublado,
    `uq_episodio_identidade`) — prioriza a versão confirmada como ativa pra
    esse anime; sem uma correspondência (ou `versao_ativa` desconhecida), cai
    na primeira por falta de critério melhor (caso raro, sem fonte confirmada
    o card nem chegaria aqui pra começo de conversa — ver `_escolher_slot`)."""
    if versao_ativa is not None:
        for episodio in candidatos:
            if episodio.versao == versao_ativa:
                return episodio
    return candidatos[0]


def _candidato_do_episodio(
    anime: Anime, episodio: Episodio, versao_ativa: str | None, atividade_em: datetime
) -> _Candidato:
    if episodio.status in (StatusEpisodio.LIBERADO, StatusEpisodio.FALHOU):
        variante = "capturavel"
    elif episodio.status == StatusEpisodio.PRONTO:
        variante = "pronto"
    else:
        variante = "processando"
    return _Candidato(
        anime=anime,
        numero=episodio.numero,
        episodio=episodio,
        variante=variante,
        atividade_em=atividade_em,
        versao=versao_ativa,
    )


def _escolher_slot(
    anime: Anime, episodios: Sequence[Episodio], versao_ativa: str | None
) -> _Candidato | None:
    em_progresso = [
        episodio
        for episodio in episodios
        if episodio.status == StatusEpisodio.PRONTO
        and episodio.progresso_s is not None
        and episodio.progresso_s > 0
        and (
            episodio.duracao_s is None
            or episodio.progresso_s < episodio.duracao_s * _LIMIAR_CONCLUSAO
        )
    ]
    if em_progresso:
        episodio = max(
            em_progresso,
            key=lambda episodio: episodio.progresso_atualizado_em or episodio.criado_em,
        )
        return _Candidato(
            anime=anime,
            numero=episodio.numero,
            episodio=episodio,
            variante="pronto",
            atividade_em=episodio.progresso_atualizado_em or episodio.criado_em,
            versao=versao_ativa,
        )

    resolvidos = [
        episodio
        for episodio in episodios
        if episodio.status in (StatusEpisodio.PRONTO, StatusEpisodio.LIBERADO)
        and (
            episodio.assistido_em is not None
            or (
                episodio.progresso_s is not None
                and (
                    episodio.duracao_s is None
                    or episodio.progresso_s >= episodio.duracao_s * _LIMIAR_CONCLUSAO
                )
            )
        )
    ]
    if not resolvidos:
        # Nada assistido ainda, mas o usuário capturou algo (2026-09-30): o card
        # é a largada do anime, o menor número que ainda não foi liberado —
        # `PRONTO` (pronto pra assistir), em pipeline ou `FALHOU` (recaptura).
        # `LIBERADO` sem `assistido_em` é arquivo apagado, não convite a ver.
        disponiveis = [
            episodio for episodio in episodios if episodio.status != StatusEpisodio.LIBERADO
        ]
        if not disponiveis:
            return None
        primeiro = min(episodio.numero for episodio in disponiveis)
        no_numero = [episodio for episodio in disponiveis if episodio.numero == primeiro]
        episodio = _preferir_versao(no_numero, versao_ativa)
        return _candidato_do_episodio(anime, episodio, versao_ativa, episodio.criado_em)

    ultimo = max(resolvidos, key=lambda episodio: episodio.numero)
    proximo_numero = ultimo.numero + 1
    atividade_em = ultimo.assistido_em or ultimo.progresso_atualizado_em or ultimo.criado_em

    no_proximo = [episodio for episodio in episodios if episodio.numero == proximo_numero]
    if no_proximo:
        episodio = _preferir_versao(no_proximo, versao_ativa)
        return _candidato_do_episodio(anime, episodio, versao_ativa, atividade_em)

    # Nunca capturado: só vira card se dá pra montar o pedido de captura
    # (fonte confirmada) e a fonte já expõe esse número (sondagem real).
    if versao_ativa is None:
        return None
    if anime.episodios_na_fonte is None or anime.episodios_na_fonte < proximo_numero:
        return None
    return _Candidato(
        anime=anime,
        numero=proximo_numero,
        episodio=None,
        variante="capturavel",
        atividade_em=atividade_em,
        versao=versao_ativa,
    )


def _slot_de_temporada_nova(
    anime: Anime, episodios_da_anterior: Sequence[Episodio], versao_ativa: VersaoEpisodio | None
) -> _Candidato | None:
    """Episódio 1 de uma temporada nova (`lancamentos.temporadas_novas`) ou da
    primeira temporada em lançamento (`lancamentos.primeiras_em_lancamento`,
    `episodios_da_anterior` vazio → atividade = `fonte_verificada_em`, o momento
    em que a fonte foi confirmada ao abrir o anime; `criado_em` só de reserva) —
    sempre `capturavel` sem `Episodio`, e só quando a fonte já mapeada expõe
    algum episódio. A atividade herda a da anterior pra ordenar a prateleira
    junto do que o usuário acabou de ver."""
    if versao_ativa is None or not anime.episodios_na_fonte:
        return None
    atividade_em = max(
        (
            episodio.assistido_em or episodio.progresso_atualizado_em or episodio.criado_em
            for episodio in episodios_da_anterior
        ),
        default=anime.fonte_verificada_em or anime.criado_em,
    )
    return _Candidato(
        anime=anime,
        numero=1,
        episodio=None,
        variante="capturavel",
        atividade_em=atividade_em,
        versao=versao_ativa.value,
        temporada_nova=True,
    )


def _still_do_cache(chave: tuple[int, int]) -> InfoDeEpisodio | None | object:
    """Devolve a `InfoDeEpisodio` cacheada (`None` incluso, cache negativo) ou
    o sentinel `_SEM_CACHE` quando não há entrada válida (nunca buscado, ou
    TTL vencido)."""
    entrada = _cache_still.get(chave)
    if entrada is None:
        return _SEM_CACHE
    expira_em, info = entrada
    if time.monotonic() >= expira_em:
        return _SEM_CACHE
    return info


async def _resolver_still_em_segundo_plano(
    sessionmaker: _SessionMaker, anime: Anime, numero: int
) -> None:
    chave = (anime.id, numero)
    try:
        info = await info_de_episodio(sessionmaker, anime, numero)
        _cache_still[chave] = (time.monotonic() + _TTL_CACHE_STILL_S, info)
    finally:
        _stills_em_voo.pop(chave, None)


def _aplicar_still_capturavel(sessionmaker: _SessionMaker, candidato: _Candidato) -> None:
    """Slot `capturavel` sem `Episodio` ainda: aplica still/título/sinopse do
    cache quando já resolvido; cache-miss agenda a busca em segundo plano
    (dedupe por `_stills_em_voo`) e não bloqueia esta resposta — o candidato
    segue com o fallback de arte do anime já aplicado por quem chama."""
    chave = (candidato.anime.id, candidato.numero)
    info = _still_do_cache(chave)
    if info is not _SEM_CACHE:
        if info is not None:
            candidato.thumb = info.still_url
            candidato.titulo = info.nome
            candidato.sinopse = info.sinopse
        return
    candidato.still_pendente = True
    if chave in _stills_em_voo:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    tarefa = loop.create_task(
        _resolver_still_em_segundo_plano(sessionmaker, candidato.anime, candidato.numero)
    )
    _stills_em_voo[chave] = tarefa


def _thumb_do_episodio(episodio: Episodio, anime: Anime) -> str | None:
    return episodio.capa_path or anime.banner_path or anime.capa_path


async def listar_continuar_assistindo(
    sessionmaker: _SessionMaker, limite: int = _LIMITE_PADRAO
) -> ResultadoContinuarAssistindo:
    async with sessionmaker() as sessao:
        # Toda temporada com QUALQUER episódio regular local entra (2026-09-30):
        # antes só entrava quem tinha progresso/`assistido_em`, então um
        # episódio recém-capturado e ainda não assistido não aparecia até o
        # usuário dar play e ficar tempo suficiente. A prateleira é a extensão
        # da página do anime — o que a página mostra, ela mostra.
        ids_result = await sessao.execute(
            select(Episodio.anime_id).where(Episodio.tipo == TipoEpisodio.REGULAR).distinct()
        )
        ids_com_episodio = [linha[0] for linha in ids_result.all()]

        # Continuação de franquia: temporada nova do catálogo, sem episódio
        # local, cuja anterior o usuário terminou. `novas` = {nova: anterior}.
        grupos = await servico_catalogo.agrupar_franquias(sessao)
        novas = await servico_lancamentos.temporadas_novas(sessao, grupos)

        primeiras = servico_lancamentos.primeiras_em_lancamento(grupos)

        ids_ativos = [*ids_com_episodio, *novas, *primeiras]
        if not ids_ativos:
            return ResultadoContinuarAssistindo(itens=[], sondagem_em_andamento=False)

        animes_result = await sessao.execute(select(Anime).where(Anime.id.in_(ids_ativos)))
        animes_por_id = {anime.id: anime for anime in animes_result.scalars()}

        episodios_result = await sessao.execute(
            select(Episodio).where(
                Episodio.anime_id.in_(ids_com_episodio), Episodio.tipo == TipoEpisodio.REGULAR
            )
        )
        episodios_por_anime: dict[int, list[Episodio]] = defaultdict(list)
        for episodio in episodios_result.scalars():
            episodios_por_anime[episodio.anime_id].append(episodio)

        versoes_ativas = await servico_sondagem.versoes_confirmadas_mais_recentes_por_anime(
            sessao, ids_ativos
        )

        # Gatilho estreito de sondagem (2026-09-19): só os animes já na
        # prateleira (`ids_ativos`), não o catálogo inteiro — a Galeria
        # (`?aquecer=true`) e a página do anime continuam cobrindo o resto do
        # catálogo (quem nunca foi assistido não aparece aqui de qualquer
        # forma). Reaproveita 100% da infra de `agendar_sondagens` (TTL de 6h,
        # semáforo global, teto por lote, dedupe) — fire-and-forget, não
        # bloqueia esta resposta. Anime ainda sem fonte (temporada nova, fonte
        # perdida) entra como resolução, com a mesma política da Galeria.
        versoes_de_sondagem = await servico_sondagem.versoes_de_sondagem_por_anime(
            sessao, ids_ativos
        )
        em_espera = await servico_sondagem.ids_em_espera(sessao, ids_ativos)
        a_resolver = await servico_sondagem.versoes_para_resolver_fonte(
            sessao,
            animes_por_id.values(),
            versoes_de_sondagem,
            com_episodios=ids_com_episodio,
            temporadas_novas=novas,
            em_espera=em_espera,
        )
        servico_sondagem.agendar_sondagens(
            sessionmaker,
            list(animes_por_id.values()),
            {**versoes_de_sondagem, **a_resolver},
            a_resolver=frozenset(a_resolver),
            em_espera=em_espera,
        )
        sondagem_em_andamento = servico_sondagem.sondagem_em_andamento(ids_ativos)

    candidatos: list[_Candidato] = []
    for anime_id, episodios in episodios_por_anime.items():
        anime = animes_por_id[anime_id]
        versao_ativa = versoes_ativas.get(anime_id)
        candidato = _escolher_slot(anime, episodios, versao_ativa.value if versao_ativa else None)
        if candidato is not None:
            candidatos.append(candidato)

    for anime_id, anterior_id in novas.items():
        candidato = _slot_de_temporada_nova(
            animes_por_id[anime_id],
            episodios_por_anime.get(anterior_id, []),
            versoes_ativas.get(anime_id),
        )
        if candidato is not None:
            candidatos.append(candidato)

    for anime_id in primeiras:
        candidato = _slot_de_temporada_nova(
            animes_por_id[anime_id], [], versoes_ativas.get(anime_id)
        )
        if candidato is not None:
            candidatos.append(candidato)

    candidatos.sort(key=lambda candidato: candidato.atividade_em, reverse=True)
    candidatos = candidatos[:limite]

    for candidato in candidatos:
        if candidato.episodio is not None:
            candidato.thumb = _thumb_do_episodio(candidato.episodio, candidato.anime)
            candidato.titulo = candidato.episodio.titulo
            candidato.sinopse = candidato.episodio.sinopse
        else:
            _aplicar_still_capturavel(sessionmaker, candidato)

    itens = []
    for candidato in candidatos:
        thumb = candidato.thumb or candidato.anime.banner_path or candidato.anime.capa_path
        episodio_novo = (
            candidato.variante == "capturavel"
            and candidato.episodio is None
            and candidato.anime.status_lancamento == StatusLancamento.EM_LANCAMENTO
            # Só a fronteira de verdade (2026-09-19): sem isto, um anime com
            # vários episódios atrasados (ex. viu até o 8, fonte já tem 9/10/11)
            # mostrava "Novo ep" no 9 — que não é novo, só é o próximo buraco
            # do SEU atraso. `numero == episodios_na_fonte` restringe a badge
            # pro slot que É o episódio mais recente conhecido da fonte; badge
            # só acende de novo quando o usuário alcançar essa fronteira.
            and (candidato.temporada_nova or candidato.numero == candidato.anime.episodios_na_fonte)
        )
        itens.append(
            ItemContinuarAssistindo(
                anime_id=candidato.anime.id,
                anime_titulo=candidato.anime.titulo,
                numero_temporada=candidato.anime.numero_temporada,
                numero=candidato.numero,
                variante=candidato.variante,
                episodio_id=candidato.episodio.id if candidato.episodio else None,
                status=candidato.episodio.status.value if candidato.episodio else None,
                progresso_s=candidato.episodio.progresso_s if candidato.episodio else None,
                duracao_s=candidato.episodio.duracao_s if candidato.episodio else None,
                thumb=thumb,
                titulo=candidato.titulo,
                sinopse=candidato.sinopse,
                versao=candidato.versao,
                episodio_novo=episodio_novo,
                still_pendente=candidato.still_pendente,
            )
        )
    return ResultadoContinuarAssistindo(itens=itens, sondagem_em_andamento=sondagem_em_andamento)

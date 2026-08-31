"""Get-or-create de `Anime` + criação de `Episodio`+`Job` — compartilhado entre o
CLI (`scripts/enfileirar_local.py`) e a API (`api/servicos/jobs.py`), pra evitar
drift de tratamento de `IntegrityError`/get-or-create entre os dois produtores de
job (ESPECIFICACAO.md §5, Passo 1.3 do plano da Fase 3).
"""

import logging
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.enums import StatusEpisodio, TipoEpisodio, VersaoEpisodio
from core.erros import EpisodioJaExiste, ErroSlimeStudio
from core.texto import slugificar
from db.fila import criar_job
from integrations.base import LancamentoDeAnime, MetadadosDeAnime
from models.anime import Anime
from models.episodio import Episodio

logger = logging.getLogger(__name__)

_SessionMaker = async_sessionmaker[AsyncSession]


async def obter_ou_criar_anime_id(sessionmaker: _SessionMaker, titulo: str, ano: int | None) -> int:
    slug = slugificar(titulo)
    async with sessionmaker() as sessao:
        resultado = await sessao.execute(select(Anime.id).where(Anime.slug == slug))
        anime_id = resultado.scalar_one_or_none()
        if anime_id is not None:
            return anime_id

        anime = Anime(titulo=titulo, slug=slug, ano=ano)
        sessao.add(anime)
        try:
            await sessao.commit()
        except IntegrityError as excecao:
            await sessao.rollback()
            anime_id = await _localizar_anime_existente(sessao, slug)
            if anime_id is None:
                raise ErroSlimeStudio(
                    f"conflito ao criar anime (slug={slug!r}) mas nenhum registro foi encontrado"
                ) from excecao
            return anime_id
        return anime.id


async def _localizar_anime_existente(sessao: AsyncSession, slug: str) -> int | None:
    resultado = await sessao.execute(select(Anime.id).where(Anime.slug == slug))
    return resultado.scalar_one_or_none()


async def aplicar_metadados(
    sessionmaker: _SessionMaker, anime_id: int, metadados: MetadadosDeAnime
) -> None:
    """Preenche só os campos de `Anime` que estão `NULL` hoje — idempotente,
    nunca sobrescreve dado já existente/confirmado (cadastro manual que já
    veio com capa/sinopse no payload, ou um enriquecimento anterior).

    `anilist_id` é `unique=True` (`models/anime.py`): se outra linha já usa
    esse id, a escrita do metadado é revertida sozinha (`rollback`) sem
    afetar o `Anime` já criado — quem chama (`api/servicos/descoberta.py`)
    não deve ter o cadastro do anime bloqueado por um conflito de metadado
    secundário."""
    async with sessionmaker() as sessao:
        anime = await sessao.get(Anime, anime_id)
        if anime is None:
            return

        if anime.capa_path is None and metadados.capa_url is not None:
            anime.capa_path = metadados.capa_url
        if anime.sinopse is None and metadados.sinopse is not None:
            anime.sinopse = metadados.sinopse
        if anime.anilist_id is None and metadados.anilist_id is not None:
            anime.anilist_id = metadados.anilist_id
        if anime.kitsu_id is None and metadados.kitsu_id is not None:
            anime.kitsu_id = metadados.kitsu_id

        # Lançamento não é idempotente por campo como o resto: quando o payload
        # traz o bloco, sobrescreve (mesma sessão, sem reabrir outra).
        if metadados.lancamento is not None:
            _aplicar_lancamento_no_anime(anime, metadados.lancamento, datetime.now(UTC))

        try:
            await sessao.commit()
        except IntegrityError as excecao:
            await sessao.rollback()
            logger.warning(
                "anilist_id=%s já usado por outro anime; metadado ignorado (anime_id=%s): %s",
                metadados.anilist_id,
                anime_id,
                excecao,
            )


def _aplicar_lancamento_no_anime(
    anime: Anime, lancamento: LancamentoDeAnime, agora: datetime
) -> None:
    """Escreve os campos de lançamento num `Anime` já carregado — sem I/O, só
    mutação de atributos. Único lugar com a semântica de SOBRESCRITA (oposta a
    `aplicar_metadados`, que só preenche nulo); reusado por `atualizar_lancamento`
    e `aplicar_metadados`.

    - `status_lancamento` / `proximo_ep_numero` / `proximo_ep_em`: gravados SEMPRE,
      inclusive `None`. A transição EM_LANCAMENTO -> FINALIZADO traz
      `proximo_ep_numero=None` e a coluna precisa zerar, senão o badge de
      "episódios novos" fica preso no último valor.
    - `total_episodios_anilist`: só grava se o provedor informou (não apagar um
      total já conhecido por causa de um refresh que veio sem o campo).
    - `lancamento_atualizado_em`: carimbo de "sincronizei agora", não de "algo
      mudou" — atualizado em toda chamada.
    """
    anime.status_lancamento = lancamento.status
    anime.proximo_ep_numero = lancamento.proximo_ep_numero
    anime.proximo_ep_em = lancamento.proximo_ep_em
    if lancamento.total_episodios is not None:
        anime.total_episodios_anilist = lancamento.total_episodios
    anime.lancamento_atualizado_em = agora


async def atualizar_lancamento(
    sessionmaker: _SessionMaker, anime_id: int, lancamento: LancamentoDeAnime
) -> None:
    """Sobrescreve os campos de lançamento de um `Anime` a partir de um refresh
    de provedor (`api/servicos/lancamentos.py`). Semântica em
    `_aplicar_lancamento_no_anime` — NÃO é idempotente por campo.

    Anime inexistente (`anime_id` sem linha) é no-op silencioso: o refresh
    oportunista não deve falhar porque a linha sumiu entre a leitura e a escrita.
    """
    async with sessionmaker() as sessao:
        anime = await sessao.get(Anime, anime_id)
        if anime is None:
            return
        _aplicar_lancamento_no_anime(anime, lancamento, datetime.now(UTC))
        await sessao.commit()


async def aplicar_lancamento_descoberto_por_titulo(
    sessionmaker: _SessionMaker,
    anime_id: int,
    *,
    anilist_id: int | None,
    lancamento: LancamentoDeAnime | None,
) -> None:
    """Persiste o resultado de um aquecimento de lançamento por BUSCA DE TÍTULO
    (`api/servicos/descoberta._buscar_por_titulo_e_persistir`, F14). Caminho
    deliberadamente separado de `aplicar_metadados` — não "simplifique"
    reusando-o:

    - **Nunca toca `capa_path`/`sinopse`/`kitsu_id`.** O match por título é
      heurístico; capa/sinopse são permanentes e visíveis, um match ruim
      gravaria lixo difícil de reverter. Só o bloco de lançamento (que o
      próximo refresh corrige sozinho) e, sob corroboração de slug feita pelo
      chamador, o `anilist_id`.
    - **`anilist_id` só entra se ainda estiver livre.** A checagem `SELECT`
      antes do `commit` evita a `IntegrityError` de `aplicar_metadados`, cujo
      `rollback` arrastaria junto o bloco de lançamento — dois animes irmãos
      (dub + leg) podem resolver pro mesmo id `unique=True`. O `except
      IntegrityError` residual cobre só a corrida TOCTOU (rara, auto-corrige no
      próximo refresh).
    - **`lancamento is None` ainda carimba `lancamento_atualizado_em`.** É o
      cache negativo ("busquei por título, provedor não achou") que impede a
      listagem de re-buscar o mesmo título a cada request enquanto o TTL vale.

    Anime inexistente é no-op silencioso (mesma regra de `atualizar_lancamento`).
    """
    agora = datetime.now(UTC)
    async with sessionmaker() as sessao:
        anime = await sessao.get(Anime, anime_id)
        if anime is None:
            return

        if anilist_id is not None and anime.anilist_id is None:
            resultado = await sessao.execute(
                select(Anime.id).where(Anime.anilist_id == anilist_id)
            )
            dono = resultado.scalar_one_or_none()
            if dono is not None:
                logger.warning(
                    "anilist_id=%s descoberto por título já pertence ao anime_id=%s; não "
                    "gravado em anime_id=%s (só o bloco de lançamento)",
                    anilist_id,
                    dono,
                    anime_id,
                )
            else:
                anime.anilist_id = anilist_id

        if lancamento is not None:
            _aplicar_lancamento_no_anime(anime, lancamento, agora)
        else:
            anime.lancamento_atualizado_em = agora

        try:
            await sessao.commit()
        except IntegrityError as excecao:
            await sessao.rollback()
            logger.warning(
                "corrida ao gravar anilist_id=%s descoberto por título (anime_id=%s); "
                "aquecimento perdido nesta passada: %s",
                anilist_id,
                anime_id,
                excecao,
            )


async def atualizar_lancamentos_em_lote(
    sessionmaker: _SessionMaker, dados: dict[int, LancamentoDeAnime]
) -> None:
    """Sobrescreve os campos de lançamento de vários `Anime` num refresh em lote
    (job periódico de `api/servicos/lancamentos.py`). Mesma semântica de
    `atualizar_lancamento`, em no máximo duas queries no total — nunca uma por
    anime.

    O `update(Anime)` com lista de dicts (bulk update by primary key) exige que
    todos os dicts do lote tenham o MESMO conjunto de chaves. Como
    `total_episodios_anilist` só pode ser escrito quando o provedor informou o
    total, os itens são particionados em dois lotes — com e sem
    `total_episodios` — e cada lote não-vazio vira um `execute`.
    """
    if not dados:
        return

    agora = datetime.now(UTC)
    com_total: list[dict[str, object]] = []
    sem_total: list[dict[str, object]] = []
    for anime_id, lanc in dados.items():
        linha: dict[str, object] = {
            "id": anime_id,
            "status_lancamento": lanc.status,
            "proximo_ep_numero": lanc.proximo_ep_numero,
            "proximo_ep_em": lanc.proximo_ep_em,
            "lancamento_atualizado_em": agora,
        }
        if lanc.total_episodios is not None:
            linha["total_episodios_anilist"] = lanc.total_episodios
            com_total.append(linha)
        else:
            sem_total.append(linha)

    async with sessionmaker() as sessao:
        for lote in (com_total, sem_total):
            if lote:
                await sessao.execute(update(Anime), lote)
        await sessao.commit()


async def atualizar_contagem_na_fonte(
    sessionmaker: _SessionMaker, anime_id: int, *, total: int, dominio: str
) -> None:
    """Grava o resultado de uma sondagem BEM-SUCEDIDA da fonte real
    (`api/servicos/sondagem.py`): quantos episódios o site expõe e qual site
    foi. `fonte_verificada_em` recebe `now(UTC)` — é o carimbo que o TTL da
    próxima sondagem consulta. Semântica separada de `_aplicar_lancamento_no_anime`
    de propósito: origem (fonte real x AniList) e ciclo de vida diferentes.

    Anime inexistente é no-op silencioso — mesma razão de `atualizar_lancamento`:
    a linha pode ter sumido entre a sondagem e a escrita.
    """
    async with sessionmaker() as sessao:
        anime = await sessao.get(Anime, anime_id)
        if anime is None:
            return
        anime.episodios_na_fonte = total
        anime.fonte_verificada_dominio = dominio
        anime.fonte_verificada_em = datetime.now(UTC)
        await sessao.commit()


async def localizar_animes_por_slug(
    sessionmaker: _SessionMaker, slugs: list[str]
) -> dict[str, int]:
    """Cruzamento em lote slug -> `Anime.id` local, usado por
    `api/servicos/descoberta.py` como *fallback* de
    `localizar_animes_por_anilist_id` (necessário para itens vindos do
    Kitsu, que não carregam `anilist_id`). Slugs sem correspondência
    simplesmente não aparecem no dict devolvido — ausência não é erro, é
    "ainda não catalogado"."""
    if not slugs:
        return {}
    async with sessionmaker() as sessao:
        resultado = await sessao.execute(select(Anime.slug, Anime.id).where(Anime.slug.in_(slugs)))
        return dict(resultado.all())


async def localizar_animes_por_anilist_id(
    sessionmaker: _SessionMaker, anilist_ids: list[int]
) -> dict[int, int]:
    """Cruzamento em lote `anilist_id` -> `Anime.id` local — prioridade sobre
    `localizar_animes_por_slug` no cruzamento do feed "em alta"
    (`api/servicos/descoberta.py`): `anilist_id` é único
    (`models/anime.py::Anime.anilist_id`) e não sofre falso-negativo por
    subtítulo/pontuação/ordem de palavra divergente entre o título do
    provedor e o título usado ao catalogar localmente, ao contrário do
    slug."""
    if not anilist_ids:
        return {}
    async with sessionmaker() as sessao:
        resultado = await sessao.execute(
            select(Anime.anilist_id, Anime.id).where(Anime.anilist_id.in_(anilist_ids))
        )
        return dict(resultado.all())


async def criar_episodio_e_job(
    sessionmaker: _SessionMaker,
    anime_id: int,
    *,
    numero: int,
    tipo: TipoEpisodio,
    versao: VersaoEpisodio,
    url_fonte: str,
    site_origem: str,
    titulo_episodio: str | None = None,
    duracao_esperada_s: int | None = None,
) -> int:
    """Cria o `Episodio` e, em seguida, o `Job` (via `db.fila.criar_job`) — duas
    transações curtas, não uma (mesma filosofia de sessão-por-operação do resto de
    `db/`). Na pior janela (processo morre entre as duas escritas) o resultado é
    um episódio `pendente` sem job — recuperável manualmente — nunca um job órfão
    sem episódio.

    Levanta `EpisodioJaExiste` se a identidade (`anime_id`, `numero`, `tipo`,
    `versao`) já existir (`uq_episodio_identidade`) — CLI e API decidem o que
    fazer com isso (a API mapeia para 409).
    """
    episodio_id = await _inserir_episodio(
        sessionmaker,
        anime_id,
        numero=numero,
        tipo=tipo,
        versao=versao,
        url_fonte=url_fonte,
        site_origem=site_origem,
        titulo_episodio=titulo_episodio,
    )
    return await criar_job(sessionmaker, episodio_id, duracao_esperada_s)


async def _inserir_episodio(
    sessionmaker: _SessionMaker,
    anime_id: int,
    *,
    numero: int,
    tipo: TipoEpisodio,
    versao: VersaoEpisodio,
    url_fonte: str,
    site_origem: str,
    titulo_episodio: str | None,
) -> int:
    async with sessionmaker() as sessao:
        episodio = Episodio(
            anime_id=anime_id,
            numero=numero,
            titulo=titulo_episodio,
            tipo=tipo,
            versao=versao,
            url_fonte=url_fonte,
            site_origem=site_origem,
            status=StatusEpisodio.PENDENTE,
        )
        sessao.add(episodio)
        try:
            await sessao.commit()
        except IntegrityError as excecao:
            await sessao.rollback()
            episodio_id = await _localizar_episodio_existente(
                sessao, anime_id, numero, tipo, versao
            )
            raise EpisodioJaExiste(episodio_id) from excecao
        return episodio.id


async def _localizar_episodio_existente(
    sessao: AsyncSession, anime_id: int, numero: int, tipo: TipoEpisodio, versao: VersaoEpisodio
) -> int | None:
    resultado = await sessao.execute(
        select(Episodio.id).where(
            Episodio.anime_id == anime_id,
            Episodio.numero == numero,
            Episodio.tipo == tipo,
            Episodio.versao == versao,
        )
    )
    return resultado.scalar_one_or_none()

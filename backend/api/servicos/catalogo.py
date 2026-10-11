"""Remoção de catálogo (anime/episódio) — apaga linha e arquivos em disco juntos
(HLS + raw) —, cálculo de uso de disco por mídia (ESPECIFICACAO.md §5, Passo 5 do
plano da Fase 3) e leitura agregada de presença de episódios para o catálogo.

Sessão própria por operação de escrita (mesmo padrão de `db/fila.py`) — não
importa `fastapi`. `ids_com_episodios` é a exceção: roda na sessão da request,
como as leituras agregadas de `lancamentos.py`/`sondagem.py`.
"""

import shutil
from collections.abc import Iterable

from sqlalchemy import exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from captura.download import caminho_raw
from core.config import Config
from core.enums import ESTADOS_EM_EXECUCAO, StatusEpisodio
from core.erros import JobEmExecucao
from core.franquia import slug_de_franquia
from core.midia import diretorio_do_episodio, podar_diretorios_do_anime
from models.anime import Anime
from models.episodio import Episodio
from models.job import Job

_SessionMaker = async_sessionmaker[AsyncSession]


async def remover_episodio(sessionmaker: _SessionMaker, config: Config, episodio_id: int) -> bool:
    """Remove o `Episodio` e seus arquivos (HLS + raw) em disco. Devolve `False`
    se o episódio não existir — quem chama decide se isso é um 404.

    Levanta `JobEmExecucao` se houver um `Job` ativo para este episódio: com
    `Job.episodio_id` em `ondelete="CASCADE"`, apagar o episódio embaixo de um
    worker em processamento apagaria o `Job` sem ele perceber (heartbeat/
    progresso passam a afetar 0 linhas, silenciosamente) e removeria o
    diretório que `empacotar()` pode estar escrevendo agora."""
    async with sessionmaker() as sessao:
        episodio = await sessao.get(Episodio, episodio_id)
        if episodio is None:
            return False

        job_ativo_id = await job_ativo_do_episodio(sessao, episodio_id)
        if job_ativo_id is not None:
            raise JobEmExecucao(job_ativo_id)

        anime = await sessao.get(Anime, episodio.anime_id)

        if anime is not None:
            remover_arquivos_do_episodio(config, anime.slug, episodio)

        await sessao.delete(episodio)
        await sessao.commit()
        return True


async def liberar_episodio(sessionmaker: _SessionMaker, config: Config, episodio_id: int) -> bool:
    """Libera o espaço em disco de um episódio já assistido sem apagar o
    registro do catálogo (diferente de `remover_episodio`): preserva
    `assistido_em`/`url_fonte`/`site_origem`/`numero_fonte`/`titulo`/
    `duracao_s` — uma recaptura futura reaproveita essa mesma linha em vez de
    criar outra (D2, `api/servicos/jobs.py::criar_job_site`). Devolve `False`
    se o episódio não existir.

    Levanta `JobEmExecucao` pelo mesmo motivo de `remover_episodio`: liberar
    arquivos que um worker está escrevendo agora corromperia o job em
    andamento.

    Idempotente: se `hls_path` já é `None` (já liberado, ou nunca teve mídia
    empacotada), é um no-op — nem checa job ativo, só devolve `True`."""
    async with sessionmaker() as sessao:
        episodio = await sessao.get(Episodio, episodio_id)
        if episodio is None:
            return False

        if episodio.hls_path is None:
            return True

        job_ativo_id = await job_ativo_do_episodio(sessao, episodio_id)
        if job_ativo_id is not None:
            raise JobEmExecucao(job_ativo_id)

        anime = await sessao.get(Anime, episodio.anime_id)
        if anime is not None:
            remover_arquivos_do_episodio(config, anime.slug, episodio)

        episodio.hls_path = None
        episodio.tamanho_bytes = None
        episodio.renditions_disponiveis = None
        episodio.status = StatusEpisodio.LIBERADO
        await sessao.commit()
        return True


async def remover_anime(sessionmaker: _SessionMaker, config: Config, anime_id: int) -> bool:
    """Remove o `Anime` (cascata apaga `Episodio`/`Job`/`FonteAnime` via
    `ondelete="CASCADE"`) e os arquivos de todos os seus episódios em disco.
    Devolve `False` se o anime não existir.

    Levanta `JobEmExecucao` se qualquer episódio do anime tiver um `Job` ativo
    — mesmo risco de `remover_episodio`, aqui multiplicado por todos os
    episódios que a cascata apagaria."""
    async with sessionmaker() as sessao:
        anime = await sessao.get(Anime, anime_id)
        if anime is None:
            return False

        job_ativo_id = await _job_ativo_do_anime(sessao, anime_id)
        if job_ativo_id is not None:
            raise JobEmExecucao(job_ativo_id)

        episodios = (
            await sessao.execute(select(Episodio).where(Episodio.anime_id == anime_id))
        ).scalars()
        for episodio in episodios:
            remover_arquivos_do_episodio(config, anime.slug, episodio)

        await sessao.delete(anime)
        await sessao.commit()
        return True


async def job_ativo_do_episodio(sessao: AsyncSession, episodio_id: int) -> int | None:
    """Pública porque também é usada por `api/servicos/jobs.py::
    _reaproveitar_episodio_para_recaptura` (mesmo padrão de promoção de
    `remover_arquivos_do_episodio`, ver docstring dela)."""
    resultado = await sessao.execute(
        select(Job.id).where(Job.episodio_id == episodio_id, Job.status.in_(ESTADOS_EM_EXECUCAO))
    )
    return resultado.scalars().first()


async def _job_ativo_do_anime(sessao: AsyncSession, anime_id: int) -> int | None:
    resultado = await sessao.execute(
        select(Job.id)
        .join(Episodio, Job.episodio_id == Episodio.id)
        .where(Episodio.anime_id == anime_id, Job.status.in_(ESTADOS_EM_EXECUCAO))
    )
    return resultado.scalars().first()


async def uso_de_disco(sessionmaker: _SessionMaker, config: Config) -> tuple[int, int, int]:
    """`(total_bytes, livre_bytes, usado_por_midia_bytes)`. Os dois primeiros vêm
    de `shutil.disk_usage` no mount de `MEDIA_ROOT`; o terceiro é a soma de
    `Episodio.tamanho_bytes` — não o uso real do filesystem (que incluiria
    `raw/` e sobras de reprocessamento). Sem "candidatos a limpeza" nesta fase
    (plano §4) — só o agregado."""
    uso = shutil.disk_usage(config.media_root)
    async with sessionmaker() as sessao:
        resultado = await sessao.execute(select(Episodio.tamanho_bytes))
        usado_por_midia = sum(tamanho for (tamanho,) in resultado if tamanho is not None)
    return uso.total, uso.free, usado_por_midia


async def ids_com_episodios(sessao: AsyncSession, ids: Iterable[int]) -> set[int]:
    """`{anime_id}` dos animes com ao menos uma linha em `Episodio`, numa única
    query agregada — `GET /api/animes` serializa o catálogo inteiro, um `SELECT`
    por anime seria N+1. Roda na sessão da request, igual
    `lancamentos.maior_numero_capturado_por_anime`. Guard de lista vazia porque
    `IN ()` é inválido no SQLite.

    Não reaproveita `maior_numero_capturado_por_anime` de propósito: aquela
    filtra `tipo == REGULAR` + `status in (PRONTO, LIBERADO)` e devolve
    `MAX(numero)` — "episódio 0" fica indistinguível de "nenhum episódio" e uma
    captura em andamento (`PENDENTE`) some do resultado. Aqui o rótulo de estreia
    do card de bookmark só quer saber se existe QUALQUER linha de `Episodio`, sem
    filtro de tipo/status.
    """
    lista_ids = list(ids)
    if not lista_ids:
        return set()
    resultado = await sessao.execute(
        select(Episodio.anime_id).where(Episodio.anime_id.in_(lista_ids)).distinct()
    )
    return set(resultado.scalars())


def remover_arquivos_do_episodio(config: Config, anime_slug: str, episodio: Episodio) -> None:
    """Melhor esforço (`ignore_errors=True`/`missing_ok=True`) — um arquivo que
    resiste à remoção não deve impedir a operação, só fica órfão em disco
    para limpeza manual.

    Pública porque três operações chamam: `remover_episodio`/`remover_anime`
    (linha do banco é apagada em seguida) e `liberar_episodio`/
    `api/servicos/jobs.py::criar_job_site` (linha do `Episodio` sobrevive,
    só os arquivos em disco somem).

    Ao final poda `hls/<slug>` e `raw/<slug>` se ficaram vazios — no laço de
    `remover_anime` a poda roda a cada episódio e só remove a pasta-mãe quando
    a última subpasta sai, sem precisar de uma passada extra depois do laço."""
    if episodio.hls_path is not None:
        diretorio_hls = diretorio_do_episodio(
            config.media_root, anime_slug, episodio.numero, episodio.tipo, episodio.versao
        )
        shutil.rmtree(diretorio_hls, ignore_errors=True)

    caminho_bruto = caminho_raw(
        config.media_root, anime_slug, episodio.numero, episodio.tipo, episodio.versao
    )
    caminho_bruto.unlink(missing_ok=True)

    podar_diretorios_do_anime(config.media_root, anime_slug)


async def agrupar_franquias(sessao: AsyncSession) -> dict[int, list[object]]:
    """`{anime_id: grupo}` — agrupa o catálogo INTEIRO em componentes conexos de
    franquia (união por `serie_ancora` OU slug do título base, `core/
    franquia.py` — o segundo sinal cobre o walk de `relations` que erra com
    OVA/ONA/split-cour no meio, Fase 6), uma query só. `grupo` é a lista
    ordenada por `numero_temporada` (NULL por último) de TODAS as linhas da
    franquia — mesma lista (referência compartilhada) pra cada `anime_id`
    membro dela, então indexar o dict não duplica dado. Espelha o agrupamento
    de `frontend/src/inicio/franquia.js`.

    A parte cara de `_temporadas_e_proxima`: varrer o catálogo inteiro (dezenas
    de linhas, uso pessoal — barato o bastante pra não justificar índice) só
    UMA VEZ por request, não por anime. `obter_anime` chama isto pro grupo de 1
    anime; `listar_animes` reaproveita o mesmo dict pra cada card da grade —
    sem isso, calcular `proxima_temporada` pro catálogo inteiro escanearia o
    catálogo inteiro de novo a cada anime (O(N²))."""
    tem_episodio = exists().where(Episodio.anime_id == Anime.id)
    linhas = (
        await sessao.execute(
            select(
                Anime.id,
                Anime.numero_temporada,
                Anime.titulo,
                Anime.serie_ancora,
                Anime.status_lancamento,
                Anime.estreia_em,
                Anime.ano,
                Anime.formato_midia,
                Anime.total_episodios_anilist,
                Anime.banner_path,
                Anime.banner_escolhido,
                tem_episodio.label("tem_episodios"),
            )
        )
    ).all()

    pai: dict[object, object] = {}

    def acha(no: object) -> object:
        pai.setdefault(no, no)
        while pai[no] != no:
            pai[no] = pai[pai[no]]
            no = pai[no]
        return no

    def une(a: object, b: object) -> None:
        pai[acha(a)] = acha(b)

    for linha in linhas:
        no = ("id", linha.id)
        acha(no)
        slug = slug_de_franquia(linha.titulo)
        if slug:
            une(no, ("slug", slug))
        if linha.serie_ancora is not None:
            une(no, ("anc", linha.serie_ancora))

    grupos_por_raiz: dict[object, list[object]] = {}
    for linha in linhas:
        grupos_por_raiz.setdefault(acha(("id", linha.id)), []).append(linha)
    for grupo in grupos_por_raiz.values():
        grupo.sort(
            key=lambda linha: (
                linha.numero_temporada is None,
                linha.numero_temporada or 0,
                linha.id,
            )
        )

    return {linha.id: grupos_por_raiz[acha(("id", linha.id))] for linha in linhas}


def banner_escolhido_da_franquia(grupo: list[object]) -> str | None:
    """Banner que o usuário escolheu no seletor, se alguma linha da franquia o tem."""
    return next((linha.banner_escolhido for linha in grupo if linha.banner_escolhido), None)


def banner_da_temporada_ou_franquia(
    grupo: list[object], banner_proprio: str | None
) -> str | None:
    """Banner a exibir para uma temporada: a escolha do usuário (vale pra franquia
    inteira); senão o da própria temporada (`banner_proprio`); senão o da primeira
    temporada da franquia (`grupo` já ordenado por `numero_temporada`) que tem um.
    `None` quando nenhuma tem."""
    return (
        banner_escolhido_da_franquia(grupo)
        or banner_proprio
        or next((linha.banner_path for linha in grupo if linha.banner_path), None)
    )


async def definir_banner_da_franquia(
    sessionmaker: _SessionMaker, anime_id: int, banner_url: str | None
) -> bool:
    """Grava `banner_escolhido` (ou o limpa, com `None`) em TODAS as linhas da
    franquia de `anime_id`. Em todas, e não só na que o usuário abriu, para que uma
    temporada anterior catalogada depois — que passa a vir primeiro no grupo —
    não esconda a escolha. Devolve `False` se o anime não existir."""
    async with sessionmaker() as sessao:
        grupos = await agrupar_franquias(sessao)
        grupo = grupos.get(anime_id)
        if grupo is None:
            return False
        await sessao.execute(
            update(Anime).where(Anime.id.in_([linha.id for linha in grupo])).values(
                banner_escolhido=banner_url
            )
        )
        await sessao.commit()
        return True


def visiveis_no_catalogo(
    animes: Iterable[Anime], grupos: dict[int, list[object]]
) -> list[Anime]:
    """Animes que ganham card próprio no catálogo: temporada normal
    (`formato_midia` nulo) OU filme/OVA/ONA/especial cuja franquia não tem
    nenhuma temporada normal catalogada pra abrigá-lo. Sem a segunda regra, uma
    série que a AniList classifica como ONA (ex. 1ª temporada de "Hitoribocchi
    no Isekai Kouryaku", sequência em TV) ficava órfã e invisível: o card de
    quem a abrigaria nunca existiu. Preserva a ordem de `animes`."""
    return [
        anime
        for anime in animes
        if anime.formato_midia is None
        or not any(linha.formato_midia is None for linha in grupos[anime.id])
    ]

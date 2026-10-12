"""Franquia no banco: agrupamento do catálogo em franquias e a aritmética de
temporadas (título-base, offset absoluto de episódios, total das partes irmãs).
Insumo de `fontes/recorte.py` (recorte de fonte achatada, também usado pela
captura no worker) e de `api/servicos/stills_de_episodio.py` (busca no TMDB por
número absoluto)."""

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.franquia import slug_de_franquia
from models.anime import Anime
from models.episodio import Episodio

_SessionMaker = async_sessionmaker[AsyncSession]


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


async def titulo_base_da_franquia(sessionmaker: _SessionMaker, anime: Anime) -> str:
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


async def _irmas_da_franquia(sessionmaker: _SessionMaker, anime: Anime) -> list[object]:
    """Linhas TV (`formato_midia` nulo) da franquia de `anime` que têm
    `numero_temporada`, sem o próprio `anime`. Agrupa por `agrupar_franquias`
    (slug do título base OU `serie_ancora`), não só por `serie_ancora`: ela
    diverge entre partes de uma mesma obra (Slime: T1 e as demais têm âncoras
    distintas)."""
    async with sessionmaker() as sessao:
        grupos = await agrupar_franquias(sessao)
    return [
        linha
        for linha in grupos.get(anime.id, [])
        if linha.id != anime.id
        and linha.formato_midia is None
        and linha.numero_temporada is not None
    ]


async def offset_de_temporada(sessionmaker: _SessionMaker, anime: Anime) -> int:
    """Nº absoluto do 1º episódio desta temporada na franquia, menos 1 — a soma
    de `total_episodios_anilist` das temporadas irmãs com `numero_temporada`
    menor. `0` para a 1ª temporada, anime sem `numero_temporada`, ou irmãs sem
    contagem.

    Serve ao recorte de fonte achatada (`fontes/recorte.py`) e ao overlay de
    still: o TMDB às vezes modela a franquia inteira numa season só (ex. Kusuriya
    no Hitorigoto — 2 temporadas na AniList, 1 season de 48 no TMDB), então pedir
    a still por `(numero_temporada, numero_por_temporada)` devolve vazio. Com o
    offset, o overlay pede pelo número ABSOLUTO e deixa a `TabelaDeTemporadas` do
    TMDB achar a season certa (funciona tanto pro TMDB achatado quanto pro
    dividido).

    Só conta o que está catalogado: temporada irmã ausente do catálogo não entra
    na soma."""
    if not anime.numero_temporada or anime.numero_temporada <= 1:
        return 0
    irmas = await _irmas_da_franquia(sessionmaker, anime)
    return sum(
        linha.total_episodios_anilist or 0
        for linha in irmas
        if linha.numero_temporada < anime.numero_temporada
    )


async def total_das_partes_irmas(sessionmaker: _SessionMaker, anime: Anime) -> int:
    """Soma de `total_episodios_anilist` das OUTRAS linhas TV da mesma franquia
    com o mesmo `numero_temporada` (ex. "2nd Season" e "2nd Season Part 2")."""
    if anime.numero_temporada is None or anime.formato_midia is not None:
        return 0
    irmas = await _irmas_da_franquia(sessionmaker, anime)
    return sum(
        linha.total_episodios_anilist or 0
        for linha in irmas
        if linha.numero_temporada == anime.numero_temporada
    )

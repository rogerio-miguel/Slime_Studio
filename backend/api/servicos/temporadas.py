"""Aritmética de temporadas de uma franquia: o título-base (sem marcador de
temporada), o offset absoluto de episódios e o total das partes irmãs. Insumo
de `api/servicos/fontes.py` (recorte de fonte achatada) e de
`api/servicos/stills_de_episodio.py` (busca no TMDB por número absoluto)."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.servicos.catalogo import agrupar_franquias
from models.anime import Anime

_SessionMaker = async_sessionmaker[AsyncSession]


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


async def offset_de_temporada(sessionmaker: _SessionMaker, anime: Anime) -> int:
    """Nº absoluto do 1º episódio desta temporada na franquia, menos 1 — a soma
    de `total_episodios_anilist` das temporadas irmãs (mesmo `serie_ancora`) com
    `numero_temporada` menor. `0` para a 1ª temporada, anime sem `serie_ancora`,
    ou irmãs sem contagem.

    Serve só ao overlay de still: o TMDB às vezes modela a franquia inteira numa
    season só (ex. Kusuriya no Hitorigoto — 2 temporadas na AniList, 1 season de
    48 no TMDB), então pedir a still por `(numero_temporada, numero_por_temporada)`
    devolve vazio. Com o offset, o overlay pede pelo número ABSOLUTO e deixa a
    `TabelaDeTemporadas` do TMDB achar a season certa (funciona tanto pro TMDB
    achatado quanto pro dividido)."""
    if not anime.serie_ancora or not anime.numero_temporada or anime.numero_temporada <= 1:
        return 0
    async with sessionmaker() as sessao:
        total = await sessao.scalar(
            select(func.coalesce(func.sum(Anime.total_episodios_anilist), 0)).where(
                Anime.serie_ancora == anime.serie_ancora,
                Anime.numero_temporada.is_not(None),
                Anime.numero_temporada < anime.numero_temporada,
            )
        )
    return int(total or 0)


async def total_das_partes_irmas(sessionmaker: _SessionMaker, anime: Anime) -> int:
    """Soma de `total_episodios_anilist` das OUTRAS linhas TV da mesma franquia
    com o mesmo `numero_temporada` (ex. "2nd Season" e "2nd Season Part 2").
    Agrupa por `agrupar_franquias` (slug do título base OU `serie_ancora`), não
    só por `serie_ancora`, que nessas partes costuma divergir."""
    if anime.numero_temporada is None or anime.formato_midia is not None:
        return 0
    async with sessionmaker() as sessao:
        grupos = await agrupar_franquias(sessao)
    return sum(
        linha.total_episodios_anilist or 0
        for linha in grupos.get(anime.id, [])
        if linha.id != anime.id
        and linha.numero_temporada == anime.numero_temporada
        and linha.formato_midia is None
    )

"""Que versão (legendado/dublado) de cada anime o sistema usa: a última escolha
de fonte (`FonteAnime`) traduzida para "o que sondar/resolver" ou para "o que
exibir no catálogo". Leitura pura do banco; consumido por `sondagem.py`,
`aquecimento.py`, `progresso.py` e `api/rotas/animes.py`."""

from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.servicos.jobs import versao_episodio_da_fonte
from core.enums import TipoEpisodio, VersaoDeFonte, VersaoEpisodio
from models.episodio import Episodio
from models.fonte_anime import FonteAnime

# `VersaoDeFonte` (estado do mapeamento) -> `VersaoEpisodio` pedível a
# `fontes.resolucao.resolver_fonte_do_anime`. NUNCA `DESCONHECIDA`:
# `resolver_fonte_do_anime` levanta `ValueError` com ela. `NAO_DIFERENCIADA` ->
# `LEGENDADO` é seguro — a resolução aceita a linha `NAO_DIFERENCIADA` e
# `fontes.listagem.filtrar_por_versao` devolve a lista inteira quando nenhum
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


async def _escolha_de_fonte_mais_recente_por_anime(
    sessao: AsyncSession, ids: Iterable[int]
) -> dict[int, VersaoDeFonte]:
    """`{anime_id: VersaoDeFonte da linha de maior resolvido_em}` para os `ids`
    com ao menos uma linha em `FonteAnime` — a última escolha manual de fonte do
    usuário, a mesma que uma captura usaria
    (`fontes.resolucao._resolver_em_mapeadas`). Query única, roda na sessão
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


async def versao_dos_episodios_capturados(
    sessao: AsyncSession, ids: Iterable[int]
) -> dict[int, VersaoEpisodio]:
    """`{anime_id: versão a PEDIR}` derivada do `Episodio.versao` mais recente já
    capturado (mesmo mapa de `versao_de_sondagem`: `DESCONHECIDA`/`NAO_DIFERENCIADA`
    nunca é pedível, vira `LEGENDADO`). É só um palpite que dá à busca ao vivo um
    ponto de partida; `resolver_fonte_do_anime` confirma a versão real assim que
    reencontra o anime num site. Anime sem episódio não aparece."""
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

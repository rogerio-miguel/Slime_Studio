"""Detector de episódios novos (badge no catálogo, ESPECIFICACAO.md §3F).

`episodios_novos` é cálculo puro sobre um `Anime` já carregado — compara
`Anime.episodios_na_fonte` (contagem da fonte real, alimentada por
`api/servicos/sondagem.py`) com a fronteira do que o usuário já acompanhou: o
maior `numero` de episódio REGULAR já capturado/assistido localmente. Usar a
fronteira em vez da contagem de capturados evita que buracos abaixo do episódio
mais recente (usuário que pulou episódios antigos) contem como novos.
`maior_numero_capturado_por_anime` é a leitura agregada que fornece essa
segunda metade em lote (uma query para o catálogo inteiro, nunca por anime num
loop). Não importa `fastapi` nem Pydantic — `api/rotas/animes.py` é quem traduz
o resultado para os esquemas de saída (regra de dependência da Clean
Architecture, CLAUDE.md §1).

O badge só aparece quando o anime está `EM_LANCAMENTO` — sem sub-trava de
sinal-vivo. A lógica de fronteira `MAX(numero)` já barra o falso-positivo do
episódio antigo pulado, então checar `proximo_ep_em`/`total_episodios_anilist`
não agregava nada e sumia o badge para animes `EM_LANCAMENTO` sem `anilist_id`.
`status_lancamento` é recalculado a cada request a partir da coluna homônima,
que `api/servicos/descoberta.py` mantém em dia via refresh oportunista de 6h —
se a AniList finaliza ou reabre um anime, o badge acompanha na próxima leitura;
não há flag persistida. Ver `episodios_novos`.
"""

from collections.abc import Iterable, Sequence

from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.enums import StatusEpisodio, StatusLancamento, TipoEpisodio
from models.anime import Anime
from models.episodio import Episodio

# Status que contam como "episódio já obtido" para o detector: `PRONTO` (arquivo
# em disco) e `LIBERADO` (já assistido, arquivos liberados, mas o usuário não
# quer vê-lo reaparecer como novo). `PENDENTE`/`FALHOU`/`SOMENTE_720P` ainda não
# renderam uma captura utilizável.
_STATUS_CAPTURADO = (StatusEpisodio.PRONTO, StatusEpisodio.LIBERADO)


def episodios_novos(anime: Anime, maior_capturado: int) -> int:
    """Nº de episódios já disponíveis na fonte real (site) acima da fronteira do
    que o usuário acompanhou — 0 quando o anime não está `EM_LANCAMENTO`.

    `episodios_na_fonte` é a contagem da última sondagem bem-sucedida do site
    (`api/servicos/sondagem.py`); fica `None` enquanto nenhuma sondagem
    carimbou, e aí o badge é 0. `maior_capturado` é o maior `numero` de
    episódio REGULAR já capturado/assistido (0 se nenhum) — a comparação é com
    essa fronteira, não com a contagem de capturados, para que episódios
    antigos que o usuário pulou não inflem o badge. Piso em 0: fonte que largou
    episódios antigos (`episodios_na_fonte` abaixo da fronteira) não vira
    negativo.

    Gate: só `EM_LANCAMENTO`, sem sub-trava de sinal-vivo. A fronteira
    `maior_capturado` já mata o falso-positivo do episódio antigo pulado. O
    status é lido da coluna `status_lancamento` a cada request (mantida em dia
    por `api/servicos/descoberta.py`): se a AniList finaliza o anime o badge
    some na próxima leitura, se reabre ele volta — não há flag persistida.
    """
    if anime.episodios_na_fonte is None:
        return 0
    if anime.status_lancamento is not StatusLancamento.EM_LANCAMENTO:
        return 0
    return max(0, anime.episodios_na_fonte - maior_capturado)


async def ids_totalmente_assistidos(sessao: AsyncSession, animes: Sequence[Anime]) -> set[int]:
    """`{anime_id}` dos animes que o usuário TERMINOU de ver — alimenta a tag
    "Assistido" do catálogo (`paginas/Galeria.jsx`). Uma única query agregada
    (mesmo motivo N+1 de `maior_numero_capturado_por_anime`).

    Regra: a contagem de episódios REGULAR assistidos (`assistido_em`, entre os
    `PRONTO`/`LIBERADO`) tem de alcançar o total de episódios do anime — o MAIOR
    entre `episodios_na_fonte` (sondagem do site) e `total_episodios_anilist`,
    porque qualquer um dos dois pode estar subestimado (sondagem que só achou
    metade, AniList sem grade fechada) e subestimar acende a tag cedo demais.
    Isso barra tanto "vi só os 3 que baixei" de um anime de 12 quanto "vi só o
    último" — pra tag acender é preciso ter visto TODOS. Quando nenhuma das duas
    contagens é conhecida, cai no critério frouxo "todo capturado foi assistido".

    Anime sem nenhum episódio capturado nunca entra (o `GROUP BY` não rende linha
    pra ele). Guard de lista vazia porque `IN ()` é inválido no SQLite."""
    ids = [anime.id for anime in animes]
    if not ids:
        return set()
    total_capturados = func.count(Episodio.id)
    total_assistidos = func.count(Episodio.assistido_em)
    regulares_assistidos = func.count(
        case(
            (
                and_(
                    Episodio.tipo == TipoEpisodio.REGULAR,
                    Episodio.assistido_em.is_not(None),
                ),
                Episodio.id,
            )
        )
    )
    linhas = await sessao.execute(
        select(Episodio.anime_id, total_capturados, total_assistidos, regulares_assistidos)
        .where(Episodio.anime_id.in_(ids), Episodio.status.in_(_STATUS_CAPTURADO))
        .group_by(Episodio.anime_id)
    )
    por_id = {anime.id: anime for anime in animes}
    concluidos: set[int] = set()
    for anime_id, capturados, assistidos, regulares_vistos in linhas.all():
        if capturados == 0:
            continue
        anime = por_id.get(anime_id)
        contagens = (
            [c for c in (anime.episodios_na_fonte, anime.total_episodios_anilist) if c]
            if anime
            else []
        )
        if contagens:
            if regulares_vistos >= max(contagens):
                concluidos.add(anime_id)
        elif assistidos == capturados:
            concluidos.add(anime_id)
    return concluidos


async def maior_numero_capturado_por_anime(
    sessao: AsyncSession, ids: Iterable[int]
) -> dict[int, int]:
    """`{anime_id: maior numero de episódio REGULAR já capturado}` para todos os
    `ids` numa única query agregada — `GET /api/animes` serializa o catálogo
    inteiro, um `SELECT` por anime seria N+1. `anime_id` ausente do dict = 0
    (nenhum episódio capturado).

    `MAX(numero)`: a fronteira do que o usuário acompanhou, não quantos
    episódios tem — buraco abaixo do mais recente (episódio antigo pulado) não
    conta como pendente. `tipo == REGULAR`: OVA/especial/filme têm numeração
    própria e não entram na comparação com `episodios_na_fonte`.
    """
    lista_ids = list(ids)
    if not lista_ids:
        return {}
    resultado = await sessao.execute(
        select(Episodio.anime_id, func.max(Episodio.numero))
        .where(
            Episodio.anime_id.in_(lista_ids),
            Episodio.tipo == TipoEpisodio.REGULAR,
            Episodio.status.in_(_STATUS_CAPTURADO),
        )
        .group_by(Episodio.anime_id)
    )
    return {anime_id: maior for anime_id, maior in resultado.all()}


def temporadas_novas_apos_concluida(
    grupos: dict[int, list[object]], concluidos: set[int]
) -> dict[int, int]:
    """`{anime_id da temporada nova: anime_id da temporada anterior}` — temporada
    de TV já no catálogo, SEM nenhum episódio local, cuja temporada imediatamente
    anterior na franquia o usuário TERMINOU (`concluidos`, de
    `ids_totalmente_assistidos`). É a continuação natural do que ele já acompanhou:
    alimenta o badge "Novo ep" e a prateleira "Continuar assistindo", que sem
    isto só enxergavam animes com episódio local (o usuário teria de abrir a
    página da temporada nova e capturar o 1º episódio pra ela aparecer).

    Só a imediatamente anterior conta: com T1 concluída, T2 e T3 no catálogo e
    nenhuma com episódio, só a T2 é "nova" — a T3 espera o usuário alcançar a T2.
    Filme/OVA/ONA (`formato_midia`), temporada sem `numero_temporada` (posição
    desconhecida) e `NAO_LANCADO` (nada a capturar ainda) ficam de fora.
    `grupos` é o dict de `catalogo.agrupar_franquias` (listas compartilhadas por
    membro — dedupe por identidade). Sem I/O."""
    resultado: dict[int, int] = {}
    vistos: set[int] = set()
    for grupo in grupos.values():
        if id(grupo) in vistos:
            continue
        vistos.add(id(grupo))
        temporadas = [
            linha
            for linha in grupo
            if linha.formato_midia is None and linha.numero_temporada is not None
        ]
        for anterior, atual in zip(temporadas, temporadas[1:], strict=False):
            if (
                atual.numero_temporada > anterior.numero_temporada
                and anterior.id in concluidos
                and not atual.tem_episodios
                and atual.status_lancamento is not StatusLancamento.NAO_LANCADO
            ):
                resultado[atual.id] = anterior.id
    return resultado


async def temporadas_novas(
    sessao: AsyncSession, grupos: dict[int, list[object]]
) -> dict[int, int]:
    """Versão com I/O de `temporadas_novas_apos_concluida`: descobre quais
    temporadas com episódio local estão concluídas (uma query de `Anime` + a
    agregada de `ids_totalmente_assistidos`) e cruza com as franquias de
    `catalogo.agrupar_franquias`. Só consulta franquias com 2+ membros."""
    ids_com_episodio = {
        linha.id
        for grupo in grupos.values()
        if len(grupo) > 1
        for linha in grupo
        if linha.tem_episodios
    }
    if not ids_com_episodio:
        return {}
    animes = (
        (await sessao.execute(select(Anime).where(Anime.id.in_(ids_com_episodio))))
        .scalars()
        .all()
    )
    concluidos = await ids_totalmente_assistidos(sessao, animes)
    return temporadas_novas_apos_concluida(grupos, concluidos)

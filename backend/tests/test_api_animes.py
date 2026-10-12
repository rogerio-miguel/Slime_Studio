"""Testes de `GET /api/admin/animes/{id}/episodios-remotos`
(`api/rotas/animes.py` -> `api/servicos/fontes.py`). Resolução de fonte remota é
monkeypatchada nos nomes importados em `api.servicos.fontes` — mesmo padrão de
`tests/test_api_jobs.py` para o modo "site" de criação de job.

Cobre também o detector de episódios novos (`api/servicos/lancamentos.py` +
`GET /api/animes` / `GET /api/animes/{id}`)."""

import asyncio
from datetime import UTC, date, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.servicos import sondagem
from api.servicos.catalogo import ids_com_episodios
from api.servicos.fontes import FonteComEpisodios
from api.servicos.lancamentos import episodios_novos, maior_numero_capturado_por_anime
from core.enums import StatusEpisodio, StatusLancamento, TipoEpisodio, VersaoDeFonte, VersaoEpisodio
from core.erros import FalhaDeExtracao
from fontes.adaptadores.base import EpisodioRemoto, ResultadoBusca
from fontes.resolucao import ConfirmacaoNecessaria, FonteResolvida
from integrations.base import AnimeEmAlta, InfoDeEpisodio
from models.anime import Anime
from models.episodio import Episodio
from models.fonte_anime import FonteAnime

_SessionMaker = async_sessionmaker[AsyncSession]


async def _criar_anime(sessionmaker: _SessionMaker, titulo: str) -> int:
    async with sessionmaker() as sessao:
        anime = Anime(titulo=titulo, slug=titulo.lower().replace(" ", "-"))
        sessao.add(anime)
        await sessao.commit()
        return anime.id


@pytest.fixture(autouse=True)
def _resolucao_de_titulo_canonico_sem_rede(monkeypatch: pytest.MonkeyPatch):
    """`api/servicos/fontes.py::listar_episodios_remotos` resolve os nomes
    canônicos do anime (`integrations.servico.buscar_titulos`, só AniList) ANTES
    da resolução de fonte e SEMPRE — sem stub, os testes de `episodios-remotos`
    bateriam em AniList de verdade. Devolve `None` ("provedor respondeu, não
    achou"), o que degrada `_referencias_de_anime` para só o título cadastrado —
    o comportamento que estes testes já assumem. Mesmo padrão de
    `tests/test_api_buscar_fontes.py`."""

    async def _sem_titulos(titulo):
        return None

    monkeypatch.setattr("integrations.servico.buscar_titulos", _sem_titulos)


async def test_listar_episodios_remotos_caminho_feliz(
    cliente: AsyncClient,
    sessionmaker_api: _SessionMaker,
    monkeypatch: pytest.MonkeyPatch,
):
    anime_id = await _criar_anime(sessionmaker_api, "Anime Remoto")

    async def _resolver_fake(sessionmaker, anime, versao, titulos_alternativos=None):
        return FonteResolvida(
            dominio="animefire.one",
            identificador="42",
            versao_da_fonte=VersaoDeFonte.NAO_DIFERENCIADA,
        )

    async def _listar_fake(sessionmaker, dominio, identificador, temporada=None):
        return [
            EpisodioRemoto(
                rotulo="1",
                numero=1,
                url="https://x/ep1",
                thumb_url="https://animefire.one/img/video/42/1.webp",
            ),
            EpisodioRemoto(rotulo="2", numero=2, url="https://x/ep2"),
            EpisodioRemoto(rotulo="especial", numero=None, url="https://x/ep-especial"),
        ]

    monkeypatch.setattr("api.servicos.fontes.resolver_fonte_do_anime", _resolver_fake)
    monkeypatch.setattr("api.servicos.fontes.listar_episodios_em", _listar_fake)

    resposta = await cliente.get(f"/api/admin/animes/{anime_id}/episodios-remotos")

    # `thumb_url` nunca reflete o que `_listar_fake` devolveu: o overlay
    # (`_sobrepor_stills_de_episodios`) substitui pela arte do anime (aqui
    # `None`, o anime de teste não tem banner/capa) sempre que o TMDB não
    # resolve — nunca mais o thumb cru do extractor (ver
    # `test_listar_episodios_remotos_sobrepoe_still_tmdb_com_fallback_pro_anime`).
    assert resposta.status_code == 200
    assert resposta.json() == {
        "dominio": "animefire.one",
        "episodios": [
            {"rotulo": "1", "numero": 1, "thumb_url": None, "titulo": None, "sinopse": None},
            {"rotulo": "2", "numero": 2, "thumb_url": None, "titulo": None, "sinopse": None},
            {
                "rotulo": "especial",
                "numero": None,
                "thumb_url": None,
                "titulo": None,
                "sinopse": None,
            },
        ],
    }


async def test_listar_episodios_remotos_fonte_ambigua_409(
    cliente: AsyncClient,
    sessionmaker_api: _SessionMaker,
    monkeypatch: pytest.MonkeyPatch,
):
    anime_id = await _criar_anime(sessionmaker_api, "Anime Remoto Ambíguo")

    async def _resolver_fake(sessionmaker, anime, versao, titulos_alternativos=None):
        return ConfirmacaoNecessaria(
            dominio="animefire.one",
            candidatos=[
                ResultadoBusca(titulo_exibicao="A", identificador="1", url="https://x/1"),
                ResultadoBusca(titulo_exibicao="B", identificador="2", url="https://x/2"),
            ],
        )

    monkeypatch.setattr("api.servicos.fontes.resolver_fonte_do_anime", _resolver_fake)

    resposta = await cliente.get(f"/api/admin/animes/{anime_id}/episodios-remotos")

    assert resposta.status_code == 409
    assert resposta.json()["detail"]["motivo"] == "fonte_ambigua"


async def test_listar_episodios_remotos_anime_inexistente_404(cliente: AsyncClient):
    resposta = await cliente.get("/api/admin/animes/999999/episodios-remotos")

    assert resposta.status_code == 404


async def test_listar_episodios_remotos_sobrepoe_still_tmdb_com_fallback_pro_anime(
    cliente: AsyncClient,
    sessionmaker_api: _SessionMaker,
    monkeypatch: pytest.MonkeyPatch,
):
    """Fatia 5 (`PLANO_ARTE_TMDB.md`) + pedido do usuário (thumb de episódio
    nunca mais "da fonte"): episódio que o TMDB resolve troca de thumb;
    episódio que o TMDB não acha cai pra arte do PRÓPRIO anime
    (`banner_path`), NUNCA MAIS o `thumb_url` que o extractor trouxe; episódio
    sem `numero` (rótulo não numérico) nem tenta o TMDB — vai direto pro
    fallback."""
    async with sessionmaker_api() as sessao:
        anime = Anime(
            titulo="Anime Com Still",
            slug="anime-com-still",
            banner_path="https://tmdb.org/banner-do-anime.jpg",
        )
        sessao.add(anime)
        await sessao.commit()
        anime_id = anime.id

    async def _resolver_fake(sessionmaker, anime, versao, titulos_alternativos=None):
        return FonteResolvida(
            dominio="animefire.one",
            identificador="42",
            versao_da_fonte=VersaoDeFonte.NAO_DIFERENCIADA,
        )

    async def _listar_fake(sessionmaker, dominio, identificador, temporada=None):
        return [
            EpisodioRemoto(
                rotulo="1", numero=1, url="https://x/ep1", thumb_url="https://original/1.webp"
            ),
            EpisodioRemoto(
                rotulo="2", numero=2, url="https://x/ep2", thumb_url="https://original/2.webp"
            ),
            EpisodioRemoto(rotulo="especial", numero=None, url="https://x/ep-especial"),
        ]

    async def _info_fake(titulo, ano, numero, temporada):
        # TMDB só resolve o episódio 1 — o 2 cai pra arte do anime.
        return InfoDeEpisodio(still_url="https://tmdb/1.jpg") if numero == 1 else None

    monkeypatch.setattr("api.servicos.fontes.resolver_fonte_do_anime", _resolver_fake)
    monkeypatch.setattr("api.servicos.fontes.listar_episodios_em", _listar_fake)
    monkeypatch.setattr(
        "api.servicos.fontes.servico_metadados.buscar_info_de_episodio", _info_fake
    )

    resposta = await cliente.get(f"/api/admin/animes/{anime_id}/episodios-remotos")

    assert resposta.status_code == 200
    episodios = resposta.json()["episodios"]
    assert episodios[0]["thumb_url"] == "https://tmdb/1.jpg"
    assert episodios[1]["thumb_url"] == "https://tmdb.org/banner-do-anime.jpg"
    assert episodios[2]["thumb_url"] == "https://tmdb.org/banner-do-anime.jpg"


async def test_listar_episodios_remotos_still_de_temporada_irma_pede_por_numero_absoluto(
    cliente: AsyncClient,
    sessionmaker_api: _SessionMaker,
    monkeypatch: pytest.MonkeyPatch,
):
    """Overlay de still da T2+ de uma franquia: tenta primeiro o par DIRETO
    (`numero`, `numero_temporada`); só quando o TMDB não tem essa temporada
    separada (franquia "achatada" numa season só) é que cai pro número
    ABSOLUTO (`offset das irmãs + numero`, `temporada=None`). Offset = soma de
    `total_episodios_anilist` das irmãs com temporada menor."""
    async with sessionmaker_api() as sessao:
        sessao.add(
            Anime(
                titulo="Franquia T1",
                slug="franquia-t1",
                serie_ancora=999,
                numero_temporada=1,
                total_episodios_anilist=24,
            )
        )
        t2 = Anime(
            titulo="Franquia T2", slug="franquia-t2", serie_ancora=999, numero_temporada=2
        )
        sessao.add(t2)
        await sessao.commit()
        t2_id = t2.id

    async def _resolver_fake(sessionmaker, anime, versao, titulos_alternativos=None):
        return FonteResolvida(
            dominio="animefire.one",
            identificador="7",
            versao_da_fonte=VersaoDeFonte.NAO_DIFERENCIADA,
        )

    async def _listar_fake(sessionmaker, dominio, identificador, temporada=None):
        return [
            EpisodioRemoto(rotulo="1", numero=1, url="https://x/ep1", thumb_url="https://o/1.webp"),
            EpisodioRemoto(rotulo="2", numero=2, url="https://x/ep2", thumb_url="https://o/2.webp"),
        ]

    chamadas: list[tuple] = []

    async def _info_fake(titulo, ano, numero, temporada):
        chamadas.append((numero, temporada))
        # Simula o TMDB SEM a temporada 2 separada (franquia achatada): o
        # direto (`temporada=2`) vem vazio, só o absoluto resolve.
        if temporada is not None:
            return None
        return InfoDeEpisodio(still_url=f"https://tmdb/{numero}.jpg")

    monkeypatch.setattr("api.servicos.fontes.resolver_fonte_do_anime", _resolver_fake)
    monkeypatch.setattr("api.servicos.fontes.listar_episodios_em", _listar_fake)
    monkeypatch.setattr(
        "api.servicos.fontes.servico_metadados.buscar_info_de_episodio", _info_fake
    )

    resposta = await cliente.get(f"/api/admin/animes/{t2_id}/episodios-remotos")

    assert resposta.status_code == 200
    assert sorted(chamadas) == [(1, 2), (2, 2), (25, None), (26, None)]
    episodios = resposta.json()["episodios"]
    assert episodios[0]["thumb_url"] == "https://tmdb/25.jpg"
    assert episodios[1]["thumb_url"] == "https://tmdb/26.jpg"


async def test_listar_episodios_remotos_still_direto_nunca_cai_pro_absoluto_com_offset_incompleto(
    cliente: AsyncClient,
    sessionmaker_api: _SessionMaker,
    monkeypatch: pytest.MonkeyPatch,
):
    """Regressão do bug real (anime 22, Tensei Slime T4): quando o TMDB TEM a
    temporada em separado, o overlay usa o par DIRETO e NUNCA tenta o
    absoluto — mesmo quando haveria `offset_de_temporada` > 0 a calcular (irmã
    catalogada com `numero_temporada` menor). Antes desta fatia, toda
    temporada > 1 com offset ia direto pro absoluto; se uma irmã ANTERIOR
    ainda não estivesse catalogada (comum: só as temporadas recentes de uma
    franquia longa costumam estar no catálogo), o offset saía sub-contado e a
    still vinha de outro episódio — real, mas do lugar errado da série."""
    async with sessionmaker_api() as sessao:
        # Só a temporada 3 catalogada como irmã — a 1ª/2ª (que também
        # existiriam numa franquia real) estão AUSENTES, deixando o offset
        # sub-contado de propósito (mesma situação do anime 22 em produção).
        sessao.add(
            Anime(
                titulo="Franquia T3",
                slug="franquia-t3",
                serie_ancora=777,
                numero_temporada=3,
                total_episodios_anilist=24,
            )
        )
        t4 = Anime(
            titulo="Franquia T4", slug="franquia-t4", serie_ancora=777, numero_temporada=4
        )
        sessao.add(t4)
        await sessao.commit()
        t4_id = t4.id

    async def _resolver_fake(sessionmaker, anime, versao, titulos_alternativos=None):
        return FonteResolvida(
            dominio="animefire.one",
            identificador="7",
            versao_da_fonte=VersaoDeFonte.NAO_DIFERENCIADA,
        )

    async def _listar_fake(sessionmaker, dominio, identificador, temporada=None):
        return [EpisodioRemoto(rotulo="1", numero=1, url="https://x/ep1")]

    chamadas: list[tuple] = []

    async def _info_fake(titulo, ano, numero, temporada):
        chamadas.append((numero, temporada))
        # TMDB TEM a temporada 4 em separado — resolve de cara no direto.
        if temporada is None:
            return None
        return InfoDeEpisodio(still_url=f"https://tmdb/temporada{temporada}-ep{numero}.jpg")

    monkeypatch.setattr("api.servicos.fontes.resolver_fonte_do_anime", _resolver_fake)
    monkeypatch.setattr("api.servicos.fontes.listar_episodios_em", _listar_fake)
    monkeypatch.setattr(
        "api.servicos.fontes.servico_metadados.buscar_info_de_episodio", _info_fake
    )

    resposta = await cliente.get(f"/api/admin/animes/{t4_id}/episodios-remotos")

    assert resposta.status_code == 200
    # Só o par direto foi tentado — nunca o absoluto (que, com offset=24 em
    # vez do correto, teria pedido o episódio 25 e trazido a still errada).
    assert chamadas == [(1, 4)]
    assert resposta.json()["episodios"][0]["thumb_url"] == "https://tmdb/temporada4-ep1.jpg"


# --- detector de episódios novos: api/servicos/lancamentos.py ---


def _anime_em_memoria(**campos) -> Anime:
    return Anime(titulo="X", slug="x", **campos)


def _futuro() -> datetime:
    return datetime.now(UTC) + timedelta(days=1)


def test_episodios_novos_conta_acima_da_fronteira_acompanhada():
    anime = _anime_em_memoria(
        status_lancamento=StatusLancamento.EM_LANCAMENTO,
        episodios_na_fonte=5,
    )
    # fonte no ep 5, usuário acompanhou até o ep 3 -> 2 novos
    assert episodios_novos(anime, maior_capturado=3) == 2


def test_episodios_novos_ignora_buraco_abaixo_da_fronteira():
    # regressão: usuário foi direto ao ep 4 (eps 1-3 nunca capturados); a fonte
    # tem 4 eps -> fronteira 4, badge 0 (contagem de capturados daria 3)
    anime = _anime_em_memoria(
        status_lancamento=StatusLancamento.EM_LANCAMENTO,
        episodios_na_fonte=4,
    )
    assert episodios_novos(anime, maior_capturado=4) == 0


def test_episodios_novos_sem_captura_conta_a_fonte_inteira():
    anime = _anime_em_memoria(
        status_lancamento=StatusLancamento.EM_LANCAMENTO,
        episodios_na_fonte=6,
    )
    assert episodios_novos(anime, maior_capturado=0) == 6


def test_episodios_novos_zero_para_status_diferente_de_em_lancamento():
    anime = _anime_em_memoria(
        status_lancamento=StatusLancamento.FINALIZADO, episodios_na_fonte=12
    )
    assert episodios_novos(anime, maior_capturado=0) == 0


def test_episodios_novos_conta_na_janela_pos_fim_de_finalizado_incompleto():
    # a AniList já fechou o status, mas o fansub ainda sobe o último episódio:
    # a fonte tem 11 de 12 e o usuário parou no 10 -> 1 novo
    anime = _anime_em_memoria(
        status_lancamento=StatusLancamento.FINALIZADO,
        estreia_em=date.today() - timedelta(weeks=12),
        total_episodios_anilist=12,
        episodios_na_fonte=11,
    )
    assert episodios_novos(anime, maior_capturado=10) == 1


def test_episodios_novos_zero_para_finalizado_incompleto_fora_da_janela_pos_fim():
    # 12 de 13 há anos (especial contado no total): arquivo, nunca badge
    anime = _anime_em_memoria(
        status_lancamento=StatusLancamento.FINALIZADO,
        estreia_em=date(2015, 1, 9),
        total_episodios_anilist=13,
        episodios_na_fonte=12,
    )
    assert episodios_novos(anime, maior_capturado=0) == 0


def test_episodios_novos_zero_quando_contagem_da_fonte_nula():
    anime = _anime_em_memoria(
        status_lancamento=StatusLancamento.EM_LANCAMENTO,
        episodios_na_fonte=None,
    )
    assert episodios_novos(anime, maior_capturado=0) == 0


def test_episodios_novos_zero_quando_status_lancamento_nulo():
    # `None is not EM_LANCAMENTO` -> 0, mesmo com a contagem da fonte conhecida e
    # `proximo_ep_em` no futuro (que antes fazia o `None` passar pela perna 1)
    anime = _anime_em_memoria(
        status_lancamento=None, episodios_na_fonte=6, proximo_ep_em=_futuro()
    )
    assert episodios_novos(anime, maior_capturado=0) == 0


def test_episodios_novos_nao_fica_negativo():
    # fonte largou episódios antigos: episodios_na_fonte abaixo da fronteira
    anime = _anime_em_memoria(
        status_lancamento=StatusLancamento.EM_LANCAMENTO,
        episodios_na_fonte=3,
    )
    assert episodios_novos(anime, maior_capturado=5) == 0


def test_episodios_novos_em_lancamento_sem_dados_anilist_conta_a_fonte():
    # caso Hanaori-san (id 19): `EM_LANCAMENTO` sem `anilist_id` /
    # `total_episodios_anilist` / `proximo_ep_em`. A sub-trava de sinal-vivo
    # (removida) zerava o badge; agora só a fronteira `MAX(numero)` decide.
    anime = _anime_em_memoria(
        status_lancamento=StatusLancamento.EM_LANCAMENTO,
        anilist_id=None,
        total_episodios_anilist=None,
        proximo_ep_em=None,
        episodios_na_fonte=8,
    )
    assert episodios_novos(anime, maior_capturado=6) == 2


# --- detector de episódios novos: fronteira em lote + GET /api/animes ---


async def _criar_anime_catalogado(
    sessionmaker: _SessionMaker,
    titulo: str,
    *,
    status_lancamento: StatusLancamento | None = None,
    episodios_na_fonte: int | None = None,
    fonte_verificada_em: datetime | None = None,
    proximo_ep_em: datetime | None = None,
    estreia_em: date | None = None,
    generos: list[str] | None = None,
    formato_midia: str | None = None,
    serie_ancora: int | None = None,
    numero_temporada: int | None = None,
) -> int:
    async with sessionmaker() as sessao:
        anime = Anime(
            titulo=titulo,
            slug=titulo.lower().replace(" ", "-"),
            formato_midia=formato_midia,
            serie_ancora=serie_ancora,
            numero_temporada=numero_temporada,
            status_lancamento=status_lancamento,
            episodios_na_fonte=episodios_na_fonte,
            fonte_verificada_em=fonte_verificada_em,
            proximo_ep_em=proximo_ep_em,
            estreia_em=estreia_em,
            generos=generos,
        )
        sessao.add(anime)
        await sessao.commit()
        return anime.id


async def _mapear_fonte(
    sessionmaker: _SessionMaker,
    anime_id: int,
    *,
    dominio: str = "site.io",
    versao: VersaoDeFonte = VersaoDeFonte.LEGENDADO,
) -> None:
    async with sessionmaker() as sessao:
        sessao.add(
            FonteAnime(
                anime_id=anime_id,
                site_dominio=dominio,
                versao=versao,
                identificador_no_site="id-no-site",
                prioridade=0,
            )
        )
        await sessao.commit()


def _ep_remoto(rotulo: str, numero: int | None) -> EpisodioRemoto:
    return EpisodioRemoto(rotulo=rotulo, numero=numero, url=f"https://x/{rotulo}")


async def _drenar_sondagens() -> None:
    """Aguarda toda `Task` de sondagem fire-and-forget em voo terminar. `gather`
    sem `return_exceptions`: re-levanta se `_sondar_e_persistir` deixar escapar
    exceção."""
    for _ in range(20):
        pendentes = [t for t in sondagem._sondagens_em_voo.values() if not t.done()]
        if not pendentes:
            break
        await asyncio.gather(*pendentes)
    await asyncio.sleep(0)


async def _capturar_episodio(
    sessionmaker: _SessionMaker,
    anime_id: int,
    *,
    numero: int,
    tipo: TipoEpisodio = TipoEpisodio.REGULAR,
    versao: VersaoEpisodio = VersaoEpisodio.LEGENDADO,
    status: StatusEpisodio = StatusEpisodio.PRONTO,
) -> None:
    async with sessionmaker() as sessao:
        sessao.add(
            Episodio(
                anime_id=anime_id,
                numero=numero,
                tipo=tipo,
                versao=versao,
                url_fonte="/x.mkv",
                site_origem="local",
                status=status,
            )
        )
        await sessao.commit()


async def test_maior_numero_capturado_por_anime_ignora_versao_tipo_e_status(
    sessionmaker_api: _SessionMaker,
):
    anime_id = await _criar_anime_catalogado(sessionmaker_api, "Anime Fronteira")
    # ep 1 legendado + dublado: duas linhas, mesma fronteira
    await _capturar_episodio(sessionmaker_api, anime_id, numero=1, versao=VersaoEpisodio.LEGENDADO)
    await _capturar_episodio(sessionmaker_api, anime_id, numero=1, versao=VersaoEpisodio.DUBLADO)
    await _capturar_episodio(sessionmaker_api, anime_id, numero=2)
    # ep 3 nunca capturado (buraco); ep 4 LIBERADO leva a fronteira a 4
    await _capturar_episodio(sessionmaker_api, anime_id, numero=4, status=StatusEpisodio.LIBERADO)
    # ep 5 só PENDENTE: não é captura utilizável, não move a fronteira
    await _capturar_episodio(sessionmaker_api, anime_id, numero=5, status=StatusEpisodio.PENDENTE)
    # OVA de número maior não conta (numeração própria)
    await _capturar_episodio(sessionmaker_api, anime_id, numero=9, tipo=TipoEpisodio.OVA)

    async with sessionmaker_api() as sessao:
        fronteira = await maior_numero_capturado_por_anime(sessao, [anime_id])

    assert fronteira == {anime_id: 4}  # maior numero REGULAR PRONTO/LIBERADO


async def test_maior_numero_capturado_por_anime_lista_vazia(sessionmaker_api: _SessionMaker):
    async with sessionmaker_api() as sessao:
        assert await maior_numero_capturado_por_anime(sessao, []) == {}


async def test_maior_numero_capturado_por_anime_id_ausente_e_zero(sessionmaker_api: _SessionMaker):
    anime_id = await _criar_anime_catalogado(sessionmaker_api, "Anime Sem Episodio")

    async with sessionmaker_api() as sessao:
        fronteira = await maior_numero_capturado_por_anime(sessao, [anime_id])

    assert fronteira == {}


# --- rótulo de estreia do card de bookmark: catalogo.ids_com_episodios ---


async def test_ids_com_episodios_lista_vazia_devolve_set_vazio(sessionmaker_api: _SessionMaker):
    # Guard de lista vazia (`IN ()` inválido no SQLite): retorna antes de tocar
    # o banco.
    async with sessionmaker_api() as sessao:
        assert await ids_com_episodios(sessao, []) == set()


async def test_ids_com_episodios_conta_qualquer_linha_sem_filtrar_status(
    sessionmaker_api: _SessionMaker,
):
    # Ao contrário de `maior_numero_capturado_por_anime`, não filtra tipo/status:
    # uma captura só `PENDENTE` conta como "tem episódio".
    com_pendente = await _criar_anime_catalogado(sessionmaker_api, "Anime Pendente Cru")
    com_pronto = await _criar_anime_catalogado(sessionmaker_api, "Anime Pronto Cru")
    sem_nada = await _criar_anime_catalogado(sessionmaker_api, "Anime Sem Nada Cru")

    await _capturar_episodio(
        sessionmaker_api, com_pendente, numero=1, status=StatusEpisodio.PENDENTE
    )
    await _capturar_episodio(sessionmaker_api, com_pronto, numero=1)

    async with sessionmaker_api() as sessao:
        resultado = await ids_com_episodios(sessao, [com_pendente, com_pronto, sem_nada])

    assert resultado == {com_pendente, com_pronto}


async def test_listar_animes_calcula_episodios_novos_por_anime_em_uma_resposta(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker
):
    em_lancamento = await _criar_anime_catalogado(
        sessionmaker_api,
        "Anime Em Lancamento",
        status_lancamento=StatusLancamento.EM_LANCAMENTO,
        episodios_na_fonte=4,
        proximo_ep_em=_futuro(),
    )
    finalizado = await _criar_anime_catalogado(
        sessionmaker_api,
        "Anime Finalizado",
        status_lancamento=StatusLancamento.FINALIZADO,
        episodios_na_fonte=8,
    )
    await _capturar_episodio(sessionmaker_api, em_lancamento, numero=1)
    await _capturar_episodio(
        sessionmaker_api, em_lancamento, numero=1, versao=VersaoEpisodio.DUBLADO
    )
    await _capturar_episodio(sessionmaker_api, em_lancamento, numero=2)

    resposta = await cliente.get("/api/animes")

    assert resposta.status_code == 200
    por_id = {item["id"]: item for item in resposta.json()}
    assert por_id[em_lancamento]["episodios_novos"] == 2  # 4 na fonte, fronteira no ep 2
    assert por_id[em_lancamento]["status_lancamento"] == "em_lancamento"
    assert por_id[finalizado]["episodios_novos"] == 0  # status != EM_LANCAMENTO
    assert por_id[finalizado]["status_lancamento"] == "finalizado"


async def test_listar_animes_badge_zero_quando_usuario_pulou_episodios_antigos(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker
):
    """Regressão: usuário foi direto ao ep 4 (eps 1-3 nunca capturados). A fonte
    tem 4 eps -> badge 0, não 3 (a contagem de capturados daria 3)."""
    anime_id = await _criar_anime_catalogado(
        sessionmaker_api,
        "Anime Pulou Antigos",
        status_lancamento=StatusLancamento.EM_LANCAMENTO,
        episodios_na_fonte=4,
        proximo_ep_em=_futuro(),
    )
    await _capturar_episodio(sessionmaker_api, anime_id, numero=4)

    resposta = await cliente.get("/api/animes")

    assert resposta.status_code == 200
    item = next(i for i in resposta.json() if i["id"] == anime_id)
    assert item["episodios_novos"] == 0


async def test_listar_animes_preserva_campos_e_defaults_sem_lancamento(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker
):
    anime_id = await _criar_anime_catalogado(sessionmaker_api, "Anime Sem Lancamento")

    resposta = await cliente.get("/api/animes")

    assert resposta.status_code == 200
    item = next(i for i in resposta.json() if i["id"] == anime_id)
    assert item["slug"] == "anime-sem-lancamento"
    assert item["titulo"] == "Anime Sem Lancamento"
    assert "capa_path" in item
    assert "criado_em" in item
    assert item["status_lancamento"] is None
    assert item["episodios_novos"] == 0


async def test_listar_animes_expoe_generos_e_preserva_null_sem_metadado(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker
):
    """`generos` sai 1:1 da coluna homônima (nullable) em `GET /api/animes` —
    alimenta o filtro por gênero da Galeria. Anime sem o metadado ainda (coluna
    NULL) não pode quebrar a resposta: precisa sair `None`, não `[]`."""
    com_generos = await _criar_anime_catalogado(
        sessionmaker_api, "Anime Com Generos", generos=["Action", "Comedy"]
    )
    sem_generos = await _criar_anime_catalogado(sessionmaker_api, "Anime Sem Generos")

    resposta = await cliente.get("/api/animes")

    assert resposta.status_code == 200
    por_id = {item["id"]: item for item in resposta.json()}
    assert por_id[com_generos]["generos"] == ["Action", "Comedy"]
    assert por_id[sem_generos]["generos"] is None


async def test_listar_animes_expoe_tem_episodios_e_proximo_ep_em_numa_resposta(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker
):
    """`tem_episodios` conta QUALQUER linha de `Episodio` (rótulo de estreia do
    card de bookmark) — sem o filtro tipo/status de `maior_numero_capturado`: um
    episódio só `PENDENTE` (captura em andamento) e um episódio `numero=0` — as
    duas armadilhas — contam. `proximo_ep_em` sai serializado 1:1 da coluna
    homônima (ISO string), ou `None` quando ausente, na mesma resposta."""
    quando = datetime(2027, 1, 15, 12, 0, tzinfo=UTC)
    so_pendente = await _criar_anime_catalogado(
        sessionmaker_api, "Anime So Pendente", proximo_ep_em=quando
    )
    sem_episodio = await _criar_anime_catalogado(sessionmaker_api, "Anime Sem Episodio Algum")
    so_numero_zero = await _criar_anime_catalogado(sessionmaker_api, "Anime So Numero Zero")

    await _capturar_episodio(
        sessionmaker_api, so_pendente, numero=1, status=StatusEpisodio.PENDENTE
    )
    await _capturar_episodio(sessionmaker_api, so_numero_zero, numero=0)

    resposta = await cliente.get("/api/animes")

    assert resposta.status_code == 200
    por_id = {item["id"]: item for item in resposta.json()}

    assert por_id[so_pendente]["tem_episodios"] is True
    proximo_ep_em_bruto = por_id[so_pendente]["proximo_ep_em"]
    assert proximo_ep_em_bruto is not None
    assert datetime.fromisoformat(proximo_ep_em_bruto) == quando

    assert por_id[sem_episodio]["tem_episodios"] is False
    assert por_id[sem_episodio]["proximo_ep_em"] is None

    assert por_id[so_numero_zero]["tem_episodios"] is True


async def test_listar_animes_expoe_estreia_em_de_bookmark_nao_lancado(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker
):
    """Bookmark de "Próximas estreias" (`NAO_LANCADO`, sem `proximo_ep_em` ainda)
    com `estreia_em` no futuro: a coluna sai serializada 1:1 (ISO `YYYY-MM-DD`)
    em `GET /api/animes` para o card de bookmark montar o rótulo de data exata."""
    estreia = date(2027, 4, 15)
    com_estreia = await _criar_anime_catalogado(
        sessionmaker_api,
        "Anime Com Estreia",
        status_lancamento=StatusLancamento.NAO_LANCADO,
        estreia_em=estreia,
    )
    sem_estreia = await _criar_anime_catalogado(sessionmaker_api, "Anime Sem Estreia Col")

    resposta = await cliente.get("/api/animes")

    assert resposta.status_code == 200
    por_id = {item["id"]: item for item in resposta.json()}
    assert por_id[com_estreia]["estreia_em"] == "2027-04-15"
    assert por_id[sem_estreia]["estreia_em"] is None


async def test_listar_animes_mostra_ona_orfao_mas_esconde_quando_a_franquia_tem_temporada_tv(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker
):
    """Série que a AniList classifica como ONA (T1 de Hitoribocchi) sem nenhuma
    temporada TV catalogada na franquia aparece na grade; com a T2 TV da mesma
    âncora catalogada, ela passa a se agrupar nela (some como card solto)."""
    ona = await _criar_anime_catalogado(
        sessionmaker_api, "Serie Ona", formato_midia="ONA", serie_ancora=900
    )
    avulso = await _criar_anime_catalogado(sessionmaker_api, "Avulso Normal")

    ids = {item["id"] for item in (await cliente.get("/api/animes")).json()}
    assert ids == {ona, avulso}

    sequencia = await _criar_anime_catalogado(
        sessionmaker_api, "Sequencia Tv", serie_ancora=900
    )
    ids = {item["id"] for item in (await cliente.get("/api/animes")).json()}
    assert ids == {sequencia, avulso}


async def test_ancora_de_midia_so_ancora_e_nao_puxa_a_serie_mae(
    monkeypatch: pytest.MonkeyPatch, sessionmaker_api: _SessionMaker
):
    """Extra (filme/OVA/especial) recebe só `serie_ancora` — não materializa a
    franquia da série-mãe nem vira temporada numerada."""
    from api.servicos import descoberta

    async def _ancora(anilist_id: int) -> int:
        return 900

    async def _materializar(*_args) -> None:
        raise AssertionError("extra não materializa a franquia")

    monkeypatch.setattr(descoberta.servico, "resolver_ancora_de_midia", _ancora)
    monkeypatch.setattr(descoberta, "_materializar_temporadas_irmas", _materializar)
    anime_id = await _criar_anime_catalogado(
        sessionmaker_api, "Midia Qualquer", formato_midia="MOVIE"
    )

    await descoberta._aplicar_ancora_de_midia(sessionmaker_api, anime_id, 173, "MOVIE")

    async with sessionmaker_api() as sessao:
        anime = await sessao.get(Anime, anime_id)
    assert (anime.serie_ancora, anime.formato_midia, anime.numero_temporada) == (
        900,
        "MOVIE",
        None,
    )


@pytest.mark.parametrize(
    ("formato_declarado", "formato_persistido"), [("ONA", "ONA"), (None, None)]
)
async def test_serie_criada_sem_formato_e_rebaixada_so_quando_a_aresta_pai_aparece(
    monkeypatch: pytest.MonkeyPatch,
    sessionmaker_api: _SessionMaker,
    formato_declarado: str | None,
    formato_persistido: str | None,
):
    """O feed não traz relações: ONA com `PARENT` nasce série (`formato` `None`) e
    o 2º estágio (`formato_se_extra`) o rebaixa a extra, zera `numero_temporada`
    e ancora na série-mãe. Sem `PARENT` segue série intocada."""
    from api.servicos import descoberta

    async def _formato_se_extra(anilist_id: int) -> str | None:
        return formato_declarado

    async def _ancora(anilist_id: int) -> int:
        return 900

    async def _serie(anilist_id: int):
        return None

    monkeypatch.setattr(descoberta.servico, "formato_se_extra", _formato_se_extra)
    monkeypatch.setattr(descoberta.servico, "resolver_ancora_de_midia", _ancora)
    monkeypatch.setattr(descoberta.servico, "resolver_serie", _serie)
    anime_id = await _criar_anime_catalogado(
        sessionmaker_api, "Ona Com Pai", numero_temporada=1
    )

    await descoberta._resolver_e_aplicar_serie(sessionmaker_api, anime_id, "Ona Com Pai", 173)

    async with sessionmaker_api() as sessao:
        anime = await sessao.get(Anime, anime_id)
    assert anime.formato_midia == formato_persistido
    if formato_declarado is None:
        assert anime.numero_temporada == 1
    else:
        assert (anime.numero_temporada, anime.serie_ancora) == (None, 900)


@pytest.mark.parametrize(
    ("formato_atual", "serie", "desfecho", "formato_final", "ancora_final"),
    [
        ("ONA", True, "promovido", None, 700),  # catálogo antigo: ONA série nascia extra
        (None, False, "rebaixado", "ONA", 900),  # PARENT perdido num 429 na criação
        ("ONA", False, None, "ONA", 555),  # já extra: intocado
        (None, True, None, None, 555),  # já série: intocado
    ],
)
async def test_reclassificar_midia_promove_rebaixa_ou_nao_mexe(
    monkeypatch: pytest.MonkeyPatch,
    sessionmaker_api: _SessionMaker,
    formato_atual: str | None,
    serie: bool,
    desfecho: str | None,
    formato_final: str | None,
    ancora_final: int,
):
    from api.servicos import descoberta
    from integrations.servico import SerieResolvida

    async def _ancora_do_pai(anilist_id: int) -> int:
        return 900

    async def _serie(anilist_id: int):
        return SerieResolvida(ancora=700, ordinal=1)

    async def _sem_franquia(anilist_id: int) -> list:
        return []

    async def _sem_extra(anilist_id: int) -> None:
        return None

    monkeypatch.setattr(descoberta.servico, "resolver_ancora_de_midia", _ancora_do_pai)
    monkeypatch.setattr(descoberta.servico, "resolver_serie", _serie)
    monkeypatch.setattr(descoberta.servico, "resolver_franquia", _sem_franquia)
    monkeypatch.setattr(descoberta.servico, "formato_se_extra", _sem_extra)
    anime_id = await _criar_anime_catalogado(
        sessionmaker_api, "Reclassificavel", formato_midia=formato_atual, serie_ancora=555
    )

    resultado = await descoberta.reclassificar_midia(
        sessionmaker_api,
        anime_id,
        "Reclassificavel",
        173,
        formato_atual=formato_atual,
        formato="ONA",
        serie=serie,
    )

    async with sessionmaker_api() as sessao:
        anime = await sessao.get(Anime, anime_id)
    assert resultado == desfecho
    assert (anime.formato_midia, anime.serie_ancora) == (formato_final, ancora_final)
    if desfecho == "promovido":
        assert anime.numero_temporada == 1


async def test_reparo_automatico_so_pega_serie_sem_ancora_respeita_teto_e_cooldown(
    monkeypatch: pytest.MonkeyPatch, sessionmaker_api: _SessionMaker
):
    """Candidato = série (`formato_midia` nulo) com `anilist_id` e `serie_ancora`
    nulo — a assinatura de criação que a AniList derrubou no meio. Extra, anime já
    ancorado e anime sem `anilist_id` ficam de fora; no máximo 2 por lote; e a
    tentativa recente entra em cooldown."""
    from api.servicos import descoberta

    chamadas: list[int] = []

    async def _reparo(_sessionmaker, anime_id: int, _titulo: str, _anilist_id: int) -> None:
        chamadas.append(anime_id)

    monkeypatch.setattr(descoberta, "_resolver_e_aplicar_serie", _reparo)

    async def _criar(titulo: str, **campos) -> Anime:
        anime_id = await _criar_anime_catalogado(sessionmaker_api, titulo, **campos)
        async with sessionmaker_api() as sessao:
            anime = await sessao.get(Anime, anime_id)
            anime.anilist_id = campos.pop("anilist_id", 100 + anime_id)
            await sessao.commit()
            await sessao.refresh(anime)
            return anime

    pendentes = [await _criar(f"Pendente {i}") for i in range(3)]
    ja_ancorado = await _criar("Ja Ancorado", serie_ancora=1)
    extra = await _criar("Extra", formato_midia="MOVIE")
    sem_anilist = await _criar_anime_catalogado(sessionmaker_api, "Sem Anilist")
    async with sessionmaker_api() as sessao:
        sem_anilist_obj = await sessao.get(Anime, sem_anilist)
        todos = [*pendentes, ja_ancorado, extra, sem_anilist_obj]

    descoberta.agendar_reparos_de_classificacao(sessionmaker_api, todos)
    await asyncio.gather(*descoberta._reparos_de_classificacao_em_voo.values())

    assert chamadas == [pendentes[0].id, pendentes[1].id]  # teto de 2, só os candidatos

    descoberta.agendar_reparos_de_classificacao(sessionmaker_api, todos)
    await asyncio.gather(*descoberta._reparos_de_classificacao_em_voo.values())

    # 1ª e 2ª estão em cooldown; entra a 3ª. Ninguém repete.
    assert chamadas == [pendentes[0].id, pendentes[1].id, pendentes[2].id]


@pytest.mark.parametrize(
    ("estreia_em", "ano", "prevista"),
    [
        (date(2999, 1, 1), None, True),  # data futura
        (date(2000, 1, 1), None, False),  # data passada
        (None, 2999, True),  # só o ano, no futuro
        (None, 2000, False),  # só o ano, no passado
        (None, None, True),  # Hitoribocchi 2nd Season: sem data nem ano → "em breve"
    ],
)
def test_proxima_temporada_prevista_inclui_a_que_nao_tem_data_nem_ano(
    estreia_em: date | None, ano: int | None, prevista: bool
):
    from types import SimpleNamespace

    from api.rotas.animes import _temporadas_e_proxima

    def _linha(id_: int, numero: int, **campos):
        base = {
            "id": id_,
            "numero_temporada": numero,
            "titulo": f"T{numero}",
            "status_lancamento": StatusLancamento.FINALIZADO,
            "estreia_em": None,
            "ano": None,
            "formato_midia": None,
            "total_episodios_anilist": None,
            "tem_episodios": True,
        }
        return SimpleNamespace(**{**base, **campos})

    grupo = [
        _linha(1, 1),
        _linha(
            2,
            2,
            status_lancamento=StatusLancamento.NAO_LANCADO,
            estreia_em=estreia_em,
            ano=ano,
            tem_episodios=False,
        ),
    ]

    _, proxima = _temporadas_e_proxima(1, 1, grupo)

    assert (proxima is not None) is prevista
    if prevista:
        assert (proxima.id, proxima.estreia_em, proxima.ano) == (2, estreia_em, ano)


async def test_obter_anime_detalhe_expoe_status_lancamento_mas_nunca_o_badge(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker
):
    anime_id = await _criar_anime_catalogado(
        sessionmaker_api,
        "Anime Detalhe Status",
        status_lancamento=StatusLancamento.EM_LANCAMENTO,
        episodios_na_fonte=3,
    )
    await _capturar_episodio(sessionmaker_api, anime_id, numero=1)

    resposta = await cliente.get(f"/api/animes/{anime_id}")

    assert resposta.status_code == 200
    assert resposta.json()["status_lancamento"] == "em_lancamento"
    # `episodios_novos` é badge só da galeria (`GET /api/animes`) — o detalhe
    # nunca expõe, mesmo no estado que na galeria daria badge 2.
    assert "episodios_novos" not in resposta.json()


async def test_obter_anime_detalhe_expoe_banner_e_capa_cor(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker
):
    async with sessionmaker_api() as sessao:
        anime = Anime(
            titulo="Anime Com Hero",
            slug="anime-com-hero",
            banner_path="https://img/banner.jpg",
            capa_cor="#e4a15d",
        )
        sessao.add(anime)
        await sessao.commit()
        anime_id = anime.id

    resposta = await cliente.get(f"/api/animes/{anime_id}")

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["banner_path"] == "https://img/banner.jpg"
    assert corpo["capa_cor"] == "#e4a15d"


async def test_obter_anime_detalhe_banner_e_capa_cor_null_por_padrao(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker
):
    anime_id = await _criar_anime_catalogado(sessionmaker_api, "Anime Sem Hero")

    resposta = await cliente.get(f"/api/animes/{anime_id}")

    assert resposta.status_code == 200
    assert resposta.json()["banner_path"] is None
    assert resposta.json()["capa_cor"] is None


async def test_obter_anime_detalhe_expoe_generos(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker
):
    async with sessionmaker_api() as sessao:
        anime = Anime(
            titulo="Anime Com Generos",
            slug="anime-com-generos",
            generos=["Action", "Comedy"],
        )
        sessao.add(anime)
        await sessao.commit()
        anime_id = anime.id

    resposta = await cliente.get(f"/api/animes/{anime_id}")

    assert resposta.status_code == 200
    assert resposta.json()["generos"] == ["Action", "Comedy"]


async def test_obter_anime_detalhe_generos_lista_vazia_por_padrao(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker
):
    anime_id = await _criar_anime_catalogado(sessionmaker_api, "Anime Sem Generos")

    resposta = await cliente.get(f"/api/animes/{anime_id}")

    assert resposta.status_code == 200
    assert resposta.json()["generos"] == []


async def test_em_alta_nao_expoe_o_badge_episodios_novos(
    cliente: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """`episodios_novos` é badge derivado só da galeria (`GET /api/animes`) — o
    feed "em alta" nunca o expõe. `status_lancamento` (e o resto do trio de
    lançamento), ao contrário, entrou no feed a partir da B2 para a tagline do
    carrossel; aqui o item não traz bloco, então sai `null`."""
    item = AnimeEmAlta(
        titulo_romaji="Em Alta",
        titulo_ingles=None,
        capa_url=None,
        banner_url=None,
        anilist_id=1,
    )

    async def _listar_fake(sessionmaker):
        return [(item, None)]

    monkeypatch.setattr("api.servicos.descoberta.listar_em_alta_com_catalogo", _listar_fake)

    resposta = await cliente.get("/api/animes/em-alta")

    assert resposta.status_code == 200
    corpo = resposta.json()[0]
    assert "episodios_novos" not in corpo
    assert corpo["status_lancamento"] is None


async def test_proxima_temporada_shape_e_ordem_de_rotas(
    cliente: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """`GET /api/animes/proxima-temporada` resolve para a rota do feed (não é
    lido como `anime_id="proxima-temporada"` por `/{anime_id}`) e devolve o
    shape de `AnimeEmAltaSaida`."""
    item = AnimeEmAlta(
        titulo_romaji="Próxima Estreia",
        titulo_ingles="Next Premiere",
        capa_url="https://img/p.jpg",
        banner_url=None,
        anilist_id=1,
        capa_cor="#e4a15d",
    )

    async def _listar_fake(sessionmaker):
        return [(item, None)]

    monkeypatch.setattr(
        "api.servicos.descoberta.listar_proxima_temporada_com_catalogo", _listar_fake
    )

    resposta = await cliente.get("/api/animes/proxima-temporada")

    assert resposta.status_code == 200
    corpo = resposta.json()[0]
    assert corpo == {
        "titulo_romaji": "Próxima Estreia",
        "titulo_ingles": "Next Premiere",
        "capa_url": "https://img/p.jpg",
        "banner_url": None,
        "anilist_id": 1,
        "anime_id": None,
        "ano_estreia": None,
        "generos": [],
        "capa_cor": "#e4a15d",
        "status_lancamento": None,
        "proximo_ep_numero": None,
        "proximo_ep_em": None,
        "total_episodios": None,
        "sinopse": None,
        "formato": None,
        "episodio_lancado": None,
        "episodio_lancado_em": None,
        "banner_com_titulo_url": None,
    }


# --- F12: GET /api/animes agenda sondagem fire-and-forget da fonte real, opt-in
# via `?aquecer=true` (só a Galeria manda a flag; a Home chama sem ela) ---


async def test_listar_animes_so_agenda_carona_de_aquecimento_com_a_flag(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker, monkeypatch: pytest.MonkeyPatch
):
    """A carona fire-and-forget (sondagem da fonte real + aquecimento de
    `status_lancamento` via AniList/Kitsu) é opt-in via `?aquecer=true` — só a
    Galeria a envia. Sem a flag, `GET /api/animes` devolve o catálogo e nada
    mais: a Home não paga esse custo a cada abertura."""
    sondagens: list[int] = []
    refreshs: list[int] = []
    monkeypatch.setattr(
        "api.servicos.sondagem.agendar_sondagens",
        lambda sessionmaker, animes, versoes, **_: sondagens.append(len(animes)),
    )
    monkeypatch.setattr(
        "api.servicos.descoberta.agendar_refreshs_do_catalogo",
        lambda sessionmaker, animes: refreshs.append(len(animes)),
    )
    await _criar_anime_catalogado(
        sessionmaker_api,
        "Anime Aquecivel",
        status_lancamento=StatusLancamento.EM_LANCAMENTO,
    )

    sem_flag = await cliente.get("/api/animes")
    assert sem_flag.status_code == 200
    assert sondagens == []
    assert refreshs == []

    com_flag = await cliente.get("/api/animes?aquecer=true")
    assert com_flag.status_code == 200
    assert sondagens == [1]
    assert refreshs == [1]


def _espiar_sondagem(
    monkeypatch: pytest.MonkeyPatch,
    *,
    episodios: list[EpisodioRemoto] | None = None,
    dominio: str = "animefire.one",
    erro: Exception | None = None,
) -> list[tuple[int, VersaoEpisodio]]:
    """Troca `sondagem.resolver_e_listar` por um espião: registra
    `(anime.id, versao)` e devolve um resultado fixo (ou levanta `erro`) — nunca
    toca extractor/rede real."""
    chamadas: list[tuple[int, VersaoEpisodio]] = []

    async def _fake(sessionmaker, anime, versao, *, resolver_canonico, tentar_fontes_alternativas):
        chamadas.append((anime.id, versao))
        if erro is not None:
            raise erro
        return FonteComEpisodios(
            dominio=dominio,
            identificador="stub",
            versao_da_fonte=VersaoDeFonte.NAO_DIFERENCIADA,
            episodios=episodios or [],
        )

    monkeypatch.setattr("api.servicos.sondagem.resolver_e_listar", _fake)
    return chamadas


async def test_listar_animes_agenda_sondagem_e_badge_atualiza_na_proxima_leitura(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker, monkeypatch: pytest.MonkeyPatch
):
    chamadas = _espiar_sondagem(
        monkeypatch, episodios=[_ep_remoto("1", 1), _ep_remoto("2", 2), _ep_remoto("3", 3)]
    )
    anime_id = await _criar_anime_catalogado(
        sessionmaker_api,
        "Anime Sondavel",
        status_lancamento=StatusLancamento.EM_LANCAMENTO,
        episodios_na_fonte=1,
        proximo_ep_em=_futuro(),
    )
    await _mapear_fonte(sessionmaker_api, anime_id)
    await _capturar_episodio(sessionmaker_api, anime_id, numero=1)

    primeira = await cliente.get("/api/animes?aquecer=true")
    assert primeira.status_code == 200
    item = next(i for i in primeira.json() if i["id"] == anime_id)
    assert item["episodios_novos"] == 0  # badge desta leitura: 1 na fonte, fronteira no ep 1

    await _drenar_sondagens()
    assert chamadas == [(anime_id, VersaoEpisodio.LEGENDADO)]
    async with sessionmaker_api() as sessao:
        anime = await sessao.get(Anime, anime_id)
        assert anime.episodios_na_fonte == 3
        assert anime.fonte_verificada_dominio == "animefire.one"

    segunda = await cliente.get("/api/animes?aquecer=true")
    item = next(i for i in segunda.json() if i["id"] == anime_id)
    assert item["episodios_novos"] == 2  # 3 na fonte, fronteira no ep 1


async def test_listar_animes_nao_agenda_sondagem_dentro_do_ttl(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker, monkeypatch: pytest.MonkeyPatch
):
    chamadas = _espiar_sondagem(monkeypatch)
    anime_id = await _criar_anime_catalogado(
        sessionmaker_api,
        "Anime Fonte Fresca",
        status_lancamento=StatusLancamento.EM_LANCAMENTO,
        episodios_na_fonte=2,
        fonte_verificada_em=datetime.now(UTC) - timedelta(minutes=10),
    )
    await _mapear_fonte(sessionmaker_api, anime_id)

    resposta = await cliente.get("/api/animes?aquecer=true")
    await _drenar_sondagens()

    assert resposta.status_code == 200
    assert chamadas == []


async def test_listar_animes_responde_200_com_badge_antigo_quando_sondagem_falha(
    cliente: AsyncClient,
    sessionmaker_api: _SessionMaker,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    _espiar_sondagem(monkeypatch, erro=FalhaDeExtracao("site fora do ar"))
    anime_id = await _criar_anime_catalogado(
        sessionmaker_api,
        "Anime Home Blindada",
        status_lancamento=StatusLancamento.EM_LANCAMENTO,
        episodios_na_fonte=5,
        proximo_ep_em=_futuro(),
    )
    await _mapear_fonte(sessionmaker_api, anime_id)

    with caplog.at_level("WARNING"):
        resposta = await cliente.get("/api/animes?aquecer=true")
        assert resposta.status_code == 200
        item = next(i for i in resposta.json() if i["id"] == anime_id)
        assert item["episodios_novos"] == 5  # badge antigo; falha de site não derruba a home
        await _drenar_sondagens()  # gather sem return_exceptions: re-levantaria se propagasse

    assert "sondagem de fonte falhou" in caplog.text
    async with sessionmaker_api() as sessao:
        anime = await sessao.get(Anime, anime_id)
        assert anime.episodios_na_fonte == 5  # intacto
        assert anime.fonte_verificada_em is None


async def test_listar_animes_duas_chamadas_concorrentes_deduplicam_sondagem(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker, monkeypatch: pytest.MonkeyPatch
):
    chamadas = _espiar_sondagem(monkeypatch)
    anime_id = await _criar_anime_catalogado(
        sessionmaker_api, "Anime Dedupe Rota", status_lancamento=StatusLancamento.EM_LANCAMENTO
    )
    await _mapear_fonte(sessionmaker_api, anime_id)

    await asyncio.gather(
        cliente.get("/api/animes?aquecer=true"), cliente.get("/api/animes?aquecer=true")
    )
    await _drenar_sondagens()

    assert chamadas == [(anime_id, VersaoEpisodio.LEGENDADO)]  # 1 task, não 2


async def test_obter_anime_sem_linha_em_fonte_anime_nao_agenda_sondagem(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker, monkeypatch: pytest.MonkeyPatch
):
    chamadas = _espiar_sondagem(monkeypatch)
    anime_id = await _criar_anime_catalogado(
        sessionmaker_api,
        "Anime Detalhe Sem Fonte",
        status_lancamento=StatusLancamento.EM_LANCAMENTO,
        episodios_na_fonte=3,
    )

    resposta = await cliente.get(f"/api/animes/{anime_id}")
    await _drenar_sondagens()

    assert resposta.status_code == 200
    assert chamadas == []
    assert sondagem._sondagens_em_voo == {}


@pytest.mark.parametrize("campo", ["capa_url", "banner_url"])
@pytest.mark.parametrize("url", ["javascript:alert(1)", "data:text/html;base64,AAAA", "file:///etc/passwd"])
async def test_criar_anime_com_url_de_imagem_fora_de_http_422(
    cliente: AsyncClient, campo: str, url: str
):
    resposta = await cliente.post("/api/admin/animes", json={"titulo": "Anime X", campo: url})

    assert resposta.status_code == 422


async def test_confirmar_fonte_dominio_desconhecido_422(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker
):
    anime_id = await _criar_anime(sessionmaker_api, "Anime Dominio Estranho")

    resposta = await cliente.post(
        f"/api/admin/animes/{anime_id}/fontes/confirmar",
        json={
            "dominio": "evil.example",
            "identificador": "42",
            "titulo_exibicao": "X",
            "url": "https://evil.example/anime/42",
        },
    )

    assert resposta.status_code == 422


@pytest.mark.parametrize(
    "identificador", ["../admin", "42?ep=1", "42#x", "a b", "a\\b", "x/../y", "..", "42\n"]
)
async def test_confirmar_fonte_identificador_com_caracteres_de_url_422(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker, identificador: str
):
    anime_id = await _criar_anime(sessionmaker_api, "Anime Identificador Estranho")

    resposta = await cliente.post(
        f"/api/admin/animes/{anime_id}/fontes/confirmar",
        json={
            "dominio": "animefire.one",
            "identificador": identificador,
            "titulo_exibicao": "X",
            "url": "https://animefire.one/anime/42",
        },
    )

    assert resposta.status_code == 422


async def test_confirmar_fonte_sem_marcador_textual_confia_no_cliente(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker
):
    """AnimeFire diferencia versão por um campo à parte da API (`audio`), sem
    marcador no slug/título (`fontes/adaptadores/animefire.py::_resultados_do_item`) —
    `inferir_versao(titulo_exibicao, identificador)` nunca encontra nada pra
    ele. Regressão do bug reportado: confirmar 'Dublado' voltava sempre
    'Legendado' porque o servidor rederivava e caía no default silencioso.
    `identificador`/`titulo_exibicao` aqui deliberadamente não carregam
    nenhum marcador — é exatamente o caso do AnimeFire."""
    anime_id = await _criar_anime(sessionmaker_api, "Anime Sem Marcador")

    resposta = await cliente.post(
        f"/api/admin/animes/{anime_id}/fontes/confirmar",
        json={
            "dominio": "animefire.one",
            "identificador": "42",
            "titulo_exibicao": "One Piece",
            "url": "https://animefire.one/anime/42",
            "versao": "dublado",
        },
    )

    assert resposta.status_code == 200
    async with sessionmaker_api() as sessao:
        fonte = (
            await sessao.execute(
                select(FonteAnime).where(
                    FonteAnime.anime_id == anime_id, FonteAnime.site_dominio == "animefire.one"
                )
            )
        ).scalar_one()
    assert fonte.versao == VersaoDeFonte.DUBLADO


async def test_listar_episodios_remotos_tenta_titulo_ingles_quando_tmdb_nao_acha_o_romaji(
    cliente: AsyncClient,
    sessionmaker_api: _SessionMaker,
    monkeypatch: pytest.MonkeyPatch,
):
    """Série que o TMDB só indexa pelo nome inglês ("Above Myriads", não o romaji
    "Wan Ren Zhi Shang"): o still/nome sai pelo `titulo_ingles` em vez de todo
    episódio cair no banner do anime."""
    async with sessionmaker_api() as sessao:
        anime = Anime(
            titulo="Wan Ren Zhi Shang",
            titulo_ingles="Above Myriads",
            slug="wan-ren-zhi-shang",
            banner_path="https://tmdb.org/banner-do-anime.jpg",
        )
        sessao.add(anime)
        await sessao.commit()
        anime_id = anime.id

    async def _resolver_fake(sessionmaker, anime, versao, titulos_alternativos=None):
        return FonteResolvida(
            dominio="meusanimes",
            identificador="42",
            versao_da_fonte=VersaoDeFonte.NAO_DIFERENCIADA,
        )

    async def _listar_fake(sessionmaker, dominio, identificador, temporada=None):
        return [EpisodioRemoto(rotulo="1", numero=1, url="https://x/ep1")]

    titulos_buscados: list[str] = []

    async def _info_fake(titulo, ano, numero, temporada):
        titulos_buscados.append(titulo)
        return InfoDeEpisodio(still_url="https://tmdb/1.jpg") if titulo == "Above Myriads" else None

    monkeypatch.setattr("api.servicos.fontes.resolver_fonte_do_anime", _resolver_fake)
    monkeypatch.setattr("api.servicos.fontes.listar_episodios_em", _listar_fake)
    monkeypatch.setattr(
        "api.servicos.fontes.servico_metadados.buscar_info_de_episodio", _info_fake
    )

    resposta = await cliente.get(f"/api/admin/animes/{anime_id}/episodios-remotos")

    assert resposta.status_code == 200
    assert resposta.json()["episodios"][0]["thumb_url"] == "https://tmdb/1.jpg"
    assert titulos_buscados == ["Wan Ren Zhi Shang", "Above Myriads"]


async def test_listar_episodios_remotos_atualiza_texto_gravado_so_com_ptbr_real(
    cliente: AsyncClient,
    sessionmaker_api: _SessionMaker,
    monkeypatch: pytest.MonkeyPatch,
):
    """Write-back em `Episodio.titulo`/`sinopse`: pt-BR de verdade substitui o
    gravado (ep 1: inglês de fallback antigo -> pt-BR); nome em fallback só
    preenche vazio e nunca regride um texto melhor já gravado (ep 2 mantém a
    tradução, ep 3 vazio recebe o inglês)."""
    async with sessionmaker_api() as sessao:
        anime = Anime(titulo="Anime Writeback", slug="anime-writeback")
        sessao.add(anime)
        await sessao.flush()
        for numero, titulo in ((1, "English One"), (2, "Tradução Boa"), (3, None)):
            sessao.add(
                Episodio(
                    anime_id=anime.id,
                    numero=numero,
                    titulo=titulo,
                    tipo=TipoEpisodio.REGULAR,
                    versao=VersaoEpisodio.LEGENDADO,
                    url_fonte=f"https://x/ep{numero}",
                    site_origem="animefire.one",
                    status=StatusEpisodio.LIBERADO,
                )
            )
        await sessao.commit()
        anime_id = anime.id

    async def _resolver_fake(sessionmaker, anime, versao, titulos_alternativos=None):
        return FonteResolvida(
            dominio="animefire.one",
            identificador="42",
            versao_da_fonte=VersaoDeFonte.NAO_DIFERENCIADA,
        )

    async def _listar_fake(sessionmaker, dominio, identificador, temporada=None):
        return [
            EpisodioRemoto(rotulo=str(n), numero=n, url=f"https://x/ep{n}") for n in (1, 2, 3)
        ]

    async def _info_fake(titulo, ano, numero, temporada):
        if numero == 1:
            return InfoDeEpisodio(still_url=None, nome="Um em PT")
        return InfoDeEpisodio(still_url=None, nome=f"English {numero}", nome_em_fallback=True)

    monkeypatch.setattr("api.servicos.fontes.resolver_fonte_do_anime", _resolver_fake)
    monkeypatch.setattr("api.servicos.fontes.listar_episodios_em", _listar_fake)
    monkeypatch.setattr(
        "api.servicos.fontes.servico_metadados.buscar_info_de_episodio", _info_fake
    )

    resposta = await cliente.get(f"/api/admin/animes/{anime_id}/episodios-remotos")

    assert resposta.status_code == 200
    async with sessionmaker_api() as sessao:
        titulos = dict(
            (await sessao.execute(
                select(Episodio.numero, Episodio.titulo).where(Episodio.anime_id == anime_id)
            )).all()
        )
    assert titulos == {1: "Um em PT", 2: "Tradução Boa", 3: "English 3"}

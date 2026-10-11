"""Feature "continuar assistindo": `api/servicos/progresso.py::listar_continuar_assistindo`
(inclusão/exclusão por status e pelo limiar de 90%) e as rotas
`GET /api/episodios/continuar-assistindo`, `GET /api/episodios/{id}` e
`POST /api/episodios/{id}/progresso` (`api/rotas/episodios.py`)."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.servicos import progresso as servico_progresso
from api.servicos.lancamentos import primeiras_em_lancamento, temporadas_novas_apos_concluida
from api.servicos.progresso import listar_continuar_assistindo
from core.enums import StatusEpisodio, StatusLancamento, TipoEpisodio, VersaoDeFonte, VersaoEpisodio
from models.anime import Anime
from models.episodio import Episodio
from models.fonte_anime import FonteAnime

_SessionMaker = async_sessionmaker[AsyncSession]


async def _criar_anime(
    sessionmaker: _SessionMaker, titulo: str, *, capa_path: str | None = None
) -> int:
    slug = titulo.lower().replace(" ", "-")
    async with sessionmaker() as sessao:
        anime = Anime(titulo=titulo, slug=slug, capa_path=capa_path)
        sessao.add(anime)
        await sessao.commit()
        return anime.id


async def _criar_episodio(
    sessionmaker: _SessionMaker,
    anime_id: int,
    *,
    numero: int = 1,
    status: StatusEpisodio = StatusEpisodio.PRONTO,
    duracao_s: int | None = 1200,
    progresso_s: int | None = None,
    progresso_atualizado_em: datetime | None = None,
    capa_path: str | None = None,
) -> int:
    async with sessionmaker() as sessao:
        episodio = Episodio(
            anime_id=anime_id,
            numero=numero,
            tipo=TipoEpisodio.REGULAR,
            versao=VersaoEpisodio.LEGENDADO,
            url_fonte="/qualquer.mkv",
            site_origem="local",
            status=status,
            hls_path="qualquer/master.m3u8" if status == StatusEpisodio.PRONTO else None,
            duracao_s=duracao_s,
            progresso_s=progresso_s,
            progresso_atualizado_em=progresso_atualizado_em,
            capa_path=capa_path,
        )
        sessao.add(episodio)
        await sessao.commit()
        return episodio.id


# --- api/servicos/progresso.py::listar_continuar_assistindo ---


async def test_listar_continuar_assistindo_inclui_pronto_com_progresso_abaixo_do_limiar(
    sessionmaker_api: _SessionMaker,
):
    anime_id = await _criar_anime(sessionmaker_api, "Anime Continuar")
    episodio_id = await _criar_episodio(
        sessionmaker_api,
        anime_id,
        duracao_s=1200,
        progresso_s=600,
        progresso_atualizado_em=datetime.now(UTC),
    )

    linhas = (await listar_continuar_assistindo(sessionmaker_api)).itens

    assert [linha.episodio_id for linha in linhas] == [episodio_id]


async def test_listar_continuar_assistindo_inclui_capturado_pronto_sem_progresso(
    sessionmaker_api: _SessionMaker,
):
    # Captura concluída e ainda nem assistida: a prateleira é extensão da página
    # do anime, então o episódio pronto já aparece (sem barra de progresso).
    anime_id = await _criar_anime(sessionmaker_api, "Anime Recem Capturado")
    episodio_id = await _criar_episodio(sessionmaker_api, anime_id, progresso_s=None)

    linhas = (await listar_continuar_assistindo(sessionmaker_api)).itens

    assert [(linha.episodio_id, linha.variante, linha.progresso_s) for linha in linhas] == [
        (episodio_id, "pronto", None)
    ]


async def test_listar_continuar_assistindo_inclui_captura_em_andamento_como_processando(
    sessionmaker_api: _SessionMaker,
):
    anime_id = await _criar_anime(sessionmaker_api, "Anime Capturando")
    await _criar_episodio(sessionmaker_api, anime_id, status=StatusEpisodio.PENDENTE)

    linhas = (await listar_continuar_assistindo(sessionmaker_api)).itens

    assert [linha.variante for linha in linhas] == ["processando"]


async def test_listar_continuar_assistindo_sem_assistido_usa_o_menor_numero_disponivel(
    sessionmaker_api: _SessionMaker,
):
    anime_id = await _criar_anime(sessionmaker_api, "Anime Varios Capturados")
    await _criar_episodio(sessionmaker_api, anime_id, numero=3)
    primeiro_id = await _criar_episodio(sessionmaker_api, anime_id, numero=2)

    linhas = (await listar_continuar_assistindo(sessionmaker_api)).itens

    assert [(linha.numero, linha.episodio_id) for linha in linhas] == [(2, primeiro_id)]


async def test_listar_continuar_assistindo_exclui_status_diferente_de_pronto(
    sessionmaker_api: _SessionMaker,
):
    anime_id = await _criar_anime(sessionmaker_api, "Anime Liberado")
    await _criar_episodio(
        sessionmaker_api,
        anime_id,
        status=StatusEpisodio.LIBERADO,
        progresso_s=300,
        progresso_atualizado_em=datetime.now(UTC),
    )

    linhas = (await listar_continuar_assistindo(sessionmaker_api)).itens

    assert linhas == []


async def test_listar_continuar_assistindo_exclui_acima_do_limiar_de_90_pct(
    sessionmaker_api: _SessionMaker,
):
    anime_id = await _criar_anime(sessionmaker_api, "Anime Quase Terminado")
    await _criar_episodio(
        sessionmaker_api,
        anime_id,
        duracao_s=1200,
        progresso_s=1100,  # 91.6% — acima do limiar
        progresso_atualizado_em=datetime.now(UTC),
    )

    linhas = (await listar_continuar_assistindo(sessionmaker_api)).itens

    assert linhas == []


async def test_listar_continuar_assistindo_inclui_sem_duracao_conhecida(
    sessionmaker_api: _SessionMaker,
):
    anime_id = await _criar_anime(sessionmaker_api, "Anime Sem Duracao")
    episodio_id = await _criar_episodio(
        sessionmaker_api,
        anime_id,
        duracao_s=None,
        progresso_s=600,
        progresso_atualizado_em=datetime.now(UTC),
    )

    linhas = (await listar_continuar_assistindo(sessionmaker_api)).itens

    assert [linha.episodio_id for linha in linhas] == [episodio_id]


async def test_listar_continuar_assistindo_um_item_por_anime_o_mais_recente(
    sessionmaker_api: _SessionMaker,
):
    """Desenho novo (2026-09-18, extensão do catálogo/página do anime pedida
    pelo usuário): um card por ANIME, não por episódio — dois episódios do
    mesmo anime com progresso salvo rendem só o mais recente, nunca os dois."""
    anime_id = await _criar_anime(sessionmaker_api, "Anime Ordenacao")
    agora = datetime.now(UTC)
    await _criar_episodio(
        sessionmaker_api,
        anime_id,
        numero=1,
        progresso_s=100,
        progresso_atualizado_em=agora - timedelta(hours=1),
    )
    mais_recente_id = await _criar_episodio(
        sessionmaker_api, anime_id, numero=2, progresso_s=100, progresso_atualizado_em=agora
    )

    linhas = (await listar_continuar_assistindo(sessionmaker_api)).itens

    assert [linha.episodio_id for linha in linhas] == [mais_recente_id]


# --- temporada nova de franquia (continuação) ---


def _linha_de_franquia(id_: int, numero_temporada: int | None, **extra) -> SimpleNamespace:
    base = dict(
        id=id_,
        numero_temporada=numero_temporada,
        formato_midia=None,
        tem_episodios=False,
        status_lancamento=StatusLancamento.EM_LANCAMENTO,
    )
    return SimpleNamespace(**{**base, **extra})


def _grupos(*linhas: SimpleNamespace) -> dict[int, list]:
    grupo = list(linhas)
    return {linha.id: grupo for linha in linhas}


def test_temporada_nova_so_a_imediatamente_posterior_a_concluida():
    t1 = _linha_de_franquia(1, 1, tem_episodios=True)
    t2 = _linha_de_franquia(2, 2)
    t3 = _linha_de_franquia(3, 3)

    assert temporadas_novas_apos_concluida(_grupos(t1, t2, t3), {1}) == {2: 1}


def test_temporada_nova_exige_anterior_concluida():
    t1 = _linha_de_franquia(1, 1, tem_episodios=True)
    t2 = _linha_de_franquia(2, 2)

    assert temporadas_novas_apos_concluida(_grupos(t1, t2), set()) == {}


def test_temporada_nova_ignora_nao_lancada_com_episodio_e_midia_avulsa():
    t1 = _linha_de_franquia(1, 1, tem_episodios=True)
    nao_lancada = _linha_de_franquia(2, 2, status_lancamento=StatusLancamento.NAO_LANCADO)
    assert temporadas_novas_apos_concluida(_grupos(t1, nao_lancada), {1}) == {}

    ja_capturada = _linha_de_franquia(2, 2, tem_episodios=True)
    assert temporadas_novas_apos_concluida(_grupos(t1, ja_capturada), {1}) == {}

    filme = _linha_de_franquia(2, None, formato_midia="MOVIE")
    assert temporadas_novas_apos_concluida(_grupos(t1, filme), {1}) == {}


def test_primeira_em_lancamento_so_a_primeira_tv_sem_episodio_local():
    solo = _linha_de_franquia(1, 1)
    assert primeiras_em_lancamento(_grupos(solo)) == {1}

    t1 = _linha_de_franquia(1, 1)
    t2 = _linha_de_franquia(2, 2)
    assert primeiras_em_lancamento(_grupos(t1, t2)) == {1}

    com_episodio = _linha_de_franquia(1, 1, tem_episodios=True)
    assert primeiras_em_lancamento(_grupos(com_episodio, t2)) == set()

    finalizada = _linha_de_franquia(1, 1, status_lancamento=StatusLancamento.FINALIZADO)
    assert primeiras_em_lancamento(_grupos(finalizada)) == set()

    nao_lancada = _linha_de_franquia(1, 1, status_lancamento=StatusLancamento.NAO_LANCADO)
    assert primeiras_em_lancamento(_grupos(nao_lancada)) == set()

    filme = _linha_de_franquia(1, None, formato_midia="MOVIE")
    assert primeiras_em_lancamento(_grupos(filme)) == set()


async def test_listar_continuar_assistindo_inclui_primeira_temporada_em_lancamento(
    sessionmaker_api: _SessionMaker,
):
    agora = datetime.now(UTC)
    async with sessionmaker_api() as sessao:
        anime = Anime(
            titulo="Recem Estreado", slug="recem-estreado", numero_temporada=1,
            episodios_na_fonte=1, fonte_verificada_em=agora,
            status_lancamento=StatusLancamento.EM_LANCAMENTO,
        )
        sessao.add(anime)
        await sessao.flush()
        sessao.add(
            FonteAnime(
                anime_id=anime.id, site_dominio="exemplo.com", versao=VersaoDeFonte.LEGENDADO,
                identificador_no_site="recem", resolvido_em=agora,
            )
        )
        await sessao.commit()
        anime_id = anime.id

    linhas = (await listar_continuar_assistindo(sessionmaker_api)).itens

    assert [
        (linha.anime_id, linha.numero, linha.variante, linha.episodio_id, linha.episodio_novo)
        for linha in linhas
    ] == [(anime_id, 1, "capturavel", None, True)]


async def test_primeira_em_lancamento_ordena_pela_fonte_confirmada_nao_pela_criacao(
    sessionmaker_api: _SessionMaker,
):
    agora = datetime.now(UTC)
    async with sessionmaker_api() as sessao:
        antigo = Anime(
            titulo="Adicionado Faz Tempo", slug="adicionado-faz-tempo", numero_temporada=1,
            episodios_na_fonte=1, fonte_verificada_em=agora,
            criado_em=agora - timedelta(days=30),
            status_lancamento=StatusLancamento.EM_LANCAMENTO,
        )
        em_andamento = Anime(
            titulo="Em Andamento", slug="em-andamento", numero_temporada=1,
            status_lancamento=StatusLancamento.FINALIZADO,
        )
        sessao.add_all([antigo, em_andamento])
        await sessao.flush()
        sessao.add(
            FonteAnime(
                anime_id=antigo.id, site_dominio="exemplo.com", versao=VersaoDeFonte.LEGENDADO,
                identificador_no_site="antigo", resolvido_em=agora,
            )
        )
        sessao.add(
            Episodio(
                anime_id=em_andamento.id, numero=1, tipo=TipoEpisodio.REGULAR,
                versao=VersaoEpisodio.LEGENDADO, url_fonte="/y.mkv", site_origem="local",
                status=StatusEpisodio.PRONTO, hls_path="y/master.m3u8", duracao_s=1200,
                progresso_s=300, progresso_atualizado_em=agora - timedelta(days=1),
            )
        )
        await sessao.commit()
        antigo_id, em_andamento_id = antigo.id, em_andamento.id

    linhas = (await listar_continuar_assistindo(sessionmaker_api)).itens

    assert [linha.anime_id for linha in linhas] == [antigo_id, em_andamento_id]


async def _criar_franquia_com_t1_concluida(
    sessionmaker: _SessionMaker, *, com_fonte_na_t2: bool
) -> tuple[int, int]:
    agora = datetime.now(UTC)
    async with sessionmaker() as sessao:
        t1 = Anime(
            titulo="Serie", slug="serie", serie_ancora=100, numero_temporada=1,
            episodios_na_fonte=1, status_lancamento=StatusLancamento.FINALIZADO,
        )
        t2 = Anime(
            titulo="Serie Continuacao", slug="serie-continuacao", serie_ancora=100,
            numero_temporada=2, episodios_na_fonte=3, fonte_verificada_em=agora,
            status_lancamento=StatusLancamento.EM_LANCAMENTO,
        )
        sessao.add_all([t1, t2])
        await sessao.flush()
        if com_fonte_na_t2:
            sessao.add(
                FonteAnime(
                    anime_id=t2.id, site_dominio="exemplo.com", versao=VersaoDeFonte.LEGENDADO,
                    identificador_no_site="serie-2", resolvido_em=agora,
                )
            )
        sessao.add(
            Episodio(
                anime_id=t1.id, numero=1, tipo=TipoEpisodio.REGULAR,
                versao=VersaoEpisodio.LEGENDADO, url_fonte="/x.mkv", site_origem="local",
                status=StatusEpisodio.PRONTO, hls_path="x/master.m3u8", duracao_s=1200,
                assistido_em=agora,
            )
        )
        await sessao.commit()
        return t1.id, t2.id


async def test_listar_continuar_assistindo_inclui_temporada_nova_da_franquia_concluida(
    sessionmaker_api: _SessionMaker,
):
    _, t2_id = await _criar_franquia_com_t1_concluida(sessionmaker_api, com_fonte_na_t2=True)

    linhas = (await listar_continuar_assistindo(sessionmaker_api)).itens

    assert [
        (linha.anime_id, linha.numero, linha.variante, linha.episodio_id, linha.episodio_novo)
        for linha in linhas
    ] == [(t2_id, 1, "capturavel", None, True)]


async def test_listar_continuar_assistindo_agenda_reparo_de_fonte_da_temporada_nova(
    sessionmaker_api: _SessionMaker, monkeypatch
):
    _, t2_id = await _criar_franquia_com_t1_concluida(sessionmaker_api, com_fonte_na_t2=False)
    chamadas = []
    monkeypatch.setattr(
        servico_progresso.servico_sondagem,
        "agendar_sondagens",
        lambda *args, **kwargs: chamadas.append((args, kwargs)),
    )

    linhas = (await listar_continuar_assistindo(sessionmaker_api)).itens

    # Sem fonte mapeada ainda: não vira card, mas a sondagem de reparo é pedida
    # (com palpite de versão herdado da T1) para a próxima leitura já achar.
    assert linhas == []
    (args, kwargs), = chamadas
    assert args[2][t2_id] == VersaoEpisodio.LEGENDADO
    assert kwargs["ignorar_gate_de_status"] == frozenset({t2_id})


# --- GET /api/episodios/continuar-assistindo ---


async def test_rota_continuar_assistindo_devolve_itens_esperados(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker
):
    anime_id = await _criar_anime(sessionmaker_api, "Anime Rota Continuar")
    episodio_id = await _criar_episodio(
        sessionmaker_api,
        anime_id,
        numero=3,
        duracao_s=1200,
        progresso_s=600,
        progresso_atualizado_em=datetime.now(UTC),
    )

    resposta = await cliente.get("/api/episodios/continuar-assistindo")

    assert resposta.status_code == 200
    corpo = resposta.json()["itens"]
    assert len(corpo) == 1
    assert corpo[0]["episodio_id"] == episodio_id
    assert corpo[0]["anime_id"] == anime_id
    assert corpo[0]["numero"] == 3
    assert corpo[0]["progresso_s"] == 600
    assert corpo[0]["duracao_s"] == 1200


async def test_rota_continuar_assistindo_thumb_vem_do_episodio_nao_do_anime(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker
):
    anime_id = await _criar_anime(
        sessionmaker_api, "Anime Thumb", capa_path="https://img/capa-do-anime.jpg"
    )
    await _criar_episodio(
        sessionmaker_api,
        anime_id,
        progresso_s=600,
        progresso_atualizado_em=datetime.now(UTC),
        capa_path="https://img/thumb-do-episodio.jpg",
    )

    resposta = await cliente.get("/api/episodios/continuar-assistindo")

    assert resposta.status_code == 200
    corpo = resposta.json()["itens"]
    assert corpo[0]["thumb"] == "https://img/thumb-do-episodio.jpg"
    assert "capa_path" not in corpo[0]


# --- GET /api/episodios/{id} ---


async def test_obter_episodio_devolve_dados(cliente: AsyncClient, sessionmaker_api: _SessionMaker):
    anime_id = await _criar_anime(sessionmaker_api, "Anime Obter Episodio")
    episodio_id = await _criar_episodio(sessionmaker_api, anime_id, progresso_s=42)

    resposta = await cliente.get(f"/api/episodios/{episodio_id}")

    assert resposta.status_code == 200
    assert resposta.json()["id"] == episodio_id
    assert resposta.json()["progresso_s"] == 42


async def test_obter_episodio_inexistente_404(cliente: AsyncClient):
    resposta = await cliente.get("/api/episodios/999999")

    assert resposta.status_code == 404


# --- POST /api/episodios/{id}/progresso ---


async def test_salvar_progresso_grava(cliente: AsyncClient, sessionmaker_api: _SessionMaker):
    anime_id = await _criar_anime(sessionmaker_api, "Anime Salvar Progresso")
    episodio_id = await _criar_episodio(sessionmaker_api, anime_id, duracao_s=1200)

    resposta = await cliente.post(f"/api/episodios/{episodio_id}/progresso", json={"segundos": 300})

    assert resposta.status_code == 204
    async with sessionmaker_api() as sessao:
        episodio = await sessao.get(Episodio, episodio_id)
        assert episodio.progresso_s == 300
        assert episodio.progresso_atualizado_em is not None


async def test_salvar_progresso_recusa_acima_do_limiar(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker
):
    anime_id = await _criar_anime(sessionmaker_api, "Anime Progresso Acima")
    episodio_id = await _criar_episodio(sessionmaker_api, anime_id, duracao_s=1200)

    resposta = await cliente.post(
        f"/api/episodios/{episodio_id}/progresso", json={"segundos": 1100}
    )

    assert resposta.status_code == 422
    async with sessionmaker_api() as sessao:
        episodio = await sessao.get(Episodio, episodio_id)
        assert episodio.progresso_s is None


async def test_salvar_progresso_episodio_inexistente_404(cliente: AsyncClient):
    resposta = await cliente.post("/api/episodios/999999/progresso", json={"segundos": 10})

    assert resposta.status_code == 404


async def test_salvar_progresso_segundos_negativo_422(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker
):
    anime_id = await _criar_anime(sessionmaker_api, "Anime Progresso Negativo")
    episodio_id = await _criar_episodio(sessionmaker_api, anime_id)

    resposta = await cliente.post(f"/api/episodios/{episodio_id}/progresso", json={"segundos": -1})

    assert resposta.status_code == 422

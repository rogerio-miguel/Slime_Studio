"""Persistência dos feeds da Home entre reinícios da API (`api/servicos/cache_de_feeds.py`
+ ganchos de `integrations/servico.py`): feed persistido volta como cache "velho" —
servido na hora, revalidado em segundo plano — e falha de persistência nunca derruba o feed."""

import asyncio
from datetime import UTC, date, datetime, timedelta

import pytest

from api.main import criar_app
from api.servicos import cache_de_feeds
from core.enums import StatusLancamento
from integrations import servico
from integrations.base import AnimeEmAlta, LancamentoDeAnime
from models.cache_de_feed import CacheDeFeed


@pytest.fixture(autouse=True)
def _caches_de_feed_limpos(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(servico, "_cache_em_alta", None)
    monkeypatch.setattr(servico, "_cache_novos_lancamentos", None)
    monkeypatch.setattr(servico, "_cache_proxima_temporada", None)
    monkeypatch.setattr(servico, "_cache_fileiras_tematicas", {})
    monkeypatch.setattr(servico, "_tarefas_de_revalidacao_em_segundo_plano", set())


def _item(anilist_id: int, **extra) -> AnimeEmAlta:
    return AnimeEmAlta(
        titulo_romaji=f"Anime {anilist_id}",
        titulo_ingles=None,
        capa_url=f"https://exemplo.test/{anilist_id}.jpg",
        banner_url=None,
        anilist_id=anilist_id,
        **extra,
    )


async def _drenar_tarefas_em_segundo_plano() -> None:
    await asyncio.gather(*servico._tarefas_de_revalidacao_em_segundo_plano)


class _Persistencia:
    def __init__(self, erro: Exception | None = None) -> None:
        self.gravacoes: list[tuple[str, list[AnimeEmAlta]]] = []
        self._erro = erro

    async def __call__(self, chave: str, itens: list[AnimeEmAlta]) -> None:
        if self._erro is not None:
            raise self._erro
        self.gravacoes.append((chave, itens))


def _buscador_de(itens: list[AnimeEmAlta], liberacao: asyncio.Event | None = None):
    async def _buscar() -> list[AnimeEmAlta]:
        if liberacao is not None:
            await liberacao.wait()
        return itens

    return _buscar


async def test_round_trip_preserva_tipos_aninhados(app_pronto):
    sessionmaker = app_pronto.state.sessionmaker
    item = _item(
        7,
        generos=("Isekai", "Ação"),
        lancamento=LancamentoDeAnime(
            status=StatusLancamento.EM_LANCAMENTO,
            total_episodios=12,
            proximo_ep_numero=5,
            proximo_ep_em=datetime(2026, 10, 9, 15, 0, tzinfo=UTC),
            estreia_em=date(2026, 7, 4),
            ano_estreia=2026,
        ),
    )

    await cache_de_feeds.gravar_feed(sessionmaker, "em-alta", [item])
    await cache_de_feeds.gravar_feed(sessionmaker, "em-alta", [item, _item(8)])  # upsert

    feeds = await cache_de_feeds.carregar_feeds_persistidos(sessionmaker)

    assert feeds == {"em-alta": [item, _item(8)]}


async def test_carregar_descarta_feed_velho_e_ilegivel(app_pronto):
    sessionmaker = app_pronto.state.sessionmaker
    agora = datetime.now(UTC)
    await cache_de_feeds.gravar_feed(sessionmaker, "novos-lancamentos", [_item(1)])
    async with sessionmaker() as sessao, sessao.begin():
        sessao.add_all(
            [
                CacheDeFeed(
                    chave="em-alta",
                    itens_json="[]",
                    atualizado_em=agora - timedelta(days=8),
                ),
                CacheDeFeed(
                    chave="proxima-temporada",
                    itens_json='[{"formato": "incompativel"}]',
                    atualizado_em=agora,
                ),
            ]
        )

    feeds = await cache_de_feeds.carregar_feeds_persistidos(sessionmaker)

    assert list(feeds) == ["novos-lancamentos"]


async def test_feed_restaurado_e_servido_na_hora_e_revalidado_em_segundo_plano(
    monkeypatch: pytest.MonkeyPatch,
):
    persistencia = _Persistencia()
    servico.instalar_persistencia_de_feeds(persistencia)
    liberacao = asyncio.Event()
    velho, novo = _item(1), _item(2)
    monkeypatch.setattr(servico, "_buscar_em_alta_sem_cache", _buscador_de([novo], liberacao))
    servico.restaurar_feeds_persistidos({"em-alta": [velho]})

    # A busca real está presa em `liberacao`: se `listar_em_alta` esperasse por ela, travaria.
    assert await asyncio.wait_for(servico.listar_em_alta(), timeout=1) == [velho]

    liberacao.set()
    await _drenar_tarefas_em_segundo_plano()

    assert await servico.listar_em_alta() == [novo]
    assert persistencia.gravacoes == [("em-alta", [novo])]


async def test_cache_miss_persiste_o_feed_buscado(monkeypatch: pytest.MonkeyPatch):
    persistencia = _Persistencia()
    servico.instalar_persistencia_de_feeds(persistencia)
    itens = [_item(1)]
    monkeypatch.setattr(servico, "_buscar_novos_lancamentos_sem_cache", _buscador_de(itens))

    assert await servico.listar_novos_lancamentos() == itens
    await _drenar_tarefas_em_segundo_plano()

    assert persistencia.gravacoes == [("novos-lancamentos", itens)]


async def test_fileira_tematica_persiste_com_chave_prefixada(monkeypatch: pytest.MonkeyPatch):
    persistencia = _Persistencia()
    servico.instalar_persistencia_de_feeds(persistencia)
    chave = next(iter(servico._fileiras_por_chave))
    itens = [_item(1)]
    monkeypatch.setattr(
        servico, "_buscar_fileira_tematica_sem_cache", lambda fileira: _buscador_de(itens)()
    )

    await servico.listar_fileira_tematica(chave)
    await _drenar_tarefas_em_segundo_plano()

    assert persistencia.gravacoes == [(f"fileira:{chave}", itens)]


async def test_falha_ao_persistir_nao_derruba_o_feed(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    servico.instalar_persistencia_de_feeds(_Persistencia(erro=RuntimeError("banco ocupado")))
    itens = [_item(1)]
    monkeypatch.setattr(servico, "_buscar_proxima_temporada_sem_cache", _buscador_de(itens))

    assert await servico.listar_proxima_temporada() == itens
    await _drenar_tarefas_em_segundo_plano()

    assert "não foi possível persistir o feed 'proxima-temporada'" in caplog.text


def test_restaurar_ignora_chave_desconhecida_e_nao_sobrescreve_cache_preenchido(
    monkeypatch: pytest.MonkeyPatch,
):
    ja_la = (123.0, [_item(9)])
    monkeypatch.setattr(servico, "_cache_em_alta", ja_la)

    servico.restaurar_feeds_persistidos(
        {
            "em-alta": [_item(1)],
            "fileira:inexistente": [_item(2)],
            "lixo": [_item(3)],
        }
    )

    assert servico._cache_em_alta is ja_la
    assert servico._cache_fileiras_tematicas == {}


async def test_api_sobe_mesmo_sem_a_tabela_de_cache(config_api, caplog: pytest.LogCaptureFixture):
    """Banco ainda sem a migration `cache_de_feed`: avisa e segue, sem impedir o boot."""
    aplicativo = criar_app(config_api)

    async with aplicativo.router.lifespan_context(aplicativo):
        pass

    assert "cache de feeds não restaurado" in caplog.text

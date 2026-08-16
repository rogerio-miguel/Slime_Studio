"""Testes de `extractors/resolucao.py`, sem rede — `resiliencia.chamar` é
substituído por uma versão que chama a operação direto (sem `ClienteLeve`/
`cloudscraper`), e adapters falsos ficam em `resolucao.EXTRATORES` via
`monkeypatch`.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config import Config
from core.erros import FonteNaoEncontrada
from db.engine import criar_engine, criar_sessionmaker
from extractors import resiliencia, resolucao
from extractors.base import EpisodioRemoto, ExtratorDeSite, ResultadoBusca
from models.anime import Anime
from models.base import Base
from models.estado_site import EstadoSite
from models.fonte_anime import FonteAnime


class _ExtratorFalso(ExtratorDeSite):
    def __init__(
        self,
        dominio: str,
        *,
        candidatos: list[ResultadoBusca] | None = None,
        episodios: list[EpisodioRemoto] | None = None,
    ) -> None:
        self._dominio = dominio
        self._candidatos = candidatos or []
        self._episodios = episodios or []
        self.chamadas_buscar = 0

    @property
    def dominio(self) -> str:
        return self._dominio

    @property
    def exige_navegador(self) -> bool:
        return False

    def buscar(self, cliente, titulo):
        self.chamadas_buscar += 1
        return self._candidatos

    def listar_episodios(self, cliente, identificador):
        return self._episodios

    def resolver_midia(self, cliente, url_episodio):
        raise NotImplementedError


@pytest.fixture
async def sessionmaker(tmp_path: Path) -> async_sessionmaker[AsyncSession]:
    config = Config(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        media_root=tmp_path,
        raiz_repo=tmp_path,
        ffmpeg=Path("/usr/bin/ffmpeg"),
        ffprobe=Path("/usr/bin/ffprobe"),
        caminho_lock=tmp_path / "worker.lock",
    )
    engine = criar_engine(config)
    async with engine.begin() as conexao:
        await conexao.run_sync(Base.metadata.create_all)

    fabrica = criar_sessionmaker(engine)
    yield fabrica

    await engine.dispose()


@pytest.fixture(autouse=True)
def _resiliencia_sem_cliente_real(monkeypatch):
    """`operacao` chama direto, sem `ClienteLeve`/`cloudscraper` — os adapters
    falsos deste teste ignoram o `cliente` recebido."""

    async def _chamar_falso(sessionmaker, extrator, operacao, *, permitir_navegador=True):
        return operacao(None)

    monkeypatch.setattr(resiliencia, "chamar", _chamar_falso)


async def _criar_anime(fabrica, titulo: str) -> Anime:
    async with fabrica() as sessao:
        anime = Anime(titulo=titulo, slug=titulo.lower().replace(" ", "-"))
        sessao.add(anime)
        await sessao.commit()
        await sessao.refresh(anime)
        return anime


async def test_fonte_ja_mapeada_devolve_direto_sem_buscar(sessionmaker):
    anime = await _criar_anime(sessionmaker, "Slime Datta Ken")
    async with sessionmaker() as sessao:
        sessao.add(
            FonteAnime(
                anime_id=anime.id,
                site_dominio="animefire.io",
                identificador_no_site="slime-datta-ken",
                prioridade=0,
            )
        )
        await sessao.commit()

    resultado = await resolucao.resolver_fonte_do_anime(sessionmaker, anime)

    assert resultado == resolucao.FonteResolvida(
        dominio="animefire.io", identificador="slime-datta-ken"
    )


async def test_sem_mapeamento_um_candidato_resolve_e_grava(sessionmaker, monkeypatch):
    extrator = _ExtratorFalso(
        "animefire.io",
        candidatos=[
            ResultadoBusca(
                titulo_exibicao="Slime Datta Ken", identificador="slime", url="http://x/slime"
            )
        ],
    )
    monkeypatch.setattr(resolucao, "EXTRATORES", (extrator,))
    anime = await _criar_anime(sessionmaker, "Slime Datta Ken")

    resultado = await resolucao.resolver_fonte_do_anime(sessionmaker, anime)

    assert resultado == resolucao.FonteResolvida(dominio="animefire.io", identificador="slime")
    async with sessionmaker() as sessao:
        fonte = await sessao.get(FonteAnime, (anime.id, "animefire.io"))
        assert fonte is not None
        assert fonte.identificador_no_site == "slime"
        assert fonte.prioridade == 0


async def test_sem_resultado_no_primeiro_site_tenta_o_proximo(sessionmaker, monkeypatch):
    extrator_a = _ExtratorFalso("site-a.io", candidatos=[])
    extrator_b = _ExtratorFalso(
        "site-b.io",
        candidatos=[
            ResultadoBusca(titulo_exibicao="Slime Datta Ken", identificador="slime", url="x")
        ],
    )
    monkeypatch.setattr(resolucao, "EXTRATORES", (extrator_a, extrator_b))
    anime = await _criar_anime(sessionmaker, "Slime Datta Ken")

    resultado = await resolucao.resolver_fonte_do_anime(sessionmaker, anime)

    assert resultado == resolucao.FonteResolvida(dominio="site-b.io", identificador="slime")
    async with sessionmaker() as sessao:
        fonte = await sessao.get(FonteAnime, (anime.id, "site-b.io"))
        assert fonte.prioridade == 1


async def test_pula_site_em_cooldown(sessionmaker, monkeypatch):
    extrator_a = _ExtratorFalso(
        "site-a.io",
        candidatos=[ResultadoBusca(titulo_exibicao="X", identificador="a", url="x")],
    )
    extrator_b = _ExtratorFalso(
        "site-b.io",
        candidatos=[
            ResultadoBusca(titulo_exibicao="Slime Datta Ken", identificador="slime", url="x")
        ],
    )
    monkeypatch.setattr(resolucao, "EXTRATORES", (extrator_a, extrator_b))
    async with sessionmaker() as sessao:
        sessao.add(
            EstadoSite(
                site_dominio="site-a.io",
                falhas_consecutivas=3,
                cooldown_ate=datetime.now(UTC) + timedelta(hours=1),
            )
        )
        await sessao.commit()

    anime = await _criar_anime(sessionmaker, "Slime Datta Ken")

    resultado = await resolucao.resolver_fonte_do_anime(sessionmaker, anime)

    assert resultado == resolucao.FonteResolvida(dominio="site-b.io", identificador="slime")
    assert extrator_a.chamadas_buscar == 0


async def test_candidatos_ambiguos_devolve_confirmacao_necessaria(sessionmaker, monkeypatch):
    candidatos = [
        ResultadoBusca(titulo_exibicao="Slime Datta Ken", identificador="a", url="x"),
        ResultadoBusca(titulo_exibicao="Slime Datta Ken OVA", identificador="b", url="y"),
    ]
    extrator = _ExtratorFalso("animefire.io", candidatos=candidatos)
    monkeypatch.setattr(resolucao, "EXTRATORES", (extrator,))
    anime = await _criar_anime(sessionmaker, "Slime Datta Ke")  # não bate exato com nenhum

    resultado = await resolucao.resolver_fonte_do_anime(sessionmaker, anime)

    assert resultado == resolucao.ConfirmacaoNecessaria(
        dominio="animefire.io", candidatos=candidatos
    )


async def test_candidatos_com_match_exato_desambigua_automaticamente(sessionmaker, monkeypatch):
    candidatos = [
        ResultadoBusca(titulo_exibicao="Slime Datta Ken OVA", identificador="ova", url="y"),
        ResultadoBusca(titulo_exibicao="Slime Datta Ken", identificador="principal", url="x"),
    ]
    extrator = _ExtratorFalso("animefire.io", candidatos=candidatos)
    monkeypatch.setattr(resolucao, "EXTRATORES", (extrator,))
    anime = await _criar_anime(sessionmaker, "Slime Datta Ken")

    resultado = await resolucao.resolver_fonte_do_anime(sessionmaker, anime)

    assert resultado == resolucao.FonteResolvida(dominio="animefire.io", identificador="principal")


async def test_nenhum_site_encontra_levanta_fonte_nao_encontrada(sessionmaker, monkeypatch):
    extrator = _ExtratorFalso("animefire.io", candidatos=[])
    monkeypatch.setattr(resolucao, "EXTRATORES", (extrator,))
    anime = await _criar_anime(sessionmaker, "Anime Obscuro")

    with pytest.raises(FonteNaoEncontrada):
        await resolucao.resolver_fonte_do_anime(sessionmaker, anime)


async def test_proximo_site_para_prefere_mapeamento_ja_existente(sessionmaker):
    anime = await _criar_anime(sessionmaker, "Slime Datta Ken")
    async with sessionmaker() as sessao:
        sessao.add_all(
            [
                FonteAnime(
                    anime_id=anime.id,
                    site_dominio="site-a.io",
                    identificador_no_site="a",
                    prioridade=0,
                ),
                FonteAnime(
                    anime_id=anime.id,
                    site_dominio="site-b.io",
                    identificador_no_site="b",
                    prioridade=1,
                ),
            ]
        )
        await sessao.commit()

    resultado = await resolucao.proximo_site_para(sessionmaker, anime, "site-a.io")

    assert resultado == resolucao.FonteResolvida(dominio="site-b.io", identificador="b")


async def test_proximo_site_para_sem_mapeamento_seguinte_descobre_novo_site(
    sessionmaker, monkeypatch
):
    extrator_a = _ExtratorFalso("site-a.io")
    extrator_b = _ExtratorFalso(
        "site-b.io",
        candidatos=[
            ResultadoBusca(titulo_exibicao="Slime Datta Ken", identificador="slime", url="x")
        ],
    )
    monkeypatch.setattr(resolucao, "EXTRATORES", (extrator_a, extrator_b))
    anime = await _criar_anime(sessionmaker, "Slime Datta Ken")
    async with sessionmaker() as sessao:
        sessao.add(
            FonteAnime(
                anime_id=anime.id,
                site_dominio="site-a.io",
                identificador_no_site="a",
                prioridade=0,
            )
        )
        await sessao.commit()

    resultado = await resolucao.proximo_site_para(sessionmaker, anime, "site-a.io")

    assert resultado == resolucao.FonteResolvida(dominio="site-b.io", identificador="slime")
    async with sessionmaker() as sessao:
        fonte = await sessao.get(FonteAnime, (anime.id, "site-b.io"))
        assert fonte is not None


async def test_proximo_site_para_sem_nenhuma_opcao_devolve_none(sessionmaker, monkeypatch):
    extrator = _ExtratorFalso("animefire.io")
    monkeypatch.setattr(resolucao, "EXTRATORES", (extrator,))
    anime = await _criar_anime(sessionmaker, "Slime Datta Ken")

    resultado = await resolucao.proximo_site_para(sessionmaker, anime, "animefire.io")

    assert resultado is None

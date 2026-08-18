"""Testes de `extractors/resolucao.py`, sem rede — `resiliencia.chamar` é
substituído por uma versão que chama a operação direto (sem `ClienteLeve`/
`cloudscraper`), e adapters falsos ficam em `resolucao.EXTRATORES` via
`monkeypatch`.

Fase 2 da modelagem dublado/legendado: `resolver_fonte_do_anime` passa a
receber a versão pedida e devolver `FonteResolvida | ConfirmacaoNecessaria |
VersaoIndisponivel`; `FonteAnime` passa a ter `versao` na PK.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config import Config
from core.enums import VersaoDeFonte, VersaoEpisodio
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
        diferencia_versao: bool = False,
    ) -> None:
        self._dominio = dominio
        self._candidatos = candidatos or []
        self._episodios = episodios or []
        self._diferencia_versao = diferencia_versao
        self.chamadas_buscar = 0

    @property
    def dominio(self) -> str:
        return self._dominio

    @property
    def exige_navegador(self) -> bool:
        return False

    @property
    def diferencia_versao(self) -> bool:
        return self._diferencia_versao

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

    async def _chamar_falso(
        sessionmaker, extrator, operacao, *, permitir_navegador=True, exigir_navegador=False
    ):
        return operacao(None)

    monkeypatch.setattr(resiliencia, "chamar", _chamar_falso)


async def _criar_anime(fabrica, titulo: str) -> Anime:
    async with fabrica() as sessao:
        anime = Anime(titulo=titulo, slug=titulo.lower().replace(" ", "-"))
        sessao.add(anime)
        await sessao.commit()
        await sessao.refresh(anime)
        return anime


async def test_fonte_mapeada_confirmada_devolve_direto_sem_buscar(sessionmaker):
    anime = await _criar_anime(sessionmaker, "Slime Datta Ken")
    async with sessionmaker() as sessao:
        sessao.add(
            FonteAnime(
                anime_id=anime.id,
                site_dominio="animefire.io",
                versao=VersaoDeFonte.LEGENDADO,
                identificador_no_site="slime-datta-ken",
                prioridade=0,
            )
        )
        await sessao.commit()

    resultado = await resolucao.resolver_fonte_do_anime(
        sessionmaker, anime, VersaoEpisodio.LEGENDADO
    )

    assert resultado == resolucao.FonteResolvida(
        dominio="animefire.io",
        identificador="slime-datta-ken",
        versao_da_fonte=VersaoDeFonte.LEGENDADO,
    )


async def test_fonte_mapeada_sem_versao_pedida_usa_nao_diferenciada_do_mesmo_site(sessionmaker):
    anime = await _criar_anime(sessionmaker, "Slime Datta Ken")
    async with sessionmaker() as sessao:
        sessao.add(
            FonteAnime(
                anime_id=anime.id,
                site_dominio="animefire.io",
                versao=VersaoDeFonte.NAO_DIFERENCIADA,
                identificador_no_site="slime-datta-ken",
                prioridade=0,
            )
        )
        await sessao.commit()

    resultado = await resolucao.resolver_fonte_do_anime(
        sessionmaker, anime, VersaoEpisodio.DUBLADO
    )

    assert resultado == resolucao.FonteResolvida(
        dominio="animefire.io",
        identificador="slime-datta-ken",
        versao_da_fonte=VersaoDeFonte.NAO_DIFERENCIADA,
    )


async def test_fonte_mapeada_sem_capacidade_no_site_segue_pro_proximo_site_mapeado(sessionmaker):
    """site-a só tem DUBLADO mapeado — não serve um pedido de LEGENDADO e não
    bloqueia; site-b tem LEGENDADO confirmado e resolve."""
    anime = await _criar_anime(sessionmaker, "Slime Datta Ken")
    async with sessionmaker() as sessao:
        sessao.add_all(
            [
                FonteAnime(
                    anime_id=anime.id,
                    site_dominio="site-a.io",
                    versao=VersaoDeFonte.DUBLADO,
                    identificador_no_site="a",
                    prioridade=0,
                ),
                FonteAnime(
                    anime_id=anime.id,
                    site_dominio="site-b.io",
                    versao=VersaoDeFonte.LEGENDADO,
                    identificador_no_site="b",
                    prioridade=1,
                ),
            ]
        )
        await sessao.commit()

    resultado = await resolucao.resolver_fonte_do_anime(
        sessionmaker, anime, VersaoEpisodio.LEGENDADO
    )

    assert resultado == resolucao.FonteResolvida(
        dominio="site-b.io", identificador="b", versao_da_fonte=VersaoDeFonte.LEGENDADO
    )


async def test_fonte_confirmada_em_site_de_prioridade_menor_vence_nao_diferenciada_de_maior(
    sessionmaker,
):
    """Bug corrigido: site-a (prioridade maior, NAO_DIFERENCIADA) não deve
    vencer sobre site-b (prioridade menor) com a versão pedida CONFIRMADA —
    confirmação exata de versão pesa mais que prioridade de site."""
    anime = await _criar_anime(sessionmaker, "Slime Datta Ken")
    async with sessionmaker() as sessao:
        sessao.add_all(
            [
                FonteAnime(
                    anime_id=anime.id,
                    site_dominio="site-a.io",
                    versao=VersaoDeFonte.NAO_DIFERENCIADA,
                    identificador_no_site="a",
                    prioridade=0,
                ),
                FonteAnime(
                    anime_id=anime.id,
                    site_dominio="site-b.io",
                    versao=VersaoDeFonte.DUBLADO,
                    identificador_no_site="b",
                    prioridade=1,
                ),
            ]
        )
        await sessao.commit()

    resultado = await resolucao.resolver_fonte_do_anime(
        sessionmaker, anime, VersaoEpisodio.DUBLADO
    )

    assert resultado == resolucao.FonteResolvida(
        dominio="site-b.io", identificador="b", versao_da_fonte=VersaoDeFonte.DUBLADO
    )


async def test_sem_mapeamento_site_nao_diferenciado_resolve_e_grava_nao_diferenciada(
    sessionmaker, monkeypatch
):
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

    resultado = await resolucao.resolver_fonte_do_anime(
        sessionmaker, anime, VersaoEpisodio.LEGENDADO
    )

    assert resultado == resolucao.FonteResolvida(
        dominio="animefire.io",
        identificador="slime",
        versao_da_fonte=VersaoDeFonte.NAO_DIFERENCIADA,
    )
    async with sessionmaker() as sessao:
        fonte = await sessao.get(
            FonteAnime, (anime.id, "animefire.io", VersaoDeFonte.NAO_DIFERENCIADA)
        )
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

    resultado = await resolucao.resolver_fonte_do_anime(
        sessionmaker, anime, VersaoEpisodio.LEGENDADO
    )

    assert resultado == resolucao.FonteResolvida(
        dominio="site-b.io", identificador="slime", versao_da_fonte=VersaoDeFonte.NAO_DIFERENCIADA
    )
    async with sessionmaker() as sessao:
        fonte = await sessao.get(
            FonteAnime, (anime.id, "site-b.io", VersaoDeFonte.NAO_DIFERENCIADA)
        )
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

    resultado = await resolucao.resolver_fonte_do_anime(
        sessionmaker, anime, VersaoEpisodio.LEGENDADO
    )

    assert resultado == resolucao.FonteResolvida(
        dominio="site-b.io", identificador="slime", versao_da_fonte=VersaoDeFonte.NAO_DIFERENCIADA
    )
    assert extrator_a.chamadas_buscar == 0


async def test_candidatos_ambiguos_site_nao_diferenciado_devolve_confirmacao_necessaria(
    sessionmaker, monkeypatch
):
    candidatos = [
        ResultadoBusca(titulo_exibicao="Slime Datta Ken", identificador="a", url="x"),
        ResultadoBusca(titulo_exibicao="Slime Datta Ken OVA", identificador="b", url="y"),
    ]
    extrator = _ExtratorFalso("animefire.io", candidatos=candidatos)
    monkeypatch.setattr(resolucao, "EXTRATORES", (extrator,))
    anime = await _criar_anime(sessionmaker, "Slime Datta Ke")  # não bate exato com nenhum

    resultado = await resolucao.resolver_fonte_do_anime(
        sessionmaker, anime, VersaoEpisodio.LEGENDADO
    )

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

    resultado = await resolucao.resolver_fonte_do_anime(
        sessionmaker, anime, VersaoEpisodio.LEGENDADO
    )

    assert resultado == resolucao.FonteResolvida(
        dominio="animefire.io",
        identificador="principal",
        versao_da_fonte=VersaoDeFonte.NAO_DIFERENCIADA,
    )


@pytest.mark.parametrize(
    ("versao_pedida", "versao_de_fonte"),
    [
        (VersaoEpisodio.LEGENDADO, VersaoDeFonte.LEGENDADO),
        (VersaoEpisodio.DUBLADO, VersaoDeFonte.DUBLADO),
    ],
)
async def test_site_que_diferencia_resolve_versao_pedida_ao_vivo(
    sessionmaker, monkeypatch, versao_pedida, versao_de_fonte
):
    candidatos = [
        ResultadoBusca(
            titulo_exibicao="Slime Datta Ken",
            identificador="slime",
            url="x",
            versao=VersaoEpisodio.LEGENDADO,
        ),
        ResultadoBusca(
            titulo_exibicao="Slime Datta Ken Dublado",
            identificador="slime-dublado",
            url="y",
            versao=VersaoEpisodio.DUBLADO,
        ),
    ]
    extrator = _ExtratorFalso("animesdrive.online", candidatos=candidatos, diferencia_versao=True)
    monkeypatch.setattr(resolucao, "EXTRATORES", (extrator,))
    anime = await _criar_anime(sessionmaker, "Slime Datta Ken")

    resultado = await resolucao.resolver_fonte_do_anime(sessionmaker, anime, versao_pedida)

    identificador_esperado = (
        "slime" if versao_pedida == VersaoEpisodio.LEGENDADO else "slime-dublado"
    )
    assert resultado == resolucao.FonteResolvida(
        dominio="animesdrive.online",
        identificador=identificador_esperado,
        versao_da_fonte=versao_de_fonte,
    )


async def test_site_que_diferencia_grava_as_duas_versoes_numa_busca_so(sessionmaker, monkeypatch):
    """Resolvendo LEGENDADO, a partição DUBLADO também desambigua sem custo de
    rede extra — deve ser persistida de graça, mesmo sem ter sido pedida."""
    candidatos = [
        ResultadoBusca(
            titulo_exibicao="Slime Datta Ken",
            identificador="slime",
            url="x",
            versao=VersaoEpisodio.LEGENDADO,
        ),
        ResultadoBusca(
            titulo_exibicao="Slime Datta Ken Dublado",
            identificador="slime-dublado",
            url="y",
            versao=VersaoEpisodio.DUBLADO,
        ),
    ]
    extrator = _ExtratorFalso("animesdrive.online", candidatos=candidatos, diferencia_versao=True)
    monkeypatch.setattr(resolucao, "EXTRATORES", (extrator,))
    anime = await _criar_anime(sessionmaker, "Slime Datta Ken")

    await resolucao.resolver_fonte_do_anime(sessionmaker, anime, VersaoEpisodio.LEGENDADO)

    async with sessionmaker() as sessao:
        legendado = await sessao.get(
            FonteAnime, (anime.id, "animesdrive.online", VersaoDeFonte.LEGENDADO)
        )
        dublado = await sessao.get(
            FonteAnime, (anime.id, "animesdrive.online", VersaoDeFonte.DUBLADO)
        )
        assert legendado is not None and legendado.identificador_no_site == "slime"
        assert dublado is not None and dublado.identificador_no_site == "slime-dublado"


async def test_site_que_diferencia_desambigua_por_identificador_com_titulo_entre_parenteses(
    sessionmaker, monkeypatch
):
    """Regressão: AnimeFire marca dublado com parênteses no título ("Nome
    (Dublado)"), fora da fronteira de token que `remover_marcador_de_versao`
    exige — comparar pelo `titulo_exibicao` nunca bateria com o slug do anime,
    mesmo a partição tendo um único candidato correto entre vários. Aqui a
    partição DUBLADO tem 2 candidatos (o certo + um filme não relacionado) só
    pra forçar o caminho de desambiguação por slug, não o atalho de item
    único."""
    candidatos = [
        ResultadoBusca(
            titulo_exibicao="One Piece",
            identificador="one-piece",
            url="x",
            versao=VersaoEpisodio.LEGENDADO,
        ),
        ResultadoBusca(
            titulo_exibicao="One Piece (Dublado)",
            identificador="one-piece-dublado",
            url="y",
            versao=VersaoEpisodio.DUBLADO,
        ),
        ResultadoBusca(
            titulo_exibicao="One Piece Film: Red (Dublado)",
            identificador="one-piece-film-red-dublado",
            url="z",
            versao=VersaoEpisodio.DUBLADO,
        ),
    ]
    extrator = _ExtratorFalso("animefire.io", candidatos=candidatos, diferencia_versao=True)
    monkeypatch.setattr(resolucao, "EXTRATORES", (extrator,))
    anime = await _criar_anime(sessionmaker, "One Piece")

    resultado = await resolucao.resolver_fonte_do_anime(
        sessionmaker, anime, VersaoEpisodio.DUBLADO
    )

    assert resultado == resolucao.FonteResolvida(
        dominio="animefire.io",
        identificador="one-piece-dublado",
        versao_da_fonte=VersaoDeFonte.DUBLADO,
    )


async def test_site_que_diferencia_confirmacao_necessaria_restrita_a_particao_pedida(
    sessionmaker, monkeypatch
):
    """Partição LEGENDADO é ambígua (2 candidatos, sem match exato); partição
    DUBLADO tem um único candidato — a `ConfirmacaoNecessaria` só deve trazer
    os candidatos LEGENDADO, sem misturar o DUBLADO."""
    candidatos = [
        ResultadoBusca(
            titulo_exibicao="Slime Datta Ken",
            identificador="slime-a",
            url="x",
            versao=VersaoEpisodio.LEGENDADO,
        ),
        ResultadoBusca(
            titulo_exibicao="Slime Datta Ken 2",
            identificador="slime-b",
            url="y",
            versao=VersaoEpisodio.LEGENDADO,
        ),
        ResultadoBusca(
            titulo_exibicao="Slime Datta Ken Dublado",
            identificador="slime-dublado",
            url="z",
            versao=VersaoEpisodio.DUBLADO,
        ),
    ]
    extrator = _ExtratorFalso("animesdrive.online", candidatos=candidatos, diferencia_versao=True)
    monkeypatch.setattr(resolucao, "EXTRATORES", (extrator,))
    anime = await _criar_anime(sessionmaker, "Slime Datta Ken 3")  # não bate com nenhum candidato

    resultado = await resolucao.resolver_fonte_do_anime(
        sessionmaker, anime, VersaoEpisodio.LEGENDADO
    )

    assert resultado == resolucao.ConfirmacaoNecessaria(
        dominio="animesdrive.online", candidatos=candidatos[:2]
    )


async def test_site_que_diferencia_particao_pedida_vazia_continua_pro_proximo_site(
    sessionmaker, monkeypatch
):
    candidatos_so_legendado = [
        ResultadoBusca(
            titulo_exibicao="Slime Datta Ken",
            identificador="slime",
            url="x",
            versao=VersaoEpisodio.LEGENDADO,
        )
    ]
    extrator_a = _ExtratorFalso(
        "animesdrive.online", candidatos=candidatos_so_legendado, diferencia_versao=True
    )
    extrator_b = _ExtratorFalso(
        "site-b.io",
        candidatos=[
            ResultadoBusca(titulo_exibicao="Slime Datta Ken", identificador="slime-b", url="y")
        ],
    )
    monkeypatch.setattr(resolucao, "EXTRATORES", (extrator_a, extrator_b))
    anime = await _criar_anime(sessionmaker, "Slime Datta Ken")

    resultado = await resolucao.resolver_fonte_do_anime(
        sessionmaker, anime, VersaoEpisodio.DUBLADO
    )

    assert resultado == resolucao.FonteResolvida(
        dominio="site-b.io", identificador="slime-b", versao_da_fonte=VersaoDeFonte.NAO_DIFERENCIADA
    )


async def test_nenhum_site_serve_versao_devolve_versao_indisponivel(sessionmaker, monkeypatch):
    extrator = _ExtratorFalso("animefire.io", candidatos=[])
    monkeypatch.setattr(resolucao, "EXTRATORES", (extrator,))
    anime = await _criar_anime(sessionmaker, "Anime Obscuro")

    resultado = await resolucao.resolver_fonte_do_anime(
        sessionmaker, anime, VersaoEpisodio.DUBLADO
    )

    assert resultado == resolucao.VersaoIndisponivel(versao=VersaoEpisodio.DUBLADO)


async def test_resolver_fonte_do_anime_rejeita_versao_desconhecida(sessionmaker, monkeypatch):
    extrator = _ExtratorFalso("animefire.io", candidatos=[])
    monkeypatch.setattr(resolucao, "EXTRATORES", (extrator,))
    anime = await _criar_anime(sessionmaker, "Slime Datta Ken")

    with pytest.raises(ValueError, match="LEGENDADO ou DUBLADO"):
        await resolucao.resolver_fonte_do_anime(sessionmaker, anime, VersaoEpisodio.DESCONHECIDA)


async def test_proximo_site_para_prefere_mapeamento_ja_existente(sessionmaker):
    anime = await _criar_anime(sessionmaker, "Slime Datta Ken")
    async with sessionmaker() as sessao:
        sessao.add_all(
            [
                FonteAnime(
                    anime_id=anime.id,
                    site_dominio="site-a.io",
                    versao=VersaoDeFonte.LEGENDADO,
                    identificador_no_site="a",
                    prioridade=0,
                ),
                FonteAnime(
                    anime_id=anime.id,
                    site_dominio="site-b.io",
                    versao=VersaoDeFonte.LEGENDADO,
                    identificador_no_site="b",
                    prioridade=1,
                ),
            ]
        )
        await sessao.commit()

    resultado = await resolucao.proximo_site_para(
        sessionmaker, anime, "site-a.io", VersaoEpisodio.LEGENDADO
    )

    assert resultado == resolucao.FonteResolvida(
        dominio="site-b.io", identificador="b", versao_da_fonte=VersaoDeFonte.LEGENDADO
    )


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
                versao=VersaoDeFonte.LEGENDADO,
                identificador_no_site="a",
                prioridade=0,
            )
        )
        await sessao.commit()

    resultado = await resolucao.proximo_site_para(
        sessionmaker, anime, "site-a.io", VersaoEpisodio.LEGENDADO
    )

    assert resultado == resolucao.FonteResolvida(
        dominio="site-b.io", identificador="slime", versao_da_fonte=VersaoDeFonte.NAO_DIFERENCIADA
    )
    async with sessionmaker() as sessao:
        fonte = await sessao.get(
            FonteAnime, (anime.id, "site-b.io", VersaoDeFonte.NAO_DIFERENCIADA)
        )
        assert fonte is not None


async def test_proximo_site_para_sem_nenhuma_opcao_devolve_none(sessionmaker, monkeypatch):
    extrator = _ExtratorFalso("animefire.io")
    monkeypatch.setattr(resolucao, "EXTRATORES", (extrator,))
    anime = await _criar_anime(sessionmaker, "Slime Datta Ken")

    resultado = await resolucao.proximo_site_para(
        sessionmaker, anime, "animefire.io", VersaoEpisodio.LEGENDADO
    )

    assert resultado is None


async def test_proximo_site_para_versao_desconhecida_ignora_capacidade_de_versao(sessionmaker):
    """Episódio de fonte não-diferenciada (`Episodio.versao == DESCONHECIDA`)
    não tem uma versão pedida de verdade a preservar — usa a 1ª fonte mapeada
    disponível, mesmo que ela seja de uma versão "confirmada" específica."""
    anime = await _criar_anime(sessionmaker, "Slime Datta Ken")
    async with sessionmaker() as sessao:
        sessao.add_all(
            [
                FonteAnime(
                    anime_id=anime.id,
                    site_dominio="site-a.io",
                    versao=VersaoDeFonte.NAO_DIFERENCIADA,
                    identificador_no_site="a",
                    prioridade=0,
                ),
                FonteAnime(
                    anime_id=anime.id,
                    site_dominio="site-b.io",
                    versao=VersaoDeFonte.DUBLADO,
                    identificador_no_site="b",
                    prioridade=1,
                ),
            ]
        )
        await sessao.commit()

    resultado = await resolucao.proximo_site_para(
        sessionmaker, anime, "site-a.io", VersaoEpisodio.DESCONHECIDA
    )

    assert resultado == resolucao.FonteResolvida(
        dominio="site-b.io", identificador="b", versao_da_fonte=VersaoDeFonte.DUBLADO
    )

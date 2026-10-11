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


class _ExtratorTruncamentoFalso(ExtratorDeSite):
    """Fake que só acha o card no termo já truncado do subtítulo — simula um
    site de busca por prefixo (ex. AnimeFire) depois que `buscar` parou de
    truncar internamente (fatia 1 de PLANO_PADRONIZACAO_FONTES.md): a
    assimetria só fica coberta se `_buscar_variantes` (fatia 2) tentar o
    termo truncado por `variantes_de_busca`."""

    def __init__(self, dominio: str, *, termo_truncado: str, candidato: ResultadoBusca) -> None:
        self._dominio = dominio
        self._termo_truncado = termo_truncado
        self._candidato = candidato
        self.chamadas: list[str] = []

    @property
    def dominio(self) -> str:
        return self._dominio

    @property
    def exige_navegador(self) -> bool:
        return False

    @property
    def diferencia_versao(self) -> bool:
        return False

    def buscar(self, cliente, titulo):
        self.chamadas.append(titulo)
        return [self._candidato] if titulo == self._termo_truncado else []

    def listar_episodios(self, cliente, identificador):
        return []

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
        sessionmaker,
        extrator,
        operacao,
        *,
        nome_operacao="operacao",
        permitir_navegador=True,
        exigir_navegador=False,
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
                site_dominio="animefire.one",
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
        dominio="animefire.one",
        identificador="slime-datta-ken",
        versao_da_fonte=VersaoDeFonte.LEGENDADO,
    )


async def test_fonte_mapeada_sem_versao_pedida_usa_nao_diferenciada_do_mesmo_site(sessionmaker):
    anime = await _criar_anime(sessionmaker, "Slime Datta Ken")
    async with sessionmaker() as sessao:
        sessao.add(
            FonteAnime(
                anime_id=anime.id,
                site_dominio="animefire.one",
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
        dominio="animefire.one",
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


async def test_fonte_confirmada_mais_recente_vence_nao_diferenciada_mais_antiga_de_prioridade_menor(
    sessionmaker,
):
    """site-a (prioridade menor, NAO_DIFERENCIADA, resolvida antes) não deve
    vencer sobre site-b (prioridade maior) com a versão pedida CONFIRMADA
    mais recentemente — prioridade de site não decide entre capazes."""
    anime = await _criar_anime(sessionmaker, "Slime Datta Ken")
    agora = datetime.now(UTC)
    async with sessionmaker() as sessao:
        sessao.add_all(
            [
                FonteAnime(
                    anime_id=anime.id,
                    site_dominio="site-a.io",
                    versao=VersaoDeFonte.NAO_DIFERENCIADA,
                    identificador_no_site="a",
                    prioridade=0,
                    resolvido_em=agora - timedelta(hours=1),
                ),
                FonteAnime(
                    anime_id=anime.id,
                    site_dominio="site-b.io",
                    versao=VersaoDeFonte.DUBLADO,
                    identificador_no_site="b",
                    prioridade=1,
                    resolvido_em=agora,
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


async def test_troca_manual_para_site_nao_diferenciado_vence_confirmada_antiga_de_outro_site(
    sessionmaker,
):
    """Regressão do bug relatado: usuário confirma manualmente ("Trocar
    fonte") um site que NÃO diferencia versão (ex. AnimeFire) depois de já
    ter uma versão CONFIRMADA mapeada num site diferente (ex. AnimesDrive) —
    a escolha manual mais recente tem que valer, mesmo sendo
    NAO_DIFERENCIADA contra uma CONFIRMADA exata mais antiga."""
    anime = await _criar_anime(sessionmaker, "Slime Datta Ken")
    agora = datetime.now(UTC)
    async with sessionmaker() as sessao:
        sessao.add_all(
            [
                FonteAnime(
                    anime_id=anime.id,
                    site_dominio="animesdrive.online",
                    versao=VersaoDeFonte.DUBLADO,
                    identificador_no_site="slime-datta-ken-dublado",
                    prioridade=0,
                    resolvido_em=agora - timedelta(days=1),
                ),
                FonteAnime(
                    anime_id=anime.id,
                    site_dominio="animefire.one",
                    versao=VersaoDeFonte.NAO_DIFERENCIADA,
                    identificador_no_site="slime-datta-ken",
                    prioridade=1,
                    resolvido_em=agora,
                ),
            ]
        )
        await sessao.commit()

    resultado = await resolucao.resolver_fonte_do_anime(
        sessionmaker, anime, VersaoEpisodio.DUBLADO
    )

    assert resultado == resolucao.FonteResolvida(
        dominio="animefire.one",
        identificador="slime-datta-ken",
        versao_da_fonte=VersaoDeFonte.NAO_DIFERENCIADA,
    )


async def test_sem_mapeamento_site_nao_diferenciado_resolve_e_grava_nao_diferenciada(
    sessionmaker, monkeypatch
):
    extrator = _ExtratorFalso(
        "animefire.one",
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
        dominio="animefire.one",
        identificador="slime",
        versao_da_fonte=VersaoDeFonte.NAO_DIFERENCIADA,
    )
    async with sessionmaker() as sessao:
        fonte = await sessao.get(
            FonteAnime, (anime.id, "animefire.one", VersaoDeFonte.NAO_DIFERENCIADA)
        )
        assert fonte is not None
        assert fonte.identificador_no_site == "slime"
        assert fonte.prioridade == 0


async def test_titulo_com_subtitulo_resolve_via_variante_truncada_sem_confirmacao_manual(
    sessionmaker, monkeypatch
):
    """D-A6 (PLANO_PADRONIZACAO_FONTES.md): antes da fatia 1, `AnimeFireProvider.
    buscar` truncava o subtítulo internamente e a resolução automática
    funcionava "de graça" para títulos com subtítulo. Agora que `buscar` não
    trunca mais, é `_buscar_variantes` (fatia 2) quem precisa cobrir essa
    necessidade — regressão: título com subtítulo continua resolvendo
    sozinho, sem cair em `ConfirmacaoNecessaria`."""
    titulo_completo = "Anime Principal: Um Subtítulo Longo"
    titulo_truncado = "Anime Principal"
    candidato = ResultadoBusca(
        titulo_exibicao="Anime Principal", identificador="anime-principal", url="http://x/ap"
    )
    extrator = _ExtratorTruncamentoFalso(
        "animefire.one", termo_truncado=titulo_truncado, candidato=candidato
    )
    monkeypatch.setattr(resolucao, "EXTRATORES", (extrator,))
    anime = await _criar_anime(sessionmaker, titulo_completo)

    resultado = await resolucao.resolver_fonte_do_anime(
        sessionmaker, anime, VersaoEpisodio.LEGENDADO
    )

    assert resultado == resolucao.FonteResolvida(
        dominio="animefire.one",
        identificador="anime-principal",
        versao_da_fonte=VersaoDeFonte.NAO_DIFERENCIADA,
    )
    # a 1ª variante roda sozinha e o resto em janelas de 2: o truncado achou,
    # mas o prefixo que dividia a janela com ele também foi chamado.
    assert extrator.chamadas[:2] == [titulo_completo, titulo_truncado]


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
    extrator = _ExtratorFalso("animefire.one", candidatos=candidatos)
    monkeypatch.setattr(resolucao, "EXTRATORES", (extrator,))
    anime = await _criar_anime(sessionmaker, "Slime Datta Ke")  # não bate exato com nenhum

    resultado = await resolucao.resolver_fonte_do_anime(
        sessionmaker, anime, VersaoEpisodio.LEGENDADO
    )

    assert resultado == resolucao.ConfirmacaoNecessaria(
        dominio="animefire.one", candidatos=candidatos
    )


async def test_candidatos_com_match_exato_desambigua_automaticamente(sessionmaker, monkeypatch):
    candidatos = [
        ResultadoBusca(titulo_exibicao="Slime Datta Ken OVA", identificador="ova", url="y"),
        ResultadoBusca(titulo_exibicao="Slime Datta Ken", identificador="principal", url="x"),
    ]
    extrator = _ExtratorFalso("animefire.one", candidatos=candidatos)
    monkeypatch.setattr(resolucao, "EXTRATORES", (extrator,))
    anime = await _criar_anime(sessionmaker, "Slime Datta Ken")

    resultado = await resolucao.resolver_fonte_do_anime(
        sessionmaker, anime, VersaoEpisodio.LEGENDADO
    )

    assert resultado == resolucao.FonteResolvida(
        dominio="animefire.one",
        identificador="principal",
        versao_da_fonte=VersaoDeFonte.NAO_DIFERENCIADA,
    )


async def test_variante_curta_devolve_card_de_outro_anime_nao_resolve_o_site(
    sessionmaker, monkeypatch
):
    """Regressão da escada de prefixos crescentes (`variantes_de_busca` sonda
    pela 1ª palavra): buscando "Naruto Shippuden", o site só devolve o card
    "Naruto" — outro anime que compartilha o prefixo. `_desambiguar` aceitaria
    esse único candidato pelo atalho de item único; `_buscar_variantes` filtra
    por `corresponde_a_alguma_referencia` antes (card de 1 palavra não valida
    referência de 2+ palavras) e o site não vira fonte."""
    extrator = _ExtratorFalso(
        "animefire.one",
        candidatos=[
            ResultadoBusca(titulo_exibicao="Naruto", identificador="naruto", url="http://x/naruto")
        ],
    )
    monkeypatch.setattr(resolucao, "EXTRATORES", (extrator,))
    anime = await _criar_anime(sessionmaker, "Naruto Shippuden")

    resultado = await resolucao.resolver_fonte_do_anime(
        sessionmaker, anime, VersaoEpisodio.LEGENDADO
    )

    assert resultado == resolucao.VersaoIndisponivel(versao=VersaoEpisodio.LEGENDADO)
    async with sessionmaker() as sessao:
        fonte = await sessao.get(
            FonteAnime, (anime.id, "animefire.one", VersaoDeFonte.NAO_DIFERENCIADA)
        )
        assert fonte is None


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


async def test_site_que_diferencia_versao_de_graca_usa_sentinel_que_nao_vence_confirmacao_antiga(
    sessionmaker, monkeypatch
):
    """Regressão do bug crítico: `bump_recencia=False` só era respeitado no
    ramo de UPDATE de `_gravar_fonte_anime` — uma linha NOVA (domínio nunca
    mapeado nesta versão) caía no `default=now()` do model. Aqui o domínio
    "animesdrive.online" é novo pras duas versões; resolvendo LEGENDADO
    (pedida), a partição DUBLADO ("de graça") também desambigua e é gravada
    com `bump_recencia=False`. Ela não pode vencer, na resolução seguinte de
    DUBLADO, uma fonte já mapeada e mais antiga em outro domínio que o
    usuário confirmou manualmente antes."""
    anime = await _criar_anime(sessionmaker, "Slime Datta Ken")
    agora = datetime.now(UTC)
    async with sessionmaker() as sessao:
        sessao.add(
            FonteAnime(
                anime_id=anime.id,
                site_dominio="site-antigo.io",
                versao=VersaoDeFonte.DUBLADO,
                identificador_no_site="antigo-dublado",
                prioridade=0,
                resolvido_em=agora - timedelta(days=30),
            )
        )
        await sessao.commit()

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

    resultado_legendado = await resolucao.resolver_fonte_do_anime(
        sessionmaker, anime, VersaoEpisodio.LEGENDADO
    )

    assert resultado_legendado == resolucao.FonteResolvida(
        dominio="animesdrive.online",
        identificador="slime",
        versao_da_fonte=VersaoDeFonte.LEGENDADO,
    )

    async with sessionmaker() as sessao:
        legendado = await sessao.get(
            FonteAnime, (anime.id, "animesdrive.online", VersaoDeFonte.LEGENDADO)
        )
        dublado_de_graca = await sessao.get(
            FonteAnime, (anime.id, "animesdrive.online", VersaoDeFonte.DUBLADO)
        )
        assert legendado is not None and legendado.resolvido_em >= agora
        assert dublado_de_graca is not None
        # Sentinel, não `datetime.now(UTC)`: bem anterior a qualquer timestamp
        # real usado neste teste, inclusive o do "site-antigo.io".
        assert dublado_de_graca.resolvido_em < agora - timedelta(days=365)

    # Resolvendo DUBLADO na sequência: a linha "de graça" recém-criada em
    # animesdrive.online NÃO pode vencer a confirmação genuína e mais antiga
    # de site-antigo.io.
    resultado_dublado = await resolucao.resolver_fonte_do_anime(
        sessionmaker, anime, VersaoEpisodio.DUBLADO
    )

    assert resultado_dublado == resolucao.FonteResolvida(
        dominio="site-antigo.io",
        identificador="antigo-dublado",
        versao_da_fonte=VersaoDeFonte.DUBLADO,
    )


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
    extrator = _ExtratorFalso("animefire.one", candidatos=candidatos, diferencia_versao=True)
    monkeypatch.setattr(resolucao, "EXTRATORES", (extrator,))
    anime = await _criar_anime(sessionmaker, "One Piece")

    resultado = await resolucao.resolver_fonte_do_anime(
        sessionmaker, anime, VersaoEpisodio.DUBLADO
    )

    assert resultado == resolucao.FonteResolvida(
        dominio="animefire.one",
        identificador="one-piece-dublado",
        versao_da_fonte=VersaoDeFonte.DUBLADO,
    )


async def test_site_que_diferencia_confirmacao_necessaria_restrita_a_particao_pedida(
    sessionmaker, monkeypatch
):
    """Partição LEGENDADO é ambígua (2 candidatos, sem match exato); partição
    DUBLADO tem um único candidato — a `ConfirmacaoNecessaria` só deve trazer
    os candidatos LEGENDADO, sem misturar o DUBLADO.

    Os 3 candidatos correspondem ao título por `corresponde_a_alguma_referencia`
    (o filtro de `_buscar_variantes` não pré-resolve a ambiguidade), mas nenhum
    identificador bate exato com o slug do anime — `_desambiguar_por_versao`
    devolve `None` dentro da partição pedida."""
    candidatos = [
        ResultadoBusca(
            titulo_exibicao="Slime Datta Ken 1st Season",
            identificador="slime-datta-ken-1st-season",
            url="x",
            versao=VersaoEpisodio.LEGENDADO,
        ),
        ResultadoBusca(
            titulo_exibicao="Slime Datta Ken 2nd Season",
            identificador="slime-datta-ken-2nd-season",
            url="y",
            versao=VersaoEpisodio.LEGENDADO,
        ),
        ResultadoBusca(
            titulo_exibicao="Slime Datta Ken Dublado",
            identificador="slime-datta-ken-dublado",
            url="z",
            versao=VersaoEpisodio.DUBLADO,
        ),
    ]
    extrator = _ExtratorFalso("animesdrive.online", candidatos=candidatos, diferencia_versao=True)
    monkeypatch.setattr(resolucao, "EXTRATORES", (extrator,))
    anime = await _criar_anime(sessionmaker, "Slime Datta Ken")

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
    extrator = _ExtratorFalso("animefire.one", candidatos=[])
    monkeypatch.setattr(resolucao, "EXTRATORES", (extrator,))
    anime = await _criar_anime(sessionmaker, "Anime Obscuro")

    resultado = await resolucao.resolver_fonte_do_anime(
        sessionmaker, anime, VersaoEpisodio.DUBLADO
    )

    assert resultado == resolucao.VersaoIndisponivel(versao=VersaoEpisodio.DUBLADO)


async def test_resolver_fonte_do_anime_rejeita_versao_desconhecida(sessionmaker, monkeypatch):
    extrator = _ExtratorFalso("animefire.one", candidatos=[])
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
        sessionmaker, anime, {"site-a.io"}, VersaoEpisodio.LEGENDADO
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
        sessionmaker, anime, {"site-a.io"}, VersaoEpisodio.LEGENDADO
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
    extrator = _ExtratorFalso("animefire.one")
    monkeypatch.setattr(resolucao, "EXTRATORES", (extrator,))
    anime = await _criar_anime(sessionmaker, "Slime Datta Ken")

    resultado = await resolucao.proximo_site_para(
        sessionmaker, anime, {"animefire.one"}, VersaoEpisodio.LEGENDADO
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
        sessionmaker, anime, {"site-a.io"}, VersaoEpisodio.DESCONHECIDA
    )

    assert resultado == resolucao.FonteResolvida(
        dominio="site-b.io", identificador="b", versao_da_fonte=VersaoDeFonte.DUBLADO
    )


async def test_fontes_mapeadas_alternativas_so_capazes_uma_por_dominio_da_mais_recente(
    sessionmaker,
):
    anime = await _criar_anime(sessionmaker, "Slime Datta Ken")
    agora = datetime.now(UTC)

    def _linha(dominio, versao, identificador, dias_atras):
        return FonteAnime(
            anime_id=anime.id,
            site_dominio=dominio,
            versao=versao,
            identificador_no_site=identificador,
            prioridade=0,
            resolvido_em=agora - timedelta(days=dias_atras),
        )

    async with sessionmaker() as sessao:
        sessao.add_all(
            [
                _linha("escolhido.io", VersaoDeFonte.LEGENDADO, "e", 0),
                _linha("b.io", VersaoDeFonte.LEGENDADO, "b-velha", 5),
                _linha("b.io", VersaoDeFonte.NAO_DIFERENCIADA, "b-nova", 2),
                _linha("c.io", VersaoDeFonte.DUBLADO, "c-so-dublado", 1),  # incapaz
                _linha("d.io", VersaoDeFonte.NAO_DIFERENCIADA, "d", 9),
            ]
        )
        await sessao.commit()

    alternativas = await resolucao.fontes_mapeadas_alternativas(
        sessionmaker, anime, VersaoEpisodio.LEGENDADO, excluir_dominio="escolhido.io"
    )

    assert alternativas == [
        resolucao.FonteResolvida("b.io", "b-nova", VersaoDeFonte.NAO_DIFERENCIADA),
        resolucao.FonteResolvida("d.io", "d", VersaoDeFonte.NAO_DIFERENCIADA),
    ]

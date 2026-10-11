"""Testes de `extractors/resiliencia.py` contra SQLite real, sem rede."""

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config import Config
from core.erros import FalhaDeExtracao, FonteNaoEncontrada, SessaoRejeitada, SiteEmCooldown
from db.engine import criar_engine, criar_sessionmaker
from extractors import circuit_breaker, resiliencia, sessao_cache
from extractors.base import EpisodioRemoto, ExtratorDeSite, LinkDeMidia, ResultadoBusca
from extractors.cliente import ClienteDeSite
from models.base import Base
from models.estado_site import EstadoSite

_DOMINIO = "animefire.one"


class _ExtratorFalso(ExtratorDeSite):
    """Implementação mínima, usada só para exercitar `resiliencia.chamar`."""

    @property
    def dominio(self) -> str:
        return _DOMINIO

    @property
    def exige_navegador(self) -> bool:
        return False

    def buscar(self, cliente: ClienteDeSite, titulo: str) -> list[ResultadoBusca]:
        return []

    def listar_episodios(
        self, cliente: ClienteDeSite, identificador: str
    ) -> list[EpisodioRemoto]:
        return []

    def resolver_midia(self, cliente: ClienteDeSite, url_episodio: str) -> LinkDeMidia:
        return LinkDeMidia(url="http://exemplo/teste", cabecalhos={})


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


async def test_chamar_propaga_site_em_cooldown_sem_retentativa_e_sem_chamar_operacao(
    sessionmaker,
):
    # Além do limite de falhas curtas (`_LIMITE_PARA_COOLDOWN`) abre o cooldown cheio.
    for _ in range(4):
        await circuit_breaker.registrar_falha(sessionmaker, _DOMINIO, RuntimeError("x"))
    assert await circuit_breaker.esta_em_cooldown(sessionmaker, _DOMINIO) is True

    chamadas: list[str] = []

    def operacao(cliente: ClienteDeSite) -> str:
        chamadas.append("chamada")
        return "não deveria chegar aqui"

    with pytest.raises(SiteEmCooldown) as excinfo:
        await resiliencia.chamar(sessionmaker, _ExtratorFalso(), operacao)

    assert excinfo.value.permite_retentativa is False
    assert excinfo.value.dominio == _DOMINIO
    assert chamadas == []


async def test_chamar_com_falha_nao_retentavel_nao_conta_no_circuit_breaker(sessionmaker):
    """`FonteNaoEncontrada` (permite_retentativa=False por padrão, core/erros.py)
    propaga sem passar por `circuit_breaker.registrar_falha` — diferente de uma
    falha retentável, que incrementaria `falhas_consecutivas`."""

    def operacao(cliente: ClienteDeSite) -> str:
        raise FonteNaoEncontrada("não encontrado: http://exemplo/x", dominio=_DOMINIO)

    with pytest.raises(FonteNaoEncontrada):
        await resiliencia.chamar(sessionmaker, _ExtratorFalso(), operacao)

    async with sessionmaker() as sessao:
        estado = await sessao.get(EstadoSite, _DOMINIO)
    assert estado is None
    assert await circuit_breaker.esta_em_cooldown(sessionmaker, _DOMINIO) is False


class _NavegadorFalso:
    """Fake de `ClienteNavegador` — `resiliencia.chamar` é quem instancia o
    cliente, então o único jeito de exercitar o caminho de navegador sem subir
    Chromium é trocar a classe no módulo."""

    instancias: list["_NavegadorFalso"] = []

    def __init__(self) -> None:
        self.fechado = False
        _NavegadorFalso.instancias.append(self)

    def cookies(self) -> dict[str, str]:
        return {"cf_clearance": "do-navegador"}

    def user_agent(self) -> str:
        return "NavegadorFalso/1.0"

    def fechar(self) -> None:
        self.fechado = True


@pytest.fixture
def navegador_falso(monkeypatch):
    _NavegadorFalso.instancias = []
    monkeypatch.setattr(resiliencia, "ClienteNavegador", _NavegadorFalso)
    return _NavegadorFalso


async def test_chamar_com_exigir_navegador_entrega_o_navegador_e_o_fecha(
    sessionmaker, navegador_falso
):
    recebidos = []

    def operacao(cliente: ClienteDeSite) -> str:
        recebidos.append(cliente)
        return "ok"

    resultado = await resiliencia.chamar(
        sessionmaker, _ExtratorFalso(), operacao, exigir_navegador=True
    )

    assert resultado == "ok"
    assert isinstance(recebidos[0], navegador_falso)
    assert [instancia.fechado for instancia in navegador_falso.instancias] == [True]


async def test_chamar_fecha_o_cliente_mesmo_quando_a_operacao_falha(
    sessionmaker, navegador_falso
):
    """Sem isso, uma falha de extração deixaria um processo Chromium órfão por job."""

    def operacao(cliente: ClienteDeSite) -> str:
        raise FonteNaoEncontrada("não encontrado: http://exemplo/x", dominio=_DOMINIO)

    with pytest.raises(FonteNaoEncontrada):
        await resiliencia.chamar(
            sessionmaker, _ExtratorFalso(), operacao, exigir_navegador=True
        )

    assert [instancia.fechado for instancia in navegador_falso.instancias] == [True]


async def test_chamar_com_navegador_guarda_a_sessao_que_o_navegador_produziu(
    sessionmaker, navegador_falso
):
    """Cookie resolvido pelo navegador realimenta `SessaoBypass` — é justamente o
    material que o cliente leve não consegue produzir sozinho."""
    await resiliencia.chamar(
        sessionmaker, _ExtratorFalso(), lambda cliente: "ok", exigir_navegador=True
    )

    contexto = await sessao_cache.carregar(sessionmaker, _DOMINIO)
    assert contexto is not None
    assert contexto.cookies == {"cf_clearance": "do-navegador"}
    assert contexto.user_agent == "NavegadorFalso/1.0"


async def test_chamar_sem_exigir_navegador_nao_sobe_navegador(sessionmaker, navegador_falso):
    await resiliencia.chamar(sessionmaker, _ExtratorFalso(), lambda cliente: "ok")

    assert navegador_falso.instancias == []


async def test_chamar_loga_duracao_e_operacao_no_sucesso(sessionmaker, caplog):
    """Fase E1 (PLANO_PADRONIZACAO_FONTES.md) — log estruturado de sucesso, sem
    escalada: domínio, operação, cliente e duração aparecem no log, sem URL."""
    with caplog.at_level("INFO", logger="extractors.resiliencia"):
        resultado = await resiliencia.chamar(
            sessionmaker, _ExtratorFalso(), lambda cliente: "ok", nome_operacao="testar"
        )

    assert resultado == "ok"
    assert f"dominio={_DOMINIO}" in caplog.text
    assert "operacao=testar" in caplog.text
    assert "cliente=leve" in caplog.text
    assert "escalou=False" in caplog.text
    assert "duracao_s=" in caplog.text


async def test_chamar_loga_escalada_com_duracao_da_etapa_leve_e_cliente_final(
    sessionmaker, navegador_falso, caplog
):
    """Sessão rejeitada no cliente leve escala pro navegador (D-E1, "Mult. 1") —
    o log de escalada carrega a duração até ali, e o log final marca
    escalou=True e cliente=navegador."""
    tentativas: list[str] = []

    def operacao(cliente: ClienteDeSite) -> str:
        tentativas.append("tentativa")
        if len(tentativas) == 1:
            raise SessaoRejeitada("desafio Cloudflare")
        return "ok"

    with caplog.at_level("INFO", logger="extractors.resiliencia"):
        resultado = await resiliencia.chamar(
            sessionmaker, _ExtratorFalso(), operacao, nome_operacao="testar"
        )

    assert resultado == "ok"
    assert "escalando para o navegador" in caplog.text
    assert "operacao=testar" in caplog.text
    assert "cliente=navegador" in caplog.text
    assert "escalou=True" in caplog.text


async def test_chamar_loga_falha_direta_sem_escalada(sessionmaker, caplog):
    """Regressão: nenhum ramo de exceção logava duração antes desta correção
    — aqui, falha direta (sem `SessaoRejeitada` no meio), sem escalada."""

    def operacao(cliente: ClienteDeSite) -> str:
        raise FonteNaoEncontrada("não encontrado: http://exemplo/x", dominio=_DOMINIO)

    with caplog.at_level("WARNING", logger="extractors.resiliencia"):
        with pytest.raises(FonteNaoEncontrada):
            await resiliencia.chamar(
                sessionmaker, _ExtratorFalso(), operacao, nome_operacao="testar"
            )

    assert f"dominio={_DOMINIO}" in caplog.text
    assert "operacao=testar" in caplog.text
    assert "escalou=False" in caplog.text
    assert "duracao_s=" in caplog.text


async def test_chamar_loga_falha_de_sessao_rejeitada_sem_fallback(
    sessionmaker, navegador_falso, caplog
):
    """`SessaoRejeitada` já no cliente de navegador (`exigir_navegador=True`)
    não escala de novo — propaga direto, e o log de falha ainda sai, com
    `escalou=False`."""

    def operacao(cliente: ClienteDeSite) -> str:
        raise SessaoRejeitada("desafio Cloudflare")

    with caplog.at_level("WARNING", logger="extractors.resiliencia"):
        with pytest.raises(SessaoRejeitada):
            await resiliencia.chamar(
                sessionmaker,
                _ExtratorFalso(),
                operacao,
                nome_operacao="testar",
                exigir_navegador=True,
            )

    assert f"dominio={_DOMINIO}" in caplog.text
    assert "operacao=testar" in caplog.text
    assert "escalou=False" in caplog.text
    assert "duracao_s=" in caplog.text


async def test_chamar_loga_falha_apos_escalar_e_navegador_tambem_falhar(
    sessionmaker, navegador_falso, caplog
):
    """Sessão rejeitada no cliente leve escala pro navegador, que também
    falha — o log de falha sai com `escalou=True`."""

    def operacao(cliente: ClienteDeSite) -> str:
        raise SessaoRejeitada("desafio Cloudflare")

    with caplog.at_level("WARNING", logger="extractors.resiliencia"):
        with pytest.raises(FalhaDeExtracao):
            await resiliencia.chamar(
                sessionmaker, _ExtratorFalso(), operacao, nome_operacao="testar"
            )

    assert f"dominio={_DOMINIO}" in caplog.text
    assert "operacao=testar" in caplog.text
    assert "escalou=True" in caplog.text
    assert "duracao_s=" in caplog.text


def test_ttl_sessao_usa_o_padrao_sem_env(monkeypatch):
    monkeypatch.delenv("SLIME_SESSAO_TTL_S", raising=False)
    assert resiliencia._ttl_sessao_s() == resiliencia._TTL_SESSAO_S_PADRAO


def test_ttl_sessao_respeita_env_valida(monkeypatch):
    monkeypatch.setenv("SLIME_SESSAO_TTL_S", "3600")
    assert resiliencia._ttl_sessao_s() == 3600


@pytest.mark.parametrize("valor", ["", "abc", "0", "-10", "1.5"])
def test_ttl_sessao_cai_no_padrao_com_env_invalida(monkeypatch, caplog, valor):
    monkeypatch.setenv("SLIME_SESSAO_TTL_S", valor)
    with caplog.at_level("WARNING", logger="extractors.resiliencia"):
        assert resiliencia._ttl_sessao_s() == resiliencia._TTL_SESSAO_S_PADRAO
    assert "SLIME_SESSAO_TTL_S" in caplog.text

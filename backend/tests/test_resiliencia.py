"""Testes de `extractors/resiliencia.py` contra SQLite real, sem rede."""

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config import Config
from core.erros import FonteNaoEncontrada, SiteEmCooldown
from db.engine import criar_engine, criar_sessionmaker
from extractors import circuit_breaker, resiliencia
from extractors.base import EpisodioRemoto, ExtratorDeSite, LinkDeMidia, ResultadoBusca
from extractors.cliente import ClienteDeSite
from models.base import Base
from models.estado_site import EstadoSite

_DOMINIO = "animefire.io"


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

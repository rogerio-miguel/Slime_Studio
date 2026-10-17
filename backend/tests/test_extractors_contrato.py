"""Teste de contrato do Strategy Pattern dos extratores (ESPECIFICACAO.md §7)."""

import pytest

from fontes.adaptadores.base import EpisodioRemoto, ExtratorDeSite, LinkDeMidia, ResultadoBusca
from fontes.adaptadores.registro import EXTRATORES
from fontes.rede.cliente import ClienteDeSite


class _ExtratorFalso(ExtratorDeSite):
    """Implementação mínima e completa, usada só para provar que o contrato é
    instanciável quando todo método abstrato está implementado."""

    @property
    def dominio(self) -> str:
        return "falso.teste"

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


class _ExtratorIncompleto(ExtratorDeSite):
    """Falta `resolver_midia` — a instanciação deve falhar."""

    @property
    def dominio(self) -> str:
        return "incompleto.teste"

    @property
    def exige_navegador(self) -> bool:
        return False

    def buscar(self, cliente: ClienteDeSite, titulo: str) -> list[ResultadoBusca]:
        return []

    def listar_episodios(
        self, cliente: ClienteDeSite, identificador: str
    ) -> list[EpisodioRemoto]:
        return []


def test_extrator_incompleto_falha_ao_instanciar():
    with pytest.raises(TypeError):
        _ExtratorIncompleto()


def test_extrator_falso_instancia_normalmente():
    extrator = _ExtratorFalso()
    assert extrator.dominio == "falso.teste"
    assert extrator.exige_navegador is False


@pytest.mark.parametrize("extrator", EXTRATORES, ids=lambda extrator: extrator.dominio)
def test_extratores_registrados_tem_dominio_nao_vazio(extrator: ExtratorDeSite):
    assert extrator.dominio
    assert isinstance(extrator.exige_navegador, bool)

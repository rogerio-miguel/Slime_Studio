"""Fallback entre fontes já mapeadas na listagem (`fontes._listar_com_alternativas`),
usado só pela sondagem: o anime 163 falhava no MeusAnimes (Cloudflare) embora
também estivesse mapeado no AnimeFire."""

from types import SimpleNamespace

import pytest

from api.servicos import fontes
from core.enums import VersaoDeFonte, VersaoEpisodio
from core.erros import FalhaDeExtracao, SessaoRejeitada
from extractors.base import EpisodioRemoto
from extractors.resolucao import FonteResolvida

_ESCOLHIDA = FonteResolvida("meusanimes", "m", VersaoDeFonte.DUBLADO)
_ALTERNATIVA = FonteResolvida("animefire.one", "a", VersaoDeFonte.DUBLADO)
_ANIME = SimpleNamespace(id=163, numero_temporada=2)
_EPISODIOS = [EpisodioRemoto(rotulo="1", numero=1, url="https://site/1")]


@pytest.fixture
def listagem(monkeypatch):
    """`falham`: domínios que levantam; `consultas`: pedidos de alternativas."""
    estado = SimpleNamespace(falham={}, consultas=0)

    async def _listar(_sessionmaker, dominio, _identificador, _temporada):
        if dominio in estado.falham:
            raise estado.falham[dominio]
        return _EPISODIOS

    async def _alternativas(_sessionmaker, _anime, _versao, *, excluir_dominio):
        estado.consultas += 1
        assert excluir_dominio == _ESCOLHIDA.dominio
        return [_ALTERNATIVA]

    monkeypatch.setattr(fontes, "listar_episodios_em", _listar)
    monkeypatch.setattr(fontes, "fontes_mapeadas_alternativas", _alternativas)
    return estado


async def _chamar(tentar: bool):
    return await fontes._listar_com_alternativas(
        None, _ANIME, VersaoEpisodio.DUBLADO, _ESCOLHIDA, tentar
    )


async def test_escolhida_que_funciona_nao_consulta_alternativas(listagem):
    fonte, episodios = await _chamar(True)

    assert fonte == _ESCOLHIDA
    assert episodios == _EPISODIOS
    assert listagem.consultas == 0


async def test_escolhida_que_falha_cai_na_alternativa(listagem):
    listagem.falham["meusanimes"] = SessaoRejeitada("cloudflare")

    fonte, episodios = await _chamar(True)

    assert fonte == _ALTERNATIVA
    assert episodios == _EPISODIOS


async def test_sem_alternativas_habilitadas_propaga_a_falha(listagem):
    listagem.falham["meusanimes"] = SessaoRejeitada("cloudflare")

    with pytest.raises(SessaoRejeitada):
        await _chamar(False)

    assert listagem.consultas == 0


async def test_todas_falhando_propaga_o_primeiro_erro(listagem):
    primeiro = SessaoRejeitada("cloudflare")
    listagem.falham["meusanimes"] = primeiro
    listagem.falham["animefire.one"] = FalhaDeExtracao("fora do ar")

    with pytest.raises(SessaoRejeitada) as excinfo:
        await _chamar(True)

    assert excinfo.value is primeiro

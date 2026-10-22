"""Política pura de ciclo de vida (`core/ciclo_de_vida.py`): tabela de decisões
com `hoje` fixo, incluindo os casos reais do catálogo que motivaram a regra."""

from datetime import UTC, date, datetime, timedelta

import pytest

from core.ciclo_de_vida import (
    Fase,
    RetratoDoAnime,
    deve_atualizar_status,
    deve_resolver_fonte,
    deve_sondar_fonte,
    fase_do_anime,
    proxima_sondagem_apos_sucesso,
    proxima_tentativa,
)
from core.enums import ResultadoDeVerificacao as R
from core.enums import StatusLancamento as S

_HOJE = date(2026, 10, 11)


def _retrato(status, estreia=None, total=None, na_fonte=None) -> RetratoDoAnime:
    return RetratoDoAnime(status, estreia, total, na_fonte)


@pytest.mark.parametrize(
    ("retrato", "fase", "sonda", "atualiza_status"),
    [
        # status ainda não aquecido: só consulta o status, não sonda a fonte
        (_retrato(None), Fase.DESCONHECIDA, False, True),
        # bookmark de estreia (ex. 172): segue reconsultado até estrear
        (_retrato(S.NAO_LANCADO, date(2026, 10, 11)), Fase.PRE_ESTREIA, False, True),
        (_retrato(S.NAO_LANCADO), Fase.PRE_ESTREIA, False, True),
        # em lançamento (ex. 163)
        (_retrato(S.EM_LANCAMENTO, date(2026, 10, 9), None, 0), Fase.EM_LANCAMENTO, True, True),
        # FINALIZADO antigo e incompleto (ex. 58, 2015, 12 de 13): arquivo
        (_retrato(S.FINALIZADO, date(2015, 1, 9), 13, 12), Fase.ARQUIVO, False, False),
        # FINALIZADO recente e incompleto (ex. 161): janela pós-fim
        (_retrato(S.FINALIZADO, date(2026, 7, 10), 12, 11), Fase.POS_FIM, True, False),
        # FINALIZADO completo, sem total ou sem estreia: arquivo
        (_retrato(S.FINALIZADO, date(2026, 7, 10), 12, 12), Fase.ARQUIVO, False, False),
        (_retrato(S.FINALIZADO, date(2026, 7, 10), None, 3), Fase.ARQUIVO, False, False),
        (_retrato(S.FINALIZADO, None, 12, 3), Fase.ARQUIVO, False, False),
        (_retrato(S.CANCELADO, date(2026, 7, 10), 12, 3), Fase.ARQUIVO, False, False),
        (_retrato(S.HIATO), Fase.ARQUIVO, False, False),
    ],
)
def test_fase_e_decisoes(retrato, fase, sonda, atualiza_status):
    assert fase_do_anime(retrato, _HOJE) is fase
    assert deve_sondar_fonte(retrato, _HOJE) is sonda
    assert deve_atualizar_status(retrato, _HOJE) is atualiza_status


def test_janela_pos_fim_fecha_45_dias_depois_do_fim_previsto():
    estreia = date(2026, 1, 1)
    fim_previsto = estreia + timedelta(weeks=12)
    retrato = _retrato(S.FINALIZADO, estreia, 12, 11)

    assert fase_do_anime(retrato, fim_previsto + timedelta(days=45)) is Fase.POS_FIM
    assert fase_do_anime(retrato, fim_previsto + timedelta(days=46)) is Fase.ARQUIVO


@pytest.mark.parametrize(
    ("retrato", "tem_episodios", "temporada_nova", "resolve"),
    [
        # estreia que virou EM_LANCAMENTO sem nunca ter sido aberta (ex. 172)
        (_retrato(S.EM_LANCAMENTO, date(2026, 10, 11)), False, False, True),
        # ainda não estreou: nada a procurar
        (_retrato(S.NAO_LANCADO, date(2026, 10, 18)), False, False, False),
        # fonte perdida: FINALIZADO antigo, mas com episódio capturado
        (_retrato(S.FINALIZADO, date(2015, 1, 9), 13, 13), True, False, True),
        # arquivo sem episódio e sem motivo: não gasta varredura
        (_retrato(S.FINALIZADO, date(2015, 1, 9), 13, 13), False, False, False),
        # continuação de franquia que o usuário terminou
        (_retrato(S.FINALIZADO, date(2024, 1, 9), 12, 12), False, True, True),
    ],
)
def test_deve_resolver_fonte(retrato, tem_episodios, temporada_nova, resolve):
    assert (
        deve_resolver_fonte(
            retrato, _HOJE, tem_episodios=tem_episodios, temporada_nova=temporada_nova
        )
        is resolve
    )


# --- backoff ---


def _intervalo(resultado, falhas):
    agora = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)
    return proxima_tentativa(resultado, falhas, agora) - agora


@pytest.mark.parametrize(
    ("resultado", "falhas", "esperado"),
    [
        (R.OK, 0, timedelta(hours=6)),
        (R.SITE_INDISPONIVEL, 3, timedelta(minutes=15)),
        (R.PRECISA_SESSAO, 5, timedelta(hours=3)),
        (R.AMBIGUO, 1, timedelta(days=7)),
        (R.NAO_ENCONTRADO, 1, timedelta(hours=6)),
        (R.NAO_ENCONTRADO, 2, timedelta(hours=12)),
        (R.NAO_ENCONTRADO, 10, timedelta(days=7)),  # teto
        (R.ERRO, 1, timedelta(hours=1)),
        (R.ERRO, 3, timedelta(hours=4)),
        (R.ERRO, 99, timedelta(hours=24)),  # teto, sem overflow
    ],
)
def test_proxima_tentativa(resultado, falhas, esperado):
    assert _intervalo(resultado, falhas) == esperado


# --- cadência ancorada no episódio ---

_AGORA = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("proximo_ep_em", "em_dia", "esperado"),
    [
        # sem âncora: intervalo padrão
        (None, True, timedelta(hours=6)),
        (None, False, timedelta(hours=6)),
        # fonte atrasada: o faltante saiu em proximo_ep_em - 7d; degraus por idade
        (_AGORA + timedelta(days=7, hours=-5), False, timedelta(hours=1)),  # saiu há 5 h
        (_AGORA + timedelta(days=7, hours=-11), False, timedelta(hours=1)),
        (_AGORA + timedelta(days=7, hours=-13), False, timedelta(hours=3)),  # saiu há 13 h
        (_AGORA + timedelta(days=7, hours=-47), False, timedelta(hours=3)),
        (_AGORA + timedelta(days=7, hours=-49), False, timedelta(hours=6)),  # passou dos degraus
        # âncora a menos/mais de uma semana do faltante (quinzenal, pausa): padrão
        (_AGORA + timedelta(days=8), False, timedelta(hours=6)),
        (_AGORA + timedelta(hours=3), False, timedelta(hours=6)),
        # episódio previsto para daqui a 3 h: dorme até +2h depois dele
        (_AGORA + timedelta(hours=3), True, timedelta(hours=5)),
        # âncora distante (ou desatualizada): teto de 24 h
        (_AGORA + timedelta(days=5), True, timedelta(hours=24)),
        # episódio saiu há 30 min: primeiro passo (+2h) ainda no futuro
        (_AGORA - timedelta(minutes=30), True, timedelta(hours=1, minutes=30)),
        # saiu há 3 h: passo de +6h
        (_AGORA - timedelta(hours=3), True, timedelta(hours=3)),
        # saiu há 7 h: passo de +12h
        (_AGORA - timedelta(hours=7), True, timedelta(hours=5)),
        # saiu há 20 h: passo de +24h
        (_AGORA - timedelta(hours=20), True, timedelta(hours=4)),
        # saiu há 3 dias e a fonte segue em dia: volta ao padrão
        (_AGORA - timedelta(days=3), True, timedelta(hours=6)),
    ],
)
def test_proxima_sondagem_apos_sucesso(proximo_ep_em, em_dia, esperado):
    assert proxima_sondagem_apos_sucesso(proximo_ep_em, em_dia, _AGORA) - _AGORA == esperado

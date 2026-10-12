"""`api/rotas/animes.py::_temporadas_e_proxima` — seletor de temporada da página do
anime, com as partes de uma mesma temporada colapsadas numa entrada."""

from types import SimpleNamespace

from core.enums import StatusLancamento


def test_seletor_colapsa_partes_da_mesma_temporada_numa_entrada():
    from api.rotas.animes import _temporadas_e_proxima

    def _linha(id_: int, numero: int, total: int, tem_episodios: bool):
        return SimpleNamespace(
            id=id_,
            numero_temporada=numero,
            titulo=f"T{numero}",
            status_lancamento=StatusLancamento.FINALIZADO,
            estreia_em=None,
            ano=None,
            formato_midia=None,
            total_episodios_anilist=total,
            tem_episodios=tem_episodios,
        )

    # T2 dividida: 43 (Part 1, com episódios) e 143 (Part 2, sem nada capturado).
    grupo = [_linha(42, 1, 24, True), _linha(43, 2, 12, True), _linha(143, 2, 12, False)]

    temporadas, _ = _temporadas_e_proxima(42, 1, grupo)

    assert [(t.id, t.numero_temporada, t.total_episodios) for t in temporadas] == [
        (42, 1, 24),
        (43, 2, 24),
    ]
    assert temporadas[1].ids_das_partes == [143]

    # Aberta pela Part 2, ela continua sendo a entrada marcada no seletor.
    temporadas, _ = _temporadas_e_proxima(143, 2, grupo)
    assert [t.id for t in temporadas] == [42, 143]
    assert temporadas[1].ids_das_partes == [43]


def test_parte_nova_de_temporada_existente_vira_proxima_como_nova_parte():
    from api.rotas.animes import _temporadas_e_proxima

    def _linha(id_: int, numero: int, status: StatusLancamento, tem_episodios: bool):
        return SimpleNamespace(
            id=id_,
            numero_temporada=numero,
            titulo=f"T{numero}",
            status_lancamento=status,
            estreia_em=None,
            ano=2027,
            formato_midia=None,
            total_episodios_anilist=None,
            tem_episodios=tem_episodios,
        )

    # Slime: T4 (22) existe; "4th Season Part 3" (144) é parte dela, não a "4ª temporada".
    grupo = [
        _linha(42, 1, StatusLancamento.FINALIZADO, True),
        _linha(22, 4, StatusLancamento.FINALIZADO, True),
        _linha(144, 4, StatusLancamento.NAO_LANCADO, False),
    ]

    for aberto, numero in ((42, 1), (22, 4)):
        _, proxima = _temporadas_e_proxima(aberto, numero, grupo)
        assert (proxima.id, proxima.nova_parte) == (144, True)

    # Uma temporada genuinamente nova (número acima) continua sem o marcador.
    grupo.append(_linha(200, 5, StatusLancamento.NAO_LANCADO, False))
    grupo.remove(grupo[2])
    _, proxima = _temporadas_e_proxima(22, 4, grupo)
    assert (proxima.id, proxima.nova_parte) == (200, False)

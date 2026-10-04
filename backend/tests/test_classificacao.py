"""Classificação série×extra (`integrations/classificacao.py`) e o que o adapter
AniList faz com ela. Os casos nomeados vêm do catálogo real e da amostra de 400
itens que calibrou as regras (2026-10-03)."""

import pytest

from integrations import servico
from integrations.anilist import AniListProvider, _item_para_anime_em_alta
from integrations.base import NoDeSerie, RelacoesDeAnime
from integrations.classificacao import eh_serie


@pytest.mark.parametrize(
    ("formato", "episodios", "duracao", "tem_pai", "serie"),
    [
        ("TV", 12, 24, False, True),
        ("TV_SHORT", 12, 5, False, True),
        ("TV", 12, 24, True, True),  # TV com PARENT segue série (ex. spin-off TV)
        (None, None, None, False, True),  # feed sem `format`
        ("ONA", 24, 12, False, True),  # NEET Kunoichi
        ("ONA", 14, 20, False, True),  # Wan Ren Zhi Shang
        ("ONA", None, None, False, True),  # Tensei Dai Seijo: estreou sem eps/duração
        ("ONA", 12, 14, True, False),  # Koyomimonogatari: PARENT TV
        ("ONA", 2, 24, True, False),  # BNHA Survival
        ("ONA", 2, 24, False, False),  # filme/curta em ONA sem pai
        ("ONA", 1, 100, False, False),  # Bubble
        ("ONA", 3, 24, False, True),
        ("MOVIE", 1, 102, True, False),
        ("MOVIE", 1, 100, False, False),
        ("SPECIAL", 12, 3, False, False),
        ("MUSIC", 1, 4, False, False),
        ("OVA", 10, 50, False, True),  # Hellsing
        ("OVA", 110, 26, False, True),  # Ginga Eiyuu Densetsu
        ("OVA", 6, 13, True, False),  # One Punch Man OVA: PARENT TV
        ("OVA", 2, 12, True, False),  # NEET Kunoichi OVAs: PARENT ONA
        ("OVA", 6, 12, False, False),  # curto demais pra série
        ("OVA", None, None, False, False),  # OVA sem dado: conservador
    ],
)
def test_eh_serie(
    formato: str | None, episodios: int | None, duracao: int | None, tem_pai: bool, serie: bool
):
    assert eh_serie(formato, episodios, duracao, tem_pai) is serie


@pytest.mark.parametrize(
    ("item", "formato"),
    [
        ({"id": 1, "format": "TV", "episodes": 12}, None),
        ({"id": 2, "format": "ONA", "episodes": 14, "duration": 20}, None),
        ({"id": 3, "format": "ONA"}, None),
        ({"id": 4, "format": "MOVIE", "episodes": 1, "duration": 102}, "MOVIE"),
        ({"id": 5, "format": "OVA", "episodes": 2, "duration": 25}, "OVA"),
        ({"id": 6, "format": "ONA", "episodes": 1, "duration": 47}, "ONA"),
        ({"id": 7}, None),
    ],
)
def test_item_do_feed_so_vira_extra_quando_a_regra_manda(item: dict, formato: str | None):
    assert _item_para_anime_em_alta(item).formato == formato


class _Resposta:
    status_code = 200

    def __init__(self, media: dict):
        self._media = media

    def json(self) -> dict:
        return {"data": {"Media": self._media}}

    def raise_for_status(self) -> None:
        return None


def _com_media(monkeypatch: pytest.MonkeyPatch, media: dict) -> AniListProvider:
    monkeypatch.setattr("integrations.anilist.requests.post", lambda *a, **k: _Resposta(media))
    return AniListProvider()


def _aresta(tipo: str, ident: int, formato: str) -> dict:
    return {
        "relationType": tipo,
        "node": {"id": ident, "type": "ANIME", "format": formato, "title": {"romaji": f"n{ident}"}},
    }


def test_buscar_relacoes_expoe_formato_proprio_e_aresta_de_pai(monkeypatch: pytest.MonkeyPatch):
    provedor = _com_media(
        monkeypatch,
        {
            "id": 185992,
            "title": {"romaji": "NEET Kunoichi OVAs"},
            "format": "ONA",
            "episodes": 2,
            "duration": 12,
            "relations": {"edges": [_aresta("PARENT", 174654, "ONA")]},
        },
    )

    relacoes = provedor.buscar_relacoes(185992)

    assert relacoes is not None
    assert (relacoes.formato, relacoes.episodios, relacoes.duracao_min, relacoes.tem_pai) == (
        "ONA",
        2,
        12,
        True,
    )


def test_buscar_relacoes_sem_dados_do_proprio_no_nao_inventa_nada(monkeypatch: pytest.MonkeyPatch):
    provedor = _com_media(
        monkeypatch,
        {
            "id": 187402,
            "title": {"romaji": "Tensei Dai Seijo"},
            "format": "ONA",
            "episodes": None,
            "duration": None,
            "relations": {
                "edges": [{"relationType": "ADAPTATION", "node": {"id": 1, "type": "MANGA"}}]
            },
        },
    )

    relacoes = provedor.buscar_relacoes(187402)

    assert relacoes is not None
    assert (relacoes.episodios, relacoes.duracao_min, relacoes.tem_pai) == (None, None, False)


def test_walk_aceita_ona_como_prequel_e_sequel(monkeypatch: pytest.MonkeyPatch):
    """Cadeias ONA↔ONA e TV↔ONA (Baki, Sakamoto Days) entram no walk; OVA fica fora."""
    provedor = _com_media(
        monkeypatch,
        {
            "id": 10,
            "title": {"romaji": "T2"},
            "format": "ONA",
            "relations": {
                "edges": [
                    _aresta("PREQUEL", 9, "ONA"),
                    _aresta("PREQUEL", 8, "OVA"),
                    _aresta("SEQUEL", 11, "TV"),
                ]
            },
        },
    )

    relacoes = provedor.buscar_relacoes(10)

    assert relacoes is not None
    assert [no.anilist_id for no in relacoes.prequels] == [9]
    assert [no.anilist_id for no in relacoes.sequels] == [11]


def test_serie_pai_prefere_parent_e_aceita_ona(monkeypatch: pytest.MonkeyPatch):
    provedor = _com_media(
        monkeypatch,
        {
            "id": 185992,
            "title": {"romaji": "extra"},
            "relations": {
                "edges": [
                    _aresta("SIDE_STORY", 5, "TV"),
                    _aresta("PARENT", 174654, "ONA"),
                    _aresta("ALTERNATIVE", 6, "MOVIE"),
                ]
            },
        },
    )

    pai = provedor.buscar_serie_pai(185992)

    assert pai is not None
    assert pai.anilist_id == 174654


def test_serie_pai_sem_no_de_temporada_devolve_none(monkeypatch: pytest.MonkeyPatch):
    provedor = _com_media(
        monkeypatch,
        {
            "id": 1,
            "title": {"romaji": "x"},
            "relations": {"edges": [_aresta("PARENT", 2, "MOVIE")]},
        },
    )

    assert provedor.buscar_serie_pai(1) is None


def _relacoes(formato: str | None, episodios: int | None, duracao: int | None, tem_pai: bool):
    async def _fake(_capazes, _anilist_id):
        if formato == "SEM_RESPOSTA":
            return None
        return RelacoesDeAnime(
            no=NoDeSerie(anilist_id=1, titulo="x", ano=None, mes=None),
            prequels=(),
            formato=formato,
            episodios=episodios,
            duracao_min=duracao,
            tem_pai=tem_pai,
        )

    return _fake


@pytest.mark.parametrize(
    ("formato", "episodios", "duracao", "tem_pai", "esperado", "extra"),
    [
        ("ONA", None, None, False, ("ONA", True), None),  # 140: estreou sem dados
        ("ONA", 12, 14, True, ("ONA", False), "ONA"),  # Koyomimonogatari
        ("MOVIE", 1, 102, True, ("MOVIE", False), "MOVIE"),
        ("TV", 12, 24, True, ("TV", True), None),
        (None, 12, 24, False, None, None),  # AniList sem `format`: não sei
        ("SEM_RESPOSTA", None, None, False, None, None),  # provedor não respondeu: não sei
    ],
)
async def test_classificar_midia_distingue_serie_extra_e_nao_sei(
    monkeypatch: pytest.MonkeyPatch,
    formato: str | None,
    episodios: int | None,
    duracao: int | None,
    tem_pai: bool,
    esperado: tuple[str, bool] | None,
    extra: str | None,
):
    monkeypatch.setattr(servico, "PROVEDORES", (AniListProvider(),))
    monkeypatch.setattr(
        servico, "_buscar_relacoes_em_cadeia", _relacoes(formato, episodios, duracao, tem_pai)
    )

    assert await servico.classificar_midia(1) == esperado
    assert await servico.formato_se_extra(1) == extra


def test_relacoes_do_mesmo_anime_custam_uma_chamada_so(monkeypatch: pytest.MonkeyPatch):
    """Classificação, walk e `buscar_serie_pai` leem as relações do mesmo id em
    seguida: a 2ª e a 3ª leitura saem do cache, ids diferentes não se misturam."""
    chamadas: list[int] = []
    media = {
        "id": 185992,
        "title": {"romaji": "extra"},
        "format": "ONA",
        "relations": {"edges": [_aresta("PARENT", 174654, "ONA")]},
    }

    def _post(*_args, **kwargs):
        chamadas.append(kwargs["json"]["variables"]["id"])
        return _Resposta(media)

    monkeypatch.setattr("integrations.anilist.requests.post", _post)
    provedor = AniListProvider()

    provedor.buscar_relacoes(185992)
    provedor.buscar_serie_pai(185992)
    provedor.buscar_relacoes(185992)
    assert chamadas == [185992]

    provedor.buscar_relacoes(174654)
    assert chamadas == [185992, 174654]

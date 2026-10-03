import pytest

from api.servicos import descoberta
from core.conteudo_adulto import eh_conteudo_adulto
from integrations.base import AnimeEmAlta


@pytest.mark.parametrize(
    ("generos", "esperado"),
    [
        (["Action", "Hentai"], True),
        ([" hentai "], True),
        (["Ecchi", "Comedy"], False),
        ([], False),
        (None, False),
    ],
)
def test_eh_conteudo_adulto(generos, esperado):
    assert eh_conteudo_adulto(generos) is esperado


def _item(anilist_id: int, generos: tuple[str, ...]) -> AnimeEmAlta:
    return AnimeEmAlta(
        titulo_romaji=f"t{anilist_id}",
        titulo_ingles=None,
        capa_url=None,
        banner_url=None,
        anilist_id=anilist_id,
        generos=generos,
    )


async def test_cruzamento_descarta_hentai(monkeypatch):
    async def _vazio(_sessionmaker, _chaves):
        return {}

    monkeypatch.setattr(descoberta, "localizar_animes_por_anilist_id", _vazio)
    monkeypatch.setattr(descoberta, "localizar_animes_por_slug", _vazio)

    pares = await descoberta._cruzar_com_catalogo(
        None, [_item(1, ("Action",)), _item(2, ("Hentai",))]
    )

    assert [item.anilist_id for item, _ in pares] == [1]

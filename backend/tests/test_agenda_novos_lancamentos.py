from datetime import UTC, datetime

from integrations.anilist import _agenda_para_animes_em_alta


def _no(media_id: int, episodio: int, instante: int | None) -> dict:
    no = {
        "episode": episodio,
        "media": {"id": media_id, "title": {"romaji": f"Anime {media_id}"}},
    }
    if instante is not None:
        no["airingAt"] = instante
    return no


def test_agenda_guarda_o_instante_em_que_o_episodio_foi_ao_ar():
    dados = {"Page": {"airingSchedules": [_no(1, 3, 1_760_000_000)]}}

    [item] = _agenda_para_animes_em_alta(dados)

    assert item.episodio_lancado == 3
    assert item.episodio_lancado_em == datetime.fromtimestamp(1_760_000_000, tz=UTC)


def test_agenda_sem_airing_at_deixa_o_instante_vazio():
    dados = {"Page": {"airingSchedules": [_no(1, 3, None)]}}

    [item] = _agenda_para_animes_em_alta(dados)

    assert item.episodio_lancado_em is None


def test_agenda_mantem_o_episodio_mais_recente_de_cada_anime():
    dados = {"Page": {"airingSchedules": [_no(1, 4, 1_760_100_000), _no(1, 3, 1_760_000_000)]}}

    [item] = _agenda_para_animes_em_alta(dados)

    assert item.episodio_lancado == 4
    assert item.episodio_lancado_em == datetime.fromtimestamp(1_760_100_000, tz=UTC)

"""Testes de `core/temporada.py::separar_temporada` — extração do número de
temporada a partir do título, usada pela resolução de arte via TMDB."""

from core.temporada import separar_temporada


def test_season_n():
    assert separar_temporada("Attack on Titan Season 3") == ("Attack on Titan", 3)


def test_n_season():
    assert separar_temporada("Attack on Titan 3rd Season") == ("Attack on Titan", 3)


def test_n_ordinal_temporada_ptbr():
    assert separar_temporada("Anime Legal 3ª Temporada") == ("Anime Legal", 3)


def test_temporada_n_ptbr():
    assert separar_temporada("Anime Legal Temporada 3") == ("Anime Legal", 3)


def test_romano_ii():
    assert separar_temporada("Overlord II") == ("Overlord", 2)


def test_romano_iii():
    assert separar_temporada("Overlord III") == ("Overlord", 3)


def test_romano_iv():
    assert separar_temporada("Overlord IV") == ("Overlord", 4)


def test_case_insensitive():
    assert separar_temporada("Overlord season 2") == ("Overlord", 2)
    assert separar_temporada("Overlord ii") == ("Overlord", 2)
    assert separar_temporada("Anime temporada 4") == ("Anime", 4)


def test_laco_season_e_part_empilhados():
    resultado = separar_temporada("Shingeki no Kyojin Season 3 Part 2")
    assert resultado == ("Shingeki no Kyojin", 3)


def test_part_sozinho_descarta_mas_nao_vira_numero():
    assert separar_temporada("Anime Legal Part 2") == ("Anime Legal", None)


def test_cour_sozinho_descarta_mas_nao_vira_numero():
    assert separar_temporada("Anime Legal Cour 2") == ("Anime Legal", None)


def test_tv_sozinho_descarta_mas_nao_vira_numero():
    assert separar_temporada("Anime Legal (TV)") == ("Anime Legal", None)


def test_ano_entre_parenteses_descarta_mas_nao_vira_numero():
    assert separar_temporada("Anime Legal (2024)") == ("Anime Legal", None)


def test_marcadores_empilhados_tv_e_season():
    assert separar_temporada("Anime Legal Season 2 (TV)") == ("Anime Legal", 2)


def test_marcadores_empilhados_ano_e_part():
    assert separar_temporada("Anime Legal (2024) Part 1") == ("Anime Legal", None)


def test_marcadores_empilhados_cour_e_romano():
    assert separar_temporada("Overlord III Cour 2") == ("Overlord", 3)


def test_torii_nao_e_confundido_com_romano():
    assert separar_temporada("Torii") == ("Torii", None)


def test_steins_gate_0_nao_muda():
    assert separar_temporada("Steins;Gate 0") == ("Steins;Gate 0", None)


def test_86_nao_muda():
    assert separar_temporada("86") == ("86", None)


def test_91_days_nao_muda():
    assert separar_temporada("91 Days") == ("91 Days", None)


def test_titulo_sem_marcador_devolve_intacto():
    assert separar_temporada("One Piece") == ("One Piece", None)

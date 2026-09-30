"""Corpos de escrita: `extra="forbid"` e tetos de tamanho (`api/esquemas.py`)."""

import pytest
from httpx import AsyncClient
from pydantic import ValidationError

from api.esquemas import ConfirmarFonteRequest, CriarAnimeRequest, CriarJobSiteRequest

# Exatamente os campos que `frontend/src/api/recursos.js::criarAnime` monta.
_CORPO_DO_FRONTEND = {
    "titulo": "Slime",
    "ano": None,
    "anilist_id": None,
    "kitsu_id": None,
    "capa_url": None,
    "sinopse": None,
    "banner_url": None,
    "capa_cor": None,
    "generos": None,
    "titulo_ingles": None,
    "formato": None,
}


def test_criar_anime_aceita_o_corpo_que_o_frontend_monta():
    CriarAnimeRequest.model_validate(_CORPO_DO_FRONTEND)


def test_criar_job_site_aceita_o_corpo_que_o_frontend_monta():
    CriarJobSiteRequest.model_validate(
        {
            "modo": "site",
            "anime_id": 1,
            "numero": 1,
            "tipo": "regular",
            "versao": "legendado",
            "duracao_esperada_s": None,
        }
    )


def test_confirmar_fonte_aceita_o_corpo_que_o_frontend_monta():
    ConfirmarFonteRequest.model_validate(
        {
            "dominio": "animefire.one",
            "identificador": "42",
            "titulo_exibicao": "X",
            "url": "https://animefire.one/anime/42",
            "versao": None,
        }
    )


@pytest.mark.parametrize(
    ("campo", "valor"),
    [
        ("titulo", "x" * 301),
        ("sinopse", "x" * 20001),
        ("capa_url", "https://x/" + "a" * 2050),
        ("titulo_ingles", "x" * 301),
        ("capa_cor", "x" * 33),
        ("generos", ["g"] * 51),
        ("generos", ["g" * 61]),
    ],
)
def test_criar_anime_recusa_campo_acima_do_teto(campo: str, valor):
    with pytest.raises(ValidationError):
        CriarAnimeRequest.model_validate({**_CORPO_DO_FRONTEND, campo: valor})


async def test_criar_anime_com_campo_extra_422(cliente: AsyncClient):
    resposta = await cliente.post("/api/admin/animes", json={"titulo": "X", "intruso": 1})

    assert resposta.status_code == 422


async def test_criar_job_com_campo_extra_422(cliente: AsyncClient):
    resposta = await cliente.post(
        "/api/admin/jobs",
        json={"modo": "site", "anime_id": 1, "numero": 1, "tipo": "regular", "intruso": 1},
    )

    assert resposta.status_code == 422


async def test_confirmar_fonte_com_campo_extra_422(cliente: AsyncClient):
    resposta = await cliente.post(
        "/api/admin/animes/1/fontes/confirmar",
        json={
            "dominio": "animefire.one",
            "identificador": "42",
            "titulo_exibicao": "X",
            "url": "https://animefire.one/anime/42",
            "intruso": 1,
        },
    )

    assert resposta.status_code == 422

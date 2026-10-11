"""`GET /api/admin/verificacoes` (`api/rotas/verificacoes.py`) e o log estruturado de
`db/verificacao.registrar_resultado`."""

import logging
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.enums import ResultadoDeVerificacao, TarefaDeVerificacao
from db import verificacao
from models.anime import Anime

_SessionMaker = async_sessionmaker[AsyncSession]


async def _criar_anime(sessionmaker: _SessionMaker, titulo: str) -> int:
    async with sessionmaker() as sessao:
        anime = Anime(titulo=titulo, slug=titulo.lower().replace(" ", "-"))
        sessao.add(anime)
        await sessao.commit()
        return anime.id


async def test_lista_vazia_sem_verificacoes(cliente: AsyncClient):
    resposta = await cliente.get("/api/admin/verificacoes")

    assert resposta.status_code == 200
    assert resposta.json() == []


async def test_expoe_estado_e_filtra_por_anime(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker
):
    a = await _criar_anime(sessionmaker_api, "Anime A")
    b = await _criar_anime(sessionmaker_api, "Anime B")
    agora = datetime.now(UTC)
    await verificacao.registrar_resultado(
        sessionmaker_api, a, TarefaDeVerificacao.FONTE, ResultadoDeVerificacao.OK, agora=agora
    )
    await verificacao.registrar_resultado(
        sessionmaker_api,
        b,
        TarefaDeVerificacao.FONTE,
        ResultadoDeVerificacao.PRECISA_SESSAO,
        detalhe="cloudflare",
        dominio="animefire.io",
        agora=agora,
    )

    todos = (await cliente.get("/api/admin/verificacoes")).json()
    so_b = (await cliente.get(f"/api/admin/verificacoes?anime_id={b}")).json()

    assert {item["anime_id"] for item in todos} == {a, b}
    assert len(so_b) == 1
    assert so_b[0]["ultimo_resultado"] == "precisa_sessao"
    assert so_b[0]["dominio"] == "animefire.io"
    assert so_b[0]["detalhe"] == "cloudflare"
    assert so_b[0]["falhas_consecutivas"] == 1
    assert so_b[0]["ultimo_sucesso_em"] is None
    assert datetime.fromisoformat(so_b[0]["proxima_em"]) > agora + timedelta(hours=2)


async def test_registrar_resultado_loga_decisao(
    sessionmaker_api: _SessionMaker, caplog
):
    anime_id = await _criar_anime(sessionmaker_api, "Anime C")

    with caplog.at_level(logging.INFO, logger="db.verificacao"):
        await verificacao.registrar_resultado(
            sessionmaker_api, anime_id, TarefaDeVerificacao.FONTE, ResultadoDeVerificacao.ERRO
        )

    mensagens = [r.getMessage() for r in caplog.records if r.name == "db.verificacao"]
    assert any(
        f"anime_id={anime_id}" in m and "resultado=erro" in m and "falhas=1" in m
        for m in mensagens
    )

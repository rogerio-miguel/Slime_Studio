"""Testes de `api/rotas/jobs.py`: criação nos dois modos, listagem/filtro,
cancelar/retry. Resolução de fonte remota (modo "site") é monkeypatchada nos
nomes importados em `api.servicos.jobs` — o comportamento de
`extractors.resolucao`/`extractors.servico` em si já tem testes próprios
(`tests/test_resolucao.py`, `tests/test_extractors_servico.py`)."""

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.enums import StatusEpisodio, StatusJob, VersaoDeFonte, VersaoEpisodio
from extractors.base import EpisodioRemoto, ResultadoBusca
from extractors.resolucao import ConfirmacaoNecessaria, FonteResolvida
from models.anime import Anime
from models.episodio import Episodio
from models.job import Job

_SessionMaker = async_sessionmaker[AsyncSession]


async def _criar_anime(sessionmaker: _SessionMaker, titulo: str) -> int:
    async with sessionmaker() as sessao:
        anime = Anime(titulo=titulo, slug=titulo.lower().replace(" ", "-"))
        sessao.add(anime)
        await sessao.commit()
        return anime.id


async def _criar_episodio_e_job(
    sessionmaker: _SessionMaker,
    anime_id: int,
    *,
    numero: int = 1,
    status: StatusJob = StatusJob.NA_FILA,
) -> tuple[int, int]:
    async with sessionmaker() as sessao:
        episodio = Episodio(
            anime_id=anime_id,
            numero=numero,
            tipo="regular",
            url_fonte="/qualquer.mkv",
            site_origem="local",
        )
        sessao.add(episodio)
        await sessao.commit()

        job = Job(episodio_id=episodio.id, status=status)
        sessao.add(job)
        await sessao.commit()
        return episodio.id, job.id


async def _criar_episodio_existente(
    sessionmaker: _SessionMaker,
    anime_id: int,
    *,
    numero: int = 1,
    status: StatusEpisodio = StatusEpisodio.PRONTO,
    versao: VersaoEpisodio = VersaoEpisodio.DESCONHECIDA,
    site_origem: str = "local",
    hls_path: str | None = None,
    capa_path: str | None = None,
    assistido_em: datetime | None = None,
    progresso_s: int | None = None,
) -> int:
    async with sessionmaker() as sessao:
        episodio = Episodio(
            anime_id=anime_id,
            numero=numero,
            tipo="regular",
            versao=versao,
            url_fonte="https://antigo/ep",
            site_origem=site_origem,
            status=status,
            hls_path=hls_path,
            capa_path=capa_path,
            tamanho_bytes=123 if hls_path else None,
            assistido_em=assistido_em,
            progresso_s=progresso_s,
            progresso_atualizado_em=datetime.now(UTC) if progresso_s is not None else None,
        )
        sessao.add(episodio)
        await sessao.commit()
        return episodio.id


async def test_criar_job_modo_local_nao_existe_na_api(cliente: AsyncClient):
    """Caminho de arquivo arbitrário do host não pode ser enfileirado por HTTP."""
    resposta = await cliente.post(
        "/api/admin/jobs",
        json={
            "modo": "local",
            "anime": "Anime Local",
            "numero": 1,
            "tipo": "regular",
            "caminho_local": "/etc/passwd",
        },
    )

    assert resposta.status_code == 422


async def test_criar_job_modo_site_anime_id_inexistente_404(cliente: AsyncClient):
    resposta = await cliente.post(
        "/api/admin/jobs",
        json={"modo": "site", "anime_id": 999999, "numero": 1, "tipo": "regular"},
    )

    assert resposta.status_code == 404


async def test_criar_job_modo_site_ambiguo_409(
    cliente: AsyncClient,
    sessionmaker_api: _SessionMaker,
    monkeypatch: pytest.MonkeyPatch,
):
    anime_id = await _criar_anime(sessionmaker_api, "Anime Ambíguo")

    async def _resolver_fake(sessionmaker, anime, versao):
        return ConfirmacaoNecessaria(
            dominio="animefire.one",
            candidatos=[
                ResultadoBusca(
                    titulo_exibicao="Anime Ambíguo A", identificador="1", url="https://x/1"
                ),
                ResultadoBusca(
                    titulo_exibicao="Anime Ambíguo B", identificador="2", url="https://x/2"
                ),
            ],
        )

    monkeypatch.setattr("api.servicos.jobs.resolver_fonte_do_anime", _resolver_fake)

    resposta = await cliente.post(
        "/api/admin/jobs",
        json={"modo": "site", "anime_id": anime_id, "numero": 1, "tipo": "regular"},
    )

    assert resposta.status_code == 409
    assert resposta.json()["detail"]["motivo"] == "fonte_ambigua"


async def test_criar_job_modo_site_episodio_nao_encontrado_404(
    cliente: AsyncClient,
    sessionmaker_api: _SessionMaker,
    monkeypatch: pytest.MonkeyPatch,
):
    anime_id = await _criar_anime(sessionmaker_api, "Anime Sem Episodio")

    async def _resolver_fake(sessionmaker, anime, versao):
        return FonteResolvida(
            dominio="animefire.one",
            identificador="42",
            versao_da_fonte=VersaoDeFonte.NAO_DIFERENCIADA,
        )

    async def _listar_fake(sessionmaker, dominio, identificador):
        return [EpisodioRemoto(rotulo="2", numero=2, url="https://x/ep2")]

    monkeypatch.setattr("api.servicos.jobs.resolver_fonte_do_anime", _resolver_fake)
    monkeypatch.setattr("api.servicos.jobs.listar_episodios_em", _listar_fake)

    resposta = await cliente.post(
        "/api/admin/jobs",
        json={"modo": "site", "anime_id": anime_id, "numero": 1, "tipo": "regular"},
    )

    assert resposta.status_code == 404


async def test_criar_job_modo_site_colisao_de_numero_usa_primeiro_e_loga(
    cliente: AsyncClient,
    sessionmaker_api: _SessionMaker,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    """Dois rótulos remotos ("7"/"07") mapeiam pro mesmo `numero=7` — regressão
    da ambiguidade introduzida por dedup-por-rótulo (extractors/base.py::
    EpisodioRemoto). Escolha determinística (1ª ocorrência) e log de aviso,
    nunca silenciosa (CLAUDE.md §4)."""
    anime_id = await _criar_anime(sessionmaker_api, "Anime Colisao")

    async def _resolver_fake(sessionmaker, anime, versao):
        return FonteResolvida(
            dominio="animefire.one",
            identificador="42",
            versao_da_fonte=VersaoDeFonte.NAO_DIFERENCIADA,
        )

    async def _listar_fake(sessionmaker, dominio, identificador):
        return [
            EpisodioRemoto(rotulo="7", numero=7, url="https://x/ep7"),
            EpisodioRemoto(rotulo="07", numero=7, url="https://x/ep07"),
        ]

    monkeypatch.setattr("api.servicos.jobs.resolver_fonte_do_anime", _resolver_fake)
    monkeypatch.setattr("api.servicos.jobs.listar_episodios_em", _listar_fake)

    with caplog.at_level("WARNING"):
        resposta = await cliente.post(
            "/api/admin/jobs",
            json={"modo": "site", "anime_id": anime_id, "numero": 7, "tipo": "regular"},
        )

    assert resposta.status_code == 201
    assert "07" in caplog.text

    async with sessionmaker_api() as sessao:
        resultado = await sessao.execute(select(Episodio).where(Episodio.anime_id == anime_id))
        episodio = resultado.scalar_one()
        assert episodio.url_fonte == "https://x/ep7"


async def test_criar_job_modo_site_versao_do_episodio_deriva_da_fonte_nao_do_request(
    cliente: AsyncClient,
    sessionmaker_api: _SessionMaker,
    monkeypatch: pytest.MonkeyPatch,
):
    """Invariante central da Fase 2 da modelagem dublado/legendado
    (`api/servicos/jobs.py::criar_job_site`): o cliente pediu `dublado`, mas a
    fonte resolvida é `NAO_DIFERENCIADA` — `Episodio.versao` persistido tem
    que ser `DESCONHECIDA`, nunca herdar o pedido do cliente."""
    anime_id = await _criar_anime(sessionmaker_api, "Anime Versao Derivada")

    async def _resolver_fake(sessionmaker, anime, versao):
        assert versao == VersaoEpisodio.DUBLADO  # propagado do request
        return FonteResolvida(
            dominio="animefire.one",
            identificador="42",
            versao_da_fonte=VersaoDeFonte.NAO_DIFERENCIADA,
        )

    async def _listar_fake(sessionmaker, dominio, identificador):
        return [EpisodioRemoto(rotulo="1", numero=1, url="https://x/ep1")]

    monkeypatch.setattr("api.servicos.jobs.resolver_fonte_do_anime", _resolver_fake)
    monkeypatch.setattr("api.servicos.jobs.listar_episodios_em", _listar_fake)

    resposta = await cliente.post(
        "/api/admin/jobs",
        json={
            "modo": "site",
            "anime_id": anime_id,
            "numero": 1,
            "tipo": "regular",
            "versao": "dublado",
        },
    )

    assert resposta.status_code == 201
    async with sessionmaker_api() as sessao:
        resultado = await sessao.execute(select(Episodio).where(Episodio.anime_id == anime_id))
        episodio = resultado.scalar_one()
        assert episodio.versao == VersaoEpisodio.DESCONHECIDA


async def test_criar_job_modo_site_reaproveita_episodio_liberado(
    cliente: AsyncClient,
    sessionmaker_api: _SessionMaker,
    monkeypatch: pytest.MonkeyPatch,
):
    """D2: episódio `LIBERADO` (Feature 1) reaproveita a linha em vez de bater
    em `uq_episodio_identidade` e propagar `EpisodioJaExiste` — `assistido_em`
    sobrevive à recaptura, mas `progresso_s`/`progresso_atualizado_em` NÃO
    (arquivo novo, posição de retomada antiga perde o sentido)."""
    anime_id = await _criar_anime(sessionmaker_api, "Anime Liberado")
    assistido_em = datetime.now(UTC)
    episodio_id = await _criar_episodio_existente(
        sessionmaker_api,
        anime_id,
        status=StatusEpisodio.LIBERADO,
        site_origem="animefire.one",
        assistido_em=assistido_em,
        progresso_s=300,
    )

    async def _resolver_fake(sessionmaker, anime, versao):
        return FonteResolvida(
            dominio="animefire.one",
            identificador="42",
            versao_da_fonte=VersaoDeFonte.NAO_DIFERENCIADA,
        )

    async def _listar_fake(sessionmaker, dominio, identificador):
        return [EpisodioRemoto(rotulo="1", numero=1, url="https://x/ep1-recapturado")]

    monkeypatch.setattr("api.servicos.jobs.resolver_fonte_do_anime", _resolver_fake)
    monkeypatch.setattr("api.servicos.jobs.listar_episodios_em", _listar_fake)

    resposta = await cliente.post(
        "/api/admin/jobs",
        json={"modo": "site", "anime_id": anime_id, "numero": 1, "tipo": "regular"},
    )

    assert resposta.status_code == 201

    async with sessionmaker_api() as sessao:
        episodio = await sessao.get(Episodio, episodio_id)
        assert episodio.status == StatusEpisodio.PENDENTE
        assert episodio.url_fonte == "https://x/ep1-recapturado"
        assert episodio.site_origem == "animefire.one"
        assert episodio.hls_path is None
        assert episodio.assistido_em is not None
        assert episodio.progresso_s is None
        assert episodio.progresso_atualizado_em is None

        todos = (
            await sessao.execute(select(Episodio).where(Episodio.anime_id == anime_id))
        ).scalars().all()
    assert len(todos) == 1  # reaproveitou a linha, não criou outra


async def test_criar_job_modo_site_reaproveita_episodio_falhou(
    cliente: AsyncClient,
    sessionmaker_api: _SessionMaker,
    monkeypatch: pytest.MonkeyPatch,
):
    """D2: episódio `FALHOU` (esgotou as retentativas de extração,
    `worker/executor.py::_MAX_TENTATIVAS_EXTRACAO`) reaproveita a linha como
    `LIBERADO` — sem isto o aviso de falha ficava preso pra sempre, mesmo
    recarregando a página, sem caminho de retentativa pelo frontend."""
    anime_id = await _criar_anime(sessionmaker_api, "Anime Falhou")
    episodio_id = await _criar_episodio_existente(
        sessionmaker_api,
        anime_id,
        status=StatusEpisodio.FALHOU,
        site_origem="animefire.one",
    )

    async def _resolver_fake(sessionmaker, anime, versao):
        return FonteResolvida(
            dominio="animefire.one",
            identificador="42",
            versao_da_fonte=VersaoDeFonte.NAO_DIFERENCIADA,
        )

    async def _listar_fake(sessionmaker, dominio, identificador):
        return [EpisodioRemoto(rotulo="1", numero=1, url="https://x/ep1-recapturado")]

    monkeypatch.setattr("api.servicos.jobs.resolver_fonte_do_anime", _resolver_fake)
    monkeypatch.setattr("api.servicos.jobs.listar_episodios_em", _listar_fake)

    resposta = await cliente.post(
        "/api/admin/jobs",
        json={"modo": "site", "anime_id": anime_id, "numero": 1, "tipo": "regular"},
    )

    assert resposta.status_code == 201

    async with sessionmaker_api() as sessao:
        episodio = await sessao.get(Episodio, episodio_id)
        assert episodio.status == StatusEpisodio.PENDENTE
        assert episodio.url_fonte == "https://x/ep1-recapturado"

        todos = (
            await sessao.execute(select(Episodio).where(Episodio.anime_id == anime_id))
        ).scalars().all()
    assert len(todos) == 1  # reaproveitou a linha, não criou outra


async def test_criar_job_modo_site_reaproveita_episodio_de_fonte_diferente(
    cliente: AsyncClient,
    sessionmaker_api: _SessionMaker,
    monkeypatch: pytest.MonkeyPatch,
):
    """D2: episódio já `PRONTO`, mas capturado numa fonte diferente da
    resolvida agora (troca de fonte) — também reaproveita a linha, sem o que
    a recaptura ficaria "grudada" batendo em `uq_episodio_identidade`."""
    anime_id = await _criar_anime(sessionmaker_api, "Anime Fonte Trocada")
    episodio_id = await _criar_episodio_existente(
        sessionmaker_api,
        anime_id,
        status=StatusEpisodio.PRONTO,
        site_origem="site-antigo.io",
        hls_path="anime-fonte-trocada/1/regular/desconhecida/master.m3u8",
    )

    async def _resolver_fake(sessionmaker, anime, versao):
        return FonteResolvida(
            dominio="site-novo.io",
            identificador="7",
            versao_da_fonte=VersaoDeFonte.NAO_DIFERENCIADA,
        )

    async def _listar_fake(sessionmaker, dominio, identificador):
        return [EpisodioRemoto(rotulo="1", numero=1, url="https://site-novo/ep1")]

    monkeypatch.setattr("api.servicos.jobs.resolver_fonte_do_anime", _resolver_fake)
    monkeypatch.setattr("api.servicos.jobs.listar_episodios_em", _listar_fake)

    resposta = await cliente.post(
        "/api/admin/jobs",
        json={"modo": "site", "anime_id": anime_id, "numero": 1, "tipo": "regular"},
    )

    assert resposta.status_code == 201

    async with sessionmaker_api() as sessao:
        episodio = await sessao.get(Episodio, episodio_id)
        assert episodio.status == StatusEpisodio.PENDENTE
        assert episodio.site_origem == "site-novo.io"
        assert episodio.hls_path is None

        todos = (
            await sessao.execute(select(Episodio).where(Episodio.anime_id == anime_id))
        ).scalars().all()
    assert len(todos) == 1


async def test_criar_job_modo_site_persiste_thumb_da_fonte_em_capa_path(
    cliente: AsyncClient,
    sessionmaker_api: _SessionMaker,
    monkeypatch: pytest.MonkeyPatch,
):
    """`EpisodioRemoto.thumb_url` da fonte resolvida é gravada em
    `Episodio.capa_path` (URL string, mesma convenção de `Anime.capa_path`)."""
    anime_id = await _criar_anime(sessionmaker_api, "Anime Com Thumb")

    async def _resolver_fake(sessionmaker, anime, versao):
        return FonteResolvida(
            dominio="animefire.one",
            identificador="42",
            versao_da_fonte=VersaoDeFonte.NAO_DIFERENCIADA,
        )

    async def _listar_fake(sessionmaker, dominio, identificador):
        return [
            EpisodioRemoto(
                rotulo="1",
                numero=1,
                url="https://x/ep1",
                thumb_url="https://animefire.one/img/video/42/1.webp",
            )
        ]

    monkeypatch.setattr("api.servicos.jobs.resolver_fonte_do_anime", _resolver_fake)
    monkeypatch.setattr("api.servicos.jobs.listar_episodios_em", _listar_fake)

    resposta = await cliente.post(
        "/api/admin/jobs",
        json={"modo": "site", "anime_id": anime_id, "numero": 1, "tipo": "regular"},
    )

    assert resposta.status_code == 201
    async with sessionmaker_api() as sessao:
        episodio = (
            await sessao.execute(select(Episodio).where(Episodio.anime_id == anime_id))
        ).scalar_one()
    assert episodio.capa_path == "https://animefire.one/img/video/42/1.webp"


async def test_criar_job_modo_site_recaptura_sem_thumb_preserva_capa_path(
    cliente: AsyncClient,
    sessionmaker_api: _SessionMaker,
    monkeypatch: pytest.MonkeyPatch,
):
    """Recaptura numa fonte que não expõe thumb (`EpisodioRemoto.thumb_url is
    None`) não apaga a `capa_path` já gravada — merge só-quando-não-nulo, mesma
    semântica de `total_episodios` em `db/catalogo.py`."""
    anime_id = await _criar_anime(sessionmaker_api, "Anime Recaptura Sem Thumb")
    episodio_id = await _criar_episodio_existente(
        sessionmaker_api,
        anime_id,
        status=StatusEpisodio.LIBERADO,
        site_origem="animefire.one",
        capa_path="https://animefire.one/img/video/42/1.webp",
    )

    async def _resolver_fake(sessionmaker, anime, versao):
        return FonteResolvida(
            dominio="animefire.one",
            identificador="42",
            versao_da_fonte=VersaoDeFonte.NAO_DIFERENCIADA,
        )

    async def _listar_fake(sessionmaker, dominio, identificador):
        return [EpisodioRemoto(rotulo="1", numero=1, url="https://x/ep1-recapturado")]

    monkeypatch.setattr("api.servicos.jobs.resolver_fonte_do_anime", _resolver_fake)
    monkeypatch.setattr("api.servicos.jobs.listar_episodios_em", _listar_fake)

    resposta = await cliente.post(
        "/api/admin/jobs",
        json={"modo": "site", "anime_id": anime_id, "numero": 1, "tipo": "regular"},
    )

    assert resposta.status_code == 201
    async with sessionmaker_api() as sessao:
        episodio = await sessao.get(Episodio, episodio_id)
    assert episodio.capa_path == "https://animefire.one/img/video/42/1.webp"


async def test_criar_job_modo_site_recaptura_com_job_ativo_409(
    cliente: AsyncClient,
    sessionmaker_api: _SessionMaker,
    monkeypatch: pytest.MonkeyPatch,
):
    """D2: episódio elegível para recaptura (`LIBERADO`), mas já tem um `Job`
    ativo — a recaptura deve levantar `JobEmExecucao`/409 ANTES de apagar
    arquivos ou criar um segundo `Job`, mesma checagem de
    `api/servicos/catalogo.py::remover_episodio`/`liberar_episodio`."""
    anime_id = await _criar_anime(sessionmaker_api, "Anime Recaptura Job Ativo")
    episodio_id = await _criar_episodio_existente(
        sessionmaker_api,
        anime_id,
        status=StatusEpisodio.LIBERADO,
        site_origem="animefire.one",
    )
    async with sessionmaker_api() as sessao:
        job_ativo = Job(episodio_id=episodio_id, status=StatusJob.TRANSCODIFICANDO)
        sessao.add(job_ativo)
        await sessao.commit()

    async def _resolver_fake(sessionmaker, anime, versao):
        return FonteResolvida(
            dominio="animefire.one",
            identificador="42",
            versao_da_fonte=VersaoDeFonte.NAO_DIFERENCIADA,
        )

    async def _listar_fake(sessionmaker, dominio, identificador):
        return [EpisodioRemoto(rotulo="1", numero=1, url="https://x/ep1-recapturado")]

    monkeypatch.setattr("api.servicos.jobs.resolver_fonte_do_anime", _resolver_fake)
    monkeypatch.setattr("api.servicos.jobs.listar_episodios_em", _listar_fake)

    resposta = await cliente.post(
        "/api/admin/jobs",
        json={"modo": "site", "anime_id": anime_id, "numero": 1, "tipo": "regular"},
    )

    assert resposta.status_code == 409
    assert resposta.json()["detail"]["motivo"] == "job_em_execucao"

    async with sessionmaker_api() as sessao:
        episodio = await sessao.get(Episodio, episodio_id)
        assert episodio.status == StatusEpisodio.LIBERADO  # linha não foi tocada
        assert episodio.url_fonte == "https://antigo/ep"

        jobs_do_episodio = (
            await sessao.execute(select(Job).where(Job.episodio_id == episodio_id))
        ).scalars().all()
    assert len(jobs_do_episodio) == 1  # nenhum job duplicado foi criado


async def test_listar_jobs_com_filtro_de_status(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker
):
    anime_id = await _criar_anime(sessionmaker_api, "Anime Listagem")
    await _criar_episodio_e_job(sessionmaker_api, anime_id, numero=1, status=StatusJob.NA_FILA)
    await _criar_episodio_e_job(sessionmaker_api, anime_id, numero=2, status=StatusJob.PRONTO)

    resposta = await cliente.get("/api/admin/jobs", params={"status": "pronto"})

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert len(corpo) == 1
    assert corpo[0]["status"] == "pronto"


async def test_obter_job_inexistente_404(cliente: AsyncClient):
    resposta = await cliente.get("/api/admin/jobs/999999")

    assert resposta.status_code == 404


async def test_cancelar_job_na_fila_cancela_direto(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker
):
    anime_id = await _criar_anime(sessionmaker_api, "Anime Cancelar Fila")
    _, job_id = await _criar_episodio_e_job(sessionmaker_api, anime_id, status=StatusJob.NA_FILA)

    resposta = await cliente.post(f"/api/admin/jobs/{job_id}/cancelar")

    assert resposta.status_code == 202
    assert resposta.json()["status"] == "cancelado"


async def test_cancelar_job_em_execucao_marca_cancelando(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker
):
    anime_id = await _criar_anime(sessionmaker_api, "Anime Cancelar Execucao")
    _, job_id = await _criar_episodio_e_job(
        sessionmaker_api, anime_id, status=StatusJob.TRANSCODIFICANDO
    )

    resposta = await cliente.post(f"/api/admin/jobs/{job_id}/cancelar")

    assert resposta.status_code == 202
    assert resposta.json()["status"] == "cancelando"


async def test_cancelar_job_ja_finalizado_409(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker
):
    anime_id = await _criar_anime(sessionmaker_api, "Anime Cancelar Pronto")
    _, job_id = await _criar_episodio_e_job(sessionmaker_api, anime_id, status=StatusJob.PRONTO)

    resposta = await cliente.post(f"/api/admin/jobs/{job_id}/cancelar")

    assert resposta.status_code == 409


async def test_cancelar_job_inexistente_404(cliente: AsyncClient):
    resposta = await cliente.post("/api/admin/jobs/999999/cancelar")

    assert resposta.status_code == 404


async def test_retry_job_falhou_volta_para_fila(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker
):
    anime_id = await _criar_anime(sessionmaker_api, "Anime Retry")
    _, job_id = await _criar_episodio_e_job(sessionmaker_api, anime_id, status=StatusJob.FALHOU)

    resposta = await cliente.post(f"/api/admin/jobs/{job_id}/retry")

    assert resposta.status_code == 200
    assert resposta.json()["job_id"] == job_id


async def test_retry_job_nao_retentavel_409(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker
):
    anime_id = await _criar_anime(sessionmaker_api, "Anime Retry Invalido")
    _, job_id = await _criar_episodio_e_job(sessionmaker_api, anime_id, status=StatusJob.NA_FILA)

    resposta = await cliente.post(f"/api/admin/jobs/{job_id}/retry")

    assert resposta.status_code == 409


async def test_retry_job_inexistente_404(cliente: AsyncClient):
    resposta = await cliente.post("/api/admin/jobs/999999/retry")

    assert resposta.status_code == 404

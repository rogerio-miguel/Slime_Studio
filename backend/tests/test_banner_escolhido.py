"""Seletor de banner da página do anime: candidatos do TMDB (ordem, limite, texto),
escolha por franquia (`banner_escolhido`) e a validação do `arquivo` recebido."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from integrations import servico
from integrations.base import CandidatoDeBanner
from integrations.tmdb import TmdbProvider
from models.anime import Anime

_SessionMaker = async_sessionmaker[AsyncSession]

_ARQUIVO = "/eJgJ2qPq5m0VkOUw3cPlaTt0sGP.jpg"
_URL_ESCOLHIDA = f"https://image.tmdb.org/t/p/original{_ARQUIVO}"


class _RespostaFalsa:
    status_code = 200

    def __init__(self, corpo):
        self._corpo = corpo

    def json(self):
        return self._corpo

    def raise_for_status(self):
        pass


def _backdrop(nome: str, *, idioma=None, largura=3840, votos=0, nota=0.0) -> dict:
    return {
        "file_path": f"/{nome}.jpg",
        "iso_639_1": idioma,
        "width": largura,
        "aspect_ratio": 1.778,
        "vote_count": votos,
        "vote_average": nota,
    }


def _tmdb_com(monkeypatch: pytest.MonkeyPatch, backdrops: list[dict]) -> TmdbProvider:
    def _fake_get(url, **kwargs):
        if url.endswith("/search/tv"):
            serie = {
                "id": 7,
                "name": "Slime",
                "original_name": "Slime",
                "first_air_date": "2018-10-02",
                "poster_path": "/poster.jpg",
            }
            return _RespostaFalsa({"results": [serie]})
        if url.endswith("/tv/7/images"):
            return _RespostaFalsa({"backdrops": backdrops})
        raise AssertionError(f"URL não mapeada no fake: {url}")

    monkeypatch.setattr("integrations.tmdb.requests.get", _fake_get)
    return TmdbProvider("token")


# --- TmdbProvider.listar_candidatos_de_banner ---


def test_candidatos_vem_em_ordem_de_resolucao_e_nota_sem_texto_primeiro(
    monkeypatch: pytest.MonkeyPatch,
):
    backdrops = [
        _backdrop("baixa", largura=1280, votos=50, nota=9.0),
        _backdrop("alta-mal-votada", votos=2, nota=1.0),
        _backdrop("alta-bem-votada", votos=40, nota=8.0),
        _backdrop("alta-nota-media", votos=10, nota=5.0),
        _backdrop("com-texto", idioma="en", votos=99, nota=10.0),
    ]
    tmdb = _tmdb_com(monkeypatch, backdrops)

    candidatos = tmdb.listar_candidatos_de_banner("Slime", None)

    # 4 sem texto >= mínimo: a arte com texto fica de fora, mesmo bem votada.
    assert [c.arquivo for c in candidatos] == [
        "/alta-bem-votada.jpg",
        "/alta-nota-media.jpg",
        "/alta-mal-votada.jpg",
        "/baixa.jpg",
    ]
    assert candidatos[0].miniatura_url == "https://image.tmdb.org/t/p/w780/alta-bem-votada.jpg"


def test_candidatos_completa_com_arte_com_texto_quando_ha_poucos_sem_texto(
    monkeypatch: pytest.MonkeyPatch,
):
    backdrops = [
        _backdrop("limpa"),
        _backdrop("texto-a", idioma="en", votos=5, nota=9.0),
        _backdrop("texto-b", idioma="en", votos=1, nota=2.0),
    ]
    tmdb = _tmdb_com(monkeypatch, backdrops)

    candidatos = tmdb.listar_candidatos_de_banner("Slime", None)

    assert [c.arquivo for c in candidatos] == ["/limpa.jpg", "/texto-a.jpg", "/texto-b.jpg"]


def test_candidatos_limita_a_doze(monkeypatch: pytest.MonkeyPatch):
    tmdb = _tmdb_com(monkeypatch, [_backdrop(f"img{i:02d}") for i in range(20)])

    assert len(tmdb.listar_candidatos_de_banner("Slime", None)) == 12


def test_candidatos_vazio_quando_a_serie_nao_e_achada(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "integrations.tmdb.requests.get", lambda *a, **k: _RespostaFalsa({"results": []})
    )

    assert TmdbProvider("token").listar_candidatos_de_banner("Nada", None) == []


# --- servico.listar_candidatos_de_banner ---


class _ProvedorFake:
    nome = "fake"

    def __init__(self, candidatos):
        self.chamadas = 0
        self._candidatos = candidatos

    def listar_candidatos_de_banner(self, titulo, ano):
        self.chamadas += 1
        return self._candidatos


async def test_servico_cacheia_por_titulo_base(monkeypatch: pytest.MonkeyPatch):
    candidato = CandidatoDeBanner(arquivo="/a.jpg", miniatura_url="https://x/a.jpg")
    provedor = _ProvedorFake([candidato])
    monkeypatch.setattr(servico, "provedores_de_arte", lambda: (provedor,))
    monkeypatch.setattr(servico, "_memo_candidatos_de_banner", {})
    monkeypatch.setattr(servico, "_arte_desabilitada_por_auth", False)

    primeira = await servico.listar_candidatos_de_banner("Slime Season 4", 2026)
    segunda = await servico.listar_candidatos_de_banner("Slime Season 4", 2026)

    assert primeira == segunda == [candidato]
    assert provedor.chamadas == 1


async def test_servico_nao_cacheia_lista_vazia(monkeypatch: pytest.MonkeyPatch):
    provedor = _ProvedorFake([])
    monkeypatch.setattr(servico, "provedores_de_arte", lambda: (provedor,))
    monkeypatch.setattr(servico, "_memo_candidatos_de_banner", {})
    monkeypatch.setattr(servico, "_arte_desabilitada_por_auth", False)

    assert await servico.listar_candidatos_de_banner("Slime", None) == []
    assert await servico.listar_candidatos_de_banner("Slime", None) == []
    assert provedor.chamadas == 2


# --- rotas ---


async def _criar_franquia(sessionmaker: _SessionMaker) -> tuple[int, int, int]:
    """Duas temporadas da mesma franquia (`serie_ancora` em comum) e um anime solto."""
    async with sessionmaker() as sessao:
        t1 = Anime(
            titulo="Slime", slug="slime", ano=2018, serie_ancora=1, numero_temporada=1,
            banner_path="https://img/auto.jpg",
        )
        t2 = Anime(
            titulo="Slime 2nd Season", slug="slime-2", ano=2021, serie_ancora=1, numero_temporada=2,
            banner_path="https://img/auto.jpg",
        )
        solto = Anime(titulo="Outro", slug="outro", banner_path="https://img/outro.jpg")
        sessao.add_all([t1, t2, solto])
        await sessao.commit()
        return t1.id, t2.id, solto.id


async def test_escolher_banner_vale_para_a_franquia_inteira(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker
):
    t1, t2, solto = await _criar_franquia(sessionmaker_api)

    resposta = await cliente.put(f"/api/admin/animes/{t2}/banner", json={"arquivo": _ARQUIVO})

    assert resposta.status_code == 204
    for anime_id in (t1, t2):
        detalhe = (await cliente.get(f"/api/animes/{anime_id}")).json()
        assert detalhe["banner_path"] == _URL_ESCOLHIDA
        assert detalhe["banner_personalizado"] is True
    fora = (await cliente.get(f"/api/animes/{solto}")).json()
    assert fora["banner_path"] == "https://img/outro.jpg"
    assert fora["banner_personalizado"] is False


async def test_restaurar_banner_volta_ao_automatico(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker
):
    t1, t2, _ = await _criar_franquia(sessionmaker_api)
    await cliente.put(f"/api/admin/animes/{t1}/banner", json={"arquivo": _ARQUIVO})

    resposta = await cliente.delete(f"/api/admin/animes/{t2}/banner")

    assert resposta.status_code == 204
    detalhe = (await cliente.get(f"/api/animes/{t1}")).json()
    assert detalhe["banner_path"] == "https://img/auto.jpg"
    assert detalhe["banner_personalizado"] is False


async def test_escolha_vence_mesmo_com_temporada_anterior_catalogada_depois(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker
):
    """Temporada com `numero_temporada` menor entra depois e passa a vir primeiro
    no grupo; sem escolha própria, ela não pode esconder a da franquia."""
    _, t2, _ = await _criar_franquia(sessionmaker_api)
    await cliente.put(f"/api/admin/animes/{t2}/banner", json={"arquivo": _ARQUIVO})
    async with sessionmaker_api() as sessao:
        prequel = Anime(
            titulo="Slime 0", slug="slime-0", serie_ancora=1, numero_temporada=0,
            banner_path="https://img/prequel.jpg",
        )
        sessao.add(prequel)
        await sessao.commit()
        prequel_id = prequel.id

    detalhe = (await cliente.get(f"/api/animes/{prequel_id}")).json()

    assert detalhe["banner_path"] == _URL_ESCOLHIDA


@pytest.mark.parametrize(
    "arquivo",
    [
        "https://evil.example/x.jpg",
        "/../../etc/passwd.jpg",
        "/curto.jpg",
        f"{_ARQUIVO}\n",
        "eJgJ2qPq5m0VkOUw3cPlaTt0sGP.jpg",
        "/eJgJ2qPq5m0VkOUw3cPlaTt0sGP.svg",
        "/eJgJ2qPq5m0VkOUw3cPlaTt0sGP.jpg?x=1",
    ],
)
async def test_escolher_banner_rejeita_arquivo_fora_do_formato(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker, arquivo: str
):
    t1, _, _ = await _criar_franquia(sessionmaker_api)

    resposta = await cliente.put(f"/api/admin/animes/{t1}/banner", json={"arquivo": arquivo})

    assert resposta.status_code == 422


async def test_escolher_banner_de_anime_inexistente_da_404(cliente: AsyncClient):
    resposta = await cliente.put("/api/admin/animes/9999/banner", json={"arquivo": _ARQUIVO})

    assert resposta.status_code == 404


async def test_listar_banners_busca_pela_primeira_temporada_da_franquia(
    cliente: AsyncClient, sessionmaker_api: _SessionMaker, monkeypatch: pytest.MonkeyPatch
):
    _, t2, _ = await _criar_franquia(sessionmaker_api)
    pedidos = []

    async def _fake(titulo, ano):
        pedidos.append((titulo, ano))
        return [CandidatoDeBanner(arquivo=_ARQUIVO, miniatura_url="https://x/m.jpg")]

    monkeypatch.setattr("integrations.servico.listar_candidatos_de_banner", _fake)

    resposta = await cliente.get(f"/api/animes/{t2}/banners")

    assert resposta.status_code == 200
    assert resposta.json() == [{"arquivo": _ARQUIVO, "miniatura_url": "https://x/m.jpg"}]
    assert pedidos == [("Slime", 2018)]


async def test_listar_banners_de_anime_inexistente_da_404(cliente: AsyncClient):
    assert (await cliente.get("/api/animes/9999/banners")).status_code == 404

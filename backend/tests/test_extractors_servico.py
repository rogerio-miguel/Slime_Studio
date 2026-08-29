"""Testes de `extractors/servico.py::_proximo_com_episodio`, sem rede —
`listar_episodios_em` é substituído por uma versão que devolve uma lista fixa;
a resolução do próximo site usa `FonteAnime` já mapeada no banco (mesmo padrão
de `tests/test_resolucao.py::test_proximo_site_para_prefere_mapeamento_ja_existente`),
sem precisar de extrator falso nem de `resiliencia.chamar`.

Também cobre `buscar_em_com_variantes` (Fase A, fatia 2 de
PLANO_PADRONIZACAO_FONTES.md), que precisa de um extrator falso injetado via
`monkeypatch.setattr(servico, "obter_extrator", ...)` e de `resiliencia.chamar`
substituído por uma versão que chama a operação direto, mesmo padrão de
`tests/test_resolucao.py::_resiliencia_sem_cliente_real`.

E `buscar_por_site_com_variantes` (Fase B, fatia 3/4 — camada `extractors/`),
que injeta extratores falsos via `monkeypatch.setattr(servico, "EXTRATORES",
...)`/`monkeypatch.setattr(servico, "obter_extrator", ...)` (mesmo padrão de
`tests/test_resolucao.py::test_pula_site_em_cooldown` pro cenário de
cooldown, inserindo `EstadoSite` de verdade no banco) — cobre a garantia
central da fatia (INV-1', "o site é a unidade atômica, não a rodada de
variante").

E o deadline de cadeia de `baixar_com_fallback_de_site` (Fase E2): o teto
(`_ORCAMENTO_CADEIA_S`) agora é um `wait_for` real (`_dentro_do_prazo`), não
só um portão — os testes de estouro usam duas técnicas diferentes conforme o
que precisam isolar:

- Estouro ANTES até de começar a buscar o próximo site: orçamento NEGATIVO
  via `monkeypatch.setattr(servico, "_ORCAMENTO_CADEIA_S", -1)` — nunca
  depende da resolução do relógio (`_dentro_do_prazo` calcula um timeout de
  `wait_for` já em 0, então cancela antes mesmo do primeiro `await` real de
  `_proximo_com_episodio` completar).
- Estouro especificamente no PORTÃO (`if time.monotonic() >= prazo`, depois
  de `_proximo_com_episodio` já ter terminado) sem que o `wait_for` interno
  dispare primeiro: orçamento POSITIVO generoso + um relógio determinístico
  via `monkeypatch.setattr(servico.time, "monotonic", ...)`, cujo fake só
  desloca o valor devolvido depois que a listagem no site novo já terminou —
  ver `test_baixar_com_fallback_de_site_deadline_estoura_entre_listar_e_baixar`
  para o raciocínio completo de por que isso isola o portão do `wait_for`.
- Estouro do `wait_for` interno em torno de `_proximo_com_episodio` (site
  novo lento, orçamento pequeno positivo): fake com `asyncio.sleep` real,
  maior que o orçamento — sem depender de relógio nenhum.
"""

import asyncio
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config import Config
from core.enums import TipoEpisodio, VersaoDeFonte, VersaoEpisodio
from core.erros import EstruturaDoSiteMudou, FalhaDeExtracao, FonteNaoEncontrada, SiteEmCooldown
from db.engine import criar_engine, criar_sessionmaker
from extractors import download, resiliencia, resolucao, servico
from extractors.base import EpisodioRemoto, LinkDeMidia, ResultadoBusca
from models.anime import Anime
from models.base import Base
from models.episodio import Episodio
from models.estado_site import EstadoSite
from models.fonte_anime import FonteAnime


@pytest.fixture
async def sessionmaker(tmp_path: Path) -> async_sessionmaker[AsyncSession]:
    config = Config(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        media_root=tmp_path,
        raiz_repo=tmp_path,
        ffmpeg=Path("/usr/bin/ffmpeg"),
        ffprobe=Path("/usr/bin/ffprobe"),
        caminho_lock=tmp_path / "worker.lock",
    )
    engine = criar_engine(config)
    async with engine.begin() as conexao:
        await conexao.run_sync(Base.metadata.create_all)

    fabrica = criar_sessionmaker(engine)
    yield fabrica

    await engine.dispose()


async def _criar_anime(fabrica, titulo: str) -> Anime:
    async with fabrica() as sessao:
        anime = Anime(titulo=titulo, slug=titulo.lower().replace(" ", "-"))
        sessao.add(anime)
        await sessao.commit()
        await sessao.refresh(anime)
        return anime


async def test_proximo_com_episodio_colisao_de_numero_escolhe_primeiro_e_loga(
    sessionmaker, monkeypatch, caplog
):
    """Dois rótulos remotos ("7"/"07") mapeiam pro mesmo `numero=7` — regressão
    da ambiguidade introduzida por dedup-por-rótulo (extractors/base.py::
    EpisodioRemoto). Escolha determinística (1ª ocorrência) e log de aviso,
    nunca silenciosa (CLAUDE.md §4)."""
    anime = await _criar_anime(sessionmaker, "Slime Datta Ken")
    async with sessionmaker() as sessao:
        sessao.add_all(
            [
                FonteAnime(
                    anime_id=anime.id,
                    site_dominio="site-a.io",
                    versao=VersaoDeFonte.NAO_DIFERENCIADA,
                    identificador_no_site="a",
                    prioridade=0,
                ),
                FonteAnime(
                    anime_id=anime.id,
                    site_dominio="site-b.io",
                    versao=VersaoDeFonte.NAO_DIFERENCIADA,
                    identificador_no_site="b",
                    prioridade=1,
                ),
            ]
        )
        await sessao.commit()

    colidentes = [
        EpisodioRemoto(rotulo="7", numero=7, url="https://x/ep7"),
        EpisodioRemoto(rotulo="07", numero=7, url="https://x/ep07"),
    ]

    async def _listar_fake(sessionmaker, dominio, identificador):
        return colidentes

    monkeypatch.setattr(servico, "listar_episodios_em", _listar_fake)

    with caplog.at_level("WARNING"):
        resultado = await servico._proximo_com_episodio(
            sessionmaker, anime, 7, {"site-a.io"}, VersaoEpisodio.DESCONHECIDA
        )

    assert resultado == ("site-b.io", "https://x/ep7")
    assert "07" in caplog.text
    assert "site-b.io" in caplog.text


async def test_proximo_com_episodio_sem_colisao_nao_loga(sessionmaker, monkeypatch, caplog):
    anime = await _criar_anime(sessionmaker, "Slime Datta Ken")
    async with sessionmaker() as sessao:
        sessao.add_all(
            [
                FonteAnime(
                    anime_id=anime.id,
                    site_dominio="site-a.io",
                    versao=VersaoDeFonte.NAO_DIFERENCIADA,
                    identificador_no_site="a",
                    prioridade=0,
                ),
                FonteAnime(
                    anime_id=anime.id,
                    site_dominio="site-b.io",
                    versao=VersaoDeFonte.NAO_DIFERENCIADA,
                    identificador_no_site="b",
                    prioridade=1,
                ),
            ]
        )
        await sessao.commit()

    async def _listar_fake(sessionmaker, dominio, identificador):
        return [EpisodioRemoto(rotulo="7", numero=7, url="https://x/ep7")]

    monkeypatch.setattr(servico, "listar_episodios_em", _listar_fake)

    with caplog.at_level("WARNING"):
        resultado = await servico._proximo_com_episodio(
            sessionmaker, anime, 7, {"site-a.io"}, VersaoEpisodio.DESCONHECIDA
        )

    assert resultado == ("site-b.io", "https://x/ep7")
    assert "episódios remotos com numero" not in caplog.text


async def test_proximo_com_episodio_prefere_versao_pedida_quando_listagem_rotula_as_duas(
    sessionmaker, monkeypatch
):
    """Listagem do site de fallback tem episódio 7 rotulado nas duas versões
    (site que diferencia, ex. AnimesDrive) — o fallback pra DUBLADO precisa
    escolher a URL dublada, não a primeira da lista."""
    anime = await _criar_anime(sessionmaker, "Slime Datta Ken")
    async with sessionmaker() as sessao:
        sessao.add_all(
            [
                # `site-a.io` só precisa existir pra já estar em `ja_tentados`
                # (passado pelo teste) — versão gravada aqui é irrelevante,
                # esta linha nunca é candidata a próxima fonte
                # (`proximo_site_para` exclui todo domínio em `ja_tentados`).
                FonteAnime(
                    anime_id=anime.id,
                    site_dominio="site-a.io",
                    versao=VersaoDeFonte.NAO_DIFERENCIADA,
                    identificador_no_site="a",
                    prioridade=0,
                ),
                FonteAnime(
                    anime_id=anime.id,
                    site_dominio="site-b.io",
                    versao=VersaoDeFonte.DUBLADO,
                    identificador_no_site="b",
                    prioridade=1,
                ),
            ]
        )
        await sessao.commit()

    async def _listar_fake(sessionmaker, dominio, identificador):
        return [
            EpisodioRemoto(
                rotulo="7", numero=7, url="https://x/ep7-leg", versao=VersaoEpisodio.LEGENDADO
            ),
            EpisodioRemoto(
                rotulo="7", numero=7, url="https://x/ep7-dub", versao=VersaoEpisodio.DUBLADO
            ),
        ]

    monkeypatch.setattr(servico, "listar_episodios_em", _listar_fake)

    resultado = await servico._proximo_com_episodio(
        sessionmaker, anime, 7, {"site-a.io"}, VersaoEpisodio.DUBLADO
    )

    assert resultado == ("site-b.io", "https://x/ep7-dub")


def _config_de_teste(tmp_path: Path) -> Config:
    return Config(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        media_root=tmp_path,
        raiz_repo=tmp_path,
        ffmpeg=Path("/usr/bin/ffmpeg"),
        ffprobe=Path("/usr/bin/ffprobe"),
        caminho_lock=tmp_path / "worker.lock",
    )


async def test_baixar_com_fallback_de_site_loga_duracao_e_sites_tentados_no_sucesso_direto(
    sessionmaker, monkeypatch, caplog, tmp_path
):
    """Fase E1 (PLANO_PADRONIZACAO_FONTES.md) — sucesso no primeiro site loga
    `sites_tentados=1` e a duração da cadeia, sem vazar `url_fonte`."""
    anime = await _criar_anime(sessionmaker, "Slime Datta Ken")
    episodio = Episodio(
        anime_id=anime.id,
        numero=1,
        tipo=TipoEpisodio.REGULAR,
        versao=VersaoEpisodio.LEGENDADO,
        url_fonte="https://animefire.io/segredo-de-sessao/ep1",
        site_origem="animefire.io",
    )
    destino = tmp_path / "saida.mp4"

    async def _baixar_episodio_fake(
        sessionmaker, config, *, extrator, url_episodio, destino, prazo=None
    ):
        return destino

    monkeypatch.setattr(servico, "baixar_episodio", _baixar_episodio_fake)

    with caplog.at_level("INFO", logger="extractors.servico"):
        resultado = await servico.baixar_com_fallback_de_site(
            sessionmaker,
            _config_de_teste(tmp_path),
            anime=anime,
            episodio=episodio,
            destino=destino,
        )

    assert resultado == destino
    assert "sites_tentados=1" in caplog.text
    assert "duracao_total_s=" in caplog.text
    assert f"anime_id={anime.id}" in caplog.text
    assert "episodio_numero=1" in caplog.text
    assert "segredo-de-sessao" not in caplog.text


async def test_baixar_com_fallback_de_site_conta_sites_tentados_apos_fallback(
    sessionmaker, monkeypatch, caplog, tmp_path
):
    """Falha não-retentável no primeiro site aciona `_proximo_com_episodio` — o
    log final tem que contar os dois sites, não só o mapeado original."""
    anime = await _criar_anime(sessionmaker, "Slime Datta Ken")
    async with sessionmaker() as sessao:
        sessao.add(
            FonteAnime(
                anime_id=anime.id,
                site_dominio="animesdrive",
                versao=VersaoDeFonte.NAO_DIFERENCIADA,
                identificador_no_site="b",
                prioridade=1,
            )
        )
        await sessao.commit()

    episodio = Episodio(
        anime_id=anime.id,
        numero=1,
        tipo=TipoEpisodio.REGULAR,
        versao=VersaoEpisodio.DESCONHECIDA,
        url_fonte="https://animefire.io/ep1",
        site_origem="animefire.io",
    )
    destino = tmp_path / "saida.mp4"

    async def _listar_fake(sessionmaker, dominio, identificador):
        return [EpisodioRemoto(rotulo="1", numero=1, url="https://animesdrive.online/ep1")]

    monkeypatch.setattr(servico, "listar_episodios_em", _listar_fake)

    chamadas: list[str] = []

    async def _baixar_episodio_fake(
        sessionmaker, config, *, extrator, url_episodio, destino, prazo=None
    ):
        chamadas.append(extrator.dominio)
        if len(chamadas) == 1:
            raise FonteNaoEncontrada(f"não encontrado: {url_episodio}", dominio=extrator.dominio)
        return destino

    monkeypatch.setattr(servico, "baixar_episodio", _baixar_episodio_fake)

    with caplog.at_level("INFO", logger="extractors.servico"):
        resultado = await servico.baixar_com_fallback_de_site(
            sessionmaker,
            _config_de_teste(tmp_path),
            anime=anime,
            episodio=episodio,
            destino=destino,
        )

    assert resultado == destino
    assert chamadas == ["animefire.io", "animesdrive"]
    assert "sites_tentados=2" in caplog.text
    # Fase E2: dentro do orçamento padrão, a cadeia completa sem o log de
    # estouro de deadline — comportamento idêntico ao de antes do E2 existir.
    assert "abortou troca de site" not in caplog.text


async def test_baixar_com_fallback_de_site_loga_ao_esgotar_sites_disponiveis(
    sessionmaker, monkeypatch, caplog, tmp_path
):
    """Fase E1 (PLANO_PADRONIZACAO_FONTES.md): quando `_proximo_com_episodio`
    esgota as opções (`None`) e a função levanta, o mesmo log de
    `sites_tentados`/`duracao_total_s` do caminho de sucesso sai antes, em
    `warning` — sem vazar `url_fonte`."""
    anime = await _criar_anime(sessionmaker, "Slime Datta Ken")
    episodio = Episodio(
        anime_id=anime.id,
        numero=1,
        tipo=TipoEpisodio.REGULAR,
        versao=VersaoEpisodio.LEGENDADO,
        url_fonte="https://animefire.io/segredo-de-sessao/ep1",
        site_origem="animefire.io",
    )
    destino = tmp_path / "saida.mp4"

    async def _baixar_episodio_fake(
        sessionmaker, config, *, extrator, url_episodio, destino, prazo=None
    ):
        raise EstruturaDoSiteMudou("estrutura mudou", dominio=extrator.dominio)

    async def _proximo_site_para_fake(sessionmaker, anime, ja_tentados, versao):
        return None

    monkeypatch.setattr(servico, "baixar_episodio", _baixar_episodio_fake)
    monkeypatch.setattr(resolucao, "proximo_site_para", _proximo_site_para_fake)

    with caplog.at_level("WARNING", logger="extractors.servico"):
        with pytest.raises(EstruturaDoSiteMudou):
            await servico.baixar_com_fallback_de_site(
                sessionmaker,
                _config_de_teste(tmp_path),
                anime=anime,
                episodio=episodio,
                destino=destino,
            )

    assert "sites_tentados=1" in caplog.text
    assert "duracao_total_s=" in caplog.text
    assert f"anime_id={anime.id}" in caplog.text
    assert "episodio_numero=1" in caplog.text
    assert "segredo-de-sessao" not in caplog.text


async def test_baixar_com_fallback_de_site_deadline_estourado_nao_tenta_proximo_site(
    sessionmaker, monkeypatch, caplog, tmp_path
):
    """Fase E2 (PLANO_PADRONIZACAO_FONTES.md): orçamento de cadeia já esgotado
    quando o 1º site falha de forma não-retentável — a busca pelo próximo
    site (`_proximo_com_episodio`, agora dentro de `_dentro_do_prazo`) nem
    chega a rodar: com orçamento negativo, o `wait_for` calcula um timeout já
    em 0 e cancela antes mesmo do primeiro `await` real (consulta a
    `FonteAnime` no banco) completar. Propaga a MESMA exceção que motivou a
    troca, nunca um erro de deadline genérico (caso de borda 2:
    `permite_retentativa` da falha original chega intacto a quem chama,
    `worker/executor.py`/`db/fila.py::falhar_extracao` decidem exatamente
    como decidiriam pra essa falha em qualquer outro contexto)."""
    monkeypatch.setattr(servico, "_ORCAMENTO_CADEIA_S", -1)

    anime = await _criar_anime(sessionmaker, "Slime Datta Ken")
    async with sessionmaker() as sessao:
        sessao.add(
            FonteAnime(
                anime_id=anime.id,
                site_dominio="animesdrive",
                versao=VersaoDeFonte.NAO_DIFERENCIADA,
                identificador_no_site="b",
                prioridade=1,
            )
        )
        await sessao.commit()

    episodio = Episodio(
        anime_id=anime.id,
        numero=1,
        tipo=TipoEpisodio.REGULAR,
        versao=VersaoEpisodio.DESCONHECIDA,
        url_fonte="https://animefire.io/segredo-1/ep1",
        site_origem="animefire.io",
    )
    destino = tmp_path / "saida.mp4"

    # Rede de segurança: se por algum motivo a listagem chegar a rodar (não
    # deveria, ver docstring), este fake garante que o teste não faz rede de
    # verdade em vez de mascarar uma regressão de timing com uma chamada real.
    async def _listar_fake(sessionmaker, dominio, identificador):
        return [
            EpisodioRemoto(rotulo="1", numero=1, url="https://animesdrive.online/segredo-2/ep1")
        ]

    monkeypatch.setattr(servico, "listar_episodios_em", _listar_fake)

    chamadas: list[str] = []
    falha_original = FonteNaoEncontrada("não encontrado no site", dominio="animefire.io")

    async def _baixar_episodio_fake(
        sessionmaker, config, *, extrator, url_episodio, destino, prazo=None
    ):
        chamadas.append(extrator.dominio)
        raise falha_original

    monkeypatch.setattr(servico, "baixar_episodio", _baixar_episodio_fake)

    with caplog.at_level("WARNING", logger="extractors.servico"):
        with pytest.raises(FonteNaoEncontrada) as excinfo:
            await servico.baixar_com_fallback_de_site(
                sessionmaker,
                _config_de_teste(tmp_path),
                anime=anime,
                episodio=episodio,
                destino=destino,
            )

    assert excinfo.value is falha_original  # a mesma falha, não um erro novo de deadline
    assert chamadas == ["animefire.io"]  # site de fallback nunca chegou a ser tentado
    assert "abortou a busca por outro site" in caplog.text  # novo log: estouro na descoberta
    assert "animesdrive" not in caplog.text  # domínio nunca chegou a ser descoberto
    assert "segredo-1" not in caplog.text  # nunca a URL crua do episódio original
    assert "segredo-2" not in caplog.text  # nem a do site de fallback


async def test_baixar_com_fallback_de_site_deadline_estoura_entre_listar_e_baixar(
    sessionmaker, monkeypatch, tmp_path
):
    """Caso de borda 1 (Fase E, PLANO_PADRONIZACAO_FONTES.md): o orçamento
    estoura DEPOIS que `_proximo_com_episodio` já listou o episódio no site
    novo (`buscas` abaixo prova que a busca aconteceu de verdade) e ANTES de
    `baixar_episodio` ser chamado por lá — e quem detecta isso tem que ser
    especificamente o PORTÃO (`if time.monotonic() >= prazo`, que permanece
    inalterado), não o `wait_for` interno de `_dentro_do_prazo` em torno de
    `_proximo_com_episodio`.

    Isolar isso com orçamento negativo (como no teste acima) não dá: um
    orçamento já vencido faz o `wait_for` estourar ANTES da listagem
    terminar, não depois. Em vez disso, usa orçamento POSITIVO generoso (o
    `wait_for` interno nunca vê motivo pra estourar, já que o tempo de
    parede real do teste é da ordem de milissegundos) e um relógio fake
    determinístico (`monkeypatch.setattr(servico.time, "monotonic", ...)`)
    que só desloca o valor devolvido DEPOIS que `_listar_fake` já terminou —
    ou seja, o "agora" que o `wait_for` usa pra decidir se cancela continua
    reportando tempo real (não estoura) até o instante exato em que a
    listagem no site novo já concluiu; só o PORTÃO, chamado depois que
    `_dentro_do_prazo` já retornou com sucesso, vê o relógio deslocado.

    Nota: `servico.time` é o módulo `time` padrão (compartilhado com o
    `asyncio` interno) — o deslocamento é aplicado só depois que a corrotina
    de `_proximo_com_episodio` já terminou de rodar (dentro do mesmo passo de
    execução da task, sem devolver o controle ao loop), então o `wait_for`
    que a envolve já concluiu com sucesso antes do timer de deadline dele ter
    qualquer chance de ver o relógio deslocado — não há corrida de fato.

    A falha propagada tem que ser a exceção original do site —
    `pytest.raises(EstruturaDoSiteMudou)` já reprova um `TimeoutError`
    genérico que perderia o diagnóstico."""
    orcamento_s = 5.0  # positivo generoso — o teste roda em milissegundos reais
    monkeypatch.setattr(servico, "_ORCAMENTO_CADEIA_S", orcamento_s)

    relogio_real = servico.time.monotonic
    deslocamento_s = 0.0

    def _relogio_fake():
        return relogio_real() + deslocamento_s

    monkeypatch.setattr(servico.time, "monotonic", _relogio_fake)

    anime = await _criar_anime(sessionmaker, "Slime Datta Ken")
    async with sessionmaker() as sessao:
        sessao.add(
            FonteAnime(
                anime_id=anime.id,
                site_dominio="animesdrive",
                versao=VersaoDeFonte.NAO_DIFERENCIADA,
                identificador_no_site="b",
                prioridade=1,
            )
        )
        await sessao.commit()

    episodio = Episodio(
        anime_id=anime.id,
        numero=1,
        tipo=TipoEpisodio.REGULAR,
        versao=VersaoEpisodio.DESCONHECIDA,
        url_fonte="https://animefire.io/ep1",
        site_origem="animefire.io",
    )
    destino = tmp_path / "saida.mp4"

    buscas: list[str] = []

    async def _listar_fake(sessionmaker, dominio, identificador):
        nonlocal deslocamento_s
        buscas.append(dominio)
        # Desloca o relógio pra além do orçamento SÓ AGORA — depois deste
        # ponto, qualquer leitura de `time.monotonic()` (o portão, o log de
        # duração) vê o orçamento como esgotado; o `wait_for` que envolveu
        # esta chamada já não tem mais nada a decidir (ver docstring acima).
        deslocamento_s = orcamento_s + 10.0
        return [EpisodioRemoto(rotulo="1", numero=1, url="https://animesdrive.online/ep1")]

    monkeypatch.setattr(servico, "listar_episodios_em", _listar_fake)

    chamadas: list[str] = []

    async def _baixar_episodio_fake(
        sessionmaker, config, *, extrator, url_episodio, destino, prazo=None
    ):
        chamadas.append(extrator.dominio)
        raise EstruturaDoSiteMudou("estrutura mudou", dominio=extrator.dominio)

    monkeypatch.setattr(servico, "baixar_episodio", _baixar_episodio_fake)

    with pytest.raises(EstruturaDoSiteMudou):
        await servico.baixar_com_fallback_de_site(
            sessionmaker,
            _config_de_teste(tmp_path),
            anime=anime,
            episodio=episodio,
            destino=destino,
        )

    assert buscas == ["animesdrive"]  # a listagem no site novo aconteceu de verdade
    assert chamadas == ["animefire.io"]  # mas o download por lá nunca foi tentado


async def test_baixar_com_fallback_de_site_propaga_falha_original_quando_proximo_site_e_lento(
    sessionmaker, monkeypatch, tmp_path
):
    """Novo caso de borda (Fase E2): `_proximo_com_episodio` (busca + listagem
    no site novo) mais lenta que o orçamento restante — o `wait_for` de
    `_dentro_do_prazo` estoura de verdade (sem relógio fake, `asyncio.sleep`
    real), mas a exceção propagada continua sendo a FALHA ORIGINAL que
    motivou a troca de site, nunca um `TimeoutError` cru (que perderia o
    diagnóstico e o `permite_retentativa` de quem chama). Orçamento e sono
    pequenos (décimos de segundo) pra o teste concluir rápido, não segundos
    reais de espera."""
    orcamento_s = 0.05
    monkeypatch.setattr(servico, "_ORCAMENTO_CADEIA_S", orcamento_s)

    anime = await _criar_anime(sessionmaker, "Slime Datta Ken")
    episodio = Episodio(
        anime_id=anime.id,
        numero=1,
        tipo=TipoEpisodio.REGULAR,
        versao=VersaoEpisodio.DESCONHECIDA,
        url_fonte="https://animefire.io/ep1",
        site_origem="animefire.io",
    )
    destino = tmp_path / "saida.mp4"

    falha_original = EstruturaDoSiteMudou("estrutura mudou", dominio="animefire.io")

    async def _baixar_episodio_fake(
        sessionmaker, config, *, extrator, url_episodio, destino, prazo=None
    ):
        raise falha_original

    async def _proximo_com_episodio_lento(
        sessionmaker, anime, numero_episodio, ja_tentados, versao
    ):
        await asyncio.sleep(0.3)
        return ("animesdrive", "https://animesdrive.cloud/ep1")

    monkeypatch.setattr(servico, "baixar_episodio", _baixar_episodio_fake)
    monkeypatch.setattr(servico, "_proximo_com_episodio", _proximo_com_episodio_lento)

    inicio = time.monotonic()
    with pytest.raises(EstruturaDoSiteMudou) as excinfo:
        await servico.baixar_com_fallback_de_site(
            sessionmaker,
            _config_de_teste(tmp_path),
            anime=anime,
            episodio=episodio,
            destino=destino,
        )
    duracao_s = time.monotonic() - inicio

    assert excinfo.value is falha_original  # a falha original, não um TimeoutError cru
    assert duracao_s < 0.3  # não esperou o sono inteiro do fake (0.3s > orçamento de 0.05s)


async def test_baixar_com_fallback_de_site_tentativa_original_respeita_orcamento_sem_trocar_de_site(
    sessionmaker, monkeypatch, tmp_path
):
    """Gap 1 da 2ª rodada de revisão da Fase E2 (PLANO_PADRONIZACAO_FONTES.md):
    prova de PONTA A PONTA, via `baixar_com_fallback_de_site` (não `baixar_episodio`
    isolado, e sem fakear `baixar_episodio` inteiro como os demais testes deste
    arquivo) que a tentativa ORIGINAL — a 1ª chamada a `baixar_episodio` dentro do
    laço, antes de qualquer troca de site — de fato repassa `prazo=prazo`. Sem este
    teste, remover `prazo=prazo` dessa 1ª chamada num refactor futuro (reintroduzindo
    o bug crítico da 1ª rodada de revisão: tentativa original sem teto) passaria
    batido, porque todo fake de `baixar_episodio` usado nos outros testes deste
    arquivo aceita `prazo` mas o ignora.

    `baixar_episodio` roda de verdade aqui — só `resiliencia.chamar` (o que
    `extrator.resolver_midia` usa por baixo) é fakeado, dormindo mais que o
    orçamento (décimos de segundo reais via `asyncio.sleep`, nunca segundos
    inteiros). Com `_ORCAMENTO_CADEIA_S` monkeypatchado bem pequeno, o `wait_for`
    de `_dentro_do_prazo` em torno de `_resolver_e_conferir` estoura de verdade e
    vira `FalhaDeExtracao(permite_retentativa=True)` — o timeout é do NOSSO
    orçamento, não do site. Como a falha é retentável, `baixar_com_fallback_de_site`
    apenas propaga (`if excecao.permite_retentativa: raise`) sem nunca entrar no
    branch que busca outro site — `resolucao.proximo_site_para` fake prova isso
    (lista de chamadas vazia): nenhuma troca de site chegou a ser tentada."""
    orcamento_s = 0.05
    monkeypatch.setattr(servico, "_ORCAMENTO_CADEIA_S", orcamento_s)

    async def _chamar_lento(sessionmaker, extrator, operacao, *, nome_operacao="operacao", **_):
        await asyncio.sleep(0.3)
        return LinkDeMidia(url="https://x/media.m3u8", cabecalhos={})

    monkeypatch.setattr(resiliencia, "chamar", _chamar_lento)

    chamadas_proximo_site: list[str] = []

    async def _proximo_site_para_fake(sessionmaker, anime, ja_tentados, versao):
        chamadas_proximo_site.append(anime.id)
        return None

    monkeypatch.setattr(resolucao, "proximo_site_para", _proximo_site_para_fake)

    anime = await _criar_anime(sessionmaker, "Slime Datta Ken")
    episodio = Episodio(
        anime_id=anime.id,
        numero=1,
        tipo=TipoEpisodio.REGULAR,
        versao=VersaoEpisodio.DESCONHECIDA,
        url_fonte="https://animefire.io/ep1",
        site_origem="animefire.io",
    )
    destino = tmp_path / "saida.mp4"

    inicio = time.monotonic()
    with pytest.raises(FalhaDeExtracao) as excinfo:
        await servico.baixar_com_fallback_de_site(
            sessionmaker,
            _config_de_teste(tmp_path),
            anime=anime,
            episodio=episodio,
            destino=destino,
        )
    duracao_s = time.monotonic() - inicio

    # timeout do NOSSO orçamento na tentativa original — nunca chegou a tentar
    # descobrir outro site
    assert excinfo.value.permite_retentativa is True
    assert chamadas_proximo_site == []  # busca por outro site nunca foi acionada
    assert duracao_s < 0.3  # não esperou o sono inteiro do fake (0.3s > orçamento de 0.05s)


async def test_baixar_episodio_prazo_vencido_nao_espera_resolucao_de_midia_lenta(
    sessionmaker, monkeypatch, tmp_path
):
    """Fase E2: `prazo` já vencido ao ENTRAR em `baixar_episodio` — mesmo com
    uma resolução de mídia lenta (`resiliencia.chamar` fake com
    `asyncio.sleep` real, maior que o orçamento restante), `_dentro_do_prazo`
    calcula um timeout de `wait_for` já em 0 e cancela sem esperar o sono
    inteiro. `FalhaDeExtracao` resultante é retentável — o orçamento é nosso,
    não uma falha do site."""

    async def _chamar_lento(sessionmaker, extrator, operacao, *, nome_operacao="operacao", **_):
        await asyncio.sleep(0.3)
        return LinkDeMidia(url="https://x/media.m3u8", cabecalhos={})

    monkeypatch.setattr(resiliencia, "chamar", _chamar_lento)

    extrator = SimpleNamespace(dominio="site-falso.io", exige_navegador_para_midia=False)
    prazo_vencido = time.monotonic() - 1.0

    inicio = time.monotonic()
    with pytest.raises(FalhaDeExtracao) as excinfo:
        await servico.baixar_episodio(
            sessionmaker,
            _config_de_teste(tmp_path),
            extrator=extrator,
            url_episodio="https://x/ep1",
            destino=tmp_path / "saida.mp4",
            prazo=prazo_vencido,
        )
    duracao_s = time.monotonic() - inicio

    assert excinfo.value.permite_retentativa is True
    assert duracao_s < 0.3  # não esperou o sono inteiro do fake


async def test_baixar_episodio_sem_prazo_preserva_comportamento_anterior(
    sessionmaker, monkeypatch, tmp_path
):
    """Fase E2: `prazo=None` (default) não aplica teto agregado nenhum a
    `baixar_episodio` — mesmo comportamento de antes desta correção, apenas
    os tetos internos de `resiliencia.chamar`/`_conferir_link_de_midia`.

    Gap 2 da 2ª rodada de revisão (PLANO_PADRONIZACAO_FONTES.md): além do
    resultado bater, dois spies provam os dois lados do contrato de
    `prazo=None` — que uma regressão futura pegaria e o `resultado == destino`
    sozinho não pegava: (1) `chamadas_conferencia` prova que
    `_conferir_link_de_midia` de fato rodou (pegaria uma regressão que pulasse
    a conferência quando `prazo is None`); (2) `chamadas_dentro_do_prazo` prova
    que `_dentro_do_prazo`/`wait_for` NUNCA foi acionado (pegaria uma regressão
    que passasse a aplicar `_dentro_do_prazo` mesmo com `prazo=None`)."""
    link_fake = LinkDeMidia(url="https://x/media.m3u8", cabecalhos={})

    async def _chamar_direto(sessionmaker, extrator, operacao, *, nome_operacao="operacao", **_):
        return link_fake

    chamadas_conferencia: list[LinkDeMidia] = []

    async def _conferir_fake(link):
        chamadas_conferencia.append(link)

    async def _baixar_fake(link, destino, ffmpeg):
        return destino

    chamadas_dentro_do_prazo: list[float] = []
    _dentro_do_prazo_original = servico._dentro_do_prazo

    async def _dentro_do_prazo_espiao(corotina, prazo):
        chamadas_dentro_do_prazo.append(prazo)
        return await _dentro_do_prazo_original(corotina, prazo)

    monkeypatch.setattr(resiliencia, "chamar", _chamar_direto)
    monkeypatch.setattr(servico, "_conferir_link_de_midia", _conferir_fake)
    monkeypatch.setattr(download, "baixar", _baixar_fake)
    monkeypatch.setattr(servico, "_dentro_do_prazo", _dentro_do_prazo_espiao)

    extrator = SimpleNamespace(dominio="site-falso.io", exige_navegador_para_midia=False)
    destino = tmp_path / "saida.mp4"

    resultado = await servico.baixar_episodio(
        sessionmaker,
        _config_de_teste(tmp_path),
        extrator=extrator,
        url_episodio="https://x/ep1",
        destino=destino,
    )

    assert resultado == destino
    assert chamadas_conferencia == [link_fake]  # a conferência de fato rodou
    assert chamadas_dentro_do_prazo == []  # _dentro_do_prazo/wait_for nunca foi acionado


class _ExtratorDeBuscaFalso:
    """Fake mínimo para `buscar_em_com_variantes` — não herda de
    `ExtratorDeSite` (ABC) porque `resiliencia.chamar` é substituído nestes
    testes por uma versão que chama a operação direto, sem checar
    `extrator.exige_navegador`/cooldown (mesmo raciocínio de
    `tests/test_resolucao.py::_ExtratorFalso`)."""

    dominio = "site-falso.io"

    def __init__(
        self,
        *,
        respostas: dict[str, list[ResultadoBusca]] | None = None,
        falha_na_variante: str | None = None,
        excecao: Exception | None = None,
    ) -> None:
        self._respostas = respostas or {}
        self._falha_na_variante = falha_na_variante
        self._excecao = excecao
        self.chamadas: list[str] = []

    def buscar(self, cliente, titulo: str) -> list[ResultadoBusca]:
        self.chamadas.append(titulo)
        if titulo == self._falha_na_variante:
            raise self._excecao
        return self._respostas.get(titulo, [])


def _resiliencia_direta(monkeypatch: pytest.MonkeyPatch) -> None:
    """`resiliencia.chamar` passa a chamar a operação direto, sem
    `ClienteLeve`/cooldown/circuit breaker — mesmo padrão de
    `tests/test_resolucao.py::_resiliencia_sem_cliente_real`."""

    async def _chamar_falso(sessionmaker, extrator, operacao, *, nome_operacao="operacao", **_):
        return operacao(None)

    monkeypatch.setattr(resiliencia, "chamar", _chamar_falso)


async def test_buscar_em_com_variantes_para_na_primeira_variante_com_candidatos(
    sessionmaker, monkeypatch
):
    _resiliencia_direta(monkeypatch)
    candidato = ResultadoBusca(titulo_exibicao="Anime X", identificador="x", url="https://x/1")
    extrator = _ExtratorDeBuscaFalso(respostas={"Anime X: Sub": [candidato]})
    monkeypatch.setattr(servico, "obter_extrator", lambda dominio: extrator)

    resultado, variante_vencedora = await servico.buscar_em_com_variantes(
        sessionmaker, "site-falso.io", ["Anime X: Sub", "Anime X"], referencia="Anime X"
    )

    assert resultado == servico.ResultadoDeFonte(
        dominio="site-falso.io", candidatos=[candidato], indisponivel=False, motivo=None
    )
    assert variante_vencedora is None  # variante 0 (título original) venceu
    assert extrator.chamadas == ["Anime X: Sub"]  # 2ª variante nem foi tentada


async def test_buscar_em_com_variantes_devolve_variante_vencedora_quando_nao_e_a_original(
    sessionmaker, monkeypatch
):
    _resiliencia_direta(monkeypatch)
    candidato = ResultadoBusca(titulo_exibicao="Anime X", identificador="x", url="https://x/1")
    extrator = _ExtratorDeBuscaFalso(respostas={"Anime X": [candidato]})
    monkeypatch.setattr(servico, "obter_extrator", lambda dominio: extrator)

    resultado, variante_vencedora = await servico.buscar_em_com_variantes(
        sessionmaker, "site-falso.io", ["Anime X: Sub", "Anime X"], referencia="Anime X"
    )

    assert resultado.candidatos == [candidato]
    assert variante_vencedora == "Anime X"
    assert extrator.chamadas == ["Anime X: Sub", "Anime X"]


async def test_buscar_em_com_variantes_falha_de_extracao_aborta_variantes_restantes(
    sessionmaker, monkeypatch
):
    _resiliencia_direta(monkeypatch)
    extrator = _ExtratorDeBuscaFalso(
        falha_na_variante="Anime X: Sub",
        excecao=SiteEmCooldown("site em cooldown", dominio="site-falso.io"),
    )
    monkeypatch.setattr(servico, "obter_extrator", lambda dominio: extrator)

    resultado, variante_vencedora = await servico.buscar_em_com_variantes(
        sessionmaker, "site-falso.io", ["Anime X: Sub", "Anime X"], referencia="Anime X"
    )

    assert resultado.indisponivel is True
    assert resultado.candidatos == []
    assert resultado.motivo == "site em cooldown"
    assert variante_vencedora is None
    assert extrator.chamadas == ["Anime X: Sub"]  # 2ª variante não foi tentada


async def test_buscar_em_com_variantes_nenhuma_variante_encontra_nada(sessionmaker, monkeypatch):
    _resiliencia_direta(monkeypatch)
    extrator = _ExtratorDeBuscaFalso()
    monkeypatch.setattr(servico, "obter_extrator", lambda dominio: extrator)

    resultado, variante_vencedora = await servico.buscar_em_com_variantes(
        sessionmaker, "site-falso.io", ["Anime X: Sub", "Anime X"], referencia="Anime X"
    )

    assert resultado == servico.ResultadoDeFonte(
        dominio="site-falso.io", candidatos=[], indisponivel=False, motivo=None
    )
    assert variante_vencedora is None
    assert extrator.chamadas == ["Anime X: Sub", "Anime X"]


async def test_buscar_em_com_variantes_descarta_candidato_que_nao_corresponde_a_referencia(
    sessionmaker, monkeypatch
):
    _resiliencia_direta(monkeypatch)
    candidato_errado_1 = ResultadoBusca(
        titulo_exibicao="Outro Anime Totalmente Diferente", identificador="y1", url="https://y/1"
    )
    candidato_errado_2 = ResultadoBusca(
        titulo_exibicao="Anime Completamente Distinto", identificador="y2", url="https://y/2"
    )
    extrator = _ExtratorDeBuscaFalso(
        respostas={
            "Anime X: Sub": [candidato_errado_1],
            "Anime X": [candidato_errado_2],
        }
    )
    monkeypatch.setattr(servico, "obter_extrator", lambda dominio: extrator)

    resultado, variante_vencedora = await servico.buscar_em_com_variantes(
        sessionmaker, "site-falso.io", ["Anime X: Sub", "Anime X"], referencia="Anime X"
    )

    assert resultado.candidatos == []
    assert resultado.indisponivel is False
    assert resultado.motivo == "2 candidato(s) descartado(s) por não corresponder ao título"
    assert variante_vencedora is None
    # loop continuou pra 2ª variante mesmo a 1ª tendo devolvido candidato (só não válido)
    assert extrator.chamadas == ["Anime X: Sub", "Anime X"]


def _configurar_extratores(
    monkeypatch: pytest.MonkeyPatch, *extratores: _ExtratorDeBuscaFalso
) -> None:
    """Registra `extratores` (cada um com `.dominio` já setado) como
    `servico.EXTRATORES`/`servico.obter_extrator` — usado pelos testes de
    `buscar_por_site_com_variantes` abaixo, mesmo padrão de
    `monkeypatch.setattr(servico, "obter_extrator", ...)` já usado pros testes
    de `buscar_em_com_variantes` acima, mais `monkeypatch.setattr(servico,
    "EXTRATORES", ...)` (mesmo padrão de
    `tests/test_resolucao.py::test_pula_site_em_cooldown`) pra controlar o
    `dominios=None` (percorre todo `EXTRATORES`)."""
    monkeypatch.setattr(servico, "EXTRATORES", tuple(extratores))
    mapa = {extrator.dominio: extrator for extrator in extratores}
    monkeypatch.setattr(servico, "obter_extrator", lambda dominio: mapa[dominio])


async def test_buscar_por_site_com_variantes_cada_site_busca_de_forma_independente(
    sessionmaker, monkeypatch
):
    """Site A acha na 1ª variante, site B só na 2ª — não existe mais rodada
    compartilhada (INV-1', fatia 3/4): os dois aparecem no dict final, cada
    um com seu próprio resultado, sem overwrite entre eles."""
    _resiliencia_direta(monkeypatch)
    candidato_a = ResultadoBusca(titulo_exibicao="Anime X", identificador="a", url="https://a/1")
    candidato_b = ResultadoBusca(titulo_exibicao="Anime X", identificador="b", url="https://b/1")
    extrator_a = _ExtratorDeBuscaFalso(respostas={"Anime X: Sub": [candidato_a]})
    extrator_a.dominio = "site-a.io"
    extrator_b = _ExtratorDeBuscaFalso(respostas={"Anime X": [candidato_b]})
    extrator_b.dominio = "site-b.io"
    _configurar_extratores(monkeypatch, extrator_a, extrator_b)

    resultado = await servico.buscar_por_site_com_variantes(
        sessionmaker, ["Anime X: Sub", "Anime X"], referencia="Anime X"
    )

    assert resultado == {
        "site-a.io": servico.ResultadoDeFonte(
            dominio="site-a.io", candidatos=[candidato_a], indisponivel=False, motivo=None
        ),
        "site-b.io": servico.ResultadoDeFonte(
            dominio="site-b.io", candidatos=[candidato_b], indisponivel=False, motivo=None
        ),
    }
    assert extrator_a.chamadas == ["Anime X: Sub"]  # achou na 1ª, não tentou a 2ª
    assert extrator_b.chamadas == ["Anime X: Sub", "Anime X"]  # só achou na 2ª


async def test_buscar_por_site_com_variantes_site_em_cooldown_nao_e_chamado(
    sessionmaker, monkeypatch
):
    _resiliencia_direta(monkeypatch)
    candidato = ResultadoBusca(titulo_exibicao="Anime X", identificador="x", url="https://x/1")
    extrator_disponivel = _ExtratorDeBuscaFalso(respostas={"Anime X": [candidato]})
    extrator_disponivel.dominio = "site-disponivel.io"
    extrator_cooldown = _ExtratorDeBuscaFalso()
    extrator_cooldown.dominio = "site-cooldown.io"
    _configurar_extratores(monkeypatch, extrator_disponivel, extrator_cooldown)

    async with sessionmaker() as sessao:
        sessao.add(
            EstadoSite(
                site_dominio="site-cooldown.io",
                falhas_consecutivas=3,
                cooldown_ate=datetime.now(UTC) + timedelta(hours=1),
            )
        )
        await sessao.commit()

    resultado = await servico.buscar_por_site_com_variantes(
        sessionmaker, ["Anime X"], referencia="Anime X"
    )

    assert resultado["site-cooldown.io"].indisponivel is True
    assert "cooldown" in resultado["site-cooldown.io"].motivo
    assert resultado["site-disponivel.io"] == servico.ResultadoDeFonte(
        dominio="site-disponivel.io", candidatos=[candidato], indisponivel=False, motivo=None
    )
    assert extrator_cooldown.chamadas == []  # em cooldown, nunca chegou a ser chamado


async def test_buscar_por_site_com_variantes_excecao_nao_tratada_marca_indisponivel(
    sessionmaker, monkeypatch
):
    _resiliencia_direta(monkeypatch)
    excecao = ValueError("erro inesperado do site")
    extrator = _ExtratorDeBuscaFalso(falha_na_variante="Anime X", excecao=excecao)
    extrator.dominio = "site-falso.io"
    _configurar_extratores(monkeypatch, extrator)

    resultado = await servico.buscar_por_site_com_variantes(
        sessionmaker, ["Anime X"], referencia="Anime X"
    )

    assert resultado == {
        "site-falso.io": servico.ResultadoDeFonte(
            dominio="site-falso.io", candidatos=[], indisponivel=True, motivo=str(excecao)
        ),
    }


async def test_buscar_por_site_com_variantes_dominios_none_cobre_todo_extratores(
    sessionmaker, monkeypatch
):
    _resiliencia_direta(monkeypatch)
    extrator_a = _ExtratorDeBuscaFalso()
    extrator_a.dominio = "site-a.io"
    extrator_b = _ExtratorDeBuscaFalso()
    extrator_b.dominio = "site-b.io"
    _configurar_extratores(monkeypatch, extrator_a, extrator_b)

    resultado = await servico.buscar_por_site_com_variantes(
        sessionmaker, ["Anime X"], referencia="Anime X"
    )

    assert set(resultado) == {"site-a.io", "site-b.io"}
    assert extrator_a.chamadas == ["Anime X"]
    assert extrator_b.chamadas == ["Anime X"]


async def test_buscar_por_site_com_variantes_dominios_explicito_limita_busca(
    sessionmaker, monkeypatch
):
    """Passar `dominios` restringe a busca a esses sites — o site fora da
    lista não é consultado nem aparece no dict final."""
    _resiliencia_direta(monkeypatch)
    extrator_a = _ExtratorDeBuscaFalso()
    extrator_a.dominio = "site-a.io"
    extrator_b = _ExtratorDeBuscaFalso()
    extrator_b.dominio = "site-b.io"
    _configurar_extratores(monkeypatch, extrator_a, extrator_b)

    resultado = await servico.buscar_por_site_com_variantes(
        sessionmaker, ["Anime X"], referencia="Anime X", dominios=["site-a.io"]
    )

    assert set(resultado) == {"site-a.io"}
    assert extrator_a.chamadas == ["Anime X"]
    assert extrator_b.chamadas == []  # fora do subconjunto pedido, nunca consultado

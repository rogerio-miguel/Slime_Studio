"""Listagem de episódios e download com fallback entre sites (ESPECIFICACAO.md
§3A) — ponto único que o resto do backend usa pra listar/baixar sem conhecer
resiliência, sessão ou circuit breaker por trás. A busca por título mora em
`extractors/busca/servico.py`.
"""

import asyncio
import logging
import time
from collections.abc import Coroutine
from dataclasses import replace
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config import Config
from core.enums import VersaoEpisodio
from core.erros import FalhaDeExtracao
from extractors import download, resiliencia, resolucao
from extractors.base import EpisodioRemoto, ExtratorDeSite, LinkDeMidia
from extractors.registro import obter_extrator
from models.anime import Anime
from models.episodio import Episodio

_SessionMaker = async_sessionmaker[AsyncSession]

logger = logging.getLogger(__name__)

# Teto de `wait_for` para `_conferir_link_de_midia`: acima do timeout de 15s que
# `download.conferir_link_de_midia` passa para a checagem HTTP curta
# (`extractors/download.py::_TIMEOUT_S`), mesmo padrão de
# `extractors/resiliencia.py::_TETO_ESPERA_S` — rede de segurança, não primeira
# linha de defesa contra travamento.
_TETO_ESPERA_CONFERENCIA_S = 30

# Teto de relógio de parede pra EXTRAÇÃO da cadeia inteira de
# `baixar_com_fallback_de_site` (busca + listagem + resolução de mídia +
# conferência de link), contado desde o início real da função e aplicado via
# `_dentro_do_prazo`/`wait_for` — não uma soma de tetos independentes por elo
# (essa era a lacuna corrigida nesta revisão: antes, nada limitava de fato o
# tempo gasto descobrindo o próximo site, e a tentativa final não descontava o
# que já tinha sido gasto). Cobre tanto a tentativa original quanto a
# descoberta/tentativa de próximo site (`_proximo_com_episodio`, escalada de
# sessão incluída). `download.baixar` (ffmpeg) fica sempre FORA deste
# orçamento — teto próprio de 2h por design (multiplicador 3 de D-E1),
# deliberadamente independente do orçamento de extração.
#
# Valor mantido em 405s mesmo com a mudança de garantia: troca de site só
# nasce de falha não-retentável (`EstruturaDoSiteMudou`, `SiteEmCooldown`,
# `FonteNaoEncontrada`), tipicamente rápida de detectar — reavaliar quando a
# Fase E1 tiver dados reais de distribuição de duração da cadeia.
#
# Limitação herdada do mesmo padrão já em uso por
# `api/servicos/busca.py::_TETO_EXPANSAO_S`: cancelar via `wait_for` não mata
# a thread do SO já em voo dentro de `asyncio.to_thread`
# (`extractors/resiliencia.py`), só o aguardo por ela — na pior das hipóteses
# ela roda até terminar sozinha. Mesma limitação documentada lá, não é
# regressão nova desta revisão.
#
# Estourar este teto não é "site lento", é "gastamos tempo demais tentando
# trocar de site" — propaga a última falha real em vez de insistir, e nunca
# loga a URL do episódio (pode carregar token de sessão).
_ORCAMENTO_CADEIA_S = 405


async def _dentro_do_prazo[T](corotina: Coroutine[Any, Any, T], prazo: float) -> T:
    """`wait_for` com o que sobrou do orçamento de cadeia (`prazo` é um
    `time.monotonic()` absoluto, não uma duração). Prazo já vencido => timeout
    imediato (`wait_for` ainda agenda e cancela a corrotina corretamente, sem
    "coroutine was never awaited")."""
    return await asyncio.wait_for(corotina, timeout=max(prazo - time.monotonic(), 0))


async def listar_episodios_em(
    sessionmaker: _SessionMaker, dominio: str, identificador: str
) -> list[EpisodioRemoto]:
    extrator = obter_extrator(dominio)
    return await resiliencia.chamar(
        sessionmaker,
        extrator,
        lambda cliente: extrator.listar_episodios(cliente, identificador),
        nome_operacao="listar_episodios",
    )


async def baixar_episodio(
    sessionmaker: _SessionMaker,
    config: Config,
    *,
    extrator: ExtratorDeSite,
    url_episodio: str,
    destino: Path,
    prazo: float | None = None,
) -> Path:
    """Resolve a mídia do episódio (com conferência de link) e baixa via `ffmpeg`.

    `prazo` (Fase E2, PLANO_PADRONIZACAO_FONTES.md): teto de relógio de
    parede — `time.monotonic()` absoluto — aplicado só à resolução de mídia +
    conferência de link, a parte que compete pelo orçamento de
    `baixar_com_fallback_de_site::_ORCAMENTO_CADEIA_S`. `None` (default,
    comportamento de qualquer chamador fora do laço de fallback) preserva o
    comportamento anterior a esta fase: nenhum teto agregado aqui, só os tetos
    internos de `resiliencia.chamar`/`_conferir_link_de_midia`.

    `download.baixar` (ffmpeg) nunca entra no `wait_for` — teto próprio de 2h
    por design, deliberadamente fora do orçamento de extração.
    """

    async def _resolver_e_conferir() -> LinkDeMidia:
        link = await resiliencia.chamar(
            sessionmaker,
            extrator,
            lambda cliente: extrator.resolver_midia(cliente, url_episodio),
            nome_operacao="resolver_midia",
            # Único ponto do sistema que consome `exige_navegador_para_midia`:
            # `resolver_midia` é a operação que pode precisar do JS da página rodando
            # (`extractors/base.py`), busca e listagem não.
            exigir_navegador=extrator.exige_navegador_para_midia,
        )
        await _conferir_link_de_midia(link)
        return link

    try:
        link = (
            await _resolver_e_conferir()
            if prazo is None
            else await _dentro_do_prazo(_resolver_e_conferir(), prazo)
        )
    except TimeoutError as excecao:
        raise FalhaDeExtracao(
            f"resolução de mídia em {extrator.dominio} excedeu o orçamento restante da cadeia",
            dominio=extrator.dominio,
            permite_retentativa=True,  # retentável — o orçamento é nosso, não uma falha do site
        ) from excecao

    return await download.baixar(link, destino, str(config.ffmpeg))


async def _conferir_link_de_midia(link: LinkDeMidia) -> None:
    """`download.conferir_link_de_midia` faz uma requisição `requests` síncrona de
    até 15s — sem `to_thread`, isso bloquearia o event loop dentro desta função
    `async`. Mesmo padrão de `to_thread`+`wait_for` de
    `extractors/resiliencia.py::_executar`."""
    try:
        await asyncio.wait_for(
            asyncio.to_thread(download.conferir_link_de_midia, link),
            timeout=_TETO_ESPERA_CONFERENCIA_S,
        )
    except TimeoutError as excecao:
        raise FalhaDeExtracao(
            f"conferência de link de mídia excedeu o teto de {_TETO_ESPERA_CONFERENCIA_S}s",
            permite_retentativa=True,
        ) from excecao


async def baixar_com_fallback_de_site(
    sessionmaker: _SessionMaker,
    config: Config,
    *,
    anime: Anime,
    episodio: Episodio,
    destino: Path,
) -> Path:
    """Laço "site mapeado falhou -> tenta o próximo" (D7 do plano).

    Falha **retentável** (rede, sessão expirada) propaga sem trocar de site — o
    job será reagendado (`db/fila.py::falhar_extracao`) e tenta de novo no
    mesmo site, comportamento certo pra uma falha transitória. Só uma falha
    **não-retentável** (`EstruturaDoSiteMudou`, site em `SiteEmCooldown`) aciona
    a busca pelo próximo site (`resolucao.proximo_site_para`), que por sua vez
    precisa localizar o mesmo `episodio.numero` na listagem do novo site antes de
    tentar baixar por lá.

    Instrumentação (Fase E1, PLANO_PADRONIZACAO_FONTES.md): loga no fim da
    cadeia inteira — sucesso em `info`, esgotamento dos sites em `warning` —
    com `sites_tentados` (tamanho de `ja_tentados`) e a duração total, nunca a
    URL do episódio, que pode carregar token de sessão.

    Deadline de cadeia (Fase E2): `prazo` é um teto de relógio de parede
    (`_ORCAMENTO_CADEIA_S`) aplicado via `_dentro_do_prazo`/`wait_for` em duas
    frentes — a resolução de mídia de `baixar_episodio` (própria e a do site
    novo) e a busca/listagem de `_proximo_com_episodio` — mais o portão
    (`time.monotonic() >= prazo`) logo antes de retomar o download num site
    novo, como segunda camada de diagnóstico. Qualquer estouro propaga a MESMA
    falha não-retentável que motivou a troca (`raise` sem argumento, dentro do
    `except`, ou `raise excecao` depois do `TimeoutError` de
    `_proximo_com_episodio`) em vez de tentar o site novo. Nunca substitui a
    falha real por um erro de deadline genérico: quem chama
    (`db/fila.py::falhar_extracao` via `worker/executor.py`) decide reagendar
    ou não pelo `permite_retentativa` da própria falha original, sem precisar
    conhecer um tipo novo.
    """
    dominio = episodio.site_origem
    url_episodio = episodio.url_fonte
    ja_tentados = {dominio}
    inicio = time.monotonic()
    prazo = inicio + _ORCAMENTO_CADEIA_S

    while True:
        extrator = obter_extrator(dominio)
        try:
            resultado = await baixar_episodio(
                sessionmaker,
                config,
                extrator=extrator,
                url_episodio=url_episodio,
                destino=destino,
                prazo=prazo,
            )
        except FalhaDeExtracao as excecao:
            if excecao.permite_retentativa:
                raise

            try:
                proximo = await _dentro_do_prazo(
                    _proximo_com_episodio(
                        sessionmaker, anime, episodio.numero, ja_tentados, episodio.versao
                    ),
                    prazo,
                )
            except TimeoutError:
                logger.warning(
                    "download abortou a busca por outro site por estouro do orçamento de "
                    "cadeia (%ds): anime_id=%s episodio_numero=%s sites_tentados=%d "
                    "duracao_total_s=%.3f",
                    _ORCAMENTO_CADEIA_S,
                    anime.id,
                    episodio.numero,
                    len(ja_tentados),
                    time.monotonic() - inicio,
                )
                # `from None`: `excecao` é a falha original já capturada, não uma causada por este
                # `TimeoutError` — sem isso o traceback ganharia um "During handling of the above
                # exception..." espúrio, ligando duas exceções que não têm relação de causa.
                raise excecao from None

            if proximo is None:
                logger.warning(
                    "download esgotou os sites disponíveis: anime_id=%s episodio_numero=%s "
                    "sites_tentados=%d duracao_total_s=%.3f",
                    anime.id,
                    episodio.numero,
                    len(ja_tentados),
                    time.monotonic() - inicio,
                )
                raise

            if time.monotonic() >= prazo:
                logger.warning(
                    "download abortou troca de site por estouro do orçamento de cadeia "
                    "(%ds): anime_id=%s episodio_numero=%s proximo_dominio=%s "
                    "sites_tentados=%d duracao_total_s=%.3f",
                    _ORCAMENTO_CADEIA_S,
                    anime.id,
                    episodio.numero,
                    proximo[0],
                    len(ja_tentados),
                    time.monotonic() - inicio,
                )
                raise

            dominio, url_episodio = proximo
            ja_tentados.add(dominio)
            continue

        logger.info(
            "download concluído: anime_id=%s episodio_numero=%s sites_tentados=%d "
            "duracao_total_s=%.3f",
            anime.id,
            episodio.numero,
            len(ja_tentados),
            time.monotonic() - inicio,
        )
        return resultado


async def _proximo_com_episodio(
    sessionmaker: _SessionMaker,
    anime: Anime,
    numero_episodio: int,
    ja_tentados: set[str],
    versao: VersaoEpisodio,
) -> tuple[str, str] | None:
    """Anda pela cadeia de próximos sites até achar um que já foi tentado (desiste,
    devolve `None`) ou que lista `numero_episodio` (usa esse). Sites mapeados/
    descobertos que não têm o episódio são marcados como tentados e pulados.

    Sem parâmetro separado pra "domínio que acabou de falhar": `ja_tentados`
    (mantido pelo chamador, `baixar_com_fallback_de_site`) já inclui esse
    domínio antes desta função ser chamada — repassar os dois seria
    redundante. `resolucao.proximo_site_para` exclui `ja_tentados` inteiro
    ao escolher a próxima fonte mapeada, não só o último domínio (ver
    docstring de lá pro porquê disso importa desde que a escolha de fonte
    passou a priorizar recência, não mais prioridade fixa de site).

    `versao` é `Episodio.versao` do episódio em fallback — propagada a
    `resolucao.proximo_site_para` pra preservar a versão pedida entre sites
    (Fase 2 da modelagem dublado/legendado); dentro de cada listagem, casar
    só por `numero` vira "casar por número E versão" quando a listagem rotula
    episódios (`ep.versao is not None`) e `versao` é confirmada
    (LEGENDADO/DUBLADO) — `filtrar_por_numero_e_versao`.
    """
    while True:
        # `proximo_site_para` já exclui todo domínio em `ja_tentados` (mapeadas
        # filtradas + descoberta ao vivo) — nunca devolve um já tentado.
        proxima_fonte = await resolucao.proximo_site_para(sessionmaker, anime, ja_tentados, versao)
        if proxima_fonte is None:
            return None

        episodios_remotos = await listar_episodios_em(
            sessionmaker, proxima_fonte.dominio, proxima_fonte.identificador
        )
        # A fonte numera o anime inteiro de forma contínua entre temporadas;
        # `numero_episodio` é `Episodio.numero` (por temporada). Recorta antes
        # de casar — mesmo recorte de `api/servicos/fontes.py` e `jobs.py`;
        # passthrough quando `numero_temporada is None`.
        episodios_remotos = recortar_para_temporada(episodios_remotos, anime.numero_temporada)
        correspondentes = filtrar_por_numero_e_versao(episodios_remotos, numero_episodio, versao)
        if len(correspondentes) > 1:
            # Mais de um rótulo mapeia pro mesmo `numero` (ex. "7"/"07" —
            # extractors/base.py::EpisodioRemoto) — o contrato de fallback só
            # carrega `numero_episodio` (int), sem como desambiguar por
            # rótulo aqui. Escolha determinística (1ª ocorrência, ordem já
            # estável do adapter) em vez de silenciosa — nunca some do log.
            logger.warning(
                "%d episódios remotos com numero=%d em %r (rótulos: %s) — usando o 1º",
                len(correspondentes),
                numero_episodio,
                proxima_fonte.dominio,
                [ep.rotulo for ep in correspondentes],
            )
        correspondente = correspondentes[0] if correspondentes else None
        if correspondente is not None:
            return proxima_fonte.dominio, correspondente.url

        ja_tentados.add(proxima_fonte.dominio)


def filtrar_por_numero_e_versao(
    episodios: list[EpisodioRemoto], numero: int, versao: VersaoEpisodio
) -> list[EpisodioRemoto]:
    """Casa por `numero` primeiro (comportamento base), depois delega o filtro
    de versão a `filtrar_por_versao`.

    Pública (não `_`-prefixada) porque também é usada por
    `api/servicos/jobs.py::criar_job_site` — mesmo risco de pegar o rótulo da
    versão errada existe lá (`resultado.dominio`/`resultado.identificador`
    pode listar episódios das duas versões, ex. página do AnimesDrive que
    cobre ambas)."""
    correspondentes = [ep for ep in episodios if ep.numero == numero]
    return filtrar_por_versao(correspondentes, versao)


def filtrar_por_versao(
    episodios: list[EpisodioRemoto], versao: VersaoEpisodio
) -> list[EpisodioRemoto]:
    """Quando a versão pedida é confirmada (LEGENDADO/DUBLADO) e a listagem
    rotula pelo menos um episódio (`ep.versao is not None` — site que
    diferencia, ex. AnimesDrive), EXIGE `ep.versao == versao`: a listagem tem
    episódios das duas versões e não filtrar pegaria a versão errada
    silenciosamente. Sites que não rotulam (`ep.versao` sempre `None`) ou
    `versao == DESCONHECIDA` devolvem a lista sem filtrar (comportamento
    anterior a esta fase).

    Pública (não `_`-prefixada) pelo mesmo motivo de `filtrar_por_numero_e_versao`
    — usada por mais de um módulo (`api/servicos/fontes.py::listar_episodios_remotos`)."""
    if versao == VersaoEpisodio.DESCONHECIDA:
        return episodios

    rotulados = [ep for ep in episodios if ep.versao is not None]
    if not rotulados:
        return episodios
    return [ep for ep in rotulados if ep.versao == versao]


def recortar_para_temporada(
    episodios: list[EpisodioRemoto], numero_temporada: int | None
) -> list[EpisodioRemoto]:
    """Recorta uma listagem contínua da fonte para uma única temporada e a
    renumera para casar com `Episodio.numero` (por temporada, reiniciando em 1).

    A fonte (ex. AnimeFire) trata o anime inteiro como uma entrada e numera os
    episódios de forma absoluta e contínua entre temporadas; cada temporada é
    uma linha `Anime` separada no nosso banco. Seis casos, nesta ordem:

    1. `numero_temporada is None` (o anime é temporada única no nosso banco) →
       listagem devolvida intacta.
    2. Nenhum episódio carrega `temporada` (fonte sem esse conceito —
       `animesdrive`/`meusanimes`) → listagem devolvida intacta.
    3. Há episódios rotulados com a temporada pedida → renumera só eles (caso 6).
    4. Nenhum episódio da temporada pedida e a fonte só tem uma temporada (o
       rótulo de season da fonte diverge do nosso) → listagem devolvida intacta.
    5. Nenhum episódio da temporada pedida e a fonte tem várias → `warning` com
       as temporadas disponíveis e lista vazia (esta temporada não existe nesta
       fonte).
    6. Renumera o recorte: onde `numero_na_temporada` existe e difere de
       `numero`, `numero` passa a ser o valor por temporada e o contínuo
       original vai para `numero_absoluto`; os demais passam intactos. Roda
       mesmo quando o recorte não reduziu a lista — cobre a entrada que é uma
       temporada só mas numera a partir de um valor maior que 1.
    """
    if numero_temporada is None:
        return episodios

    temporadas = {ep.temporada for ep in episodios if ep.temporada is not None}
    if not temporadas:
        return episodios

    alvo = [ep for ep in episodios if ep.temporada == numero_temporada]
    if not alvo:
        if len(temporadas) == 1:
            return episodios
        logger.warning(
            "recorte de temporada: temporada %d pedida ausente na fonte "
            "(disponíveis: %s, %d episódios no total) — devolvendo lista vazia",
            numero_temporada,
            sorted(temporadas),
            len(episodios),
        )
        return []

    return [
        replace(ep, numero=ep.numero_na_temporada, numero_absoluto=ep.numero)
        if ep.numero_na_temporada is not None and ep.numero_na_temporada != ep.numero
        else ep
        for ep in alvo
    ]

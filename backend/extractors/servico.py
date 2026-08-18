"""API pública dos extratores (ESPECIFICACAO.md §3A) — ponto único que o resto do
backend usa pra buscar/listar/baixar sem conhecer resiliência, sessão ou circuit
breaker por trás.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config import Config
from core.erros import FalhaDeExtracao
from extractors import circuit_breaker, download, resiliencia, resolucao
from extractors.base import EpisodioRemoto, ExtratorDeSite, LinkDeMidia, ResultadoBusca
from extractors.registro import EXTRATORES, obter_extrator
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


async def buscar_em(
    sessionmaker: _SessionMaker, dominio: str, titulo: str
) -> list[ResultadoBusca]:
    extrator = obter_extrator(dominio)
    return await resiliencia.chamar(
        sessionmaker, extrator, lambda cliente: extrator.buscar(cliente, titulo)
    )


@dataclass(frozen=True, slots=True)
class ResultadoDeFonte:
    """Resultado da busca em um site específico, dentro de
    `buscar_em_todas_as_fontes`. Distingue "busquei e não achei nada"
    (`indisponivel=False`, `candidatos=[]`) de "não consegui nem tentar"
    (`indisponivel=True`, cooldown ou exceção não tratada) — os dois colapsavam
    para o mesmo `[]` antes desta mudança, violando a regra de erro nunca
    silencioso (CLAUDE.md §4)."""

    dominio: str
    candidatos: list[ResultadoBusca]
    indisponivel: bool
    motivo: str | None


async def buscar_em_todas_as_fontes(
    sessionmaker: _SessionMaker, titulo: str
) -> list[ResultadoDeFonte]:
    """Busca em paralelo em todos os EXTRATORES (Strategy Pattern) — usado pela
    busca ao vivo da Home (ainda não catalogado localmente). Falha ou cooldown de
    um site não derruba os demais: cada extrator é isolado, e o resultado
    (disponível ou não, com motivo) vem estruturado em `ResultadoDeFonte`, nunca
    apenas omitido da lista (nunca silencioso, CLAUDE.md §4)."""
    extratores_disponiveis: list[ExtratorDeSite] = []
    por_dominio: dict[str, ResultadoDeFonte] = {}

    # Pré-filtro redundante de propósito: `resiliencia.chamar` (dentro de
    # `buscar_em`) já faz essa mesma checagem de cooldown internamente e
    # levantaria `SiteEmCooldown` de qualquer forma — cairia no branch de
    # exceção abaixo. Filtrar aqui evita essa chamada redundante pra extratores
    # já sabidamente em cooldown, não é redundância acidental.
    for extrator in EXTRATORES:
        if await circuit_breaker.esta_em_cooldown(sessionmaker, extrator.dominio):
            cooldown_ate = await circuit_breaker.obter_cooldown_ate(sessionmaker, extrator.dominio)
            por_dominio[extrator.dominio] = ResultadoDeFonte(
                dominio=extrator.dominio,
                candidatos=[],
                indisponivel=True,
                motivo=_formatar_motivo_cooldown(cooldown_ate),
            )
        else:
            extratores_disponiveis.append(extrator)

    resultados_por_extrator = await asyncio.gather(
        *(buscar_em(sessionmaker, extrator.dominio, titulo) for extrator in extratores_disponiveis),
        return_exceptions=True,
    )

    for extrator, resultado in zip(extratores_disponiveis, resultados_por_extrator, strict=True):
        if isinstance(resultado, BaseException):
            logger.warning(
                "extrator %r falhou na busca por título %r: %s",
                extrator.dominio,
                titulo,
                resultado,
            )
            por_dominio[extrator.dominio] = ResultadoDeFonte(
                dominio=extrator.dominio, candidatos=[], indisponivel=True, motivo=str(resultado)
            )
        else:
            por_dominio[extrator.dominio] = ResultadoDeFonte(
                dominio=extrator.dominio, candidatos=resultado, indisponivel=False, motivo=None
            )

    return [por_dominio[extrator.dominio] for extrator in EXTRATORES]


def _formatar_motivo_cooldown(cooldown_ate: datetime | None) -> str:
    if cooldown_ate is None:
        return "em cooldown"
    return f"em cooldown até {cooldown_ate.strftime('%Y-%m-%d %H:%M:%S UTC')}"


async def listar_episodios_em(
    sessionmaker: _SessionMaker, dominio: str, identificador: str
) -> list[EpisodioRemoto]:
    extrator = obter_extrator(dominio)
    return await resiliencia.chamar(
        sessionmaker, extrator, lambda cliente: extrator.listar_episodios(cliente, identificador)
    )


async def baixar_episodio(
    sessionmaker: _SessionMaker,
    config: Config,
    *,
    extrator: ExtratorDeSite,
    url_episodio: str,
    destino: Path,
) -> Path:
    link = await resiliencia.chamar(
        sessionmaker, extrator, lambda cliente: extrator.resolver_midia(cliente, url_episodio)
    )
    await _conferir_link_de_midia(link)
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
    """
    dominio = episodio.site_origem
    url_episodio = episodio.url_fonte
    ja_tentados = {dominio}

    while True:
        extrator = obter_extrator(dominio)
        try:
            return await baixar_episodio(
                sessionmaker, config, extrator=extrator, url_episodio=url_episodio, destino=destino
            )
        except FalhaDeExtracao as excecao:
            if excecao.permite_retentativa:
                raise

            proximo = await _proximo_com_episodio(
                sessionmaker, anime, episodio.numero, dominio, ja_tentados
            )
            if proximo is None:
                raise
            dominio, url_episodio = proximo
            ja_tentados.add(dominio)


async def _proximo_com_episodio(
    sessionmaker: _SessionMaker,
    anime: Anime,
    numero_episodio: int,
    dominio_que_falhou: str,
    ja_tentados: set[str],
) -> tuple[str, str] | None:
    """Anda pela cadeia de próximos sites até achar um que já foi tentado (desiste,
    devolve `None`) ou que lista `numero_episodio` (usa esse). Sites mapeados/
    descobertos que não têm o episódio são marcados como tentados e pulados."""
    dominio_referencia = dominio_que_falhou
    while True:
        proxima_fonte = await resolucao.proximo_site_para(sessionmaker, anime, dominio_referencia)
        if proxima_fonte is None or proxima_fonte.dominio in ja_tentados:
            return None

        episodios_remotos = await listar_episodios_em(
            sessionmaker, proxima_fonte.dominio, proxima_fonte.identificador
        )
        correspondentes = [ep for ep in episodios_remotos if ep.numero == numero_episodio]
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
        dominio_referencia = proxima_fonte.dominio

"""Busca por título em sites de streaming, com escada de variantes
(ESPECIFICACAO.md §3A) — ponto único que o resto do backend usa pra buscar
sem conhecer resiliência, sessão ou circuit breaker por trás. Listagem e
download moram em `extractors/servico.py`.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.erros import FalhaDeExtracao
from extractors import circuit_breaker, resiliencia
from extractors.base import ExtratorDeSite, ResultadoBusca
from extractors.busca.correspondencia import corresponde_ao_titulo, proximidade_do_titulo
from extractors.registro import EXTRATORES, obter_extrator

_SessionMaker = async_sessionmaker[AsyncSession]

logger = logging.getLogger(__name__)


async def buscar_em(
    sessionmaker: _SessionMaker, dominio: str, titulo: str
) -> list[ResultadoBusca]:
    extrator = obter_extrator(dominio)
    return await resiliencia.chamar(
        sessionmaker,
        extrator,
        lambda cliente: extrator.buscar(cliente, titulo),
        nome_operacao="buscar",
    )


@dataclass(frozen=True, slots=True)
class ResultadoDeFonte:
    """Resultado da busca em um site específico, dentro de `buscar_em`/
    `buscar_em_com_variantes`/`buscar_por_site_com_variantes`. Distingue
    "busquei e não achei nada"
    (`indisponivel=False`, `candidatos=[]`) de "não consegui nem tentar"
    (`indisponivel=True`, cooldown ou exceção não tratada) — os dois colapsavam
    para o mesmo `[]` antes desta mudança, violando a regra de erro nunca
    silencioso (CLAUDE.md §4)."""

    dominio: str
    candidatos: list[ResultadoBusca]
    indisponivel: bool
    motivo: str | None


async def _separar_por_cooldown(
    sessionmaker: _SessionMaker, extratores: list[ExtratorDeSite]
) -> tuple[list[ExtratorDeSite], dict[str, ResultadoDeFonte]]:
    """Separa `extratores` entre os disponíveis (não em cooldown) e os já
    resolvidos como indisponíveis — pré-filtro redundante de propósito:
    `resiliencia.chamar` já faz essa mesma checagem de cooldown internamente e
    levantaria `SiteEmCooldown` de qualquer forma, caindo no mesmo motivo de
    "indisponível". Filtrar aqui evita essa chamada redundante pra extratores
    já sabidamente em cooldown, não é redundância acidental."""
    disponiveis: list[ExtratorDeSite] = []
    por_dominio: dict[str, ResultadoDeFonte] = {}

    for extrator in extratores:
        if await circuit_breaker.esta_em_cooldown(sessionmaker, extrator.dominio):
            cooldown_ate = await circuit_breaker.obter_cooldown_ate(sessionmaker, extrator.dominio)
            por_dominio[extrator.dominio] = ResultadoDeFonte(
                dominio=extrator.dominio,
                candidatos=[],
                indisponivel=True,
                motivo=_formatar_motivo_cooldown(cooldown_ate),
            )
        else:
            disponiveis.append(extrator)

    return disponiveis, por_dominio


async def buscar_em_com_variantes(
    sessionmaker: _SessionMaker, dominio: str, variantes: list[str], *, referencia: str
) -> tuple[ResultadoDeFonte, str | None]:
    """Tenta cada variante em `dominio`, na ordem, e para na primeira que
    devolver candidatos validados contra `referencia`
    (`extractors/busca/correspondencia.py::corresponde_ao_titulo`). Devolve o
    `ResultadoDeFonte` e a variante que funcionou (`None` quando foi a variante
    0, o título original).

    `ResultadoDeFonte.candidatos` volta ordenado por
    `extractors/busca/correspondencia.py::proximidade_do_titulo`: o match exato
    de `referencia` primeiro, depois os que só compartilham prefixo, cada grupo
    do comprimento mais próximo ao mais distante. Importa porque a sonda larga
    (recall pela 1ª palavra em `variantes_de_busca`) faz uma variante devolver
    vários cards legítimos e `candidatos[0]` é o que a UI mostra e a captura
    tende a pegar. Sort estável — no empate, a ordem em que o site listou fica.

    `referencia` é keyword-only e sem default derivado de `variantes[0]` de
    propósito: num chamador futuro a referência não será o primeiro elemento
    da lista de variantes.

    Candidatos que a busca devolve mas não correspondem a `referencia` são
    descartados e o loop CONTINUA pra próxima variante — não é o mesmo caso
    de "site não achou nada" nessa variante, é "achou algo errado, tenta de
    novo" (nunca silencioso, CLAUDE.md §4): `descartados` acumula a
    contagem e vira `motivo` na resposta final se nenhuma variante validar.

    `FalhaDeExtracao` de qualquer variante aborta as restantes — mesmo
    critério de "indisponível" usado por `_separar_por_cooldown` (nunca
    silencioso, CLAUDE.md §4): uma falha de extração não é "não achei nada",
    é "não consegui nem tentar"."""
    extrator = obter_extrator(dominio)
    descartados = 0
    for indice, variante in enumerate(variantes):
        try:
            candidatos = await resiliencia.chamar(
                sessionmaker,
                extrator,
                lambda cliente, v=variante: extrator.buscar(cliente, v),
                nome_operacao="buscar",
            )
        except FalhaDeExtracao as excecao:
            logger.warning(
                "extrator %r falhou na busca por variante %r: %s",
                dominio,
                variante,
                excecao,
            )
            return (
                ResultadoDeFonte(
                    dominio=dominio, candidatos=[], indisponivel=True, motivo=str(excecao)
                ),
                None,
            )
        validos = [c for c in candidatos if corresponde_ao_titulo(referencia, c.titulo_exibicao)]
        validos.sort(key=lambda c: proximidade_do_titulo(referencia, c.titulo_exibicao))
        if validos:
            variante_vencedora = variante if indice > 0 else None
            return (
                ResultadoDeFonte(
                    dominio=dominio, candidatos=validos, indisponivel=False, motivo=None
                ),
                variante_vencedora,
            )
        descartados += len(candidatos)  # não achou match válido nesta variante — segue tentando

    motivo = None
    if descartados > 0:
        motivo = f"{descartados} candidato(s) descartado(s) por não corresponder ao título"
        logger.info(
            "extrator %r descartou %d candidato(s) por não corresponder à referência %r",
            dominio,
            descartados,
            referencia,
        )
    return (
        ResultadoDeFonte(dominio=dominio, candidatos=[], indisponivel=False, motivo=motivo),
        None,
    )


async def buscar_por_site_com_variantes(
    sessionmaker: _SessionMaker,
    variantes: list[str],
    *,
    referencia: str,
    dominios: list[str] | None = None,
) -> dict[str, ResultadoDeFonte]:
    """Busca em paralelo em cada site, cada um esgotando sua própria escada de
    variantes de forma independente e exaustiva (D-B1/D-B2, Fase B do
    PLANO_PADRONIZACAO_FONTES.md — escopo `todas`).

    INV-1' — a unidade atômica é o SITE, não a rodada de variante (substitui a
    antiga INV-1 de "rodada atômica"): a rodada atômica causava um bug real —
    um site secundário com busca mais permissiva (ex. AnimesDrive, WordPress
    `?s=` por palavra solta) "ganhava a corrida" numa variante grosseira antes
    do site principal (AnimeFire, busca por prefixo estrito) chegar na sua
    própria variante truncada correta, e o resultado do AnimeFire nunca
    aparecia mesmo tendo o anime. Aqui, cada fonte chama
    `buscar_em_com_variantes` (que já valida cada candidato contra
    `referencia` via `extractors/busca/correspondencia.py::corresponde_ao_titulo`,
    fatia 2) em paralelo com as demais — nenhum site interrompe ou "rouba a
    vez" da busca dos outros. O resultado é a união de todas as fontes onde o
    anime realmente existe, não a rodada de variante que respondeu primeiro.

    `dominios=None` (default) consulta todo `EXTRATORES`. Um subconjunto
    explícito (`dominios=[...]`) limita a busca a esses sites — não usado
    ainda por nenhum chamador desta fatia, mas já com o contrato pronto pra
    uma fatia futura que reestrutura a Fase 2 de termos de provedor (continuar
    só nos sites que ainda não têm candidato, sem reconsultar quem já
    achou)."""
    extratores = [obter_extrator(d) for d in dominios] if dominios is not None else list(EXTRATORES)
    disponiveis, resultados = await _separar_por_cooldown(sessionmaker, extratores)

    respostas = await asyncio.gather(
        *(
            buscar_em_com_variantes(
                sessionmaker, extrator.dominio, variantes, referencia=referencia
            )
            for extrator in disponiveis
        ),
        return_exceptions=True,
    )
    for extrator, resposta in zip(disponiveis, respostas, strict=True):
        if isinstance(resposta, BaseException):
            logger.warning(
                "extrator %r falhou na busca por variantes (referência %r): %s",
                extrator.dominio,
                referencia,
                resposta,
            )
            resultados[extrator.dominio] = ResultadoDeFonte(
                dominio=extrator.dominio, candidatos=[], indisponivel=True, motivo=str(resposta)
            )
        else:
            resultado, _variante_vencedora = resposta
            resultados[extrator.dominio] = resultado
    return resultados


def _formatar_motivo_cooldown(cooldown_ate: datetime | None) -> str:
    if cooldown_ate is None:
        return "em cooldown"
    return f"em cooldown até {cooldown_ate.strftime('%Y-%m-%d %H:%M:%S UTC')}"

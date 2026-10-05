"""Busca por título em sites de streaming, com escada de variantes
(ESPECIFICACAO.md §3A) — ponto único que o resto do backend usa pra buscar
sem conhecer resiliência, sessão ou circuit breaker por trás. Listagem e
download moram em `extractors/servico.py`.
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.erros import FalhaDeExtracao
from extractors import circuit_breaker, resiliencia
from extractors.base import ExtratorDeSite, ResultadoBusca
from extractors.busca.correspondencia import (
    corresponde_a_alguma_referencia,
    e_nome_do_anime,
    proximidade_a_referencias,
)
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


# Variantes buscadas ao mesmo tempo num mesmo site (após a 1ª, que roda sozinha).
# 2 e não mais: o anti-bot dos sites é proporcional à rajada, e o ganho principal
# (site que não tem o anime esgota a escada inteira) já vem de dividir o tempo
# por ~2.
_PARALELISMO_DE_VARIANTES = 2


async def buscar_variantes_em_janelas(
    sessionmaker: _SessionMaker, extrator: ExtratorDeSite, variantes: list[str]
) -> AsyncIterator[tuple[str, list[ResultadoBusca] | BaseException]]:
    """Busca `variantes` em `extrator` e devolve `(variante, resultado)` NA ORDEM
    DA ESCADA; `resultado` é a lista de candidatos ou a exceção daquela chamada
    (devolvida, não levantada — quem consome decide, e só vê a exceção de uma
    variante se nenhuma anterior já resolveu o caso). O consumidor para quando
    quiser; o que já estava em voo na mesma janela só é descartado.

    A 1ª variante roda SOZINHA: é a mais provável e, ao terminar, já deixou a
    sessão do site gravada (`sessao_cache.salvar` faz `get` + `add`, e duas
    chamadas simultâneas num site sem sessão colidiriam na chave primária). As
    demais rodam em janelas de `_PARALELISMO_DE_VARIANTES`. Site que exige
    navegador fica sequencial: cada chamada abriria o seu próprio Chrome."""
    tamanho = 1 if extrator.exige_navegador else _PARALELISMO_DE_VARIANTES
    janelas = [variantes[:1]] + [
        variantes[i : i + tamanho] for i in range(1, len(variantes), tamanho)
    ]
    for janela in janelas:
        respostas = await asyncio.gather(
            *(
                resiliencia.chamar(
                    sessionmaker,
                    extrator,
                    lambda cliente, v=variante: extrator.buscar(cliente, v),
                    nome_operacao="buscar",
                )
                for variante in janela
            ),
            return_exceptions=True,
        )
        for variante, resposta in zip(janela, respostas, strict=True):
            yield variante, resposta


@dataclass(frozen=True, slots=True)
class ResultadoDeFonte:
    """Resultado da busca em um site específico, dentro de `buscar_em`/
    `buscar_em_com_variantes`/`buscar_por_site_com_variantes`. Distingue
    "busquei e não achei nada"
    (`indisponivel=False`, `candidatos=[]`) de "não consegui nem tentar"
    (`indisponivel=True`, cooldown ou exceção não tratada) — os dois colapsavam
    para o mesmo `[]` antes desta mudança, violando a regra de erro nunca
    silencioso (CLAUDE.md §4).

    `correspondencia_incerta=True` é um terceiro estado: `candidatos` NÃO
    bateram nenhuma referência canônica, mas vieram de uma busca por um termo
    que É um nome do anime (`buscar_em_com_variantes`, degrau de sonda
    precisa) — provável acerto sob um título fora do provedor de metadados
    (ex. só PT-BR). Invariante: `candidatos` é homogêneo — ou todos validados
    (`correspondencia_incerta=False`) ou todos incertos (`True`), nunca
    misturado. `ResultadoBusca` (caminho de captura) não carrega essa
    distinção; ela morre aqui e vira um aviso na UI via a rota."""

    dominio: str
    candidatos: list[ResultadoBusca]
    indisponivel: bool
    motivo: str | None
    correspondencia_incerta: bool = False


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


# Teto de cards de "correspondência incerta" devolvidos por site quando NENHUMA
# variante validou contra as referências (ver `buscar_em_com_variantes`). O
# degrau existe pra não perder o anime indexado só sob um título fora do
# provedor de metadados; 5 cobre o caso real (site com 1-2 grafias do mesmo
# anime, achadas por sondas precisas distintas) sem transformar um punhado de
# sondas num despejo de lixo numa lista que o usuário ainda precisa escolher.
_MAXIMO_INCERTOS = 5


async def buscar_em_com_variantes(
    sessionmaker: _SessionMaker, dominio: str, variantes: list[str], *, referencias: list[str]
) -> tuple[ResultadoDeFonte, str | None]:
    """Tenta as variantes em `dominio` na ordem da escada (a 1ª sozinha, o resto em
    janelas de `_PARALELISMO_DE_VARIANTES` — ver `buscar_variantes_em_janelas`;
    o veredito segue a ordem da escada, uma janela só custa a chamada a mais) e para na primeira que
    devolver candidatos validados contra `referencias`
    (`extractors/busca/correspondencia.py::corresponde_a_alguma_referencia` — o
    card só precisa bater com UM dos nomes do anime). Devolve o
    `ResultadoDeFonte` e a variante que funcionou (`None` quando foi a variante
    0, o título original).

    `ResultadoDeFonte.candidatos` volta ordenado por
    `extractors/busca/correspondencia.py::proximidade_a_referencias`: o match
    exato da referência mais parecida primeiro, depois os que só compartilham
    prefixo, cada grupo do comprimento mais próximo ao mais distante. Importa
    porque a sonda larga (recall pela 1ª palavra em `variantes_de_busca`) faz
    uma variante devolver vários cards legítimos e `candidatos[0]` é o que a UI
    mostra e a captura tende a pegar. Sort estável — no empate, a ordem em que
    o site listou fica. (No degrau de correspondência incerta abaixo os
    candidatos NÃO passam por esse sort — nenhum bate referência, então
    `proximidade_a_referencias` não os separa; ficam na ordem em que o site os
    listou, escada de variantes adentro.)

    `referencias` é keyword-only e sem default derivado de `variantes` de
    propósito: são os vários nomes do anime (romaji/inglês/nativo/sinônimos),
    montados pelo chamador, não um recorte da lista de variantes de busca.

    Candidatos que a busca devolve mas não correspondem a nenhuma referência
    são descartados e o loop CONTINUA pra próxima variante — não é o mesmo caso
    de "site não achou nada" nessa variante, é "achou algo errado, tenta de
    novo" (nunca silencioso, CLAUDE.md §4): `descartados` acumula a
    contagem e vira `motivo` na resposta final se nenhuma variante validar.

    Exceção ao descarte (degrau de "correspondência incerta"): se ao fim da
    escada NENHUMA variante produziu card validado, mas alguma variante que É
    um nome canônico do anime
    (`extractors/busca/correspondencia.py::e_nome_do_anime` — sonda precisa,
    não prefixo curto da escada de recall) trouxe card(s), esses card(s)
    voltam num `ResultadoDeFonte(correspondencia_incerta=True)`, deduplicados
    por `identificador` e truncados a `_MAXIMO_INCERTOS`. Cobre o site que
    indexa o anime só sob um título que o provedor de metadados não conhece
    (ex. só em PT-BR). A variante vencedora devolvida é `None` nesse caso — não
    houve uma única variante "certa", e o chamador não deve montar banner de
    troca de termo (`api/servicos/busca.py`).

    `FalhaDeExtracao` de qualquer variante aborta as restantes — mesmo
    critério de "indisponível" usado por `_separar_por_cooldown` (nunca
    silencioso, CLAUDE.md §4): uma falha de extração não é "não achei nada",
    é "não consegui nem tentar"."""
    extrator = obter_extrator(dominio)
    descartados = 0
    incertos: list[ResultadoBusca] = []
    indice = -1
    async for variante, resposta in buscar_variantes_em_janelas(sessionmaker, extrator, variantes):
        indice += 1
        if isinstance(resposta, FalhaDeExtracao):
            excecao = resposta
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
        if isinstance(resposta, BaseException):
            raise resposta
        candidatos = resposta
        validos = [
            c for c in candidatos if corresponde_a_alguma_referencia(referencias, c.titulo_exibicao)
        ]
        validos.sort(key=lambda c: proximidade_a_referencias(referencias, c.titulo_exibicao))
        if validos:
            variante_vencedora = variante if indice > 0 else None
            return (
                ResultadoDeFonte(
                    dominio=dominio, candidatos=validos, indisponivel=False, motivo=None
                ),
                variante_vencedora,
            )
        # Nenhum card desta variante bateu as referências: todos são órfãos.
        # Só viram "incertos" quando a variante de origem é uma sonda precisa (o
        # termo buscado É um nome canônico do anime) — prefixo curto da escada de
        # recall, origem real do lixo, nunca entra.
        descartados += len(candidatos)
        if candidatos and e_nome_do_anime(variante, referencias):
            incertos.extend(candidatos)

    if incertos:
        incertos = _deduplicar_candidatos(incertos)[:_MAXIMO_INCERTOS]
        logger.info(
            "extrator %r devolveu %d correspondência(s) incerta(s): termo buscado é um"
            " nome canônico do anime, mas nenhum card bateu as referências %r",
            dominio,
            len(incertos),
            referencias,
        )
        return (
            ResultadoDeFonte(
                dominio=dominio,
                candidatos=incertos,
                indisponivel=False,
                motivo=(
                    f"{len(incertos)} correspondência(s) incerta(s): busca por nome"
                    " canônico do anime, nenhum card batendo as referências"
                ),
                correspondencia_incerta=True,
            ),
            None,
        )

    motivo = None
    if descartados > 0:
        motivo = f"{descartados} candidato(s) descartado(s) por não corresponder ao título"
        logger.info(
            "extrator %r descartou %d candidato(s) por não corresponder às referências %r",
            dominio,
            descartados,
            referencias,
        )
    return (
        ResultadoDeFonte(dominio=dominio, candidatos=[], indisponivel=False, motivo=motivo),
        None,
    )


def _deduplicar_candidatos(candidatos: list[ResultadoBusca]) -> list[ResultadoBusca]:
    """Remove `ResultadoBusca` repetidos por `identificador` (o id do anime
    naquele site), preservando a primeira ocorrência e a ordem. Usado só no
    caminho de "correspondência incerta" de `buscar_em_com_variantes`, onde os
    candidatos são acumulados de VÁRIAS variantes de sonda precisa (romaji e
    inglês, por exemplo) e o mesmo card pode voltar em mais de uma."""
    vistos: set[str] = set()
    unicos: list[ResultadoBusca] = []
    for candidato in candidatos:
        if candidato.identificador in vistos:
            continue
        vistos.add(candidato.identificador)
        unicos.append(candidato)
    return unicos


async def buscar_por_site_com_variantes(
    sessionmaker: _SessionMaker,
    variantes: list[str],
    *,
    referencias: list[str],
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
    `referencias` via
    `extractors/busca/correspondencia.py::corresponde_a_alguma_referencia`,
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
                sessionmaker, extrator.dominio, variantes, referencias=referencias
            )
            for extrator in disponiveis
        ),
        return_exceptions=True,
    )
    for extrator, resposta in zip(disponiveis, respostas, strict=True):
        if isinstance(resposta, BaseException):
            logger.warning(
                "extrator %r falhou na busca por variantes (referências %r): %s",
                extrator.dominio,
                referencias,
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

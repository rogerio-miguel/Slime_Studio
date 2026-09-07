"""Orquestração de `GET /api/animes/buscar-fontes` que cruza `extractors/` ×
`integrations/` — único ponto que importa os dois lados da fronteira pra este
fluxo, mesma decisão de `api/servicos/descoberta.py`/`fontes.py` (CLAUDE.md
§1: `extractors/` NUNCA importa de `integrations/`, e vice-versa; orquestração
cross-camada mora aqui).

Duas funções públicas, dois contratos de saída, e — desde as reescritas de
2026-09-06/09-07 — dois pipelines parecidos mas não idênticos:

- `buscar_com_titulos_alternativos` (escopo `padrao`): resolve o anime
  canônico no provedor de metadados (AniList) UPFRONT, monta a escada de
  termos combinada dos vários idiomas (`_termos_de_busca`) e a lista de
  referências de validação (`_referencias_de_anime`), consulta o site padrão
  (`extractors.registro.EXTRATORES[0]`) com essa escada e — só se ele não
  cravar um acerto de chave exata — faz fan-out paralelo nos sites restantes,
  elegendo UMA fonte vencedora por proximidade à referência, com desempate
  determinístico pela ordem de `EXTRATORES`. Devolve UMA fonte. Alimenta o
  banner de "termo/fonte alternativa" da Home.
- `buscar_em_todas_as_fontes_com_titulos_alternativos` (escopo `todas`):
  resolve o canônico no provedor UPFRONT (como o `padrao`), monta a mesma
  escada combinada `_termos_de_busca` e as `_referencias_de_anime`, e faz Fase
  1 PARALELA (cada site esgotando essa escada combinada de forma independente,
  validação multi-referência), seguida de Fase 2 por termo de provedor
  (romaji/inglês, best-effort) enquanto sobrar site pendente; devolve a UNIÃO
  das fontes onde o anime realmente existe. Serve o diálogo "Trocar fonte".

Por que o `padrao` mudou (a orquestração antiga era 2 fases ordenadas por
custo — regex de graça primeiro, rede de provedor só como último recurso, se
a Fase 1 tivesse dado ZERO em todo site): (1) o provedor entrava tarde
demais, então um card em romaji só era alcançado depois da busca pelo título
digitado (PT) ter falhado em todo lugar; (2) "primeiro site com QUALQUER
candidato ganha" deixava um site de busca permissiva vencer com lixo antes de
o site padrão sequer ser avaliado; (3) a validação era contra o título
digitado, que podia estar num idioma que nenhum site indexa, descartando o
card romaji certo. Agora o provedor é o resolvedor canônico e roda primeiro;
a validação é multi-referência
(`extractors/busca/correspondencia.py::corresponde_a_alguma_referencia` sobre
todos os nomes do anime); o desempate é por `proximidade_a_referencias` +
ordem de `EXTRATORES`.

O escopo `todas` também resolve o canônico UPFRONT desde 2026-09-07 (a Fase 1
dele passou a varrer a escada combinada `_termos_de_busca`, não mais só as
variantes de regex do título digitado) — o contrato dele continua sendo a
UNIÃO das fontes, então cada site esgota a própria escada de forma
independente e a Fase 2 por termo de provedor continua valendo enquanto
sobrar site PENDENTE (não `indisponivel` e sem candidato). Bug real que o
gate por-site resolve (2026-08-29): com gate global, "Dogul Wang" achado no
site padrão pela escada de regex impedia o segundo site de ser consultado com
o título inglês do provedor ("Tomb Raider King"), onde o anime existe — o
diálogo "Trocar fonte" listava uma fonte só. (A escada combinada da Fase 1
agora cobre esse caso já na Fase 1; a Fase 2 do `todas` virou redundante e
está rastreada para remoção — ver
`_expandir_com_termos_de_provedor_em_todas_as_fontes`.)

Infra compartilhada pelos dois escopos:

- `variantes_de_busca` de `extractors.busca.termos` — gerador de variantes de
  regex, o mesmo em todo lugar;
- `_referencias_de_anime` (todos os nomes do anime para `referencias=` da
  validação de card) e `_termos_de_busca` (escada combinada dos idiomas) —
  os DOIS escopos montam a Fase 1 com esses dois helpers desde 2026-09-07; a
  Fase 2 do `todas` ainda tem sua própria expansão termo a termo via
  `_termos_alternativos`, hoje redundante;
- `_completar_nao_consultados` — todo `EXTRATORES` aparece na saída, mesmo o
  site que não chegou a ser consultado (senão a UI que checa "todas as fontes
  indisponíveis" mentiria);
- tetos: `_TETO_METADADOS_S` (só o round-trip de `buscar_titulos`) e
  `_TETO_EXPANSAO_S` (o trabalho de rede best-effort DEPOIS da primeira rodada
  de scraping) — ver o comentário-bloco de `_TETO_EXPANSAO_S` para o perfil de
  pior caso, que agora DIFERE entre os escopos;
- caráter best-effort do trabalho de provedor/fan-out: falha, timeout ou
  qualquer outro erro nunca propaga pra fora nem derruba a rodada de scraping
  já obtida.

Por que NÃO são uma função só: a diferença de contrato de saída (fonte única
com desempate vs. união de fontes) é o motivo — registrado aqui pra evitar
que a próxima passada (humana ou agente) tente fundir os dois caminhos.

Capa de anime não é responsabilidade deste módulo nem de `extractors/`
(Fatia 3 de `PLANO_ARTE_TMDB.md` — `extractors/` volta a ser só extração de
VÍDEO, `ResultadoBusca` não tem mais campo `capa_url`): o enriquecimento mora
inteiro em `api/servicos/capas.py::capas_por_titulo`, aplicado pela rota
(`api/rotas/animes.py`) DEPOIS da busca em fontes.
"""

import asyncio
import logging
from dataclasses import dataclass, replace

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.texto import slugificar
from extractors.base import ResultadoBusca
from extractors.busca import servico as servico_extractors
from extractors.busca.correspondencia import (
    corresponde_a_alguma_referencia,
    proximidade_a_referencias,
)
from extractors.busca.servico import ResultadoDeFonte
from extractors.busca.termos import variantes_de_busca
from extractors.registro import EXTRATORES
from integrations import servico as servico_metadados
from integrations.base import TitulosDeAnime

logger = logging.getLogger(__name__)

_SessionMaker = async_sessionmaker[AsyncSession]

# Teto do trabalho de rede best-effort que cada escopo faz DEPOIS da primeira
# rodada de scraping — `wait_for` externo que, ao estourar, devolve o que já
# se tem em vez de travar a resposta. O perfil de pior caso DIFERE entre os
# escopos desde a reescrita do `padrao`:
#
# `todas` — perfil "Fase 2, escada por termo de provedor": desde 2026-09-07 a
# Fase 1 do `todas` também resolve o canônico UPFRONT (round-trip de
# `buscar_titulos` sob `_TETO_METADADOS_S` próprio, FORA deste orçamento) e
# varre a escada COMBINADA `_termos_de_busca` — mas a Fase 1 NÃO está sob este
# teto. O que fica sob ele é só a Fase 2
# (`_expandir_com_termos_de_provedor_em_todas_as_fontes`): até 2 termos de
# provedor (romaji, inglês), cada um gerando a PRÓPRIA escada de variantes
# (`extractors/busca/termos.py::variantes_de_busca` — bloco de precisão com
# até 3 termos mais bloco de recall com até `_MAXIMO_PREFIXOS`=3 prefixos
# crescentes, 6 variantes no pior caso), tentados termo a termo em SEQUÊNCIA
# (sites em PARALELO dentro de cada termo via `buscar_por_site_com_variantes`,
# então os sites não multiplicam nada). Cada variante custa até o timeout do
# GET síncrono dos adapters (`_TIMEOUT_S` de `extractors/animefire.py` etc.,
# 15s). Conta: até 2 × (6 × 15s) = 180s, dentro dos 190 (a Fase 2 do `todas`
# hoje é redundante — a escada combinada da Fase 1 já a domina, ela nem chega
# a tocar a rede, ver `_expandir_com_termos_de_provedor_em_todas_as_fontes` —
# mas o teto fica em 190 porque o perfil do `padrao` abaixo precisa dele).
#
# `padrao` — perfil "uma escada combinada, um fan-out": o round-trip de
# `buscar_titulos` NÃO entra mais neste orçamento (roda UPFRONT, sob
# `_TETO_METADADOS_S` próprio). O que sobra sob este teto é UM fan-out
# (`buscar_por_site_com_variantes` nos sites depois do padrão) da escada
# combinada `_termos_de_busca` — a concatenação, deduplicada por slug, das
# escadas de romaji + inglês + título digitado. No pior caso teórico são
# 3 × 6 = 18 variantes, mas as três escadas se sobrepõem forte no caso comum
# (o título digitado costuma ser o romaji ou um prefixo dele). Sem a
# multiplicação sequencial por termo que o `todas` tem, o `padrao` é mais
# barato: 190s cobrem ~12 variantes sequenciais no site mais lento, folga
# suficiente para a escada combinada realista; o que passar disso é cancelado
# e a rodada do site padrão (que já esgotou a escada inteira, passo 3) é
# devolvida.
#
# A variância de captura de navegador de um site com challenge (até 90s) é um
# risco estrutural separado, rastreado na Fase E do plano — fora do escopo
# desta conta.
_TETO_EXPANSAO_S = 190

# Sub-teto só de `buscar_titulos`, consumido igual pelos DOIS escopos:
# `_resolver_titulos_canonicos` roda como `wait_for` separado, UPFRONT, porque a
# escada de termos da Fase 1 (`_termos_de_busca`) já depende do título canônico
# nos dois caminhos. Sem este teto, uma AniList pendurada seguraria a busca nos
# sites de extração antes de a primeira rodada de scraping sequer começar.
#
# `buscar_titulos` percorre só `PROVEDORES_DE_TITULO` (AniList — ver
# `integrations/registro.py`), então o pior caso é UM provedor lento, não dois:
# o `_chamar` interno de `integrations/servico.py` já estoura em
# `_TIMEOUT_POR_PROVEDOR_S` (8s) e a cadeia degrada para `FalhaDeMetadados` ->
# `None`. Este teto externo fica logo acima disso (9s, era 10s quando a cadeia
# ainda caía para o Kitsu aqui) só para garantir que o timeout interno por
# provedor dispare primeiro — o mesmo racional do próprio
# `_TIMEOUT_POR_PROVEDOR_S` ser > o timeout de `requests` de cada adapter.
_TETO_METADADOS_S = 9


@dataclass(frozen=True, slots=True)
class BuscaEmFontes:
    """Resultado da busca em fontes + de qual termo/domínio ele veio.
    `termo_alternativo is None` significa "veio do termo digitado".
    `dominio_alternativo` é `None` quando quem respondeu foi
    `EXTRATORES[0].dominio` (o site padrão, ex. AnimeFire) OU quando nenhum
    site respondeu; é o domínio real quando a resposta veio de um site
    diferente do padrão (ex. teve que cair pro AnimesDrive)."""

    fontes: list[ResultadoDeFonte]
    termo_alternativo: str | None
    dominio_alternativo: str | None


# --- Escopo `padrao`: canônico UPFRONT + site padrão + fan-out nos restantes ---
async def buscar_com_titulos_alternativos(
    sessionmaker: _SessionMaker, titulo: str
) -> BuscaEmFontes:
    """Busca que reporta UMA fonte, com o provedor de metadados (AniList) como
    resolvedor canônico rodando PRIMEIRO — não mais como último recurso da
    orquestração antiga em 2 fases (ver docstring de módulo para o histórico
    do porquê da mudança).

    1. Resolve o anime canônico no provedor (`_resolver_titulos_canonicos`,
       best-effort sob `_TETO_METADADOS_S`) — `None` degrada a busca para só o
       título digitado como referência, não a derruba.
    2. Monta `referencias` (`_referencias_de_anime` — todos os nomes do anime,
       o card do site pode estar grafado em qualquer um) e `termos`
       (`_termos_de_busca` — escada combinada de romaji + inglês + digitado).
    3. Consulta SÓ o site padrão (`EXTRATORES[0]`) com a escada combinada.
    4. Se o melhor candidato dele bate uma chave EXATA de referência
       (`_e_exato`), o site padrão venceu — os demais sites nem são tocados
       (contrato histórico: site padrão acertou → segundo site nunca é
       consultado).
    5. Senão, fan-out paralelo nos sites restantes
       (`_consultar_sites_restantes`, best-effort sob `_TETO_EXPANSAO_S`) com
       a mesma escada.
    6. Elege UMA fonte vencedora (`_escolher_vencedor_unico`): menor
       `proximidade_a_referencias` no melhor candidato, desempate pela ordem
       de `EXTRATORES`. Candidatos dos sites perdedores são suprimidos
       (`candidatos=[]`) — o contrato deste escopo é fonte única; falha real
       (`indisponivel`) de um perdedor CONTINUA reportada.
    7. `dominio_alternativo` = o vencedor quando não é o site padrão;
       `termo_alternativo` = o título canônico (romaji/inglês) contra o qual o
       card do vencedor mais se aproxima, quando difere do digitado
       (`_termo_alternativo_do_vencedor`).

    Limitação conhecida (mesma já documentada em
    `api/servicos/capas.py::_consultar_capas`): o `wait_for` do fan-out cancela
    a *task* asyncio, não a thread do SO já em voo dentro do `to_thread` de
    `extractors/resiliencia.py` — na pior das hipóteses ela roda até terminar
    sozinha, e a rodada cancelada não registra sucesso/falha no circuit
    breaker.
    """
    titulos = await _resolver_titulos_canonicos(titulo)
    referencias = _referencias_de_anime(titulos, titulo)
    termos = _termos_de_busca(titulos, titulo)

    site_padrao = EXTRATORES[0].dominio
    r1, _variante = await servico_extractors.buscar_em_com_variantes(
        sessionmaker, site_padrao, termos, referencias=referencias
    )

    resultados: dict[str, ResultadoDeFonte]
    vencedor_dominio: str | None
    if r1.candidatos and _e_exato(referencias, r1.candidatos[0]):
        resultados = {site_padrao: r1}
        vencedor_dominio = site_padrao
    else:
        resto = await _consultar_sites_restantes(sessionmaker, termos, referencias, titulo)
        resultados = {site_padrao: r1, **resto}
        vencedor_dominio = _escolher_vencedor_unico(resultados, referencias)
        for dominio, resultado in list(resultados.items()):
            if dominio != vencedor_dominio and resultado.candidatos:
                resultados[dominio] = replace(resultado, candidatos=[])

    fontes = _completar_nao_consultados(resultados, vencedor_dominio)
    dominio_alternativo = (
        vencedor_dominio if vencedor_dominio not in (None, site_padrao) else None
    )
    candidato_vencedor = (
        resultados[vencedor_dominio].candidatos[0] if vencedor_dominio is not None else None
    )
    termo_alternativo = _termo_alternativo_do_vencedor(titulos, titulo, candidato_vencedor)
    return BuscaEmFontes(
        fontes=fontes,
        termo_alternativo=termo_alternativo,
        dominio_alternativo=dominio_alternativo,
    )


async def _resolver_titulos_canonicos(titulo: str) -> TitulosDeAnime | None:
    """Resolve o anime canônico para `titulo` só na AniList
    (`integrations.servico.buscar_titulos` percorre apenas `PROVEDORES_DE_TITULO`
    — Kitsu não entra aqui, ver o comentário da tupla em `integrations/registro.py`)
    — a base de `_referencias_de_anime` e `_termos_de_busca`.

    Best-effort: qualquer falha (rede, timeout de `_TETO_METADADOS_S`, AniList
    fora do ar, formato inesperado) degrada para `None` e a busca segue só com
    o título digitado como referência. Captura ampla e intencional (CLAUDE.md §4
    — degrada explícito com `logger.warning`, não silencioso): resolver o
    canônico é enriquecimento, não pré-condição; o provedor fora do ar não pode
    derrubar a busca nos sites de extração."""
    try:
        return await asyncio.wait_for(
            servico_metadados.buscar_titulos(titulo), timeout=_TETO_METADADOS_S
        )
    except Exception as excecao:
        logger.warning(
            "resolução de título canônico best-effort falhou para título %r: %s",
            titulo,
            excecao,
        )
        return None


async def _consultar_sites_restantes(
    sessionmaker: _SessionMaker,
    termos: list[str],
    referencias: list[str],
    titulo: str,
) -> dict[str, ResultadoDeFonte]:
    """Fan-out paralelo nos sites depois do padrão (`EXTRATORES[1:]`), cada um
    esgotando a escada combinada `termos` — só roda quando o site padrão não
    cravou um acerto de chave exata. Sites em cooldown são resolvidos como
    `indisponivel` por dentro de `buscar_por_site_com_variantes`
    (`_separar_por_cooldown`), não filtrados aqui.

    Best-effort sob `_TETO_EXPANSAO_S`: timeout ou falha do lote degrada para
    `{}` — o chamador segue com o resultado do site padrão, e
    `_completar_nao_consultados` preenche os sites sem resposta. Captura ampla
    e intencional, mesmo motivo de `_resolver_titulos_canonicos`."""
    try:
        return await asyncio.wait_for(
            servico_extractors.buscar_por_site_com_variantes(
                sessionmaker,
                termos,
                referencias=referencias,
                dominios=[extrator.dominio for extrator in EXTRATORES[1:]],
            ),
            timeout=_TETO_EXPANSAO_S,
        )
    except Exception as excecao:
        logger.warning(
            "fan-out best-effort nos sites restantes falhou para título %r: %s",
            titulo,
            excecao,
        )
        return {}


def _e_exato(referencias: list[str], candidato: ResultadoBusca) -> bool:
    """`True` quando `candidato` bate a chave normalizada de ALGUMA referência
    (não só compartilha prefixo) — o primeiro elemento da tupla de
    `proximidade_a_referencias` é 0. Um acerto de chave exata no site padrão
    dispensa consultar os demais."""
    return proximidade_a_referencias(referencias, candidato.titulo_exibicao)[0] == 0


def _escolher_vencedor_unico(
    resultados: dict[str, ResultadoDeFonte], referencias: list[str]
) -> str | None:
    """O site cujo melhor candidato (`candidatos[0]`, já ordenado por
    `proximidade_a_referencias` dentro de `buscar_em_com_variantes`) fica mais
    perto das `referencias` — o contrato do escopo `padrao` é UMA fonte só.
    Empate no melhor score é desfeito pela ordem de prioridade de `EXTRATORES`
    (o mesmo critério determinístico da busca sequencial anterior, agora sobre
    o resultado pronto do fan-out em vez de "quem respondeu primeiro"). `None`
    quando nenhum site devolveu candidato.

    Toda chave de `resultados` é um domínio de `EXTRATORES` (montado assim pelo
    chamador), então o `next` sempre encontra o vencedor."""
    scores = {
        dominio: proximidade_a_referencias(referencias, resultado.candidatos[0].titulo_exibicao)
        for dominio, resultado in resultados.items()
        if resultado.candidatos
    }
    if not scores:
        return None
    melhor = min(scores.values())
    return next(
        extrator.dominio for extrator in EXTRATORES if scores.get(extrator.dominio) == melhor
    )


def _termo_alternativo_do_vencedor(
    titulos: TitulosDeAnime | None, titulo: str, candidato_vencedor: ResultadoBusca | None
) -> str | None:
    """O título canônico do provedor (romaji ou inglês) contra o qual o melhor
    candidato do site vencedor mais se aproxima — o que a Home mostra no banner
    "resultado veio de outro termo". Romaji e inglês são comparados por
    `proximidade_a_referencias` isoladamente; vence o de menor tupla (empate
    fica com o romaji, comparado primeiro).

    `None` quando não houve vencedor, quando o provedor não resolveu `titulos`,
    quando o melhor termo canônico slugifica igual ao título digitado, ou —
    guard principal — quando o próprio título digitado JÁ corresponde ao card
    vencedor (`corresponde_a_alguma_referencia`): aí houve resultado pro que o
    usuário digitou e o banner da Home ("Nenhum resultado para X, mostrando
    resultados para Y") seria falso. Só é "termo alternativo" de verdade quando
    o digitado não alcançaria esse card sozinho (ex.: usuário digitou em PT, o
    site indexa só o romaji). Semântica de `termo_alternativo is None` = "veio
    do termo digitado"."""
    if titulos is None or candidato_vencedor is None:
        return None
    if corresponde_a_alguma_referencia([titulo], candidato_vencedor.titulo_exibicao):
        return None
    canonicos = [
        canonico
        for canonico in (titulos.titulo_romaji, titulos.titulo_ingles)
        if canonico and slugificar(canonico)
    ]
    if not canonicos:
        return None
    melhor = min(
        canonicos,
        key=lambda canonico: proximidade_a_referencias(
            [canonico], candidato_vencedor.titulo_exibicao
        ),
    )
    return melhor if slugificar(melhor) != slugificar(titulo) else None


# --- Escopo `todas`: canônico UPFRONT + Fase 1 combinada paralela + Fase 2 ---
# Fase 2 (expansão por termo de provedor, best-effort) mora em
# `_expandir_com_termos_de_provedor_em_todas_as_fontes` — hoje redundante (a
# escada combinada da Fase 1 já a domina), mantida até uma fatia de remoção
# própria. O escopo `padrao` (`buscar_com_titulos_alternativos`) resolve o
# mesmo canônico upfront mas faz um fan-out só, com desempate de fonte única;
# ver docstring de módulo.
async def buscar_em_todas_as_fontes_com_titulos_alternativos(
    sessionmaker: _SessionMaker, titulo: str
) -> BuscaEmFontes:
    """`escopo=todas` (D-B1/D-B2, Fase B do PLANO_PADRONIZACAO_FONTES.md):
    devolve a UNIÃO de todas as fontes que realmente têm o anime — busca
    paralela em todos os sites, cada um esgotando sua própria escada de
    variantes de forma independente e exaustiva
    (`extractors.busca.servico.buscar_por_site_com_variantes`, INV-1'): nenhum
    site interrompe ou "rouba a vez" da busca dos outros. A validação de card
    (`extractors/busca/correspondencia.py::corresponde_a_alguma_referencia`
    sobre todos os nomes do anime) vem embutida em `buscar_em_com_variantes`.
    Serve o diálogo "Trocar fonte", que mostra as alternativas lado a lado
    (D-B2).

    Desde 2026-09-07 espelha a resolução canônica do escopo `padrao` — não é
    mais "regex de graça primeiro, provedor só como expansão":

    1. `_resolver_titulos_canonicos` (best-effort sob `_TETO_METADADOS_S`) —
       `None` degrada para só o título digitado como referência/termo, não
       derruba a busca.
    2. `referencias` (`_referencias_de_anime` — todos os nomes do anime) e
       `termos` (`_termos_de_busca` — escada combinada de romaji + inglês +
       digitado, deduplicada por slug).
    3. Fase 1: `buscar_por_site_com_variantes` com a escada combinada em TODOS
       os sites em paralelo, cada um esgotando a escada.
    4. Fase 2 (`_expandir_com_termos_de_provedor_em_todas_as_fontes`,
       best-effort sob `_TETO_EXPANSAO_S`): enquanto sobrar site PENDENTE (não
       `indisponivel` e sem candidato), reexpande só os pendentes com cada
       título canônico isolado. REDUNDANTE desde que a Fase 1 passou a varrer
       a escada combinada (a Fase 2 nunca alcança uma variante que a Fase 1
       não tentou) — mantida por segurança, rastreada para remoção; ver a
       docstring dela.

    O gate da Fase 2 é POR-SITE, não global — bug real 2026-08-29 ("Dogul
    Wang"): com gate global, um site achar pela escada de regex pulava a Fase
    2 inteira e o segundo site nunca era consultado com o título inglês do
    provedor ("Tomb Raider King"), onde o anime existe — o diálogo listava uma
    fonte só. A escada combinada da Fase 1 hoje cobre esse caso já na Fase 1.

    `termo_alternativo`/`dominio_alternativo` sempre `None` aqui — o resultado
    é por definição a união de vários sites, cada um com seu próprio termo
    vencedor; não faz sentido expor um só. O diálogo "Trocar fonte" mostra
    `dominio`/`versao` por candidato (D-B3/D-B4), não depende de um banner de
    "termo alternativo" como a Home no escopo `padrao`.
    """
    titulos = await _resolver_titulos_canonicos(titulo)
    referencias = _referencias_de_anime(titulos, titulo)
    termos = _termos_de_busca(titulos, titulo)

    resultado_por_dominio = await servico_extractors.buscar_por_site_com_variantes(
        sessionmaker, termos, referencias=referencias
    )
    resultado = _completar_nao_consultados(resultado_por_dominio, None)

    # Mesmo critério do `pendentes` de `_expandir_com_termos_de_provedor_em_
    # todas_as_fontes`: site sem candidato e ainda disponível é trabalho em
    # aberto pro contrato de UNIÃO, mesmo com outro site já tendo achado. Gate
    # mais frouxo que esse filtro desperdiça rede; mais estrito pula a Fase 2 e
    # o site pendente nunca é consultado (bug real, ver docstring de módulo).
    algum_site_pendente = any(
        not fonte.indisponivel and not fonte.candidatos for fonte in resultado
    )
    if algum_site_pendente:
        slugs_fase1 = {slugificar(v) for v in termos}
        try:
            expandido = await asyncio.wait_for(
                _expandir_com_termos_de_provedor_em_todas_as_fontes(
                    sessionmaker, titulo, titulos, resultado, slugs_fase1
                ),
                timeout=_TETO_EXPANSAO_S,
            )
        except Exception as excecao:
            # Captura ampla e intencional, mesmo motivo de
            # `buscar_com_titulos_alternativos`: a expansão da Fase 2 é
            # best-effort — timeout do lote de scraping ou qualquer outro erro
            # não pode derrubar a busca da Fase 1 (o metadado já foi resolvido
            # upfront, fora daqui).
            logger.warning(
                "expansão por termo de provedor best-effort falhou para título %r"
                " (escopo=todas): %s",
                titulo,
                excecao,
            )
            expandido = None
        if expandido is not None:
            resultado = expandido

    return BuscaEmFontes(fontes=resultado, termo_alternativo=None, dominio_alternativo=None)


async def _expandir_com_termos_de_provedor_em_todas_as_fontes(
    sessionmaker: _SessionMaker,
    titulo: str,
    titulos: TitulosDeAnime | None,
    resultado_fase1: list[ResultadoDeFonte],
    slugs_fase1: set[str],
) -> list[ResultadoDeFonte] | None:
    """Fase 2 do escopo `todas` (best-effort): reexpande os sites ainda
    PENDENTES com cada título canônico do provedor isoladamente. Contrato de
    saída: a UNIÃO das fontes.

    Recebe `titulos` JÁ resolvido pelo chamador (`_resolver_titulos_canonicos`,
    upfront, uma vez só — compartilhado com a montagem da Fase 1); NÃO refaz o
    round-trip de metadados. `titulos is None` → `None` (o chamador mantém a
    Fase 1).

    `_termos_alternativos` uma vez (romaji, depois inglês, descartando o que
    repete o digitado); por termo: `pendentes` recalculado (não `indisponivel`
    e sem candidato de termo anterior), escada própria (`variantes_de_busca`)
    filtrada pelo dedupe de `slugs_fase1`, fan-out `buscar_por_site_com_
    variantes` só nos `pendentes` (`dominios=`, evita reconsultar quem já
    respondeu), referência isolada `[termo]`. Só passa pro próximo termo se
    ainda sobrar pendente.

    REDUNDANTE na prática: `slugs_fase1 = {slugificar(v) for v in termos}` e
    `termos` (`_termos_de_busca`) já concatena as escadas de romaji e inglês —
    então `_variantes_sem_repetir_fase1` esvazia a escada de todo termo aqui e
    esta função retorna `None` sem tocar a rede. Mantida intacta na fatia d3
    (Fase 1 combinada + dedupe correto); a remoção — desta função, de
    `_termos_alternativos` e do gate — é uma fatia própria do orquestrador.

    `None` quando o provedor não resolveu `titulos`, quando `_termos_
    alternativos` degrada para vazio (romaji/inglês repetem o digitado ou
    slugificam para vazio), ou quando nenhum termo achou candidato novo — o
    chamador mantém o resultado (intacto) da Fase 1."""
    if titulos is None:
        return None
    termos = _termos_alternativos(titulos, titulo)
    if not termos:
        return None

    por_dominio = {fonte.dominio: fonte for fonte in resultado_fase1}
    algum_termo_achou = False

    for termo in termos:
        pendentes = [
            dominio
            for dominio, fonte in por_dominio.items()
            if not fonte.indisponivel and not fonte.candidatos
        ]
        if not pendentes:
            break  # todo site já achou candidato ou ficou indisponível
        variantes_termo = _variantes_sem_repetir_fase1(variantes_de_busca(termo), slugs_fase1)
        if not variantes_termo:
            continue  # a escada combinada da Fase 1 já varreu toda a escada deste termo
        resposta_por_dominio = await servico_extractors.buscar_por_site_com_variantes(
            sessionmaker, variantes_termo, referencias=[termo], dominios=pendentes
        )
        por_dominio.update(resposta_por_dominio)
        if any(fonte.candidatos for fonte in resposta_por_dominio.values()):
            algum_termo_achou = True

    if not algum_termo_achou:
        return None
    return _completar_nao_consultados(por_dominio, None)


# --- Compartilhado pelos dois escopos ---


def _completar_nao_consultados(
    resultados: dict[str, ResultadoDeFonte], dominio_respondeu: str | None
) -> list[ResultadoDeFonte]:
    """`resultados` pode não ter entrada pra todo `EXTRATORES` — o `padrao`
    para de consultar assim que o site padrão crava um acerto de chave exata
    (early-exit), e um fan-out best-effort cancelado por timeout também pode
    não ter resposta pra todo site. O contrato de saída da API precisa listar
    todos os domínios mesmo assim (senão a UI que checa "todas as fontes
    indisponíveis" mentiria) — o não consultado sai como
    `indisponivel=False, candidatos=[], motivo="não consultado (<dominio> respondeu)"`
    (ou só "não consultado" quando não houve vencedor a nomear)."""
    finais = []
    for extrator in EXTRATORES:
        if extrator.dominio in resultados:
            finais.append(resultados[extrator.dominio])
        else:
            motivo = (
                f"não consultado ({dominio_respondeu} respondeu)"
                if dominio_respondeu is not None
                else "não consultado"
            )
            finais.append(
                ResultadoDeFonte(
                    dominio=extrator.dominio,
                    candidatos=[],
                    indisponivel=False,
                    motivo=motivo,
                )
            )
    return finais


def _termos_alternativos(titulos: TitulosDeAnime, titulo_original: str) -> list[str]:
    """Ordem: romaji, depois inglês. Descarta por chave `core/texto.py::slugificar`
    o que repete o termo digitado e o que slugifica pra vazio (kanji)."""
    slug_original = slugificar(titulo_original)
    candidatos = [titulos.titulo_romaji, titulos.titulo_ingles]

    termos: list[str] = []
    slugs_vistos: set[str] = {slug_original}
    for candidato in candidatos:
        if candidato is None:
            continue
        slug = slugificar(candidato)
        if not slug or slug in slugs_vistos:
            continue
        slugs_vistos.add(slug)
        termos.append(candidato)
    return termos


def _referencias_de_anime(titulos: TitulosDeAnime | None, titulo: str) -> list[str]:
    """Todos os nomes conhecidos do anime, para passar como `referencias=` à
    validação de card
    (`extractors/busca/correspondencia.py::corresponde_a_alguma_referencia`): o
    card devolvido pelo site pode estar grafado em qualquer um dos nomes do
    anime (romaji, inglês, nativo, sinônimo de provedor) e basta bater com um —
    validar só contra o título digitado rejeitaria o card certo quando o site
    indexa outro idioma.

    Ordem: `titulo` (o digitado) primeiro — é a âncora, o único nome que
    sabemos ser o que o usuário quis; depois `titulo_romaji`, `titulo_ingles`,
    `titulo_nativo` e cada `sinonimo` na ordem que o provedor devolveu.

    `titulo` fica na lista mesmo que slugifique pra vazio (título só em kanji —
    improvável no campo digitado, mas `corresponde_a_alguma_referencia` já
    degrada pra aceitar quando a referência não tem chave de comparação, então
    mantê-lo é inócuo e preserva a âncora). Todo OUTRO candidato cujo slug
    (`core/texto.py::slugificar`) seja vazio é descartado: `titulo_nativo` em
    kanji vira chave vazia e `corresponde_a_alguma_referencia` compara por
    contenção de chave normalizada — chave vazia não valida nem rejeita nada,
    só entra como ruído. Duplicata por chave `slugificar` também sai (o título
    digitado em caixa baixa e o romaji do provedor em Title Case colapsam numa
    referência só), assim como `None` e string em branco. A tolerância mais
    forte — espaço vs. grafia colada, "Dogul Wang" vs "DogulWang" — é de
    `corresponde_a_alguma_referencia` (que remove o hífen do slug), não deste
    filtro: manter as duas grafias na lista aqui é redundância inócua, não bug.

    `titulos is None` (o provedor não achou o anime) → só `[titulo]`.
    """
    if titulos is None:
        return [titulo]

    referencias = [titulo]
    slugs_vistos: set[str] = {slugificar(titulo)}
    candidatos = (
        titulos.titulo_romaji,
        titulos.titulo_ingles,
        titulos.titulo_nativo,
        *titulos.sinonimos,
    )
    for candidato in candidatos:
        if candidato is None:
            continue
        slug = slugificar(candidato)
        if not slug or slug in slugs_vistos:
            continue
        slugs_vistos.add(slug)
        referencias.append(candidato)
    return referencias


def _termos_de_busca(titulos: TitulosDeAnime | None, titulo: str) -> list[str]:
    """Escada de termos de busca combinada dos vários idiomas do anime, pra
    varrer os sites de extração — concatena a escada de `variantes_de_busca`
    (`extractors/busca/termos.py`, o mesmo gerador da Fase 1) de cada idioma.

    Ordem: `titulo_romaji`, `titulo_ingles`, `titulo` (o digitado) — romaji
    primeiro porque os sites de streaming indexam romaji com mais frequência
    que qualquer outra grafia. A ordem aqui é só a heurística de "qual termo
    tende a fazer o card certo aparecer primeiro"; a PRECISÃO não vem desta
    lista e sim da validação multi-referência
    (`corresponde_a_alguma_referencia` sobre `_referencias_de_anime`) e do
    desempate de `proximidade_a_referencias`, que rodam sobre os cards achados.

    `titulo_nativo` e `sinonimos` NÃO entram (ao contrário de
    `_referencias_de_anime`, onde entram): nativo em kanji slugifica pra vazio
    e não é termo de busca nenhum; sinônimo de provedor (abreviação, título
    regional) é ruidoso demais como termo — dispararia scraping à toa — e só
    presta como referência de validação depois que o card já apareceu.

    Dedup final por chave `core/texto.py::slugificar`, preservando a primeira
    ocorrência (a escada do romaji vence as repetições nas escadas seguintes).
    Nunca vazia — `titulo` sempre contribui pelo menos a si mesmo.

    `titulos is None` (o provedor não achou o anime) → `variantes_de_busca(titulo)`.
    """
    if titulos is None:
        return variantes_de_busca(titulo)

    escada: list[str] = []
    slugs_vistos: set[str] = set()
    for idioma in (titulos.titulo_romaji, titulos.titulo_ingles, titulo):
        if idioma is None:
            continue
        for variante in variantes_de_busca(idioma):
            slug = slugificar(variante)
            if slug in slugs_vistos:
                continue
            slugs_vistos.add(slug)
            escada.append(variante)
    return escada


def _variantes_sem_repetir_fase1(variantes: list[str], slugs_fase1: set[str]) -> list[str]:
    """Filtra a escada de variantes de um termo de provedor (`variantes_de_busca`),
    removendo qualquer entrada cujo slug (`core/texto.py::slugificar`) já foi
    tentado na Fase 1 (`variantes_puras` do título digitado) — dedupe entre
    fases: nunca reconsulta um site com exatamente o mesmo termo de busca que
    a Fase 1 já tentou e não achou."""
    return [variante for variante in variantes if slugificar(variante) not in slugs_fase1]

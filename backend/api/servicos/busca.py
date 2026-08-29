"""Orquestração de `GET /api/animes/buscar-fontes` que cruza `extractors/` ×
`integrations/` — único ponto que importa os dois lados da fronteira pra este
fluxo, mesma decisão de `api/servicos/descoberta.py`/`fontes.py` (CLAUDE.md
§1: `extractors/` NUNCA importa de `integrations/`, e vice-versa; orquestração
cross-camada mora aqui).

Duas funções públicas, o MESMO pipeline de duas fases em dois contratos de
saída diferentes (Fases A/B do PLANO_PADRONIZACAO_FONTES.md):

- `buscar_com_titulos_alternativos` (escopo `padrao`): Fase 1 SEQUENCIAL por
  site (ordem de `extractors.registro.EXTRATORES`), para no primeiro site que
  acha candidatos; devolve UMA fonte. Alimenta o banner de "termo/fonte
  alternativa" da Home.
- `buscar_em_todas_as_fontes_com_titulos_alternativos` (escopo `todas`): Fase
  1 PARALELA, cada site esgota a própria escada de variantes de forma
  independente e exaustiva; devolve a UNIÃO das fontes onde o anime realmente
  existe. Serve o diálogo "Trocar fonte".

Fase 1 = variantes puras de regex (`variantes_de_busca` de
`extractors.busca.termos`, de graça, sem I/O de provedor). Fase 2 = termos de
provedor romaji/inglês (via `integrations.servico.buscar_titulos`),
best-effort, quando a Fase 1 deixou trabalho em aberto (critério por escopo —
ver "O que DIFERE") — tolerância a idioma (usuário digitou em inglês, sites
indexam romaji, ou vice-versa).

O que é IDÊNTICO nos dois escopos:

- gerador de variantes: `variantes_de_busca` de `extractors.busca.termos`, o
  mesmo nas duas fases;
- ordem por custo: as variantes de regex (de graça) sempre antes da rede de
  provedor;
- guarda de expansão: nunca gastar o round-trip de `buscar_titulos` quando a
  Fase 2 não teria site nenhum pra consultar — o gate de cada escopo é
  exatamente o filtro de elegibilidade de site que o helper dele aplica
  (`disponiveis` no `padrao`, `pendentes` no `todas`); gate e filtro
  divergentes já causaram bug real, ver "O que DIFERE";
- termos de provedor: obtidos por `_termos_alternativos` (romaji, depois
  inglês; descarta o que repete o título digitado ou slugifica pra vazio);
- dedupe entre fases: `_variantes_sem_repetir_fase1` remove da escada de cada
  termo toda variante cujo slug a Fase 1 já tentou;
- referência de validação: `referencia=<termo>` própria por termo de provedor
  na Fase 2 (o invariante multilíngue — cada termo valida contra si mesmo,
  não contra o título digitado, que pode estar em outro idioma);
- tetos: `_TETO_EXPANSAO_S` (fase inteira da expansão) e `_TETO_METADADOS_S`
  (só o `buscar_titulos` dentro dela), os mesmos valores nos dois escopos
  porque o perfil de pior caso é o mesmo;
- caráter best-effort da Fase 2: falha, timeout (`_TETO_EXPANSAO_S`) ou
  qualquer outro erro da expansão nunca propaga pra fora nem derruba a busca
  da Fase 1 — devolve a rodada já obtida.

O que DIFERE entre os escopos:

- Fase 1: `padrao` é sequencial-com-break (para no primeiro site que acha);
  `todas` é fan-out paralelo (cada site esgota a própria escada);
- contrato de saída: `padrao` reporta uma fonte ÚNICA, com desempate
  determinístico por prioridade de `EXTRATORES` quando mais de um site acha
  no mesmo termo de provedor; `todas` reporta a UNIÃO das fontes;
- alvo de `dominios=` na Fase 2: `padrao` restringe aos sites ainda
  DISPONÍVEIS (não `indisponivel`); `todas` restringe aos PENDENTES (não
  `indisponivel` E ainda sem candidato de termo de provedor anterior);
- gatilho da Fase 2: `padrao` só expande se NENHUM site achou na Fase 1
  (early-exit — o contrato é UMA fonte que funciona; com vencedor em mãos,
  candidato de outro site seria descartado pelo desempate de qualquer forma);
  `todas` expande enquanto sobrar site PENDENTE (não `indisponivel` e sem
  candidato), mesmo com outro site já tendo achado — o contrato é a UNIÃO.
  Bug real (2026-08-29): com gate global, "Dogul Wang" achado no AnimeFire
  pela escada de regex impedia o AnimesDrive de ser consultado com o título
  inglês do provedor ("Tomb Raider King"), onde o anime existe — o diálogo
  "Trocar fonte" listava uma fonte só;
- `termo_alternativo`/`dominio_alternativo`: preenchidos no `padrao` (a Home
  precisa saber de qual termo/site veio o resultado), sempre `None` no
  `todas` (a união já expõe `dominio`/`versao` por candidato).

Por que NÃO são uma função só: a diferença de contrato de saída (fonte única
com desempate vs. união de fontes) é o motivo — registrado aqui pra evitar
que a próxima passada (humana ou agente) tente fundir os dois caminhos.

O enriquecimento de capa saiu deste módulo pra `api/servicos/capas.py` e é
aplicado pela rota (`api/rotas/animes.py`) DEPOIS da busca — o resultado que
sai daqui ainda NÃO tem `capa_url` preenchida pros candidatos que vieram sem.
"""

import asyncio
import logging
from dataclasses import dataclass, replace

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.texto import slugificar
from extractors.busca import servico as servico_extractors
from extractors.busca.servico import ResultadoDeFonte
from extractors.busca.termos import variantes_de_busca
from extractors.registro import EXTRATORES
from integrations import servico as servico_metadados
from integrations.base import TitulosDeAnime

logger = logging.getLogger(__name__)

_SessionMaker = async_sessionmaker[AsyncSession]

# Teto da fase inteira de expansão por termo de provedor (Fase 2, fatia 5 do
# plano): `buscar_titulos` (até `_TETO_METADADOS_S`, 10s) mais o pior caso de
# uma escada por termo — cada termo de provedor (romaji, inglês — até 2) gera
# sua PRÓPRIA escada de variantes (`extractors/busca/termos.py::variantes_de_busca`,
# mesmo gerador da Fase 1: bloco de precisão com até 3 termos — título + corte
# de subtítulo + corte de marcador de temporada — mais bloco de recall com até
# `_MAXIMO_PREFIXOS`=3 prefixos crescentes, 6 variantes no pior caso), cada
# uma até o timeout do GET síncrono dos adapters (`_TIMEOUT_S` de
# `extractors/animefire.py`/`extractors/animesdrive.py`, 15s) — uma escada
# completa custa até 6 × 15s = 90s num único site.
#
# `_expandir_com_termos_de_provedor` (escopo `padrao`) e
# `_expandir_com_termos_de_provedor_em_todas_as_fontes` (escopo `todas`) têm o
# MESMO perfil de pior caso: as duas são termo-major sequencial, mas sites em
# PARALELO dentro de cada termo (`extractors.busca.servico.buscar_por_site_com_
# variantes` nas duas — a paralelização de sites dentro do termo já eliminou
# o fator de 2 sites que multiplicava a escada). Só os até 2 termos
# multiplicam a escada agora — os sites não multiplicam mais nada, correm
# juntos. Conta final: 10 (metadado) + até 2 × 90s (uma escada completa no
# site mais lento do par que respondeu por último) = 190s. Reaproveitar o
# mesmo teto entre os dois escopos reflete a mesma estrutura de fato, não só
# "por padrão".
#
# A variância de captura de navegador do AnimesDrive (até 90s) é um risco
# estrutural separado, rastreado na Fase E do plano — fora do escopo desta
# conta. Quem não terminar a tempo é cancelado — devolve a rodada da Fase 1
# em vez de travar a resposta.
_TETO_EXPANSAO_S = 190

# Sub-teto só de `buscar_titulos` dentro da fase acima: sem isto, AniList +
# Kitsu no pior caso (cada um até `integrations/servico.py::
# _TIMEOUT_POR_PROVEDOR_S`, 8s) poderiam consumir tempo imprevisível antes de
# `_TETO_EXPANSAO_S` sequer começar a rodada de scraping com termo de
# provedor — teto próprio evita essa incerteza, independente de quanto sobra
# do orçamento maior.
_TETO_METADADOS_S = 10


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


# --- Escopo `padrao`: Fase 1 sequencial por site + Fase 2 por termo de provedor ---
# Fase 2 (expansão por termo de provedor, best-effort) mora em
# `_expandir_com_termos_de_provedor` — o helper irmão do escopo `todas` é
# `_expandir_com_termos_de_provedor_em_todas_as_fontes` (mesma estrutura, só o
# contrato de saída difere).
async def buscar_com_titulos_alternativos(
    sessionmaker: _SessionMaker, titulo: str
) -> BuscaEmFontes:
    """Busca sequencial por site (ordem de `extractors.registro.EXTRATORES`),
    em duas fases ordenadas por custo (Fase A do PLANO_PADRONIZACAO_FONTES.md
    — nunca gastar rede de provedor externo antes de esgotar as variantes de
    regex, que são de graça):

    Fase 1 — variantes puras (`extractors.busca.termos.variantes_de_busca`, sem I/O
    de provedor), tentadas em cada site até o primeiro achar candidatos.

    Fase 2 — só se a Fase 1 não achou nada em site nenhum (ao contrário do
    escopo `todas`, que expande enquanto sobrar site pendente — ver docstring
    de módulo): termos de provedor (romaji/inglês, via
    `integrations.servico.buscar_titulos`) — tolerância a idioma (usuário
    digitou em inglês, sites indexam romaji, ou vice-versa).
    Cada termo tem sua PRÓPRIA escada de variantes (mesmo gerador da Fase 1,
    `variantes_de_busca`) e sua PRÓPRIA referência de validação (o próprio
    termo, não `titulo`) — um termo que não corresponde a `titulo` sob
    `corresponde_ao_titulo` (ex. título em inglês vs romaji) não pode ser
    rejeitado por validar contra a referência errada. Variante cujo slug já
    foi tentado na Fase 1 é pulada (dedupe, não reconsulta o mesmo termo).
    Delegada a `_expandir_com_termos_de_provedor`, best-effort: falha ou timeout
    (`_TETO_EXPANSAO_S`) nunca propaga daqui pra fora nem derruba a busca da
    Fase 1 — devolve a rodada já obtida.

    Limitação conhecida (mesma já documentada em
    `api/servicos/capas.py::_consultar_capas`): o `wait_for` da Fase 2 cancela
    a *task* asyncio, não a thread do SO já em voo dentro do `to_thread` de
    `extractors/resiliencia.py` — na pior das hipóteses ela roda até terminar
    sozinha, e a rodada cancelada não registra sucesso/falha no circuit
    breaker.
    """
    variantes_puras = variantes_de_busca(titulo)

    resultados: dict[str, ResultadoDeFonte] = {}
    vencedor_dominio: str | None = None
    vencedor_termo: str | None = None

    for extrator in EXTRATORES:
        resultado, termo = await servico_extractors.buscar_em_com_variantes(
            sessionmaker, extrator.dominio, variantes_puras, referencia=titulo
        )
        resultados[extrator.dominio] = resultado
        if resultado.candidatos:
            vencedor_dominio, vencedor_termo = extrator.dominio, termo
            break

    # `resultados` já está completo pra todo `EXTRATORES` neste ponto (a Fase 1
    # só sai do loop sem `break` depois de tentar todos) — se os dois já vieram
    # `indisponivel` (cooldown/erro), a Fase 2 vai pular ambos de qualquer
    # forma (mesmo filtro dentro de `_expandir_com_termos_de_provedor`), então
    # gastar o round-trip de `buscar_titulos` seria rede garantidamente desperdiçada.
    if vencedor_dominio is None and any(not r.indisponivel for r in resultados.values()):
        slugs_fase1 = {slugificar(v) for v in variantes_puras}
        try:
            expandido = await asyncio.wait_for(
                _expandir_com_termos_de_provedor(sessionmaker, titulo, resultados, slugs_fase1),
                timeout=_TETO_EXPANSAO_S,
            )
        except Exception as excecao:
            # Captura ampla e intencional: expansão por termo de provedor é
            # best-effort (docstring acima) — falha de metadado, timeout do
            # lote ou qualquer outro erro não pode derrubar a busca da Fase 1.
            logger.warning(
                "expansão por termo de provedor best-effort falhou para título %r: %s",
                titulo,
                excecao,
            )
            expandido = None
        if expandido is not None:
            return expandido

    fontes = _completar_nao_consultados(resultados, vencedor_dominio)
    dominio_alternativo = (
        vencedor_dominio if vencedor_dominio not in (None, EXTRATORES[0].dominio) else None
    )
    return BuscaEmFontes(
        fontes=fontes, termo_alternativo=vencedor_termo, dominio_alternativo=dominio_alternativo
    )


async def _expandir_com_termos_de_provedor(
    sessionmaker: _SessionMaker,
    titulo: str,
    resultados: dict[str, ResultadoDeFonte],
    slugs_fase1: set[str],
) -> BuscaEmFontes | None:
    """Fase 2 do escopo `padrao`. Par, no escopo `todas`, de
    `_expandir_com_termos_de_provedor_em_todas_as_fontes`: mesma estrutura —
    `_termos_alternativos` uma vez, escada própria por termo com dedupe contra
    a Fase 1, fan-out paralelo por site — só mudam o contrato de saída (fonte
    única com desempate vs. união de fontes) e o critério de elegibilidade de
    site (`disponiveis` vs. `pendentes`).

    Só chamada quando nenhum site achou nada com as variantes puras de
    `extractors/busca/termos.py`. Busca romaji/inglês do provedor UMA VEZ e tenta
    termo por termo (escada própria por termo, não aborta tudo se um termo
    falhar): para cada termo, gera sua própria escada de variantes
    (`variantes_de_busca`, mesmo gerador da Fase 1) filtrada pelo dedupe de
    `slugs_fase1`, e busca essa escada em TODOS os sites ainda disponíveis
    (não `indisponivel` em `resultados`) EM PARALELO — mesma função que o
    escopo `todas` usa (`extractors.busca.servico.buscar_por_site_com_variantes`,
    `dominios=` restrito aos sites ainda disponíveis), não mais um loop
    sequencial `for extrator in EXTRATORES`. Só passa pro próximo termo depois
    que o fan-out inteiro do termo atual não achar candidato em site nenhum.

    Ao contrário do escopo `todas` (que só precisa da união dos resultados,
    `termo_alternativo`/`dominio_alternativo` sempre `None` — ver docstring de
    `buscar_em_todas_as_fontes_com_titulos_alternativos`), este escopo precisa
    reportar uma ÚNICA fonte. Critério de desempate quando mais de um site
    acha candidato no MESMO termo (fan-out paralelo, sem ordem de chegada
    garantida): vence o primeiro site na ordem de prioridade de
    `extractors.registro.EXTRATORES` que tiver candidatos — mesma prioridade
    de site já usada na Fase 1 (sequencial), aplicada aqui sobre o resultado
    já pronto do fan-out em vez de parar no primeiro que responde em tempo
    real. Determinístico, independente de latência de rede entre sites. O
    site que perdeu o desempate teve seus `candidatos` genuinamente
    encontrados descartados da resposta (`candidatos=[]`) — o contrato deste
    escopo é uma fonte só, o fan-out paralelo é só otimização de latência,
    não motivo pra passar a expor várias fontes como o escopo `todas` faz.

    `termo_alternativo` reporta o TERMO (romaji/inglês) que funcionou, não
    mais a variante específica dentro da escada dele: `buscar_por_site_com_
    variantes` não expõe qual variante da escada casou por site, só o
    `ResultadoDeFonte` agregado (mesmo contrato que o escopo `todas` já
    aceita). Precisão um nível abaixo da versão sequencial anterior (que
    apontava a variante exata via `buscar_em_com_variantes`) — troca aceita
    pelo ganho de paralelismo entre sites.

    Muta `resultados` (o dict do chamador, não uma cópia) conforme cada termo
    é tentado — mesmo quando esta função devolve `None` (nenhum termo achou
    nada), o chamador monta a resposta final a partir do MESMO dict, então o
    status mais recente de cada site (não mais o congelado da Fase 1) chega a
    `_completar_nao_consultados` (CLAUDE.md §4, erro nunca silencioso: um site
    que falhou durante esta fase não pode ser reportado com o status otimista
    de antes dela).
    """
    titulos = await asyncio.wait_for(
        servico_metadados.buscar_titulos(titulo), timeout=_TETO_METADADOS_S
    )
    if titulos is None:
        return None
    termos = _termos_alternativos(titulos, titulo)
    if not termos:
        return None

    for termo in termos:
        variantes_termo = _variantes_sem_repetir_fase1(variantes_de_busca(termo), slugs_fase1)
        if not variantes_termo:
            continue  # toda a escada deste termo já foi tentada na Fase 1
        disponiveis = [
            dominio for dominio, resultado in resultados.items() if not resultado.indisponivel
        ]
        if not disponiveis:
            break  # todo site já ficou indisponível — sem sentido tentar mais termos
        resposta_por_dominio = await servico_extractors.buscar_por_site_com_variantes(
            sessionmaker, variantes_termo, referencia=termo, dominios=disponiveis
        )
        resultados.update(resposta_por_dominio)

        vencedor: str | None = None
        for extrator in EXTRATORES:
            resultado_extrator = resposta_por_dominio.get(extrator.dominio)
            if resultado_extrator is not None and resultado_extrator.candidatos:
                vencedor = extrator.dominio
                break
        if vencedor is not None:
            # Escopo `padrao` reporta uma única fonte (contrato de
            # `termo_alternativo`/`dominio_alternativo` escalares) — um site
            # que também achou candidato no mesmo termo mas perdeu o
            # desempate não pode vazar pra resposta final só porque o
            # fan-out paralelo consultou os dois de verdade. Falha real
            # (`indisponivel`) descoberta durante este termo continua sendo
            # reportada (não suprimida) — só o achado concorrente é.
            for dominio, resultado_extrator in resposta_por_dominio.items():
                if dominio != vencedor and resultado_extrator.candidatos:
                    resultados[dominio] = replace(resultado_extrator, candidatos=[])
            fontes = _completar_nao_consultados(resultados, vencedor)
            dominio_alternativo = vencedor if vencedor != EXTRATORES[0].dominio else None
            return BuscaEmFontes(
                fontes=fontes, termo_alternativo=termo, dominio_alternativo=dominio_alternativo
            )
    return None


# --- Escopo `todas`: Fase 1 paralela por site + Fase 2 por termo de provedor ---
# Fase 2 (expansão por termo de provedor, best-effort) mora em
# `_expandir_com_termos_de_provedor_em_todas_as_fontes` — o helper irmão do
# escopo `padrao` é `_expandir_com_termos_de_provedor` (mesma estrutura, só o
# contrato de saída difere).
async def buscar_em_todas_as_fontes_com_titulos_alternativos(
    sessionmaker: _SessionMaker, titulo: str
) -> BuscaEmFontes:
    """`escopo=todas` (D-B1/D-B2, Fase B do PLANO_PADRONIZACAO_FONTES.md):
    busca paralela em todos os sites, cada um esgotando sua própria escada de
    variantes de forma independente e exaustiva
    (`extractors.busca.servico.buscar_por_site_com_variantes`, fatia 3/4, INV-1') —
    nenhum site interrompe ou "rouba a vez" da busca dos outros, o resultado
    final é a união de todas as fontes que realmente têm o anime (aplicando a
    validação de `extractors/busca/correspondencia.py::corresponde_ao_titulo` já embutida em
    `buscar_em_com_variantes`). Serve o diálogo "Trocar fonte", que existe
    justamente pra mostrar as alternativas lado a lado (D-B2).

    Mesma composição de variantes da Fase A, em duas fases ordenadas por
    custo — reaproveita `variantes_de_busca` e `_termos_alternativos` (não
    duplica a lógica de juntar os dois, D-B1):

    Fase 1 — variantes puras de regex (`extractors.busca.termos.variantes_de_busca`,
    sem I/O de provedor), tentadas em todos os sites em paralelo, cada site
    esgotando sua própria escada.

    Fase 2 — enquanto sobrar site PENDENTE depois da Fase 1 (não
    `indisponivel` e sem candidato), mesmo que outro site já tenha achado:
    termos de provedor (romaji/inglês), mesma escada por termo (variantes e
    referência próprias, dedupe contra a Fase 1) e mesmo caráter best-effort
    de `_expandir_com_termos_de_provedor` (falha ou timeout nunca derruba a
    busca, devolve o resultado da Fase 1) — só que aqui cada termo busca em
    paralelo nos sites ainda pendentes (`dominios=`, restringindo a sites que
    nenhum termo anterior já achou candidato), delegada a
    `_expandir_com_termos_de_provedor_em_todas_as_fontes`.

    `termo_alternativo`/`dominio_alternativo` sempre `None` aqui — ao
    contrário de `buscar_em_com_variantes` (escopo `padrao`), o resultado
    aqui é por definição a união de vários sites, cada um com seu próprio
    termo vencedor — não faz sentido expor um só. Sem prejuízo prático: o
    diálogo "Trocar fonte" mostra `dominio`/`versao` por candidato (D-B3/D-B4),
    não depende de um banner de "termo alternativo" como a Home depende no
    escopo `padrao`.
    """
    variantes_puras = variantes_de_busca(titulo)
    resultado_por_dominio = await servico_extractors.buscar_por_site_com_variantes(
        sessionmaker, variantes_puras, referencia=titulo
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
        slugs_fase1 = {slugificar(v) for v in variantes_puras}
        try:
            expandido = await asyncio.wait_for(
                _expandir_com_termos_de_provedor_em_todas_as_fontes(
                    sessionmaker, titulo, resultado, slugs_fase1
                ),
                timeout=_TETO_EXPANSAO_S,
            )
        except Exception as excecao:
            # Captura ampla e intencional, mesmo motivo de
            # `buscar_com_titulos_alternativos`: expansão por termo de
            # provedor é best-effort — falha de metadado, timeout do lote ou
            # qualquer outro erro não pode derrubar a busca da Fase 1.
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
    resultado_fase1: list[ResultadoDeFonte],
    slugs_fase1: set[str],
) -> list[ResultadoDeFonte] | None:
    """Fase 2 do escopo `todas`, par de `_expandir_com_termos_de_provedor`
    (escopo `padrao`): mesma estrutura de Fase 2 — `_termos_alternativos` uma
    vez, escada própria por termo com dedupe contra a Fase 1, fan-out paralelo
    por site — só mudam o contrato de saída (união de fontes vs. fonte única
    com desempate por prioridade de `EXTRATORES`) e o critério de elegibilidade
    de site (`pendentes`, sem candidato de termo anterior, vs. `disponiveis`).

    Só chamada quando sobrou pelo menos um site PENDENTE depois da Fase 1 —
    mesmo critério do `pendentes` calculado aqui dentro (o chamador não pode
    ser mais frouxo nem mais estrito que este filtro). Busca romaji/inglês do
    provedor UMA VEZ (`_termos_alternativos`, reaproveitado da Fase A) e tenta
    termo por termo (escada própria por termo, mesmo critério de
    `_expandir_com_termos_de_provedor`): cada termo gera sua própria escada de
    variantes (`variantes_de_busca`) filtrada pelo dedupe de
    `slugs_fase1`, e busca em paralelo (`buscar_por_site_com_variantes`) só
    nos sites ainda pendentes — os que não estão `indisponivel` e ainda não
    acharam candidato num termo anterior (`dominios=`, evita reconsultar quem
    já respondeu). Só passa pro próximo termo se ainda sobrar site pendente.

    `None` quando o provedor não devolveu título nenhum, nenhum termo achou
    candidato em site nenhum, ou nenhuma variante de termo nenhum sobrou após
    o dedupe — o chamador mantém o resultado (intacto) da Fase 1."""
    titulos = await asyncio.wait_for(
        servico_metadados.buscar_titulos(titulo), timeout=_TETO_METADADOS_S
    )
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
            continue  # toda a escada deste termo já foi tentada na Fase 1
        resposta_por_dominio = await servico_extractors.buscar_por_site_com_variantes(
            sessionmaker, variantes_termo, referencia=termo, dominios=pendentes
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
    """`resultados` pode não ter entrada pra todo `EXTRATORES` — o laço
    sequencial para assim que um site acha candidatos, então sites depois
    dele na ordem nunca chegam a ser tentados. O contrato de saída da API
    precisa listar os dois domínios mesmo assim (senão a UI que checa "todas
    as fontes indisponíveis" mentiria) — o não tentado sai como
    `indisponivel=False, candidatos=[], motivo="não consultado (<dominio> respondeu)"`."""
    finais = []
    for extrator in EXTRATORES:
        if extrator.dominio in resultados:
            finais.append(resultados[extrator.dominio])
        else:
            finais.append(
                ResultadoDeFonte(
                    dominio=extrator.dominio,
                    candidatos=[],
                    indisponivel=False,
                    motivo=f"não consultado ({dominio_respondeu} respondeu)",
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


def _variantes_sem_repetir_fase1(variantes: list[str], slugs_fase1: set[str]) -> list[str]:
    """Filtra a escada de variantes de um termo de provedor (`variantes_de_busca`),
    removendo qualquer entrada cujo slug (`core/texto.py::slugificar`) já foi
    tentado na Fase 1 (`variantes_puras` do título digitado) — dedupe entre
    fases: nunca reconsulta um site com exatamente o mesmo termo de busca que
    a Fase 1 já tentou e não achou."""
    return [variante for variante in variantes if slugificar(variante) not in slugs_fase1]

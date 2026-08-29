"""Orquestração de `GET /api/animes/buscar-fontes` que cruza `extractors/` ×
`integrations/` — único ponto que importa os dois lados da fronteira pra este
fluxo, mesma decisão de `api/servicos/descoberta.py`/`fontes.py` (CLAUDE.md
§1: `extractors/` NUNCA importa de `integrations/`, e vice-versa; orquestração
cross-camada mora aqui). Três responsabilidades:

- `buscar_com_titulos_alternativos` (escopo `padrao`): busca sequencial por
  site (ordem de `extractors.registro.EXTRATORES`), em duas fases ordenadas
  por custo (Fase A do PLANO_PADRONIZACAO_FONTES.md): primeiro as variantes
  puras de regex de `extractors/nomes.py::variantes_de_busca` (de graça, sem
  I/O de provedor externo), e só se nenhum site achar nada com elas, os
  termos de provedor (romaji/inglês, via `integrations/servico.py::
  buscar_titulos`) — tolerância a idioma (usuário digitou em inglês, sites
  indexam romaji, ou vice-versa).
- `buscar_em_todas_as_fontes_com_titulos_alternativos` (escopo `todas`, Fase
  B): mesma composição de variantes acima, mas busca paralela por site
  (`extractors.servico.buscar_por_site_com_variantes`) — cada site esgota sua
  própria escada de variantes de forma independente e exaustiva, sem que um
  "roube a vez" do outro (INV-1'); o resultado final é a união de todas as
  fontes onde o anime realmente existe. Serve o diálogo "Trocar fonte".
- `enriquecer_capas`: preenche `capa_url` dos candidatos que vieram sem, via
  metadado de provedor externo (`integrations/`). Hoje só o AnimeFire precisa
  disto — a página de busca dele genuinamente não expõe imagem nenhuma
  (confirmado ao vivo e no código de referência Slime_Shell_Web, não é bug de
  parsing). O AnimesDrive já vem com capa própria da busca
  (`extractors/animesdrive.py::buscar`).
"""

import asyncio
import logging
from dataclasses import dataclass, replace

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.texto import slugificar
from extractors import servico as servico_extractors
from extractors.base import ResultadoBusca
from extractors.nomes import variantes_de_busca
from extractors.registro import EXTRATORES
from extractors.servico import ResultadoDeFonte
from integrations import servico as servico_metadados
from integrations.base import TitulosDeAnime

logger = logging.getLogger(__name__)

_SessionMaker = async_sessionmaker[AsyncSession]

# Teto pequeno de propósito: `buscar-fontes` já roda a busca sequencial por
# site de `buscar_com_titulos_alternativos`; este enriquecimento roda LOGO
# DEPOIS, sobre um provedor diferente (AniList/Kitsu, sem circuit breaker
# próprio como `extractors/`) — 5 é um teto conservador pra nunca virar uma
# segunda rajada descontrolada, mesmo espírito de
# `integrations/servico.py::_lock_em_alta` (thundering herd), sem depender de
# medição real de rate limit ainda inexistente pra este caminho.
_CONCORRENCIA_MAXIMA = 5

# Teto do LOTE inteiro (asyncio.wait, não wait_for por chamada individual):
# `integrations/servico.py::buscar_por_titulo` tenta AniList e, se falhar,
# Kitsu, cada um com até `_TIMEOUT_POR_PROVEDOR_S` (8s) — pior caso de UMA
# chamada é 16s. Mesmo raciocínio de
# `api/servicos/descoberta.py::_TETO_ENRIQUECIMENTO_S` (16s + margem = 18s)
# pra essa mesma função; aqui o teto cobre várias chamadas em paralelo
# (limitadas pelo semáforo acima) — quem não terminar a tempo é cancelado
# explicitamente, nunca some rodando em segundo plano após a resposta.
_TETO_LOTE_S = 18

# Teto da fase inteira de expansão por termo de provedor (Fase 2, fatia 5 do
# plano): `buscar_titulos` (até `_TETO_METADADOS_S`, 10s) mais o pior caso de
# uma escada por termo — cada termo de provedor (romaji, inglês — até 2) gera
# sua PRÓPRIA escada de variantes (`extractors/nomes.py::variantes_de_busca`,
# mesmo gerador da Fase 1: título + até 2 cortes de subtítulo/temporada + até
# `_MAXIMO_PREFIXOS`=5 prefixos truncados, ~7 variantes no pior caso), cada
# uma até o timeout do GET síncrono dos adapters (`_TIMEOUT_S` de
# `extractors/animefire.py`/`extractors/animesdrive.py`, 15s) — uma escada
# completa custa até 7 × 15s = 105s num único site.
#
# `_tentar_termos_de_provedor` (escopo `padrao`) e
# `_expandir_termo_de_provedor_em_todas_as_fontes` (escopo `todas`) têm hoje o
# MESMO perfil de pior caso: as duas são termo-major sequencial, mas sites em
# PARALELO dentro de cada termo (`extractors.servico.buscar_por_site_com_
# variantes` nas duas, desde esta revisão — antes dela, `_tentar_termos_de_
# provedor` também era site-major sequencial, com o extra fator de 2 sites
# multiplicando a escada: 2 termos × 2 sites × 105s = 420s, teto de 430s; a
# paralelização de sites dentro do termo, no molde de
# `buscar_por_site_com_variantes`, eliminou esse fator). Só os até 2 termos
# multiplicam a escada agora — os sites não multiplicam mais nada, correm
# juntos. Conta final: 10 (metadado) + até 2 × 105s (uma escada completa no
# site mais lento do par que respondeu por último) = 220s. Reaproveitar o
# mesmo teto entre os dois escopos agora reflete a mesma estrutura de fato,
# não só "por padrão".
#
# A variância de captura de navegador do AnimesDrive (até 90s) é um risco
# estrutural separado, rastreado na Fase E do plano — fora do escopo desta
# conta. Quem não terminar a tempo é cancelado — devolve a rodada da Fase 1
# em vez de travar a resposta.
_TETO_EXPANSAO_S = 220

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


async def buscar_com_titulos_alternativos(
    sessionmaker: _SessionMaker, titulo: str
) -> BuscaEmFontes:
    """Busca sequencial por site (ordem de `extractors.registro.EXTRATORES`),
    em duas fases ordenadas por custo (Fase A do PLANO_PADRONIZACAO_FONTES.md
    — nunca gastar rede de provedor externo antes de esgotar as variantes de
    regex, que são de graça):

    Fase 1 — variantes puras (`extractors.nomes.variantes_de_busca`, sem I/O
    de provedor), tentadas em cada site até o primeiro achar candidatos.

    Fase 2 — só se a Fase 1 não achou nada em site nenhum: termos de provedor
    (romaji/inglês, via `integrations.servico.buscar_titulos`) — tolerância a
    idioma (usuário digitou em inglês, sites indexam romaji, ou vice-versa).
    Cada termo tem sua PRÓPRIA escada de variantes (mesmo gerador da Fase 1,
    `variantes_de_busca`) e sua PRÓPRIA referência de validação (o próprio
    termo, não `titulo`) — um termo que não corresponde a `titulo` sob
    `corresponde_ao_titulo` (ex. título em inglês vs romaji) não pode ser
    rejeitado por validar contra a referência errada. Variante cujo slug já
    foi tentado na Fase 1 é pulada (dedupe, não reconsulta o mesmo termo).
    Delegada a `_tentar_termos_de_provedor`, best-effort: falha ou timeout
    (`_TETO_EXPANSAO_S`) nunca propaga daqui pra fora nem derruba a busca da
    Fase 1 — devolve a rodada já obtida.

    Limitação conhecida (mesma já documentada em `_consultar_capas`): o
    `wait_for` da Fase 2 cancela a *task* asyncio, não a thread do SO já em
    voo dentro do `to_thread` de `extractors/resiliencia.py` — na pior das
    hipóteses ela roda até terminar sozinha, e a rodada cancelada não registra
    sucesso/falha no circuit breaker.
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
    # forma (mesmo filtro dentro de `_tentar_termos_de_provedor`), então gastar
    # o round-trip de `buscar_titulos` seria rede garantidamente desperdiçada.
    if vencedor_dominio is None and any(not r.indisponivel for r in resultados.values()):
        slugs_fase1 = {slugificar(v) for v in variantes_puras}
        try:
            expandido = await asyncio.wait_for(
                _tentar_termos_de_provedor(sessionmaker, titulo, resultados, slugs_fase1),
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


async def _tentar_termos_de_provedor(
    sessionmaker: _SessionMaker,
    titulo: str,
    resultados: dict[str, ResultadoDeFonte],
    slugs_fase1: set[str],
) -> BuscaEmFontes | None:
    """Só chamada quando nenhum site achou nada com as variantes puras de
    `extractors/nomes.py`. Busca romaji/inglês do provedor UMA VEZ e tenta
    termo por termo (escada própria por termo, não aborta tudo se um termo
    falhar): para cada termo, gera sua própria escada de variantes
    (`variantes_de_busca`, mesmo gerador da Fase 1) filtrada pelo dedupe de
    `slugs_fase1`, e busca essa escada em TODOS os sites ainda disponíveis
    (não `indisponivel` em `resultados`) EM PARALELO — mesma função que o
    escopo `todas` usa (`extractors.servico.buscar_por_site_com_variantes`,
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


async def buscar_em_todas_as_fontes_com_titulos_alternativos(
    sessionmaker: _SessionMaker, titulo: str
) -> BuscaEmFontes:
    """`escopo=todas` (D-B1/D-B2, Fase B do PLANO_PADRONIZACAO_FONTES.md):
    busca paralela em todos os sites, cada um esgotando sua própria escada de
    variantes de forma independente e exaustiva
    (`extractors.servico.buscar_por_site_com_variantes`, fatia 3/4, INV-1') —
    nenhum site interrompe ou "rouba a vez" da busca dos outros, o resultado
    final é a união de todas as fontes que realmente têm o anime (aplicando a
    validação de `extractors/nomes.py::corresponde_ao_titulo` já embutida em
    `buscar_em_com_variantes`). Serve o diálogo "Trocar fonte", que existe
    justamente pra mostrar as alternativas lado a lado (D-B2).

    Mesma composição de variantes da Fase A, em duas fases ordenadas por
    custo — reaproveita `variantes_de_busca` e `_termos_alternativos` (não
    duplica a lógica de juntar os dois, D-B1):

    Fase 1 — variantes puras de regex (`extractors.nomes.variantes_de_busca`,
    sem I/O de provedor), tentadas em todos os sites em paralelo, cada site
    esgotando sua própria escada.

    Fase 2 — só se a Fase 1 não achou nada em site nenhum e pelo menos um
    site ainda está disponível: termos de provedor (romaji/inglês), mesma
    escada por termo (variantes e referência próprias, dedupe contra a Fase
    1) e mesmo caráter best-effort de `_tentar_termos_de_provedor` (falha ou
    timeout nunca derruba a busca, devolve o resultado da Fase 1) — só que
    aqui cada termo busca em paralelo nos sites ainda pendentes (`dominios=`,
    restringindo a sites que nenhum termo anterior já achou candidato),
    delegada a `_expandir_termo_de_provedor_em_todas_as_fontes`.

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

    ja_achou = any(fonte.candidatos for fonte in resultado)
    algum_site_disponivel = any(not fonte.indisponivel for fonte in resultado)
    if not ja_achou and algum_site_disponivel:
        slugs_fase1 = {slugificar(v) for v in variantes_puras}
        try:
            expandido = await asyncio.wait_for(
                _expandir_termo_de_provedor_em_todas_as_fontes(
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


async def _expandir_termo_de_provedor_em_todas_as_fontes(
    sessionmaker: _SessionMaker,
    titulo: str,
    resultado_fase1: list[ResultadoDeFonte],
    slugs_fase1: set[str],
) -> list[ResultadoDeFonte] | None:
    """Só chamada quando a Fase 1 (variantes puras, escopo `todas`) não achou
    nada em site nenhum e pelo menos um site ainda está disponível. Busca
    romaji/inglês do provedor UMA VEZ (`_termos_alternativos`, reaproveitado
    da Fase A) e tenta termo por termo (escada própria por termo, mesmo
    critério de `_tentar_termos_de_provedor`): cada termo gera sua própria
    escada de variantes (`variantes_de_busca`) filtrada pelo dedupe de
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


async def enriquecer_capas(
    sessionmaker: _SessionMaker, resultados: list[ResultadoDeFonte]
) -> list[ResultadoDeFonte]:
    """Preenche `capa_url` dos candidatos que vieram sem (`ResultadoBusca.
    capa_url is None`) consultando `integrations.servico.buscar_por_titulo`.
    Best-effort: falha de uma consulta (`FalhaDeMetadados`, timeout ou
    qualquer outra exceção do provedor) nunca propaga daqui pra fora nem
    derruba os demais candidatos — aquele título simplesmente fica sem capa.

    `sessionmaker` não é usado no corpo hoje (`buscar_por_titulo` não toca o
    banco) — mantido na assinatura por consistência com as demais funções de
    `api/servicos/` (todas recebem sessionmaker como 1º parâmetro) e pra não
    obrigar mudar a assinatura no dia em que este enriquecimento passar a
    persistir alguma coisa (ex. cache de capa por título).
    """
    titulos_pendentes = _titulos_sem_capa(resultados)
    if not titulos_pendentes:
        return resultados

    capa_por_titulo = await _consultar_capas(titulos_pendentes)
    if not capa_por_titulo:
        return resultados

    return [
        replace(
            fonte,
            candidatos=[_com_capa(candidato, capa_por_titulo) for candidato in fonte.candidatos],
        )
        for fonte in resultados
    ]


def _titulos_sem_capa(resultados: list[ResultadoDeFonte]) -> list[str]:
    """Dedupe por título normalizado (`core/texto.py::slugificar`) — dois
    candidatos com o mesmo título, do mesmo site ou de sites diferentes, geram
    só uma consulta a `buscar_por_titulo`."""
    vistos: set[str] = set()
    titulos: list[str] = []
    for fonte in resultados:
        for candidato in fonte.candidatos:
            if candidato.capa_url is not None:
                continue
            chave = slugificar(candidato.titulo_exibicao)
            if chave in vistos:
                continue
            vistos.add(chave)
            titulos.append(candidato.titulo_exibicao)
    return titulos


def _com_capa(candidato: ResultadoBusca, capa_por_titulo: dict[str, str]) -> ResultadoBusca:
    if candidato.capa_url is not None:
        return candidato
    capa = capa_por_titulo.get(slugificar(candidato.titulo_exibicao))
    return candidato if capa is None else replace(candidato, capa_url=capa)


async def _consultar_capas(titulos: list[str]) -> dict[str, str]:
    """Dispara `buscar_por_titulo` para cada título em paralelo, limitado por
    `_CONCORRENCIA_MAXIMA` e pelo teto de tempo `_TETO_LOTE_S` do lote
    inteiro. `asyncio.wait` (não `wait_for`) pra aproveitar o que já terminou
    dentro do prazo em vez de cancelar tudo de uma vez; as tasks que ainda
    estiverem pendentes quando o prazo bater são canceladas explicitamente, e
    a cancelação é aguardada antes de devolver — a *task* não some rodando
    solta. Isso não cobre a chamada HTTP síncrona já em voo dentro do
    `asyncio.to_thread` de `integrations/servico.py`: cancelamento não
    interrompe uma thread do OS em andamento (mesma limitação documentada em
    `extractors/resiliencia.py`), então na pior das hipóteses ela roda até
    terminar sozinha — só o resultado é descartado, nunca aplicado."""
    semaforo = asyncio.Semaphore(_CONCORRENCIA_MAXIMA)

    async def _consultar_um(titulo: str) -> tuple[str, str | None]:
        chave = slugificar(titulo)
        async with semaforo:
            try:
                metadados = await servico_metadados.buscar_por_titulo(titulo)
            except Exception as excecao:
                # Captura ampla e intencional: enriquecimento de capa é
                # best-effort (docstring do módulo) — `FalhaDeMetadados`
                # (todos os provedores falharam), timeout ou qualquer outro
                # erro do adapter não pode derrubar os demais títulos do lote.
                logger.warning(
                    "enriquecimento de capa best-effort falhou para título %r: %s",
                    titulo,
                    excecao,
                )
                return chave, None
        return chave, metadados.capa_url if metadados is not None else None

    tasks = [asyncio.ensure_future(_consultar_um(titulo)) for titulo in titulos]
    concluidas, pendentes = await asyncio.wait(tasks, timeout=_TETO_LOTE_S)
    if pendentes:
        for tarefa in pendentes:
            tarefa.cancel()
        # Aguarda a cancelação de fato assentar antes de devolver — sem isto a
        # *task* asyncio fica solta (não a thread do OS por trás dela, ver
        # docstring acima). `return_exceptions=True` porque toda pendente aqui
        # levanta `CancelledError` por construção.
        await asyncio.gather(*pendentes, return_exceptions=True)

    capa_por_titulo: dict[str, str] = {}
    for tarefa in concluidas:
        chave, capa = tarefa.result()
        if capa:  # filtra None e "" (provedor externo não garante não-vazio)
            capa_por_titulo[chave] = capa
    return capa_por_titulo

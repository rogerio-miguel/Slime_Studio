"""Orquestração de `GET /api/animes/buscar-fontes` que cruza `fontes/` ×
`integrations/` — único ponto que importa os dois lados da fronteira pra este
fluxo, mesma decisão de `api/servicos/descoberta.py`/`fontes.py` (CLAUDE.md
§1: `fontes/` NUNCA importa de `integrations/`, e vice-versa; orquestração
cross-camada mora aqui).

Uma função pública, `buscar_em_todas_as_fontes_com_titulos_alternativos`, que
serve o diálogo "Trocar fonte": resolve o anime canônico no provedor de
metadados (AniList) UPFRONT (`titulos_canonicos.resolver_titulos_canonicos`),
monta a escada de termos combinada dos vários idiomas (`termos_de_busca`) e a
lista de referências de validação multi-idioma (`referencias_de_anime`), e faz Fase 1
PARALELA (cada site esgotando a escada de forma independente, validação
multi-referência via `correspondencia.py`). Devolve a UNIÃO das fontes onde o
anime realmente existe.

A busca da Home NÃO passa mais por aqui — virou busca direta na AniList
(`GET /api/animes/buscar`, `integrations.servico.listar_por_busca`); a
resolução de fonte da Home ficou preguiçosa, na página do anime.

Infra:

- `_completar_nao_consultados` — todo `EXTRATORES` aparece na saída, mesmo o
  site que não chegou a ser consultado (senão a UI que checa "todas as fontes
  indisponíveis" mentiria);
- caráter best-effort do metadado de provedor: falha ou timeout nunca derruba a
  busca nos sites, que segue só com o título digitado.

Candidato de busca em fonte não carrega capa: `fontes/` é só extração de
VÍDEO (`ResultadoBusca` não tem `capa_url`) e o diálogo "Trocar fonte" lista
os candidatos só por nome/site/versão. A capa do anime é resolvida na
materialização (`criar_anime` -> `enriquecer_anime_criado`), não aqui.
"""

import logging
import time

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.servicos.titulos_canonicos import (
    referencias_de_anime,
    resolver_titulos_canonicos,
    termos_de_busca,
)
from core.texto import slugificar
from fontes.adaptadores.registro import EXTRATORES
from fontes.busca import servico as servico_fontes
from fontes.busca.servico import ResultadoDeFonte

logger = logging.getLogger(__name__)

_SessionMaker = async_sessionmaker[AsyncSession]

# --- Busca combinada paralela em todos os sites ---

# Cache em memória do resultado de "Trocar fonte", por título digitado: reabrir o
# diálogo ou voltar de outra temporada refazia dezenas de requests idênticos aos
# sites. Só guarda resposta COMPLETA e positiva (todo site consultado e disponível e ao menos
# um candidato) — "não achei" e "não consegui tentar" nunca ficam presos, porque o
# usuário que busca de novo espera uma tentativa de verdade. Vive só no processo da
# API (some no restart) e é limitado em tamanho. Os candidatos de um anime quase não
# mudam em minutos, então a validade é longa; quem pesquisa de novo de propósito
# (botão "Buscar"/Enter do seletor) passa `atualizar` e descarta a entrada antes
# (`descartar_cache_da_busca`) — o cache só serve à abertura do seletor.
_TTL_CACHE_DE_BUSCA_S = 900
_MAXIMO_ENTRADAS_CACHE_DE_BUSCA = 64
_relogio = time.monotonic
_cache_de_busca: dict[str, tuple[float, list[ResultadoDeFonte]]] = {}


def _chave_do_cache_de_busca(titulo: str) -> str:
    return slugificar(titulo) or titulo.strip().casefold()


def descartar_cache_da_busca(titulo: str) -> None:
    """Esquece a entrada de `titulo`: a próxima busca vai de verdade aos sites."""
    _cache_de_busca.pop(_chave_do_cache_de_busca(titulo), None)


async def buscar_em_todas_as_fontes_com_titulos_alternativos(
    sessionmaker: _SessionMaker, titulo: str
) -> list[ResultadoDeFonte]:
    """`_buscar_em_todas_as_fontes` com o cache de `_cache_de_busca` por cima."""
    chave = _chave_do_cache_de_busca(titulo)
    agora = _relogio()
    guardado = _cache_de_busca.get(chave)
    if guardado is not None and agora - guardado[0] < _TTL_CACHE_DE_BUSCA_S:
        return guardado[1]

    resultado = await _buscar_em_todas_as_fontes(sessionmaker, titulo)

    completo = not any(f.indisponivel or f.motivo == _MOTIVO_NAO_CONSULTADO for f in resultado)
    if completo and any(f.candidatos for f in resultado):
        _cache_de_busca[chave] = (_relogio(), resultado)
        while len(_cache_de_busca) > _MAXIMO_ENTRADAS_CACHE_DE_BUSCA:
            del _cache_de_busca[next(iter(_cache_de_busca))]  # a mais antiga (ordem de inserção)
    else:
        _cache_de_busca.pop(chave, None)
    return resultado


async def _buscar_em_todas_as_fontes(
    sessionmaker: _SessionMaker, titulo: str
) -> list[ResultadoDeFonte]:
    """Devolve a UNIÃO de todas as fontes que realmente têm o anime — busca
    paralela em todos os sites, cada um esgotando sua própria escada de
    variantes de forma independente e exaustiva
    (`fontes.busca.servico.buscar_por_site_com_variantes`): nenhum site
    interrompe ou "rouba a vez" da busca dos outros. A validação de card
    (`fontes/busca/correspondencia.py::corresponde_a_alguma_referencia`
    sobre todos os nomes do anime) vem embutida em `buscar_em_com_variantes`.
    Serve o diálogo "Trocar fonte", que mostra as alternativas lado a lado.

    1. `resolver_titulos_canonicos` (best-effort sob `_TETO_METADADOS_S`) —
       `None` degrada para só o título digitado como referência/termo, não
       derruba a busca.
    2. `referencias` (`referencias_de_anime` — todos os nomes do anime) e
       `termos` (`termos_de_busca` — escada combinada de romaji + inglês +
       digitado, deduplicada por slug).
    3. `buscar_por_site_com_variantes` com a escada combinada em TODOS os sites
       em paralelo, cada um esgotando a escada.

    Havia uma Fase 2 (reexpandir os sites sem candidato com cada título canônico
    isolado) que a escada combinada já tornava redundante — não tocava a rede e
    segurava um teto de 190s à toa; foi removida. O bug que a motivou ("Dogul
    Wang", 2026-08-29: um site achar pela escada de regex impedia o segundo de
    ser consultado com o título inglês do provedor) é coberto por a escada
    combinada incluir o título inglês de cada site desde a 1ª varredura.
    """
    titulos = await resolver_titulos_canonicos(titulo)
    referencias = referencias_de_anime(titulos, titulo)
    termos = termos_de_busca(titulos, titulo)

    resultado_por_dominio = await servico_fontes.buscar_por_site_com_variantes(
        sessionmaker, termos, referencias=referencias
    )
    return _completar_nao_consultados(resultado_por_dominio)


_MOTIVO_NAO_CONSULTADO = "não consultado"


def _completar_nao_consultados(
    resultados: dict[str, ResultadoDeFonte],
) -> list[ResultadoDeFonte]:
    """Saída na ordem de `EXTRATORES`. `resultados` pode não ter entrada pra todo
    site; o contrato da API precisa listar todos os domínios mesmo assim (senão a
    UI que checa "todas as fontes indisponíveis" mentiria) — o ausente sai como
    `indisponivel=False, candidatos=[], motivo="não consultado"`."""
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
                    motivo=_MOTIVO_NAO_CONSULTADO,
                )
            )
    return finais

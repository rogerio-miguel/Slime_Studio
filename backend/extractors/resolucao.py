"""Resolução automática de fonte com fallback entre sites (ESPECIFICACAO.md §3A
item 2 / §10, Fase 2/3) — versão consciente de legendado/dublado (Fase 2 da
modelagem dublado/legendado).
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.enums import VersaoDeFonte, VersaoEpisodio
from core.texto import slugificar
from extractors import circuit_breaker
from extractors.base import ExtratorDeSite, ResultadoBusca
from extractors.busca.correspondencia import corresponde_a_alguma_referencia
from extractors.busca.servico import buscar_variantes_em_janelas
from extractors.busca.termos import escada_combinada
from extractors.registro import EXTRATORES
from extractors.versao import remover_marcador_de_versao
from models.anime import Anime
from models.fonte_anime import FonteAnime

_SessionMaker = async_sessionmaker[AsyncSession]

# `VersaoEpisodio` (LEGENDADO/DUBLADO) -> `VersaoDeFonte` correspondente — as
# duas têm o mesmo valor de string por design (`core/enums.py`), mas são
# enums separados de propósito (não fundir), daí o mapeamento explícito em
# vez de reinterpretar um pelo outro por acaso de implementação.
_MAPA_VERSAO_EPISODIO_PARA_FONTE: Final[dict[VersaoEpisodio, VersaoDeFonte]] = {
    VersaoEpisodio.LEGENDADO: VersaoDeFonte.LEGENDADO,
    VersaoEpisodio.DUBLADO: VersaoDeFonte.DUBLADO,
}


@dataclass(frozen=True, slots=True)
class FonteResolvida:
    dominio: str
    identificador: str
    # O que a fonte resolvida realmente é: confirmada igual à versão pedida,
    # ou `NAO_DIFERENCIADA` (site não separa, chamador nunca deve tratar como
    # confirmação da versão pedida — `api/servicos/jobs.py` deriva
    # `Episodio.versao = DESCONHECIDA` nesse caso, nunca do request).
    versao_da_fonte: VersaoDeFonte


@dataclass(frozen=True, slots=True)
class ConfirmacaoNecessaria:
    dominio: str
    candidatos: list[ResultadoBusca]


@dataclass(frozen=True, slots=True)
class VersaoIndisponivel:
    """Nenhum site, mapeado ou buscado ao vivo, consegue servir `versao` — nem
    confirmada, nem `NAO_DIFERENCIADA`."""

    versao: VersaoEpisodio


async def resolver_fonte_do_anime(
    sessionmaker: _SessionMaker,
    anime: Anime,
    versao: VersaoEpisodio,
    titulos_alternativos: list[str] | None = None,
) -> FonteResolvida | ConfirmacaoNecessaria | VersaoIndisponivel:
    """`versao` é a versão PEDIDA pelo cliente — só `LEGENDADO`/`DUBLADO`
    (nunca `DESCONHECIDA`, que não é uma versão pedível, só um estado de
    `Episodio` de fonte não-diferenciada).

    `titulos_alternativos` são todos os nomes conhecidos do anime (digitado,
    romaji, inglês, nativo, sinônimos), já resolvidos no provedor de metadados
    por quem chama — `extractors/` não cruza a fronteira de `integrations/`
    (CLAUDE.md §1), então a lista vem pronta de
    `api/servicos/fontes.py::listar_episodios_remotos` (via
    `api/servicos/busca.py::_referencias_de_anime`), com o título cadastrado na
    posição 0 como âncora. `None` (default) = caminho SEM resolução canônica
    (captura em `api/servicos/jobs.py`, fallback de job no worker): degrada para
    só o título cadastrado, byte a byte o comportamento anterior a esta mudança.

    Sem canônico, um site que indexa o anime só pelo título inglês (ex.
    AnimeFire cataloga "Villainess Level 99..." para *Akuyaku Reijou Level 99*)
    não é alcançado pela busca ao vivo, e a resolução cai para o próximo site
    enquanto "Trocar fonte" (que já resolve canônico) o encontra — a
    divergência que esta lista corrige.

    1. `FonteAnime` já mapeadas: entre as capazes de servir `versao` (uma
       CONFIRMADA da versão pedida ou uma `NAO_DIFERENCIADA`, em QUALQUER site
       mapeado), a mais recentemente confirmada (`resolvido_em`) vence —
       nem prioridade de site nem exatidão de versão se sobrepõem a uma
       escolha manual mais recente ("Trocar fonte"), ver `_resolver_em_mapeadas`.
    2. Nenhum mapeamento serve: percorre `EXTRATORES` em ordem, buscando ao
       vivo com a escada de variantes de TODOS os nomes do anime
       (`_variantes_das_referencias`). Sites que diferenciam versão
       (`diferencia_versao=True`) particionam os candidatos por versão e
       desambiguam dentro da partição pedida; a outra partição é persistida de
       graça quando também desambigua sem custo de rede extra. Sites que não
       diferenciam seguem o comportamento de sempre (desambigua no pool
       inteiro, `NAO_DIFERENCIADA`).
    3. Nenhum site (mapeado ou buscado) serve a versão pedida -> `VersaoIndisponivel`.
    """
    if versao not in (VersaoEpisodio.LEGENDADO, VersaoEpisodio.DUBLADO):
        raise ValueError(
            f"versão pedida a resolver_fonte_do_anime deve ser LEGENDADO ou"
            f" DUBLADO, recebido {versao!r}"
        )
    versao_confirmada = _MAPA_VERSAO_EPISODIO_PARA_FONTE[versao]

    # `titulos_alternativos` já traz `anime.titulo` como primeiro elemento
    # quando presente; `None`/vazio degrada para só o título cadastrado.
    referencias = titulos_alternativos or [anime.titulo]

    mapeadas = await _fontes_mapeadas_ordenadas(sessionmaker, anime.id)
    resolvida = _resolver_em_mapeadas(mapeadas, versao_confirmada)
    if resolvida is not None:
        return resolvida

    for indice, extrator in enumerate(EXTRATORES):
        if await circuit_breaker.esta_em_cooldown(sessionmaker, extrator.dominio):
            continue

        candidatos = await _buscar_variantes(sessionmaker, extrator, referencias)
        if not candidatos:
            continue

        if extrator.diferencia_versao:
            resultado = await _resolver_no_site_que_diferencia(
                sessionmaker, anime, referencias, extrator, indice, candidatos, versao
            )
            if resultado is not None:
                return resultado
            continue  # partição pedida vazia neste site — não desiste, tenta o próximo

        return await _resolver_no_site_nao_diferenciado(
            sessionmaker, anime, referencias, extrator, indice, candidatos
        )

    return VersaoIndisponivel(versao=versao)


async def proximo_site_para(
    sessionmaker: _SessionMaker, anime: Anime, ja_tentados: set[str], versao: VersaoEpisodio
) -> FonteResolvida | None:
    """Próxima fonte mapeada ainda não tentada nesta cadeia de fallback —
    usado quando um site já mapeado falha de extração (não confundir com
    `resolver_fonte_do_anime`, que pode pedir confirmação: aqui o job já está em
    andamento e não há quem confirme, então um site novo ambíguo é simplesmente
    pulado, não devolvido como `ConfirmacaoNecessaria`).

    `ja_tentados` é o conjunto de domínios já tentados nesta cadeia (mantido
    pelo chamador, `extractors/servico.py::_proximo_com_episodio`) — inclui o
    domínio que acabou de falhar. Corte por exclusão explícita, não mais por
    `FonteAnime.prioridade` (bug corrigido: o corte antigo — "qualquer fonte
    mapeada de prioridade MAIOR que a que falhou" — dependia implicitamente
    de a fonte em uso ser sempre a de MENOR prioridade entre as mapeadas, o
    que só valia enquanto `_resolver_em_mapeadas` escolhia por prioridade. Ao
    passar a escolher por `resolvido_em` — mais recentemente confirmada
    vence, não a de site com índice menor em `EXTRATORES`, pra "Trocar
    fonte" valer de fato — essa invariante quebrou: uma fonte mapeada,
    capaz e nunca tentada podia ficar de fora só por ter prioridade menor
    que a que falhou, fazendo o fallback desistir com `None` mesmo havendo
    alternativa válida).

    `versao` aqui é `Episodio.versao` de quem está com download em andamento
    (`extractors/servico.py::baixar_com_fallback_de_site`) — ao contrário de
    `resolver_fonte_do_anime`, PODE ser `DESCONHECIDA` (episódio veio de fonte
    `NAO_DIFERENCIADA`, sem versão pedida de verdade pra preservar): nesse
    caso a busca de fallback ignora a dimensão de versão por completo
    (comportamento anterior a esta fase — primeira fonte disponível, sem
    exigir capacidade de versão nenhuma).
    """
    mapeadas = await _fontes_mapeadas_ordenadas(sessionmaker, anime.id)
    candidatas_mapeadas = [fonte for fonte in mapeadas if fonte.site_dominio not in ja_tentados]
    resolvida = _proxima_mapeada_capaz(candidatas_mapeadas, versao)
    if resolvida is not None:
        return resolvida

    # Fallback de job em andamento roda no worker, sem acesso a `integrations/`
    # (fronteira de Clean Architecture, CLAUDE.md §1) — a descoberta ao vivo aqui
    # valida só contra o título cadastrado, nunca os títulos canônicos do
    # provedor; `resolver_fonte_do_anime` (chamado da API) é quem recebe a lista
    # completa via `titulos_alternativos`.
    referencias = [anime.titulo]

    dominios_ja_conhecidos = {fonte.site_dominio for fonte in mapeadas} | ja_tentados
    for indice, extrator in enumerate(EXTRATORES):
        if extrator.dominio in dominios_ja_conhecidos:
            continue
        if await circuit_breaker.esta_em_cooldown(sessionmaker, extrator.dominio):
            continue

        candidatos = await _buscar_variantes(sessionmaker, extrator, referencias)
        if not candidatos:
            continue

        if extrator.diferencia_versao and versao != VersaoEpisodio.DESCONHECIDA:
            resultado = await _resolver_no_site_que_diferencia(
                sessionmaker, anime, referencias, extrator, indice, candidatos, versao
            )
            if isinstance(resultado, FonteResolvida):
                return resultado
            continue  # ConfirmacaoNecessaria ou partição vazia: sem quem confirme, pula

        escolhido = _desambiguar(referencias, candidatos)
        if escolhido is None:
            continue

        versao_de_fonte = _versao_de_fonte_do_candidato_generico(extrator, escolhido)
        await _gravar_fonte_anime(
            sessionmaker,
            anime.id,
            extrator.dominio,
            escolhido.identificador,
            versao_de_fonte,
            prioridade=indice,
        )
        return FonteResolvida(
            dominio=extrator.dominio,
            identificador=escolhido.identificador,
            versao_da_fonte=versao_de_fonte,
        )

    return None


def _variantes_das_referencias(referencias: list[str]) -> list[str]:
    """Escada de busca combinada de TODOS os nomes do anime
    (`extractors/busca/termos.py::escada_combinada`: por degrau — títulos
    completos, depois cortes, depois prefixos), referências na ordem da lista
    (digitado, romaji, inglês, nativo, sinônimos), deduplicando por
    `core/texto.py::slugificar` e preservando a primeira ocorrência.

    Espelha `api/servicos/busca.py::_termos_de_busca` (que `extractors/` não
    pode importar — fronteira de `integrations/`). A posição 0 CRUA de cada
    referência sobrevive ao dedup: `_referencias_de_anime` já entrega a lista
    slug-única, então a raw-0 de uma referência nunca colide com a raw-0 de
    outra — só variantes DERIVADAS (cortes de subtítulo, prefixos) se sobrepõem
    entre referências e são as únicas descartadas aqui.

    Com `referencias == [anime.titulo]` (caminho sem canônico) o resultado é
    `variantes_de_busca(anime.titulo)` inalterado."""
    return escada_combinada(referencias)


async def _buscar_variantes(
    sessionmaker: _SessionMaker, extrator: ExtratorDeSite, referencias: list[str]
) -> list[ResultadoBusca]:
    """Tenta cada variante da escada combinada de todos os nomes do anime
    (`_variantes_das_referencias`), na ordem, e para na primeira que devolver
    candidatos que correspondem a ALGUMA referência
    (`extractors/busca/correspondencia.py::corresponde_a_alguma_referencia`),
    não qualquer candidato — o bloco de recall de `variantes_de_busca` sonda por
    prefixo curto (1ª palavra), então uma variante devolve cards de outros
    animes que só compartilham o prefixo; sem o filtro,
    `_desambiguar`/`_desambiguar_por_versao` receberia esse pool largo e cairia
    em `None` (slug exato não único) → `ConfirmacaoNecessaria`/site pulado com
    muito mais frequência.

    `referencias` tem `anime.titulo` na posição 0; quando é a lista completa
    (resolução canônica upfront em `api/servicos/fontes.py`), a escada varre
    também o título inglês/romaji, alcançando o site que indexa o anime só nesse
    idioma, e a validação aceita o card grafado em qualquer um dos nomes.

    Corrige também a assimetria em que só o AnimeFire tratava subtítulo
    internamente (na busca) e o AnimesDrive nunca via variante nenhuma.

    Exceção de `resiliencia.chamar` propaga direto, igual ao comportamento
    anterior de variante única — este helper não introduz um novo modo de
    falha, só mais tentativas antes de desistir (não confundir com
    `extractors/busca/servico.py::buscar_em_com_variantes`, que captura
    `FalhaDeExtracao` e devolve `indisponivel`; aqui a exceção sobe de
    propósito)."""
    async for _variante, resposta in buscar_variantes_em_janelas(
        sessionmaker, extrator, _variantes_das_referencias(referencias)
    ):
        if isinstance(resposta, BaseException):
            raise resposta
        candidatos = resposta
        validos = [
            c
            for c in candidatos
            if corresponde_a_alguma_referencia(referencias, c.titulo_exibicao)
        ]
        if validos:
            return validos
    return []


def _resolver_em_mapeadas(
    mapeadas: list[FonteAnime], versao_confirmada: VersaoDeFonte
) -> FonteResolvida | None:
    """Percorre os sites já mapeados e devolve a fonte capaz de servir
    `versao_confirmada`: uma linha CONFIRMADA da versão pedida OU uma
    `NAO_DIFERENCIADA` (site não separa, mas pode servir qualquer versão),
    QUALQUER site mapeado. Entre as capazes, a mais RECENTEMENTE confirmada
    (`resolvido_em`) vence sempre — nunca a de maior prioridade fixa de site
    (`mapeadas` ainda vem ordenada por `FonteAnime.prioridade` — usado por
    `_proxima_mapeada_capaz`/`proximo_site_para` para fallback determinístico
    quando não há capaz nenhuma) nem a mais "exata" (bug corrigido: recência
    tem que valer entre TODAS as capazes, não só como desempate dentro da
    mesma exatidão — antes, uma linha CONFIRMADA da versão pedida sempre
    vencia uma `NAO_DIFERENCIADA` mesmo quando esta era a escolha mais
    recente do usuário via "Trocar fonte": clicar num site que não diferencia
    versão — ex. AnimeFire — ficava sem efeito prático, a resolução
    continuava caindo numa fonte CONFIRMADA antiga de outro domínio, tipo
    AnimesDrive, e o usuário via a troca "não pegar". Prioridade de site já
    tinha perdido essa disputa antes — ver histórico desta função —
    exatidão de versão não pode ser a próxima a se sobrepor à mesma decisão
    manual e recente). Empate de `resolvido_em` (`max` sobre a lista) cai para
    a ordem de prioridade de site preservada em `mapeadas` — raro depois da
    correção do sentinel de `bump_recencia=False` (duas confirmações reais no
    mesmo instante são improváveis; duas escritas oportunistas de buscas
    diferentes colidindo no mesmo sentinel fixo, ainda possível), mas não
    eliminado."""
    capazes = [
        f for f in mapeadas if f.versao in (versao_confirmada, VersaoDeFonte.NAO_DIFERENCIADA)
    ]
    if not capazes:
        return None
    mais_recente = max(capazes, key=lambda f: f.resolvido_em)
    return _fonte_resolvida_de(mais_recente, versao_confirmada)


def _fonte_resolvida_de(linha: FonteAnime, versao_confirmada: VersaoDeFonte) -> FonteResolvida:
    versao_da_fonte = (
        versao_confirmada
        if linha.versao == versao_confirmada
        else VersaoDeFonte.NAO_DIFERENCIADA
    )
    return FonteResolvida(
        dominio=linha.site_dominio,
        identificador=linha.identificador_no_site,
        versao_da_fonte=versao_da_fonte,
    )


async def fontes_mapeadas_alternativas(
    sessionmaker: _SessionMaker, anime: Anime, versao: VersaoEpisodio, *, excluir_dominio: str
) -> list[FonteResolvida]:
    """Demais fontes JÁ MAPEADAS capazes de servir `versao` (mesma regra de
    `_resolver_em_mapeadas`), uma por domínio, da mais recente para a mais antiga,
    sem `excluir_dominio`. Sem rede: só lê `FonteAnime`. Serve de fallback quando a
    fonte escolhida está fora do ar ou bloqueada (ex. Cloudflare rejeitando a
    sessão) mas o anime também está mapeado em outro site."""
    versao_confirmada = _MAPA_VERSAO_EPISODIO_PARA_FONTE[versao]
    mapeadas = await _fontes_mapeadas_ordenadas(sessionmaker, anime.id)
    capazes = sorted(
        (
            f
            for f in mapeadas
            if f.site_dominio != excluir_dominio
            and f.versao in (versao_confirmada, VersaoDeFonte.NAO_DIFERENCIADA)
        ),
        key=lambda f: f.resolvido_em,
        reverse=True,
    )
    por_dominio = {}
    for linha in capazes:
        por_dominio.setdefault(linha.site_dominio, linha)
    return [_fonte_resolvida_de(linha, versao_confirmada) for linha in por_dominio.values()]


def _proxima_mapeada_capaz(
    mapeadas: list[FonteAnime], versao: VersaoEpisodio
) -> FonteResolvida | None:
    """Variante de `_resolver_em_mapeadas` usada por `proximo_site_para`,
    tolerante a `VersaoEpisodio.DESCONHECIDA` (sem versão pedida de verdade a
    preservar): nesse caso usa a 1ª fonte mapeada disponível, na ordem de
    prioridade, sem checar capacidade de versão (comportamento anterior a
    esta fase)."""
    if versao == VersaoEpisodio.DESCONHECIDA:
        if not mapeadas:
            return None
        primeira = mapeadas[0]
        return FonteResolvida(
            dominio=primeira.site_dominio,
            identificador=primeira.identificador_no_site,
            versao_da_fonte=primeira.versao,
        )
    return _resolver_em_mapeadas(mapeadas, _MAPA_VERSAO_EPISODIO_PARA_FONTE[versao])


async def _resolver_no_site_que_diferencia(
    sessionmaker: _SessionMaker,
    anime: Anime,
    referencias: list[str],
    extrator: ExtratorDeSite,
    indice: int,
    candidatos: list[ResultadoBusca],
    versao_pedida: VersaoEpisodio,
) -> FonteResolvida | ConfirmacaoNecessaria | None:
    """`None` = partição da versão pedida veio vazia neste site (site não tem
    essa versão) — o chamador decide se continua pro próximo site.

    `referencias` = todos os nomes do anime (título cadastrado na posição 0),
    threaded até `_desambiguar_por_versao`."""
    por_versao: dict[VersaoEpisodio, list[ResultadoBusca]] = {}
    for candidato in candidatos:
        if candidato.versao is not None:
            por_versao.setdefault(candidato.versao, []).append(candidato)

    particao_pedida = por_versao.get(versao_pedida, [])
    if not particao_pedida:
        return None

    escolhido = _desambiguar_por_versao(referencias, particao_pedida)
    if escolhido is None:
        return ConfirmacaoNecessaria(dominio=extrator.dominio, candidatos=particao_pedida)

    versao_confirmada = _MAPA_VERSAO_EPISODIO_PARA_FONTE[versao_pedida]
    await _gravar_fonte_anime(
        sessionmaker,
        anime.id,
        extrator.dominio,
        escolhido.identificador,
        versao_confirmada,
        prioridade=indice,
    )

    # Dado grátis: a outra versão veio na mesma busca — se ela também
    # desambigua sem ambiguidade, persiste também, sem custo de rede extra.
    # Ambiguidade na outra partição não bloqueia nada, só não persiste.
    outra_versao = (
        VersaoEpisodio.DUBLADO if versao_pedida == VersaoEpisodio.LEGENDADO
        else VersaoEpisodio.LEGENDADO
    )
    particao_outra = por_versao.get(outra_versao, [])
    if particao_outra:
        escolhido_outra = _desambiguar_por_versao(referencias, particao_outra)
        if escolhido_outra is not None:
            # `bump_recencia=False`: isto é cache oportunista ("dado grátis"),
            # não uma confirmação — se `outra_versao` já tinha uma linha
            # mapeada neste domínio (o usuário confirmou este site pra essa
            # versão antes e já trocou pra outro desde então), tocar nela só
            # porque a busca da versão PEDIDA passou por aqui não pode
            # reviver essa fonte antiga como "mais recente" em
            # `_resolver_em_mapeadas` — sem isto, resolver a versão PEDIDA
            # (ex. dublado) podia silenciosamente desfazer uma troca de
            # fonte manual anterior da OUTRA versão (ex. legendado). Mesma
            # proteção vale quando a linha é NOVA (domínio nunca mapeado
            # nesta versão): `_gravar_fonte_anime` grava um `resolvido_em`
            # sentinel (`_RESOLVIDO_EM_OPORTUNISTA`), nunca `datetime.now(UTC)`
            # — senão esta escrita "de graça" venceria, em `_resolver_em_mapeadas`,
            # uma confirmação manual genuína feita antes noutro domínio.
            await _gravar_fonte_anime(
                sessionmaker,
                anime.id,
                extrator.dominio,
                escolhido_outra.identificador,
                _MAPA_VERSAO_EPISODIO_PARA_FONTE[outra_versao],
                prioridade=indice,
                bump_recencia=False,
            )

    return FonteResolvida(
        dominio=extrator.dominio,
        identificador=escolhido.identificador,
        versao_da_fonte=versao_confirmada,
    )


async def _resolver_no_site_nao_diferenciado(
    sessionmaker: _SessionMaker,
    anime: Anime,
    referencias: list[str],
    extrator: ExtratorDeSite,
    indice: int,
    candidatos: list[ResultadoBusca],
) -> FonteResolvida | ConfirmacaoNecessaria:
    """Comportamento idêntico ao de antes desta fase — sem particionamento por
    versão, fonte gravada sempre como `NAO_DIFERENCIADA`.

    `referencias` = todos os nomes do anime (título cadastrado na posição 0),
    threaded até `_desambiguar`."""
    escolhido = _desambiguar(referencias, candidatos)
    if escolhido is None:
        return ConfirmacaoNecessaria(dominio=extrator.dominio, candidatos=candidatos)

    await _gravar_fonte_anime(
        sessionmaker,
        anime.id,
        extrator.dominio,
        escolhido.identificador,
        VersaoDeFonte.NAO_DIFERENCIADA,
        prioridade=indice,
    )
    return FonteResolvida(
        dominio=extrator.dominio,
        identificador=escolhido.identificador,
        versao_da_fonte=VersaoDeFonte.NAO_DIFERENCIADA,
    )


def _versao_de_fonte_do_candidato_generico(
    extrator: ExtratorDeSite, candidato: ResultadoBusca
) -> VersaoDeFonte:
    """Usada só pelo ramo "sem versão pedida de verdade" de `proximo_site_para`
    (`_proxima_mapeada_capaz`/descoberta ao vivo com `versao=DESCONHECIDA`):
    site que não diferencia, ou candidato sem marcador detectado mesmo em site
    que diferencia, grava como `NAO_DIFERENCIADA` — nunca assume confirmação
    que não foi pedida."""
    if not extrator.diferencia_versao or candidato.versao is None:
        return VersaoDeFonte.NAO_DIFERENCIADA
    return _MAPA_VERSAO_EPISODIO_PARA_FONTE[candidato.versao]


def _desambiguar(
    referencias: list[str], candidatos: list[ResultadoBusca]
) -> ResultadoBusca | None:
    """Desambiguação ESTRITA: um candidato só é auto-escolhido se o slug do seu
    `titulo_exibicao` bate por IGUALDADE (não contenção de prefixo) o slug de
    alguma referência, e se ele é o ÚNICO nesse caso — mais de um match devolve
    `None` (→ `ConfirmacaoNecessaria`/site pulado), preservando a semântica de
    "match único" de antes.

    Estrita de propósito: `corresponde_a_alguma_referencia` (contenção de
    prefixo + tolerância a grafia colada) já filtrou o pool em
    `_buscar_variantes`; aqui, onde o veredito decide qual card baixar,
    afrouxar para prefixo faria um card que só COMEÇA como o anime ser
    escolhido sozinho. Com `referencias == [anime.titulo]` (sem canônico) o
    conjunto tem um slug só e o teste vira a igualdade exata de antes."""
    if len(candidatos) == 1:
        return candidatos[0]

    slugs_referencia = {slugificar(referencia) for referencia in referencias}
    correspondentes = [
        candidato
        for candidato in candidatos
        if slugificar(candidato.titulo_exibicao) in slugs_referencia
    ]
    return correspondentes[0] if len(correspondentes) == 1 else None


def _desambiguar_por_versao(
    referencias: list[str], candidatos: list[ResultadoBusca]
) -> ResultadoBusca | None:
    """Mesma lógica de `_desambiguar` (desambiguação ESTRITA por igualdade de
    slug — ver a docstring de lá), mas compara o slug do candidato SEM o
    marcador de versão (ex. "Nome Dublado" -> "Nome") contra o slug de cada
    referência (todos os nomes do anime) — os candidatos aqui já vêm de uma
    partição por versão de um site que diferencia, então título/slug do
    candidato costuma carregar o marcador que o título do anime cadastrado não
    tem.

    Remove o marcador do `identificador` (slug), não do `titulo_exibicao`: o
    título de exibição varia de formatação por site — AnimeFire envolve o
    marcador em parênteses ("Nome (Dublado)"), fora da fronteira de token
    `-`/espaço que `remover_marcador_de_versao` exige, então nunca seria
    removido do título e o slug resultante nunca bateria com referência
    nenhuma. O identificador já é slug (hifens), onde o marcador sempre está
    isolado por `-`/início/fim — mesma convenção nos dois sites hoje."""
    if len(candidatos) == 1:
        return candidatos[0]

    slugs_referencia = {slugificar(referencia) for referencia in referencias}
    correspondentes = [
        candidato
        for candidato in candidatos
        if slugificar(remover_marcador_de_versao(candidato.identificador)) in slugs_referencia
    ]
    return correspondentes[0] if len(correspondentes) == 1 else None


async def _fontes_mapeadas_ordenadas(
    sessionmaker: _SessionMaker, anime_id: int
) -> list[FonteAnime]:
    async with sessionmaker() as sessao:
        resultado = await sessao.execute(
            select(FonteAnime)
            .where(FonteAnime.anime_id == anime_id)
            .order_by(FonteAnime.prioridade)
        )
        return list(resultado.scalars())


async def confirmar_fonte(
    sessionmaker: _SessionMaker, anime: Anime, dominio: str, candidato: ResultadoBusca
) -> FonteResolvida:
    """Grava a escolha manual de um candidato de `ConfirmacaoNecessaria` — usado por
    `scripts/resolver_fonte.py`, que desempata via `input()` na ausência de API.

    `versao_da_fonte` gravada é derivada de `candidato.versao` (presente
    quando veio da partição de um site que diferencia versão — a mesma
    `ConfirmacaoNecessaria` que `resolver_fonte_do_anime` devolve já é
    restrita a uma única partição/versão, nunca mistura as duas) — na
    ausência de marcador (site que não diferencia), `NAO_DIFERENCIADA`.
    """
    prioridade = next(
        (indice for indice, extrator in enumerate(EXTRATORES) if extrator.dominio == dominio), 0
    )
    versao_da_fonte = (
        _MAPA_VERSAO_EPISODIO_PARA_FONTE[candidato.versao]
        if candidato.versao is not None
        else VersaoDeFonte.NAO_DIFERENCIADA
    )
    await _gravar_fonte_anime(
        sessionmaker,
        anime.id,
        dominio,
        candidato.identificador,
        versao_da_fonte,
        prioridade=prioridade,
    )
    return FonteResolvida(
        dominio=dominio, identificador=candidato.identificador, versao_da_fonte=versao_da_fonte
    )


# Sentinel de `resolvido_em` para a escrita "de graça" (`bump_recencia=False`)
# quando a linha é NOVA — a coluna é `nullable=False` (`models/fonte_anime.py`),
# então precisa de um valor explícito, mas nunca `datetime.now(UTC)`: isso
# tornaria a escrita oportunista indistinguível de uma confirmação real em
# `_resolver_em_mapeadas` (`max(capazes, key=resolvido_em)`), deixando-a vencer
# uma fonte já confirmada manualmente em outro domínio. Data mínima
# representável — nunca vence um `resolvido_em` genuíno, mas ainda deixa a
# linha elegível quando é a ÚNICA fonte capaz daquela versão.
_RESOLVIDO_EM_OPORTUNISTA: Final[datetime] = datetime.min.replace(tzinfo=UTC)


async def _gravar_fonte_anime(
    sessionmaker: _SessionMaker,
    anime_id: int,
    dominio: str,
    identificador: str,
    versao: VersaoDeFonte,
    *,
    prioridade: int,
    bump_recencia: bool = True,
) -> None:
    async with sessionmaker() as sessao:
        existente = await sessao.get(FonteAnime, (anime_id, dominio, versao))
        if existente is None:
            # `resolvido_em` explícito nos dois casos (coluna sem default
            # aproveitável aqui, ver `_RESOLVIDO_EM_OPORTUNISTA` acima): uma
            # gravação real (`bump_recencia=True`, o padrão) grava
            # `datetime.now(UTC)`, igual à reconfirmação abaixo; a escrita "de
            # graça" da OUTRA versão em `_resolver_no_site_que_diferencia`
            # (`bump_recencia=False`) grava o sentinel — bug corrigido: antes
            # caía no `default=now()` do model por omissão, tornando uma
            # linha nunca escolhida pelo usuário capaz de vencer, em
            # `_resolver_em_mapeadas`, uma fonte confirmada manualmente antes
            # noutro domínio.
            sessao.add(
                FonteAnime(
                    anime_id=anime_id,
                    site_dominio=dominio,
                    versao=versao,
                    identificador_no_site=identificador,
                    prioridade=prioridade,
                    resolvido_em=(
                        datetime.now(UTC) if bump_recencia else _RESOLVIDO_EM_OPORTUNISTA
                    ),
                )
            )
            try:
                await sessao.commit()
                return
            except IntegrityError:
                # Corrida: duas chamadas concorrentes pra este mesmo (anime_id,
                # dominio, versao) — ex. o frontend disparando `episodios-
                # remotos` duas vezes quase junto (StrictMode/efeito duplicado)
                # — os dois `get` acima rodaram antes de qualquer `commit`, os
                # dois viram `None`, e só um `INSERT` vence a constraint
                # única. Sem isto o perdedor derrubava a request com 500 em
                # vez de reconfirmar como o ramo `else` abaixo já faz — mesmo
                # padrão de `db/catalogo.py::obter_ou_criar_anime_id`.
                await sessao.rollback()
                existente = await sessao.get(FonteAnime, (anime_id, dominio, versao))
                if existente is None:
                    raise
        existente.identificador_no_site = identificador
        existente.prioridade = prioridade
        # Reconfirmar um domínio já mapeado (ex.: "Trocar fonte" de volta
        # pra um site usado antes) também é uma escolha manual do
        # usuário agora — sem bumpar `resolvido_em`, `_resolver_em_mapeadas`
        # continuaria preferindo outro domínio só por ter sido tocado
        # mais recentemente por acaso, não por decisão do usuário.
        # `bump_recencia=False` (só usado pela escrita "de graça" da
        # OUTRA versão em `_resolver_no_site_que_diferencia`): a linha já
        # existia com um `resolvido_em` de antes (real ou sentinel) — não
        # tocar nele preserva o que já estava lá, seja uma confirmação
        # genuína anterior, seja um sentinel de uma escrita oportunista
        # anterior. Ver comentário no call site.
        if bump_recencia:
            existente.resolvido_em = datetime.now(UTC)
        await sessao.commit()

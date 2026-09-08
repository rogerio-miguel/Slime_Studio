"""Criação de job nos dois modos (`local`, `site` — ESPECIFICACAO.md §5, Passo 4
do plano da Fase 3). Cancelamento/retry não têm serviço próprio: são uma
chamada só para `db/fila.py` (que já concentra toda a regra de verdade), então
`api/rotas/jobs.py` chama `db.fila` direto — "não criar serviço pass-through".

Não importa `fastapi`: devolve o `job_id` ou levanta erro de `core/erros.py`;
`api/rotas/jobs.py` traduz para `HTTPException`/schemas.
"""

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.servicos.catalogo import job_ativo_do_episodio, remover_arquivos_do_episodio
from core.config import Config
from core.enums import SITE_LOCAL, StatusEpisodio, TipoEpisodio, VersaoDeFonte, VersaoEpisodio
from core.erros import (
    ErroSlimeStudio,
    FalhaDeExtracao,
    FonteAmbigua,
    FonteNaoEncontrada,
    JobEmExecucao,
    VersaoIndisponivelError,
)
from db import catalogo
from db.fila import criar_job as criar_job_na_fila
from extractors.resolucao import ConfirmacaoNecessaria, VersaoIndisponivel, resolver_fonte_do_anime
from extractors.servico import filtrar_por_numero_e_versao, listar_episodios_em
from models.anime import Anime
from models.episodio import Episodio

_SessionMaker = async_sessionmaker[AsyncSession]

logger = logging.getLogger(__name__)

# Teto para a etapa de rede da criação de job em modo "site" (resolver fonte +
# listar episódios) — mesma filosofia de
# `extractors/servico.py::_TETO_ESPERA_CONFERENCIA_S`: rede de segurança acima
# dos timeouts internos dos extratores, não a primeira linha de defesa.
_TETO_CRIACAO_SITE_S = 60


async def criar_job_local(
    sessionmaker: _SessionMaker,
    *,
    anime: str,
    numero: int,
    tipo: TipoEpisodio,
    versao: VersaoEpisodio,
    caminho_local: str,
    titulo_episodio: str | None,
    ano: int | None,
    duracao_esperada_s: int | None,
) -> int:
    anime_id = await catalogo.obter_ou_criar_anime_id(sessionmaker, anime, ano)
    return await catalogo.criar_episodio_e_job(
        sessionmaker,
        anime_id,
        numero=numero,
        tipo=tipo,
        versao=versao,
        url_fonte=caminho_local,
        site_origem=SITE_LOCAL,
        titulo_episodio=titulo_episodio,
        duracao_esperada_s=duracao_esperada_s,
    )


async def criar_job_site(
    sessionmaker: _SessionMaker,
    config: Config,
    *,
    anime: Anime,
    numero: int,
    tipo: TipoEpisodio,
    versao: VersaoEpisodio,
    duracao_esperada_s: int | None,
) -> int:
    """`anime` já carregado por quem chama (`api/rotas/jobs.py`, que faz o 404 de
    `anime_id` inexistente antes de chegar aqui — mesmo padrão das outras rotas
    que operam por id).

    `ConfirmacaoNecessaria` (mais de um candidato, sem match exato de título)
    vira `FonteAmbigua`; nenhum job é criado nesse caso — o cliente resolve via
    `POST /api/admin/animes/{id}/fontes/confirmar` e reenvia esta chamada.

    `VersaoIndisponivel` (nenhum site serve `versao`) vira `VersaoIndisponivelError`
    — sem tratamento HTTP dedicado ainda (fase seguinte), propaga em vez de
    falhar silenciosamente tratando o resultado como `FonteResolvida`.

    Invariante: `Episodio.versao` (abaixo) NUNCA vem de `versao` (o pedido do
    cliente) direto — deriva de `resultado.versao_da_fonte`, a única fonte de
    verdade sobre o que a fonte resolvida realmente é.

    Ponto único de recaptura (D2): se já existe um `Episodio` para a
    identidade resolvida (`anime.id`, `numero`, `tipo`, `versao_do_episodio`)
    e ele está `LIBERADO` (Feature 1) ou foi capturado numa fonte diferente
    da resolvida agora, a linha é reaproveitada (`_reaproveitar_episodio_
    para_recaptura`) em vez de bater em `uq_episodio_identidade` e propagar
    `EpisodioJaExiste` — ver ESPECIFICACAO.md/plano da feature "continuar
    assistindo"/"liberar arquivo". Fora desses dois casos (ex.: já `PRONTO`
    na mesma fonte), o comportamento de sempre continua valendo: o insert
    abaixo bate no unique index e `db/catalogo.py::_inserir_episodio` propaga
    `EpisodioJaExiste`.
    """
    try:
        # `titulos_alternativos` fica no default (`None`): a captura NÃO resolve
        # o título canônico. `resolver_fonte_do_anime` consulta as `FonteAnime`
        # já mapeadas primeiro e os helpers `_resolver_no_site_*` persistem a
        # fonte resolvida — no fluxo normal a página do anime
        # (`api/servicos/fontes.py::listar_episodios_remotos`, que resolve o
        # canônico) roda antes e grava o site, então a captura cai em
        # `_resolver_em_mapeadas` e reusa o mapeamento.
        resultado = await asyncio.wait_for(
            resolver_fonte_do_anime(sessionmaker, anime, versao), timeout=_TETO_CRIACAO_SITE_S
        )
    except TimeoutError as excecao:
        raise FalhaDeExtracao(
            f"resolução de fonte excedeu o teto de {_TETO_CRIACAO_SITE_S}s",
            permite_retentativa=True,
        ) from excecao
    if isinstance(resultado, ConfirmacaoNecessaria):
        raise FonteAmbigua(
            resultado.dominio,
            [
                {
                    "titulo_exibicao": candidato.titulo_exibicao,
                    "identificador": candidato.identificador,
                    "url": candidato.url,
                    "versao": candidato.versao.value if candidato.versao else None,
                }
                for candidato in resultado.candidatos
            ],
        )
    if isinstance(resultado, VersaoIndisponivel):
        raise VersaoIndisponivelError(resultado.versao)

    try:
        episodios_remotos = await asyncio.wait_for(
            listar_episodios_em(
                sessionmaker,
                resultado.dominio,
                resultado.identificador,
                anime.numero_temporada,
            ),
            timeout=_TETO_CRIACAO_SITE_S,
        )
    except TimeoutError as excecao:
        raise FalhaDeExtracao(
            f"listagem de episódios excedeu o teto de {_TETO_CRIACAO_SITE_S}s",
            dominio=resultado.dominio,
            permite_retentativa=True,
        ) from excecao

    # O adapter já devolveu a temporada de `anime.numero_temporada` numerada de
    # 1 (contrato de `ExtratorDeSite.listar_episodios`), então `ep.numero` casa
    # com `numero` (o pedido do cliente) e com `Episodio.numero` — mesmo caminho
    # de `api/servicos/fontes.py::listar_episodios_remotos`.

    # `Episodio.versao` deriva do que a fonte resolvida realmente é
    # (`resultado.versao_da_fonte`), nunca do `versao` pedido pelo cliente —
    # a invariante desta fase. Também usado para filtrar a listagem abaixo:
    # sem isso, um site que lista episódios das duas versões (mesmo risco de
    # `extractors/servico.py::_proximo_com_episodio`) poderia gravar a URL da
    # versão errada sob o rótulo certo.
    versao_do_episodio = versao_episodio_da_fonte(resultado.versao_da_fonte)

    correspondentes = filtrar_por_numero_e_versao(episodios_remotos, numero, versao_do_episodio)
    if len(correspondentes) > 1:
        # Mais de um rótulo remoto mapeia pro mesmo `numero` (ex. "7"/"07" —
        # extractors/base.py::EpisodioRemoto) — o request só carrega `numero`
        # (int), sem como o cliente escolher o rótulo. Escolha determinística
        # (1ª ocorrência, ordem já estável do adapter) em vez de silenciosa —
        # nunca some do log.
        logger.warning(
            "%d episódios remotos com numero=%d em %r (rótulos: %s) — usando o 1º",
            len(correspondentes),
            numero,
            resultado.dominio,
            [ep.rotulo for ep in correspondentes],
        )
    correspondente = correspondentes[0] if correspondentes else None
    if correspondente is None:
        raise FonteNaoEncontrada(
            f"episódio {numero} não encontrado em {resultado.dominio} para {anime.titulo!r}",
            dominio=resultado.dominio,
        )

    # `numero_fonte` guarda "o número original como o site mostrou"
    # (ESPECIFICACAO.md §4, auditoria/debug) — é o `rotulo` cru do adapter, que
    # nunca é reescrito pelo recorte de temporada (`EpisodioRemoto`). `None`
    # quando o rótulo não é puramente numérico (ex. "07" continua virando 7).
    try:
        numero_na_fonte = int(correspondente.rotulo)
    except ValueError:
        numero_na_fonte = None

    episodio_existente = await _localizar_episodio_por_identidade(
        sessionmaker, anime.id, numero, tipo, versao_do_episodio
    )
    if episodio_existente is not None and (
        episodio_existente.status == StatusEpisodio.LIBERADO
        or episodio_existente.site_origem != resultado.dominio
    ):
        return await _reaproveitar_episodio_para_recaptura(
            sessionmaker,
            config,
            anime.slug,
            episodio_existente.id,
            url_fonte=correspondente.url,
            site_origem=resultado.dominio,
            numero_fonte=numero_na_fonte,
            capa_path=correspondente.thumb_url,
            duracao_esperada_s=duracao_esperada_s,
        )

    return await catalogo.criar_episodio_e_job(
        sessionmaker,
        anime.id,
        numero=numero,
        tipo=tipo,
        versao=versao_do_episodio,
        url_fonte=correspondente.url,
        site_origem=resultado.dominio,
        capa_path=correspondente.thumb_url,
        duracao_esperada_s=duracao_esperada_s,
    )


async def _localizar_episodio_por_identidade(
    sessionmaker: _SessionMaker,
    anime_id: int,
    numero: int,
    tipo: TipoEpisodio,
    versao: VersaoEpisodio,
) -> Episodio | None:
    async with sessionmaker() as sessao:
        resultado = await sessao.execute(
            select(Episodio).where(
                Episodio.anime_id == anime_id,
                Episodio.numero == numero,
                Episodio.tipo == tipo,
                Episodio.versao == versao,
            )
        )
        return resultado.scalar_one_or_none()


async def _reaproveitar_episodio_para_recaptura(
    sessionmaker: _SessionMaker,
    config: Config,
    anime_slug: str,
    episodio_id: int,
    *,
    url_fonte: str,
    site_origem: str,
    numero_fonte: int | None,
    capa_path: str | None,
    duracao_esperada_s: int | None,
) -> int:
    """D2 — episódio já cadastrado sob a mesma identidade, `LIBERADO` (Feature
    1) ou capturado numa fonte diferente da resolvida agora: reaproveita a
    linha em vez de bater em `uq_episodio_identidade`. Apaga os arquivos da
    captura anterior (`remover_arquivos_do_episodio`, best-effort), zera os
    campos de mídia e volta o episódio para `PENDENTE`; `assistido_em`
    sobrevive (indicador de "já assistido" não reinicia numa recaptura), mas
    `progresso_s`/`progresso_atualizado_em` NÃO sobrevivem — o arquivo novo
    pode vir de outra fonte/duração, uma posição de retomada antiga não tem
    relação nenhuma com ele (senão o episódio reapareceria em "continuar
    assistindo" numa posição sem sentido).

    `capa_path` (thumb da fonte) só é gravada quando não-nula — mesma semântica
    de `db/catalogo.py::_aplicar_lancamento_no_anime` para `total_episodios`:
    uma recaptura numa fonte que não expõe thumb não apaga a que já havia.

    Levanta `JobEmExecucao` se já existir um `Job` ativo para este episódio —
    mesma checagem/motivo de `api/servicos/catalogo.py::remover_episodio`/
    `liberar_episodio` (`job_ativo_do_episodio`): sem isto, um duplo clique em
    "Recapturar" apagaria arquivos que um worker já está escrevendo e criaria
    um segundo `Job` para o mesmo episódio.

    Duas transações curtas (mesma filosofia de sessão-por-operação de
    `db/catalogo.py::criar_episodio_e_job`): atualizar o `Episodio`, depois
    criar o `Job`."""
    async with sessionmaker() as sessao:
        episodio = await sessao.get(Episodio, episodio_id)
        if episodio is None:
            raise ErroSlimeStudio(f"episódio {episodio_id} desapareceu antes da recaptura")

        job_ativo_id = await job_ativo_do_episodio(sessao, episodio_id)
        if job_ativo_id is not None:
            raise JobEmExecucao(job_ativo_id)

        remover_arquivos_do_episodio(config, anime_slug, episodio)
        episodio.hls_path = None
        episodio.tamanho_bytes = None
        episodio.renditions_disponiveis = None
        episodio.progresso_s = None
        episodio.progresso_atualizado_em = None
        episodio.status = StatusEpisodio.PENDENTE
        episodio.url_fonte = url_fonte
        episodio.site_origem = site_origem
        episodio.numero_fonte = numero_fonte
        if capa_path is not None:
            episodio.capa_path = capa_path
        await sessao.commit()
    return await criar_job_na_fila(sessionmaker, episodio_id, duracao_esperada_s)


def versao_episodio_da_fonte(versao_da_fonte: VersaoDeFonte) -> VersaoEpisodio:
    """`VersaoDeFonte.NAO_DIFERENCIADA` vira sempre `VersaoEpisodio.DESCONHECIDA`
    — nunca herda o que o cliente pediu. `LEGENDADO`/`DUBLADO` convertem 1:1
    (mesmo valor de string por design, `core/enums.py`, mas enums separados
    de propósito — daí a conversão explícita em vez de reinterpretar um pelo
    outro).

    Pública (não `_`-prefixada) porque também é usada por
    `api/rotas/animes.py::obter_anime` para derivar
    `AnimeDetalheSaida.versao_confirmada_mais_recente`."""
    if versao_da_fonte == VersaoDeFonte.NAO_DIFERENCIADA:
        return VersaoEpisodio.DESCONHECIDA
    return VersaoEpisodio(versao_da_fonte.value)

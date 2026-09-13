"""Criação de job nos dois modos (`local`, `site` — ESPECIFICACAO.md §5, Passo 4
do plano da Fase 3). Cancelamento/retry não têm serviço próprio: são uma
chamada só para `db/fila.py` (que já concentra toda a regra de verdade), então
`api/rotas/jobs.py` chama `db.fila` direto — "não criar serviço pass-through".

Não importa `fastapi`: devolve o `job_id` ou levanta erro de `core/erros.py`;
`api/rotas/jobs.py` traduz para `HTTPException`/schemas.
"""

import logging
from collections import defaultdict
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.servicos.catalogo import job_ativo_do_episodio, remover_arquivos_do_episodio
from api.servicos.fontes import info_de_episodio, resolver_e_listar
from core.config import Config
from core.enums import SITE_LOCAL, StatusEpisodio, TipoEpisodio, VersaoDeFonte, VersaoEpisodio
from core.erros import (
    EpisodioJaExiste,
    ErroSlimeStudio,
    FonteNaoEncontrada,
    JobEmExecucao,
)
from db import catalogo
from db.fila import criar_job as criar_job_na_fila
from extractors.servico import filtrar_por_numero_e_versao, filtrar_por_versao
from models.anime import Anime
from models.episodio import Episodio

_SessionMaker = async_sessionmaker[AsyncSession]

logger = logging.getLogger(__name__)


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

    Resolução de fonte + listagem via `api/servicos/fontes.py::resolver_e_listar`
    (`resolver_canonico=False`: a captura conta que a página do anime já rodou
    antes e gravou a `FonteAnime` — ver a nota de módulo de lá). Ele traduz
    `ConfirmacaoNecessaria` -> `FonteAmbigua` (nenhum job é criado; o cliente
    resolve via `POST /api/admin/animes/{id}/fontes/confirmar` e reenvia) e
    `VersaoIndisponivel` -> `VersaoIndisponivelError`.

    Invariante: `Episodio.versao` (abaixo) NUNCA vem de `versao` (o pedido do
    cliente) direto — deriva de `fonte.versao_da_fonte`, a única fonte de
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
    fonte = await resolver_e_listar(sessionmaker, anime, versao, resolver_canonico=False)

    # O adapter já devolveu a temporada de `anime.numero_temporada` numerada de
    # 1 (contrato de `ExtratorDeSite.listar_episodios`), então `ep.numero` casa
    # com `numero` (o pedido do cliente) e com `Episodio.numero`.

    # `Episodio.versao` deriva do que a fonte resolvida realmente é
    # (`fonte.versao_da_fonte`), nunca do `versao` pedido pelo cliente — a
    # invariante desta fase. Também usado para filtrar a listagem abaixo: sem
    # isso, um site que lista episódios das duas versões (mesmo risco de
    # `extractors/servico.py::_proximo_com_episodio`) poderia gravar a URL da
    # versão errada sob o rótulo certo.
    versao_do_episodio = versao_episodio_da_fonte(fonte.versao_da_fonte)

    correspondentes = filtrar_por_numero_e_versao(fonte.episodios, numero, versao_do_episodio)
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
            fonte.dominio,
            [ep.rotulo for ep in correspondentes],
        )
    correspondente = correspondentes[0] if correspondentes else None
    if correspondente is None:
        raise FonteNaoEncontrada(
            f"episódio {numero} não encontrado em {fonte.dominio} para {anime.titulo!r}",
            dominio=fonte.dominio,
        )

    # `numero_fonte` guarda "o número original como o site mostrou"
    # (ESPECIFICACAO.md §4, auditoria/debug) — é o `rotulo` cru do adapter, que
    # nunca é reescrito pelo recorte de temporada (`EpisodioRemoto`). `None`
    # quando o rótulo não é puramente numérico (ex. "07" continua virando 7).
    try:
        numero_na_fonte = int(correspondente.rotulo)
    except ValueError:
        numero_na_fonte = None

    # `capa_path`/`titulo`/`sinopse` gravados no `Episodio` NUNCA vêm do
    # extractor (scraping não expõe nada disso) — pedido explícito do usuário
    # pra `capa_path`, mesma regra aplicada aos dois campos novos.
    # `info_de_episodio` busca a mesma info TMDB que a listagem de exibição já
    # sobrepõe (`api/servicos/fontes.py::_sobrepor_stills_de_episodios`);
    # best-effort, `None` quando o TMDB não acha — o frontend cai pra arte do
    # anime nesse caso (`PaginaDoAnime.jsx`), nunca pro thumb da fonte; título/
    # sinopse simplesmente ficam vazios.
    info = await info_de_episodio(sessionmaker, anime, numero)
    still = info.still_url if info else None

    episodio_existente = await _localizar_episodio_por_identidade(
        sessionmaker, anime.id, numero, tipo, versao_do_episodio
    )
    if episodio_existente is not None and (
        episodio_existente.status == StatusEpisodio.LIBERADO
        or episodio_existente.site_origem != fonte.dominio
    ):
        return await _reaproveitar_episodio_para_recaptura(
            sessionmaker,
            config,
            anime.slug,
            episodio_existente.id,
            url_fonte=correspondente.url,
            site_origem=fonte.dominio,
            numero_fonte=numero_na_fonte,
            capa_path=still,
            titulo=info.nome if info else None,
            sinopse=info.sinopse if info else None,
            duracao_esperada_s=duracao_esperada_s,
        )

    return await catalogo.criar_episodio_e_job(
        sessionmaker,
        anime.id,
        numero=numero,
        tipo=tipo,
        versao=versao_do_episodio,
        url_fonte=correspondente.url,
        site_origem=fonte.dominio,
        capa_path=still,
        titulo_episodio=info.nome if info else None,
        sinopse=info.sinopse if info else None,
        duracao_esperada_s=duracao_esperada_s,
    )


async def marcar_todos_assistidos(
    sessionmaker: _SessionMaker,
    *,
    anime: Anime,
    versao: VersaoEpisodio,
) -> None:
    """Botão "Marcar como assistido" da página do anime
    (`api/rotas/animes.py`). Dois passos:

    1. `UPDATE` em lote — marca `assistido_em` (agora) em todo `Episodio` já
       capturado localmente (qualquer fonte/versão) que ainda não tem a
       marca; mesma semântica de `POST /episodios/{id}/assistido`, aplicada
       em lote.
    2. Cria uma linha `LIBERADO` + `assistido_em` (`db/catalogo.py::
       criar_episodio_assistido`, sem `Job`) pra cada episódio `REGULAR` que
       a fonte remota ativa lista e que ainda não tem `Episodio` nenhum aqui
       — pedido explícito do usuário: o botão marca TODO episódio disponível
       na fonte como assistido, não só os já baixados. "Capturar"/
       "Recapturar" seguem disponíveis depois (`criar_job_site` acima já
       reaproveita `LIBERADO`).

    Mesma resolução de fonte de `criar_job_site` (`resolver_canonico=False`:
    a página do anime já resolveu/confirmou a `FonteAnime` antes de o botão
    ficar clicável) — pode levantar `FonteAmbigua`/`VersaoIndisponivelError`/
    `FalhaDeExtracao` pelos mesmos motivos de lá; nesse caso o passo 1 já
    comitou (nenhum episódio já capturado deixa de ser marcado), só o passo 2
    (criar os que faltam) não roda.

    Sem `info_de_episodio` aqui (ao contrário de `criar_job_site`): seria uma
    chamada ao TMDB por episódio faltante, e thumb/título/sinopse exibidos na
    página do anime já vêm de `remotos.dados` (`PaginaDoAnime.jsx`), não de
    `Episodio.capa_path`/`titulo`/`sinopse` — não há ganho visual que
    justifique o custo num "marcar todos" em lote.
    """
    async with sessionmaker() as sessao:
        locais = (
            await sessao.execute(select(Episodio).where(Episodio.anime_id == anime.id))
        ).scalars().all()
        await sessao.execute(
            update(Episodio)
            .where(Episodio.anime_id == anime.id, Episodio.assistido_em.is_(None))
            .values(assistido_em=datetime.now(UTC))
        )
        await sessao.commit()

    fonte = await resolver_e_listar(sessionmaker, anime, versao, resolver_canonico=False)
    versao_do_episodio = versao_episodio_da_fonte(fonte.versao_da_fonte)
    remotos_por_numero: dict[int, list] = defaultdict(list)
    for remoto in filtrar_por_versao(fonte.episodios, versao_do_episodio):
        if remoto.numero is not None:
            remotos_por_numero[remoto.numero].append(remoto)

    numeros_locais = {
        ep.numero
        for ep in locais
        if ep.tipo == TipoEpisodio.REGULAR and ep.versao == versao_do_episodio
    }
    for numero, candidatos in remotos_por_numero.items():
        if numero in numeros_locais:
            continue
        if len(candidatos) > 1:
            # Mesma escolha determinística de `criar_job_site` acima.
            logger.warning(
                "%d episódios remotos com numero=%d em %r (rótulos: %s) — usando o 1º",
                len(candidatos),
                numero,
                fonte.dominio,
                [ep.rotulo for ep in candidatos],
            )
        try:
            await catalogo.criar_episodio_assistido(
                sessionmaker,
                anime.id,
                numero=numero,
                tipo=TipoEpisodio.REGULAR,
                versao=versao_do_episodio,
                url_fonte=candidatos[0].url,
                site_origem=fonte.dominio,
            )
        except EpisodioJaExiste:
            # Corrida genuína (dois cliques quase simultâneos do botão) — a
            # checagem contra `numeros_locais` já é feita com os dados de
            # antes do passo 1, então uma criação concorrente aqui é o único
            # jeito de bater no índice único.
            continue


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
    titulo: str | None,
    sinopse: str | None,
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

    `capa_path`/`titulo`/`sinopse` (TMDB, ver `info_de_episodio`) só são
    gravados quando não-nulos — mesma semântica de `db/catalogo.py::
    _aplicar_lancamento_no_anime` para `total_episodios`: uma recaptura sem
    still/nome/sinopse (TMDB não achou) não apaga o que já havia.

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
        if titulo is not None:
            episodio.titulo = titulo
        if sinopse is not None:
            episodio.sinopse = sinopse
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

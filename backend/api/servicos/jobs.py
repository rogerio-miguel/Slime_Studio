"""Criação de job (modo `site` — ESPECIFICACAO.md §5, Passo 4 do plano da Fase 3;
o modo `local` só existe via `scripts/enfileirar_local.py`, não pela API).
Cancelamento/retry não têm serviço próprio: são uma chamada só para `db/fila.py`
(que já concentra toda a regra de verdade), então `api/rotas/jobs.py` chama
`db.fila` direto — "não criar serviço pass-through".

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
from core.enums import StatusEpisodio, TipoEpisodio, VersaoDeFonte, VersaoEpisodio
from core.erros import (
    EpisodioJaExiste,
    ErroSlimeStudio,
    FonteNaoEncontrada,
    JobEmExecucao,
)
from db import catalogo
from db.fila import criar_job as criar_job_na_fila
from fontes.listagem import filtrar_por_numero_e_versao, filtrar_por_versao
from models.anime import Anime
from models.episodio import Episodio

_SessionMaker = async_sessionmaker[AsyncSession]

logger = logging.getLogger(__name__)


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
    e ele está `LIBERADO` (Feature 1), `FALHOU` (esgotou as retentativas de
    extração — sem isto o aviso de falha ficava preso mesmo depois de
    recarregar a página, sem caminho de retentativa pelo frontend) ou foi
    capturado numa fonte diferente da resolvida agora, a linha é reaproveitada
    (`_reaproveitar_episodio_para_recaptura`) em vez de bater em
    `uq_episodio_identidade` e propagar `EpisodioJaExiste` — ver
    ESPECIFICACAO.md/plano da feature "continuar assistindo"/"liberar arquivo".
    Fora desses casos (ex.: já `PRONTO` na mesma fonte), o comportamento de
    sempre continua valendo: o insert abaixo bate no unique index e
    `db/catalogo.py::_inserir_episodio` propaga `EpisodioJaExiste`.
    """
    fonte = await resolver_e_listar(sessionmaker, anime, versao, resolver_canonico=False)

    # O adapter já devolveu a temporada de `anime.numero_temporada` numerada de
    # 1 (contrato de `ExtratorDeSite.listar_episodios`), então `ep.numero` casa
    # com `numero` (o pedido do cliente) e com `Episodio.numero`.

    # `Episodio.versao` deriva do que a fonte resolvida realmente é
    # (`fonte.versao_da_fonte`), nunca do `versao` pedido pelo cliente — a
    # invariante desta fase. Também usado para filtrar a listagem abaixo: sem
    # isso, um site que lista episódios das duas versões (mesmo risco de
    # `captura/servico.py::_proximo_com_episodio`) poderia gravar a URL da
    # versão errada sob o rótulo certo.
    versao_do_episodio = versao_episodio_da_fonte(fonte.versao_da_fonte)

    correspondentes = filtrar_por_numero_e_versao(fonte.episodios, numero, versao_do_episodio)
    if len(correspondentes) > 1:
        # Mais de um rótulo remoto mapeia pro mesmo `numero` (ex. "7"/"07" —
        # fontes/adaptadores/base.py::EpisodioRemoto) — o request só carrega `numero`
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
        episodio_existente.status in (StatusEpisodio.LIBERADO, StatusEpisodio.FALHOU)
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
    """Botão "Marcar como assistido" da página do anime (`api/rotas/animes.py`)
    — marca o anime INTEIRO. Ver docstring de `_marcar_assistidos` pros dois
    passos; aqui `numero=None` não restringe nenhum dos dois a um episódio só.
    """
    await _marcar_assistidos(sessionmaker, anime=anime, versao=versao, numero=None)


async def marcar_episodio_assistido(
    sessionmaker: _SessionMaker,
    *,
    anime: Anime,
    numero: int,
    versao: VersaoEpisodio,
) -> None:
    """Item "Marcar como assistido" do menu de
    `components/CartaoContinuarAssistindo.jsx` (Home) — mesmos dois passos de
    `marcar_todos_assistidos` (ver docstring de `_marcar_assistidos`), só que
    restritos a UM número. Pedido explícito do usuário (2026-09-21): o botão
    original marca o anime inteiro; "Continuar assistindo" mostra só o
    PRÓXIMO episódio, então marcar em lote surpreende ali — o usuário queria
    marcar só o slot que está vendo.
    """
    await _marcar_assistidos(sessionmaker, anime=anime, versao=versao, numero=numero)


async def _marcar_assistidos(
    sessionmaker: _SessionMaker,
    *,
    anime: Anime,
    versao: VersaoEpisodio,
    numero: int | None,
) -> None:
    """Núcleo compartilhado por `marcar_todos_assistidos`/
    `marcar_episodio_assistido` — `numero=None` cobre o anime inteiro,
    `numero=<n>` restringe os dois passos a um único número. Dois passos:

    1. `UPDATE` em lote — marca `assistido_em` (agora) em todo `Episodio` já
       capturado localmente (qualquer fonte/versão, restrito a `numero`
       quando informado) que ainda não tem a marca; mesma semântica de
       `POST /episodios/{id}/assistido`, aplicada em lote.
    2. Cria uma linha `LIBERADO` + `assistido_em` (`db/catalogo.py::
       criar_episodio_assistido`, sem `Job`) pra cada episódio `REGULAR` que
       a fonte remota ativa lista (restrito a `numero` quando informado) e
       que ainda não tem `Episodio` nenhum aqui — pedido explícito do
       usuário: marca TODO episódio disponível na fonte como assistido, não
       só os já baixados. "Capturar"/"Recapturar" seguem disponíveis depois
       (`criar_job_site` acima já reaproveita `LIBERADO`).

    Mesma resolução de fonte de `criar_job_site` (`resolver_canonico=False`:
    o chamador já resolveu/confirmou a `FonteAnime` antes do botão/menu ficar
    clicável) — pode levantar `FonteAmbigua`/`VersaoIndisponivelError`/
    `FalhaDeExtracao` pelos mesmos motivos de lá; nesse caso o passo 1 já
    comitou (nenhum episódio já capturado deixa de ser marcado), só o passo 2
    (criar os que faltam) não roda.

    `titulo`/`sinopse` vêm de `info_de_episodio` (best-effort, como em
    `criar_job_site`): a página do anime tem fallback ao vivo, mas "Continuar
    assistindo" lê só o `Episodio` gravado — sem isto o episódio ficava sem nome
    pra sempre. O custo é baixo: a 1ª consulta memoiza a temporada inteira
    (`integrations/servico.py`), os demais episódios saem do cache.
    """
    async with sessionmaker() as sessao:
        filtro_numero = [Episodio.numero == numero] if numero is not None else []
        locais = (
            await sessao.execute(
                select(Episodio).where(Episodio.anime_id == anime.id, *filtro_numero)
            )
        ).scalars().all()
        await sessao.execute(
            update(Episodio)
            .where(Episodio.anime_id == anime.id, Episodio.assistido_em.is_(None), *filtro_numero)
            .values(assistido_em=datetime.now(UTC))
        )
        await sessao.commit()

    fonte = await resolver_e_listar(sessionmaker, anime, versao, resolver_canonico=False)
    versao_do_episodio = versao_episodio_da_fonte(fonte.versao_da_fonte)
    remotos_por_numero: dict[int, list] = defaultdict(list)
    for remoto in filtrar_por_versao(fonte.episodios, versao_do_episodio):
        if remoto.numero is not None and (numero is None or remoto.numero == numero):
            remotos_por_numero[remoto.numero].append(remoto)

    numeros_locais = {
        ep.numero
        for ep in locais
        if ep.tipo == TipoEpisodio.REGULAR and ep.versao == versao_do_episodio
    }
    for numero_remoto, candidatos in remotos_por_numero.items():
        if numero_remoto in numeros_locais:
            continue
        if len(candidatos) > 1:
            # Mesma escolha determinística de `criar_job_site` acima.
            logger.warning(
                "%d episódios remotos com numero=%d em %r (rótulos: %s) — usando o 1º",
                len(candidatos),
                numero_remoto,
                fonte.dominio,
                [ep.rotulo for ep in candidatos],
            )
        info = await info_de_episodio(sessionmaker, anime, numero_remoto)
        try:
            await catalogo.criar_episodio_assistido(
                sessionmaker,
                anime.id,
                numero=numero_remoto,
                tipo=TipoEpisodio.REGULAR,
                versao=versao_do_episodio,
                url_fonte=candidatos[0].url,
                site_origem=fonte.dominio,
                titulo_episodio=info.nome if info else None,
                sinopse=info.sinopse if info else None,
            )
        except EpisodioJaExiste:
            # Corrida genuína (dois cliques quase simultâneos do botão/menu) —
            # a checagem contra `numeros_locais` já é feita com os dados de
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
    1), `FALHOU` (tentativa de captura anterior esgotou as retentativas —
    sem isto o episódio ficava com o aviso de falha preso pra sempre, mesmo
    recarregando a página, até intervenção manual no banco) ou capturado numa
    fonte diferente da resolvida agora: reaproveita a linha em vez de bater em
    `uq_episodio_identidade`. Apaga os arquivos da captura anterior
    (`remover_arquivos_do_episodio`, best-effort — num `FALHOU` normalmente não
    há nada pra apagar, o download nunca chegou a terminar), zera os campos de
    mídia e volta o episódio para `PENDENTE`; `assistido_em`
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

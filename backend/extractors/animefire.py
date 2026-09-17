"""Adapter AnimeFire (ESPECIFICACAO.md §3A) — porte de
`Slime_Shell_Web/backend/api/animefire.py` para o contrato de `extractors/base.py`.

Mudanças em relação ao original: sem cliente HTTP próprio (recebe `ClienteDeSite`
injetado), sem cache em disco (substituído por `FonteAnime`/banco), e nenhum
`except Exception: return []`/`{}` — parsing vazio onde o chamador já espera
conteúdo (listagem de episódios, mídia de um episódio) vira `EstruturaDoSiteMudou`
em vez de devolver silenciosamente uma coleção vazia.

Decisão registrada: busca (`buscar`) devolvendo zero resultados **não** é erro —
é o caso normal de "este título não existe neste site", usado por
`extractors/resolucao.py` para cair para o próximo site da lista de prioridade.
"""

import logging
from dataclasses import replace
from html import unescape
from urllib.parse import parse_qs, urlparse

from core.enums import VersaoEpisodio
from core.erros import EstruturaDoSiteMudou, FonteNaoEncontrada
from core.texto import slugificar
from extractors.base import (
    EpisodioRemoto,
    ExtratorDeSite,
    FormatoDeMidia,
    LinkDeMidia,
    ResultadoBusca,
)
from extractors.cliente import ClienteDeSite
from extractors.versao import inferir_versao

logger = logging.getLogger(__name__)

_TIMEOUT_S = 15
# Sem token — endpoint de busca/detalhe é API JSON pública (confirmado ao vivo
# em 2026-09-04). `BASE_URL` continua servindo só pra URLs "humanas"
# (`ResultadoBusca.url`, listagem de episódios, página de episódio). Domínio
# migrado de .io para .one (site inteiro, API incluída — confirmado pelo
# usuário em 2026-09-15, API .io parou de responder).
_API_URL = "https://api.animefire.one"


class AnimeFireProvider(ExtratorDeSite):
    BASE_URL = "https://animefire.one"

    @property
    def dominio(self) -> str:
        return "animefire.one"

    @property
    def exige_navegador(self) -> bool:
        return False

    @property
    def diferencia_versao(self) -> bool:
        # Confirmado ao vivo em 2026-08-18 (busca por "One Piece"): mesmo
        # padrão do AnimesDrive — dublado é outra entrada de catálogo com
        # marcador próprio ("One Piece (Dublado)" / slug `one-piece-dublado`),
        # não uma aba do mesmo anime. Pendência da modelagem original
        # (CONTEXT_NEXT.md) resolvida — capability já existia, só faltava
        # confirmar e ligar.
        return True

    def buscar(self, cliente: ClienteDeSite, titulo: str) -> list[ResultadoBusca]:
        return self._buscar_termo(cliente, titulo)

    def _buscar_termo(self, cliente: ClienteDeSite, termo: str) -> list[ResultadoBusca]:
        # `slugificar`: mesmo formato de query que a antiga página humana de
        # busca já usava — o endpoint aceita tanto hífen quanto espaço
        # (confirmado ao vivo em 2026-09-04 com "tensei-shitara-slime" e
        # "tensei shitara slime datta ken"), não precisou mudar aqui.
        busca_formatada = slugificar(termo)
        url = f"{_API_URL}/animes/pesquisar?q={busca_formatada}"
        try:
            dados = cliente.obter_json(url, timeout_s=_TIMEOUT_S)
        except FonteNaoEncontrada:
            # Não confirmado ao vivo que o endpoint de busca por si só devolva
            # 404 — o padrão observado é `data: []` com HTTP 200 (tratado
            # abaixo). Mantido por paridade com o comportamento anterior e
            # como cinto e suspensório: se acontecer, é "zero resultados", não
            # falha.
            logger.info("AnimeFire: busca por %r não encontrou nada (404) em %s", termo, url)
            return []

        itens = dados.get("data") if isinstance(dados, dict) else None
        if not isinstance(itens, list):
            raise EstruturaDoSiteMudou(
                f"resposta de busca do AnimeFire sem 'data' em formato de lista em {url}",
                dominio=self.dominio,
            )

        resultados: list[ResultadoBusca] = []
        for item in itens:
            resultados.extend(self._resultados_do_item(item, url))

        if not resultados:
            # info, não warning: com a busca em paralelo em todos os sites
            # (extractors/busca/servico.py::buscar_por_site_com_variantes), um título
            # existir só num dos dois é o caso comum, não uma falha — não dá
            # pra distinguir "não achei mesmo" de "estrutura mudou" só por
            # contagem zero, então não escala pra warning (isso viraria
            # ruído em toda busca parcial). Falha de parsing de verdade ainda
            # sobe como `EstruturaDoSiteMudou` via `_resultados_do_item`.
            logger.info("AnimeFire: nenhum resultado encontrado em %s", url)
        return resultados

    def _resultados_do_item(self, item: object, url: str) -> list[ResultadoBusca]:
        """Um item de `data[]` vira um ou dois `ResultadoBusca`, conforme o
        campo `audio` menciona dublado, legendado, ou ambos (mesmo `id` de
        anime nos dois, versões diferentes) — ex. `"Dublado & Legendado"`."""
        try:
            identificador = item["id"]
            titulo_exibicao = self._titulo_preferido(item["titles"], url)
        except (TypeError, KeyError) as excecao:
            raise EstruturaDoSiteMudou(
                f"item de busca do AnimeFire sem 'id'/'titles' em {url}: {excecao}",
                dominio=self.dominio,
            ) from excecao

        # `unescape`: a API já observada devolvendo o campo com entity HTML
        # (`"Dublado &amp; Legendado"`) em vez do `&` literal. `audio` fora do
        # formato esperado (ausente, `None`, tipo não-string) vira string
        # vazia — cai no ramo "nenhum marcador" abaixo, não numa exceção de tipo.
        audio_bruto = item.get("audio")
        audio = unescape(audio_bruto).lower() if isinstance(audio_bruto, str) else ""
        tem_dublado = "dublado" in audio
        tem_legendado = "legendado" in audio

        versoes: list[VersaoEpisodio | None]
        if tem_dublado and tem_legendado:
            versoes = [VersaoEpisodio.DUBLADO, VersaoEpisodio.LEGENDADO]
        elif tem_dublado:
            versoes = [VersaoEpisodio.DUBLADO]
        elif tem_legendado:
            versoes = [VersaoEpisodio.LEGENDADO]
        else:
            # Nem "Dublado" nem "Legendado" no campo — não observado ao vivo,
            # mas não é motivo pra descartar o item inteiro: versão fica
            # indeterminada (`None`) e o item segue visível pro chamador.
            logger.warning(
                "AnimeFire: item %r com campo 'audio' inesperado (%r), versão indeterminada",
                identificador,
                item.get("audio"),
            )
            versoes = [None]

        return [
            ResultadoBusca(
                titulo_exibicao=titulo_exibicao,
                identificador=identificador,
                url=f"{self.BASE_URL}/anime/{identificador}",
                versao=versao,
            )
            for versao in versoes
        ]

    # Ordem de preferência de locale — confirmado ao vivo em 2026-09-17: a
    # API trocou `title` (string única) por `titles` (objeto por região,
    # chaves observadas `BR`/`US`/`JP`, nem sempre as três presentes). `BR`
    # é o título em português que o site exibia como `title` antes da
    # mudança — mesmo papel; cai para qualquer chave presente quando falta
    # (ex. animes sem tradução BR, só `US`/`JP`).
    _ORDEM_LOCALE_TITULO = ("BR", "US", "JP")

    def _titulo_preferido(self, titulos: object, url: str) -> str:
        if not isinstance(titulos, dict) or not titulos:
            raise EstruturaDoSiteMudou(
                f"item de busca do AnimeFire com 'titles' vazio ou inválido em {url}",
                dominio=self.dominio,
            )
        for locale in self._ORDEM_LOCALE_TITULO:
            titulo = titulos.get(locale)
            if titulo:
                return titulo
        return next(iter(titulos.values()))

    def listar_episodios(
        self, cliente: ClienteDeSite, identificador: str, temporada: int | None
    ) -> list[EpisodioRemoto]:
        url = f"{_API_URL}/anime/{identificador}"
        dados = cliente.obter_json(url, timeout_s=_TIMEOUT_S)

        dados_do_anime = dados.get("data") if isinstance(dados, dict) else None
        episodios_brutos = (
            dados_do_anime.get("episodes") if isinstance(dados_do_anime, dict) else None
        )
        if not isinstance(episodios_brutos, list):
            # HTTP 200 com página "Serviço indisponível" em vez do JSON
            # esperado é um caso real (confirmado ao vivo) — sem os campos
            # certos, isto é estrutura mudou, nunca "zero episódios" (isso
            # seria regressão silenciosa de catálogo).
            raise EstruturaDoSiteMudou(
                f"resposta de detalhe do AnimeFire sem 'data.episodes' em formato de lista"
                f" em {url}",
                dominio=self.dominio,
            )

        primeiro_episodio_por_temporada = self._mapa_primeiro_episodio_por_temporada(
            dados_do_anime.get("seasons"), url
        )

        # `(numero_da_temporada, numero_na_temporada, episódio)` — a temporada e
        # o número por temporada só vivem nesta tupla interna durante o parse;
        # `_recortar_para_temporada` os consome e devolve `EpisodioRemoto`s puros.
        vistos: set[tuple[str, VersaoEpisodio | None]] = set()
        brutos: list[tuple[int, int, EpisodioRemoto]] = []
        for episodio_bruto in episodios_brutos:
            for temp, numero_na_temp, episodio in self._episodios_do_item(
                episodio_bruto, identificador, primeiro_episodio_por_temporada, url
            ):
                chave = (episodio.rotulo, episodio.versao)
                if chave in vistos:
                    continue
                vistos.add(chave)
                brutos.append((temp, numero_na_temp, episodio))

        if not brutos:
            raise EstruturaDoSiteMudou(
                f"nenhum episódio encontrado para {identificador!r} no AnimeFire",
                dominio=self.dominio,
            )

        logger.info(
            "AnimeFire: %d episódio(s) em %d temporada(s) encontrados para %r",
            len(brutos),
            len({temp for temp, _n, _ep in brutos}),
            identificador,
        )

        # AnimeFire já lista os episódios do mais antigo pro mais novo na
        # resposta — sem reordenar; o recorte preserva a ordem.
        return self._recortar_para_temporada(brutos, temporada, identificador)

    def _recortar_para_temporada(
        self,
        brutos: list[tuple[int, int, EpisodioRemoto]],
        temporada: int | None,
        identificador: str,
    ) -> list[EpisodioRemoto]:
        """Contrato de degradação de `ExtratorDeSite.listar_episodios`. O
        AnimeFire numera `data.episodes[].number` reiniciando a cada temporada
        (`season`), então o recorte é filtrar por `season` e usar esse `number`
        nativo como `numero` — sem renumerar. `rotulo` continua sendo o número
        ABSOLUTO da série (preserva `Episodio.numero_fonte`)."""
        if temporada is None:
            return [ep for _t, _n, ep in brutos]

        disponiveis = sorted({t for t, _n, _ep in brutos})
        alvo = [(numero_na_temp, ep) for t, numero_na_temp, ep in brutos if t == temporada]
        if not alvo:
            if len(disponiveis) == 1:
                logger.info(
                    "AnimeFire: temporada %d pedida não bate o rótulo de season da fonte "
                    "(única: %d) para %r — devolvendo a listagem inteira (%d episódios)",
                    temporada,
                    disponiveis[0],
                    identificador,
                    len(brutos),
                )
                return [ep for _t, _n, ep in brutos]
            logger.warning(
                "AnimeFire: temporada %d ausente na fonte para %r (disponíveis: %s) — "
                "devolvendo lista vazia",
                temporada,
                identificador,
                disponiveis,
            )
            return []

        return [replace(ep, numero=numero_na_temp) for numero_na_temp, ep in alvo]

    def _mapa_primeiro_episodio_por_temporada(
        self, temporadas: object, url: str
    ) -> dict[int, int]:
        """`data.seasons[].number -> data.seasons[].first_episode_number`, usado
        pra calcular o número absoluto de cada episódio (`episodes[].number`
        reinicia em 1 a cada temporada — confirmado ao vivo em anime real com
        4 temporadas/79 episódios)."""
        if not isinstance(temporadas, list):
            raise EstruturaDoSiteMudou(
                f"resposta de detalhe do AnimeFire sem 'data.seasons' em formato de lista em {url}",
                dominio=self.dominio,
            )
        mapa: dict[int, int] = {}
        for temporada in temporadas:
            try:
                mapa[temporada["number"]] = temporada["first_episode_number"]
            except (TypeError, KeyError) as excecao:
                raise EstruturaDoSiteMudou(
                    f"temporada do AnimeFire sem 'number'/'first_episode_number' em {url}:"
                    f" {excecao}",
                    dominio=self.dominio,
                ) from excecao
        return mapa

    def _episodios_do_item(
        self,
        episodio_bruto: object,
        identificador: str,
        primeiro_episodio_por_temporada: dict[int, int],
        url: str,
    ) -> list[tuple[int, int, EpisodioRemoto]]:
        """Um item de `data.episodes[]` vira uma ou duas tuplas
        `(numero_da_temporada, numero_na_temporada, EpisodioRemoto)`, conforme o
        campo `audio` menciona dublado, legendado, ou ambos — mesmo critério de
        `_resultados_do_item` (busca), duplicado aqui em vez de compartilhado por
        método: aquele é código de uma fatia irmã em migração paralela, não é
        pra mexer nele nesta fatia."""
        try:
            id_episodio = episodio_bruto["id"]
            numero_na_temporada = episodio_bruto["number"]
            numero_da_temporada = episodio_bruto["season"]
        except (TypeError, KeyError) as excecao:
            raise EstruturaDoSiteMudou(
                f"episódio do AnimeFire sem 'id'/'number'/'season' em {url}: {excecao}",
                dominio=self.dominio,
            ) from excecao

        primeiro_episodio = primeiro_episodio_por_temporada.get(numero_da_temporada)
        if primeiro_episodio is None:
            raise EstruturaDoSiteMudou(
                f"episódio {id_episodio!r} do AnimeFire pertence à temporada"
                f" {numero_da_temporada!r}, ausente em 'data.seasons' em {url}",
                dominio=self.dominio,
            )
        numero_absoluto = primeiro_episodio + (numero_na_temporada - 1)
        rotulo = str(numero_absoluto)
        thumb_url = episodio_bruto.get("still_src")

        # `unescape`: a API já observada devolvendo o campo com entity HTML
        # (`"Dublado &amp; Legendado"`) em vez do `&` literal. `audio` fora do
        # formato esperado (ausente, `None`, tipo não-string) vira string
        # vazia — cai no ramo "nenhum marcador" abaixo, não numa exceção de tipo.
        audio_bruto = episodio_bruto.get("audio")
        audio = unescape(audio_bruto).lower() if isinstance(audio_bruto, str) else ""
        tem_dublado = "dublado" in audio
        tem_legendado = "legendado" in audio

        versoes: list[VersaoEpisodio | None]
        if tem_dublado and tem_legendado:
            versoes = [VersaoEpisodio.DUBLADO, VersaoEpisodio.LEGENDADO]
        elif tem_dublado:
            versoes = [VersaoEpisodio.DUBLADO]
        elif tem_legendado:
            versoes = [VersaoEpisodio.LEGENDADO]
        else:
            logger.warning(
                "AnimeFire: episódio %r com campo 'audio' inesperado (%r), versão indeterminada",
                id_episodio,
                episodio_bruto.get("audio"),
            )
            versoes = [None]

        return [
            (
                numero_da_temporada,
                numero_na_temporada,
                EpisodioRemoto(
                    rotulo=rotulo,
                    numero=numero_absoluto,
                    url=self._url_sintetica_de_episodio(identificador, id_episodio, versao),
                    versao=versao,
                    thumb_url=thumb_url,
                ),
            )
            for versao in versoes
        ]

    def _url_sintetica_de_episodio(
        self, identificador: str, id_episodio: str, versao: VersaoEpisodio | None
    ) -> str:
        """URL sintética, não a URL canônica do site: a API nova não tem rota
        de página de episódio de verdade, então esta URL é convenção interna
        do adapter, carregando o id do episódio e o áudio escolhido como query
        params — `resolver_midia` (fatia irmã) parseia os dois de volta pra
        escolher o stream certo na API de streams (que devolve um stream por
        áudio, sem outro jeito de saber qual foi pedido)."""
        audio = "dublado" if versao == VersaoEpisodio.DUBLADO else "legendado"
        return f"{self.BASE_URL}/anime/{identificador}?ep={id_episodio}&audio={audio}"

    def resolver_midia(self, cliente: ClienteDeSite, url_episodio: str) -> LinkDeMidia:
        """Resolve o stream (playlist HLS disfarçada de imagem — era manifesto
        MPEG-DASH até a mudança de CDN confirmada ao vivo em 2026-09-14, ver
        `FormatoDeMidia`) do episódio, escolhendo entre `data.streams[]` da API
        de episódio pelo áudio pedido na URL sintética (`_url_sintetica_de_episodio`,
        fatia irmã de `listar_episodios`).

        Sem `Referer`: a URL sintética que geramos não é uma página real que
        um player enviaria como referer, e a chamada ao vivo (confirmada em
        2026-09-04) funcionou sem nenhum cabeçalho especial.
        """
        query = parse_qs(urlparse(url_episodio).query)
        id_episodio = (query.get("ep") or [None])[0]
        if not id_episodio:
            raise EstruturaDoSiteMudou(
                f"URL de episódio do AnimeFire sem parâmetro 'ep' em {url_episodio}",
                dominio=self.dominio,
            )
        audio_pedido = (query.get("audio") or [None])[0]

        url = f"{_API_URL}/episode/{id_episodio}"
        dados = cliente.obter_json(url, timeout_s=_TIMEOUT_S)
        dados_do_episodio = dados.get("data") if isinstance(dados, dict) else None
        streams_brutos = (
            dados_do_episodio.get("streams") if isinstance(dados_do_episodio, dict) else None
        )
        if not isinstance(streams_brutos, list) or not streams_brutos:
            raise EstruturaDoSiteMudou(
                f"resposta de episódio do AnimeFire sem 'data.streams' em formato de lista"
                f" em {url}",
                dominio=self.dominio,
            )

        streams_hospedados = [
            stream
            for stream in streams_brutos
            if isinstance(stream, dict) and stream.get("is_offline") is not True
        ]
        if not streams_hospedados:
            raise FonteNaoEncontrada(
                f"nenhum stream hospedado para o episódio {id_episodio!r} no AnimeFire",
                dominio=self.dominio,
            )

        stream_escolhido, audio_escolhido = self._escolher_stream(
            streams_hospedados, audio_pedido, id_episodio
        )

        link_direto = stream_escolhido.get("url")
        if not link_direto:
            raise EstruturaDoSiteMudou(
                f"AnimeFire não devolveu 'url' de stream para o episódio {id_episodio!r}",
                dominio=self.dominio,
            )

        logger.info(
            "AnimeFire: episódio %r com %d stream(s) hospedados, áudio escolhido=%r",
            id_episodio,
            len(streams_hospedados),
            audio_escolhido,
        )

        return LinkDeMidia(
            url=link_direto,
            cabecalhos={"User-Agent": cliente.user_agent()},
            formato=FormatoDeMidia.HLS,
        )

    def _escolher_stream(
        self, streams: list[dict], audio_pedido: str | None, id_episodio: str
    ) -> tuple[dict, str | None]:
        """Escolhe o stream certo dentre os já filtrados por `is_offline`, de
        acordo com o áudio pedido na URL sintética (`audio_pedido`, sempre
        `"dublado"`/`"legendado"`/`None` — nunca vazio, gerado por
        `_url_sintetica_de_episodio`). Devolve o stream e o rótulo de áudio
        efetivamente escolhido, só para o log de `resolver_midia`."""
        classificados = [
            (stream, inferir_versao(stream.get("audio", "") or "", "")) for stream in streams
        ]

        versao_pedida = {
            "dublado": VersaoEpisodio.DUBLADO,
            "legendado": VersaoEpisodio.LEGENDADO,
        }.get(audio_pedido or "")

        if versao_pedida is not None:
            candidatos = [stream for stream, versao in classificados if versao is versao_pedida]
            if not candidatos:
                raise FonteNaoEncontrada(
                    f"nenhum stream {audio_pedido!r} disponível para o episódio"
                    f" {id_episodio!r} no AnimeFire",
                    dominio=self.dominio,
                )
            return self._desempatar_por_mtl(candidatos), audio_pedido

        if len(streams) == 1:
            return streams[0], streams[0].get("audio")

        candidatos_legendado = [
            stream for stream, versao in classificados if versao is VersaoEpisodio.LEGENDADO
        ]
        if candidatos_legendado:
            logger.warning(
                "AnimeFire: episódio %r sem áudio reconhecido na URL e múltiplos streams —"
                " preferindo legendado",
                id_episodio,
            )
            return self._desempatar_por_mtl(candidatos_legendado), "legendado"

        logger.warning(
            "AnimeFire: episódio %r sem áudio reconhecido na URL e nenhum stream"
            " classificável — usando o primeiro disponível",
            id_episodio,
        )
        return streams[0], streams[0].get("audio")

    def _desempatar_por_mtl(self, candidatos: list[dict]) -> dict:
        """Desempate entre streams empatados na escolha de áudio: prefere
        `is_mtl` falso. Nunca um filtro — não pode zerar a lista, então cai no
        primeiro candidato se todos forem `is_mtl`."""
        for stream in candidatos:
            if stream.get("is_mtl") is not True:
                return stream
        return candidatos[0]

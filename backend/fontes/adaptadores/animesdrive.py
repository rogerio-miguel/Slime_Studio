"""Adapter AnimesDrive (ESPECIFICACAO.md §3A) — segundo site da lista de
prioridade de fallback (`fontes/adaptadores/registro.py`), atrás do AnimeFire.

Strategy Pattern completo. É o único adapter do projeto que declara
`exige_navegador_para_midia`: os players embutidos aqui só montam a URL de
mídia rodando o próprio JS, e a estratégia é **observar** o navegador fazendo o
que a página faria com um usuário real (`fontes/rede/cliente.py::capturar_midia`),
nunca reimplementar o player. Achados ao vivo contra o site (host mudou de
`animesdrive.online` para `animesdrive.cloud` em 2026-08-25 — `dominio` é
identificador estável desacoplado do host, só `BASE_URL` muda numa próxima
troca de domínio; achados abaixo continuam válidos, foi só migração de host):

- Nenhum dos players de iframe expõe URL de vídeo estática no HTML:
  `blogger.com/video.g?token=...` é SPA do Google (framework "Wiz"), e
  `animeshd.cloud`/`animes.strp2p.com` são o mesmo player de terceiros, que lê
  `location.hash` como id, chama `GET /api/v1/video?id=<hash>&...` e monta a
  mídia a partir de uma resposta cifrada (2026-08-15).
- Navegar direto pro **embed** não resolve: os dois players de terceiros
  respondem "Video is not ready yet" quando abertos fora da página de episódio,
  mesmo com o `Referer` certo. Quem se carrega é a página do episódio; o player
  embutido nela resolve normal (3 episódios de 3 animes, 2026-08-17).
- Os cabeçalhos do `LinkDeMidia` vêm da requisição observada, não de suposição:
  o `Referer` real medido é a origem do site (só a origem, por causa do
  `referrer-policy` do embed) — não a URL do embed, como esta docstring previa
  antes de existir medição.
- Orçamento: `_TIMEOUT_CAPTURA_S`/`_ORCAMENTO_CAPTURAS_S` abaixo, cobertos por
  `fontes/rede/resiliencia.py::_TETO_ESPERA_NAVEGADOR_S`.

Confirmado ao vivo em 2026-08-18 (episódios com seletor de qualidade): a página
de episódio pode renderizar uma seção `animeq-player` com botões
`[data-animeq-switch]` (um por servidor/qualidade) e painéis
`[data-animeq-source]` correspondentes — cada painel é um `<video><source>`
(vídeo direto) ou um `<iframe>` (mesmos players de terceiros de cima). O rótulo
do botão **não prediz** o tipo de painel (um "FHD" pode ser vídeo direto num
episódio e iframe em outro), o vocabulário de rótulo varia entre episódios
(`"Mobile / Celular"`, `"FullHD / HLS"`, `"Dublado"`), e o botão marcado
`is-active` é só o único com `src` real no HTML estático — os demais vêm
`about:blank` + `data-lazy-src` (WP Rocket), sem relação com qualidade. Páginas
sem esse seletor (modo legado) seguem exatamente como antes.

Como no AnimeFire, `buscar` vazio é caso normal, e erro de parsing vira
`EstruturaDoSiteMudou` via `except AttributeError`.
"""

import logging
import re
import time
import urllib.parse
from dataclasses import dataclass

from bs4 import BeautifulSoup

from core.enums import VersaoEpisodio
from core.erros import EstruturaDoSiteMudou, FalhaDeExtracao, FonteNaoEncontrada, SessaoRejeitada
from fontes.adaptadores.base import (
    EpisodioRemoto,
    ExtratorDeSite,
    LinkDeMidia,
    ResultadoBusca,
    ordenar_episodios,
)
from fontes.adaptadores.qualidade import NivelDeQualidade, qualidade_do_rotulo
from fontes.adaptadores.versao import inferir_versao
from fontes.rede.cliente import ClienteComCaptura, ClienteDeSite, responde

logger = logging.getLogger(__name__)

_TIMEOUT_S = 15
# Janela de UMA captura no navegador. Medido ao vivo: 3s a 17s da navegação até
# a requisição de mídia. O excedente é folga pro caso patológico (overlay de
# anúncio engolindo os primeiros cliques), não expectativa de caso normal.
_TIMEOUT_CAPTURA_S = 90
# Relógio de parede pro CONJUNTO de tentativas de servidor de um episódio —
# cobre também os `responde()` dos candidatos de vídeo direto. Com um único
# candidato de navegador a janela calculada por `_janela_de_captura` dá
# min(90, 120) = 90, idêntica a hoje (não regride a calibração medida acima).
_ORCAMENTO_CAPTURAS_S = 120
_MAX_CAPTURAS_POR_EPISODIO = 3
_HOSTS_YOUTUBE = ("youtube.com", "youtu.be")
# `/?` antes do `$`: URL de episódio com barra final (`.../episodio-7/`) é
# válida e comum (link relativo normalizado por navegador/CMS) — sem isso o
# `numero` some inteiro da listagem em vez de só perder a barra.
_REGEX_EPISODIO = re.compile(r"^/episodio/(?P<slug>.+?)-episodio-(?P<numero>[^/]+)/?$")
# Box de episódios do próprio anime (tema DooPlay). É daqui que a listagem sai —
# e **não** de um filtro de `href` por prefixo do `identificador`, porque o slug
# do episódio não é derivável do identificador do anime: o anime
# `one-piece-dublado-todos-os-episodios` lista episódios
# `/episodio/one-piece-dublado-episodio-N`, e o filtro por prefixo descartava os
# 302 episódios, quebrando a listagem com "nenhum episódio encontrado"
# (confirmado ao vivo em 2026-08-17). Todo link de episódio da página vive dentro
# deste box — conferido em 6 páginas reais, incluindo uma com 19 temporadas.
_SELETOR_LISTA_EPISODIOS = "#episodes a[href]"
# Ordem de leitura de atributo do iframe dentro de um painel de qualidade —
# WP Rocket adia o `src` real em `data-lazy-src` até o elemento entrar em
# viewport; o `src` cru costuma ficar `about:blank` até lá. `data-animeq-src`
# é o lazy-src do próprio player `animeq` (painel HD, confirmado ao vivo em
# 2026-08-25) — mesma convenção `data-animeq-*` do resto do markup.
_ATRIBUTOS_DE_IFRAME = ("data-lazy-src", "data-animeq-src", "src", "data-src")


class AnimesDriveProvider(ExtratorDeSite):
    # Migração de domínio 2026-08-25 (.online -> .cloud): `dominio` abaixo é
    # identificador estável, desacoplado do host real — troca de domínio
    # futura exige mudar só esta constante, nunca `dominio` nem os dados já
    # persistidos com ele como chave (`fonte_anime.site_dominio` etc.).
    BASE_URL = "https://animesdrive.cloud"

    @property
    def dominio(self) -> str:
        return "animesdrive"

    @property
    def exige_navegador(self) -> bool:
        return False

    @property
    def exige_navegador_para_midia(self) -> bool:
        return True

    @property
    def diferencia_versao(self) -> bool:
        return True

    def buscar(self, cliente: ClienteDeSite, titulo: str) -> list[ResultadoBusca]:
        consulta = " ".join(re.sub(r"[-_]+", " ", titulo).split())
        url = f"{self.BASE_URL}/?{urllib.parse.urlencode({'s': consulta})}"
        try:
            html = cliente.obter_html(url, timeout_s=_TIMEOUT_S)
        except FonteNaoEncontrada:
            # Mesmo tratamento do AnimeFire (`fontes/adaptadores/animefire.py::buscar`),
            # por simetria — não confirmado ao vivo se o AnimesDrive também
            # responde 404 numa busca sem resultado, mas tratar aqui é seguro
            # (404 vira lista vazia, não erro) e evita divergência entre os dois
            # adapters caso o site se comporte assim.
            logger.warning(
                "AnimesDrive: busca por %r não encontrou nada (404) em %s", titulo, url
            )
            return []

        try:
            soup = BeautifulSoup(html, "html.parser")
            resultados = []
            for artigo in soup.select("div.result-item article"):
                tag_link = artigo.find("a", href=True)
                if tag_link is None or "/anime/" not in tag_link["href"]:
                    continue

                tag_titulo = artigo.select_one(".title") or artigo.find("h3") or artigo.find("h2")
                if tag_titulo is None:
                    logger.warning("AnimesDrive: card de busca sem título extraível, ignorado")
                    continue

                url_anime = tag_link["href"]
                titulo_exibicao = " ".join(tag_titulo.get_text().split())
                identificador = _extrair_identificador(url_anime)
                resultados.append(
                    ResultadoBusca(
                        titulo_exibicao=titulo_exibicao,
                        identificador=identificador,
                        url=url_anime,
                        # Site declara `diferencia_versao=True`: convenção dos
                        # sites BR é dublado sempre marcado, legendado é o
                        # default silencioso — ausência de marcador aqui
                        # nunca é "indeterminado", é `LEGENDADO`.
                        versao=(
                            inferir_versao(titulo_exibicao, identificador)
                            or VersaoEpisodio.LEGENDADO
                        ),
                    )
                )
            if not resultados:
                # info, não warning: com a busca em paralelo em todos os sites
                # (fontes/busca/servico.py::buscar_por_site_com_variantes), um título
                # existir só num dos dois é o caso comum, não uma falha — não
                # dá pra distinguir "não achei mesmo" de "estrutura mudou" só
                # por contagem zero, então não escala pra warning (isso viraria
                # ruído em toda busca parcial). Falha de parsing de verdade
                # ainda sobe como `EstruturaDoSiteMudou` via `except AttributeError`.
                logger.info("AnimesDrive: nenhum resultado de busca encontrado em %s", url)
            return resultados
        except AttributeError as excecao:
            raise EstruturaDoSiteMudou(
                f"estrutura da página de busca do AnimesDrive mudou: {excecao}",
                dominio=self.dominio,
            ) from excecao

    def listar_episodios(
        self, cliente: ClienteDeSite, identificador: str, temporada: int | None
    ) -> list[EpisodioRemoto]:
        # `temporada` é IGNORADA: no AnimesDrive cada temporada é uma entrada de
        # catálogo própria (`identificador` já aponta pra certa) e a numeração
        # de `-episodio-N` já é 1-based dentro dela. O markup não expõe nenhum
        # dado de season, então não há como recortar uma página multi-temporada
        # — devolver a listagem inteira é a degradação segura do contrato de
        # `ExtratorDeSite.listar_episodios`.
        url_anime = f"{self.BASE_URL}/anime/{identificador}"
        html = cliente.obter_html(url_anime, timeout_s=_TIMEOUT_S)

        try:
            soup = BeautifulSoup(html, "html.parser")
            total_brutos = 0
            # Agrupado por slug de episódio: o box lista mais de um slug quando a
            # página cobre duas versões do mesmo título (a página de filme lista
            # a legendada e a dublada lado a lado) — sem separar, a listagem
            # misturaria as duas.
            # Dentro de cada grupo, a chave de dedup é o rótulo cru (string), não
            # `int(numero)`: "7" e "07" não são necessariamente o mesmo episódio,
            # e colapsar os dois por valor inteiro perderia um episódio de
            # verdade (fontes/adaptadores/base.py::EpisodioRemoto).
            tags_a = soup.select(_SELETOR_LISTA_EPISODIOS)
            # Cada card do #episodes tem dois <a> com o mesmo href: um envolve a
            # <img> da thumb, o outro é o texto. Pareia thumb por href pra
            # reanexar no episódio já deduplicado.
            thumb_por_href = {
                tag_a["href"]: urllib.parse.urljoin(self.BASE_URL, tag_img["src"].strip())
                for tag_a in tags_a
                if (tag_img := tag_a.find("img", src=True)) is not None
                and tag_img["src"].strip()
            }

            por_slug: dict[str, dict[str, EpisodioRemoto]] = {}
            for tag_a in tags_a:
                href = tag_a["href"]
                match = _REGEX_EPISODIO.match(urllib.parse.urlparse(href).path)
                if match is None:
                    continue
                total_brutos += 1

                rotulo = match.group("numero")
                try:
                    numero = int(rotulo)
                except ValueError:
                    numero = None

                por_rotulo = por_slug.setdefault(match.group("slug"), {})
                if rotulo in por_rotulo:
                    # Duplicata com o mesmo href é esperada (thumbnail + título
                    # apontam pro mesmo episódio) — só avisa se os links relatados
                    # para o mesmo rótulo divergirem de verdade.
                    if por_rotulo[rotulo].url != href:
                        logger.warning(
                            "AnimesDrive: episódio %r com hrefs conflitantes para %r,"
                            " mantendo a 1ª ocorrência",
                            rotulo,
                            identificador,
                        )
                    continue
                por_rotulo[rotulo] = EpisodioRemoto(
                    rotulo=rotulo, numero=numero, url=href, thumb_url=thumb_por_href.get(href)
                )
        except AttributeError as excecao:
            raise EstruturaDoSiteMudou(
                f"estrutura da listagem de episódios do AnimesDrive mudou: {excecao}",
                dominio=self.dominio,
            ) from excecao

        if not por_slug:
            raise EstruturaDoSiteMudou(
                f"nenhum episódio encontrado para {identificador!r} no AnimesDrive",
                dominio=self.dominio,
            )

        if len(por_slug) == 2:
            slug_a, slug_b = por_slug
            if _diferem_so_por_marcador_de_versao(slug_a, slug_b):
                # Exceção cirúrgica ao "fica com o grupo maior" abaixo: página
                # cobre duas versões do MESMO anime (slug base idêntico, ex.
                # "...-dublado" vs sem sufixo) — aqui as duas listas são
                # legítimas, nenhuma é descarte. Qualquer outro caso (slugs
                # que divergem por outro motivo, ou mais de 2 grupos) cai no
                # comportamento de sempre logo abaixo.
                episodios_das_duas_versoes = [
                    EpisodioRemoto(
                        rotulo=episodio.rotulo,
                        numero=episodio.numero,
                        url=episodio.url,
                        versao=inferir_versao("", slug) or VersaoEpisodio.LEGENDADO,
                        thumb_url=episodio.thumb_url,
                    )
                    for slug in (slug_a, slug_b)
                    for episodio in por_slug[slug].values()
                ]
                logger.info(
                    "AnimesDrive: %d episódio(s) brutos encontrados para %r, %d após dedup"
                    " (2 slugs versão-relacionados: %r e %r)",
                    total_brutos,
                    identificador,
                    len(episodios_das_duas_versoes),
                    slug_a,
                    slug_b,
                )
                return ordenar_episodios(episodios_das_duas_versoes)

        # Fica com o grupo maior — a lista do próprio anime — e diz o que
        # descartou, em vez de devolver duas versões misturadas. Empate mantém o
        # 1º da ordem do documento, porque `max` devolve a 1ª chave de maior
        # valor e `dict` preserva ordem de inserção.
        slug_escolhido = max(por_slug, key=lambda slug: len(por_slug[slug]))
        if len(por_slug) > 1:
            logger.warning(
                "AnimesDrive: %d slugs de episódio na página de %r — usando %r,"
                " descartando %s",
                len(por_slug),
                identificador,
                slug_escolhido,
                [slug for slug in por_slug if slug != slug_escolhido],
            )
        por_rotulo = por_slug[slug_escolhido]

        logger.info(
            "AnimesDrive: %d episódio(s) brutos encontrados para %r, %d após dedup",
            total_brutos,
            identificador,
            len(por_rotulo),
        )

        return ordenar_episodios(por_rotulo.values())

    def resolver_midia(self, cliente: ClienteDeSite, url_episodio: str) -> LinkDeMidia:
        """Resolve a melhor mídia utilizável do episódio.

        Dois modos, detectados pela presença de `[data-animeq-switch]`:

        - **Modo A** (com seletor de qualidade): classifica cada servidor,
          descarta abaixo do piso HD (nunca SD), tenta o de maior qualidade
          primeiro (vídeo direto antes de iframe no mesmo tier — "vídeo
          direto" cobre tanto `<video><source>` quanto o painel Video.js
          `[data-animeq-videojs-host]`, ver `_url_de_video_direto`), e falha
          sem retentativa se só sobrou SD/Mobile — retentar não faz FHD
          aparecer.
        - **Modo B** (legado, sem seletor): caminho de sempre — um iframe,
          uma captura, sem escolha de qualidade.
        """
        html = cliente.obter_html(url_episodio, timeout_s=_TIMEOUT_S)
        candidatos = self._candidatos_de_servidor(html, url_episodio)

        if not candidatos:
            return self._resolver_modo_legado(cliente, html, url_episodio)

        usaveis = [c for c in candidatos if c.qualidade >= NivelDeQualidade.HD]
        if not usaveis:
            # Página não oferece escolha de qualidade real (conteúdo legado tipo
            # "Dublado"): o piso existe pra ESCOLHER entre qualidades; sem
            # escolha, exigi-lo só quebraria episódio antigo que funciona hoje.
            usaveis = [c for c in candidatos if c.qualidade is NivelDeQualidade.DESCONHECIDA]
        if not usaveis:
            raise FalhaDeExtracao(
                f"nenhum servidor acima do piso de qualidade (HD) em {url_episodio};"
                f" descartados: {[(c.rotulo, c.qualidade.name) for c in candidatos]}",
                dominio=self.dominio,
                permite_retentativa=False,
            )

        usaveis.sort(key=_chave_de_ordenacao)

        if not isinstance(cliente, ClienteComCaptura):
            # Contrato quebrado, não falha de site: `exige_navegador_para_midia`
            # é `True` aqui e `fontes/rede/resiliencia.py` deveria ter entregue o
            # cliente de navegador. Retentar com o mesmo cliente repetiria o erro.
            # Conferido cedo (não só no 1º candidato de iframe): modo A pode nem
            # precisar de captura (vídeo direto vivo), mas a mensagem de
            # "contrato quebrado" fica mais clara conferindo antes do loop.
            raise FalhaDeExtracao(
                "resolver mídia do AnimesDrive exige cliente de navegador, recebido"
                f" {type(cliente).__name__}",
                dominio=self.dominio,
                permite_retentativa=False,
            )

        cabecalhos = {"User-Agent": cliente.user_agent(), "Referer": f"{self.BASE_URL}/"}
        limite = time.monotonic() + _ORCAMENTO_CAPTURAS_S
        capturas_feitas = 0
        falhas: list[str] = []

        for posicao, candidato in enumerate(usaveis):
            try:
                if candidato.url_video:
                    if responde(candidato.url_video, cabecalhos):
                        logger.info(
                            "AnimesDrive: %s (%s) resolvido por vídeo direto",
                            candidato.rotulo,
                            candidato.qualidade.name,
                        )
                        return LinkDeMidia(url=candidato.url_video, cabecalhos=cabecalhos)
                    falhas.append(f"{candidato.rotulo}: URL estática não responde")
                    continue

                restante = limite - time.monotonic()
                capturas_restantes = min(
                    sum(1 for c in usaveis[posicao:] if not c.url_video),
                    _MAX_CAPTURAS_POR_EPISODIO - capturas_feitas,
                )
                if capturas_restantes <= 0 or restante <= 0:
                    falhas.append(f"{candidato.rotulo}: sem orçamento de captura restante")
                    continue

                capturas_feitas += 1
                capturada = cliente.capturar_midia(
                    url_episodio,
                    hosts_ignorados=_HOSTS_YOUTUBE,
                    seletor_para_ativar=f'[data-animeq-switch="{candidato.indice}"]',
                    timeout_s=_janela_de_captura(restante, capturas_restantes),
                )
                logger.info(
                    "AnimesDrive: %s (%s) resolvido por captura de navegador",
                    candidato.rotulo,
                    candidato.qualidade.name,
                )
                return LinkDeMidia(url=capturada.url, cabecalhos=capturada.cabecalhos)
            except SessaoRejeitada:
                raise  # sessão, não candidato: o próximo bateria na mesma parede
            except FalhaDeExtracao as excecao:
                falhas.append(f"{candidato.rotulo}: {excecao}")
                logger.warning(
                    "AnimesDrive: servidor %r falhou (%s)", candidato.rotulo, excecao
                )

        raise FalhaDeExtracao(
            f"nenhum servidor FHD/HD utilizável em {url_episodio}: {falhas}",
            dominio=self.dominio,
            permite_retentativa=True,
        )

    def _candidatos_de_servidor(self, html: str, url_episodio: str) -> list["_Candidato"]:
        """Lê os botões `[data-animeq-switch]` e os painéis correspondentes.
        Lista vazia (nenhum botão na página) sinaliza modo B ao chamador — não é
        erro, é a maioria das páginas do site hoje."""
        try:
            soup = BeautifulSoup(html, "html.parser")
            botoes = soup.select("[data-animeq-switch]")
            if not botoes:
                return []

            candidatos: list[_Candidato] = []
            indices_vistos: set[str] = set()
            for botao in botoes:
                indice = botao.get("data-animeq-switch")
                if indice in indices_vistos:
                    logger.warning(
                        "AnimesDrive: dois botões com data-animeq-switch=%r em %s,"
                        " usando o painel do 1º",
                        indice,
                        url_episodio,
                    )
                    continue
                indices_vistos.add(indice)

                rotulo = botao.get("data-source-name") or " ".join(botao.get_text().split())
                painel = soup.select_one(f'[data-animeq-source="{indice}"]')
                if painel is None:
                    logger.warning(
                        "AnimesDrive: botão %r sem painel correspondente em %s, ignorado",
                        indice,
                        url_episodio,
                    )
                    continue

                url_video = _url_de_video_direto(painel, self.BASE_URL)
                tem_iframe = _tem_iframe_utilizavel(painel)
                if url_video is None and not tem_iframe:
                    logger.warning(
                        "AnimesDrive: painel %r sem vídeo direto nem iframe em %s, ignorado",
                        indice,
                        url_episodio,
                    )
                    continue

                candidatos.append(
                    _Candidato(
                        indice=indice,
                        rotulo=rotulo,
                        qualidade=qualidade_do_rotulo(rotulo),
                        url_video=url_video,
                        tem_iframe=tem_iframe,
                    )
                )

            if not candidatos:
                raise EstruturaDoSiteMudou(
                    f"botões de qualidade em {url_episodio} sem painel parseável",
                    dominio=self.dominio,
                )
            return candidatos
        except AttributeError as excecao:
            raise EstruturaDoSiteMudou(
                f"estrutura do seletor de qualidade do AnimesDrive mudou: {excecao}"
                f" ({url_episodio})",
                dominio=self.dominio,
            ) from excecao

    def _resolver_modo_legado(
        self, cliente: ClienteDeSite, html: str, url_episodio: str
    ) -> LinkDeMidia:
        """Caminho de antes do seletor de qualidade existir: um iframe, uma
        captura, sem escolha entre servidores."""
        hosts_de_player = self._hosts_de_player(html, url_episodio)

        if not hosts_de_player:
            raise EstruturaDoSiteMudou(
                f"nenhum iframe de player em {url_episodio}", dominio=self.dominio
            )

        if not isinstance(cliente, ClienteComCaptura):
            raise FalhaDeExtracao(
                "resolver mídia do AnimesDrive exige cliente de navegador, recebido"
                f" {type(cliente).__name__}",
                dominio=self.dominio,
                permite_retentativa=False,
            )

        logger.info(
            "AnimesDrive: capturando mídia de %s (players na página: %s)",
            url_episodio,
            hosts_de_player,
        )
        capturada = cliente.capturar_midia(
            url_episodio, hosts_ignorados=_HOSTS_YOUTUBE, timeout_s=_TIMEOUT_CAPTURA_S
        )
        return LinkDeMidia(url=capturada.url, cabecalhos=capturada.cabecalhos)

    def _hosts_de_player(self, html: str, url_episodio: str) -> list[str]:
        """Hosts dos iframes que podem tocar o episódio — iframe vazio/`about:blank`
        (aba de servidor ainda não ativada) e trailer do YouTube não contam."""
        try:
            soup = BeautifulSoup(html, "html.parser")
            hosts = []
            for iframe in soup.find_all("iframe", src=True):
                src = iframe["src"].strip()
                if not src or src == "about:blank":
                    continue
                if src.startswith("//"):
                    src = f"https:{src}"
                host = urllib.parse.urlparse(src).netloc
                if any(marcador in host for marcador in _HOSTS_YOUTUBE):
                    continue
                hosts.append(host)
            return hosts
        except AttributeError as excecao:
            raise EstruturaDoSiteMudou(
                f"estrutura da página de episódio do AnimesDrive mudou: {excecao}"
                f" ({url_episodio})",
                dominio=self.dominio,
            ) from excecao


@dataclass(frozen=True, slots=True)
class _Candidato:
    indice: str  # valor cru de data-animeq-switch (string: casamento é igualdade de atributo)
    rotulo: str
    qualidade: NivelDeQualidade
    url_video: str | None  # <source src> absolutizado, quando o painel é vídeo direto
    tem_iframe: bool


def _url_de_video_direto(painel, base_url: str) -> str | None:
    """URL de vídeo direto do painel, em dois padrões possíveis: `<video><source
    src>` (padrão original) ou `[data-animeq-videojs-host][data-video-src]`
    (player Video.js sem `<video>`/`<iframe>` nenhum no HTML, confirmado ao
    vivo em 2026-08-25 — painel FHD). Ambos resultam numa URL que o resto do
    pipeline valida com `responde()` antes de confiar, então tratá-los como o
    mesmo tipo de candidato é seguro."""
    tag = painel.select_one("video source[src], video[src]")
    if tag is not None:
        src = (tag.get("src") or "").strip()
    else:
        host_videojs = painel.select_one("[data-animeq-videojs-host]")
        src = (host_videojs.get("data-video-src") or "").strip() if host_videojs else ""
    if not src or src == "about:blank":
        return None
    url = urllib.parse.urljoin(base_url, src)
    if any(marcador in urllib.parse.urlparse(url).netloc for marcador in _HOSTS_YOUTUBE):
        return None
    return url


def _tem_iframe_utilizavel(painel) -> bool:
    iframe = painel.find("iframe")
    if iframe is None:
        return False
    for atributo in _ATRIBUTOS_DE_IFRAME:
        src = (iframe.get(atributo) or "").strip()
        if not src or src == "about:blank":
            continue
        if src.startswith("//"):
            src = f"https:{src}"
        host = urllib.parse.urlparse(src).netloc
        if any(marcador in host for marcador in _HOSTS_YOUTUBE):
            return False
        return True
    return False


def _chave_de_ordenacao(candidato: _Candidato) -> tuple[int, int]:
    """Maior qualidade primeiro; dentro do mesmo tier, vídeo direto antes de
    iframe (custa uma requisição `Range: bytes=0-0`, não uma janela de captura
    inteira). `sorted` é estável, então a ordem da página desempata sozinha
    entre iframes do mesmo tier — nenhum peso extra pro botão `is-active`."""
    return (-candidato.qualidade, 0 if candidato.url_video else 1)


def _janela_de_captura(restante_s: float, capturas_restantes: int) -> int:
    return max(1, min(_TIMEOUT_CAPTURA_S, int(restante_s // capturas_restantes)))


def _extrair_identificador(url_anime: str) -> str:
    return urllib.parse.urlparse(url_anime).path.split("/anime/", 1)[-1].strip("/")


# Marcador de versão isolado por `-` ou início/fim do slug — mesma fronteira
# de token de `fontes/adaptadores/versao.py`, só que aplicada a segmento de slug
# (hífen, não espaço) para comparar dois slugs de grupo de episódio entre si.
_REGEX_MARCADOR_VERSAO_SLUG = re.compile(
    r"(?:^|-)(?:dublado|dub|legendado|leg)(?=-|$)", re.IGNORECASE
)


def _slug_sem_marcador_de_versao(slug: str) -> str:
    return _REGEX_MARCADOR_VERSAO_SLUG.sub("", slug, count=1)


def _diferem_so_por_marcador_de_versao(slug_a: str, slug_b: str) -> bool:
    """`True` quando `slug_a`/`slug_b` só divergem pelo marcador de versão
    (ex. slug base idêntico, um com `-dublado` e outro sem) — usado por
    `listar_episodios` para distinguir "duas versões do mesmo anime" de
    "dois grupos genuinamente diferentes na mesma página"."""
    return _slug_sem_marcador_de_versao(slug_a) == _slug_sem_marcador_de_versao(slug_b)

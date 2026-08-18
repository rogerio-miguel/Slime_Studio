"""Adapter AnimesDrive (ESPECIFICACAO.md §3A) — segundo site da lista de
prioridade de fallback (`extractors/registro.py`), atrás do AnimeFire.

Strategy Pattern completo. É o único adapter do projeto que declara
`exige_navegador_para_midia`: os três players embutidos aqui só montam a URL de
mídia rodando o próprio JS, e a estratégia é **observar** o navegador fazendo o
que a página faria com um usuário real (`extractors/cliente.py::capturar_midia`),
nunca reimplementar o player. Achados ao vivo contra animesdrive.online:

- Nenhum dos três players expõe URL de vídeo estática no HTML:
  `blogger.com/video.g?token=...` é SPA do Google (framework "Wiz"), e
  `animeshd.cloud`/`animes.strp2p.com` são o mesmo player de terceiros, que lê
  `location.hash` como id, chama `GET /api/v1/video?id=<hash>&...` e monta a
  mídia a partir de uma resposta cifrada (2026-08-15).
- Navegar direto pro **embed** não resolve: os dois players de terceiros
  respondem "Video is not ready yet" quando abertos fora da página de episódio,
  mesmo com o `Referer` certo. Quem se carrega é a página do episódio; o player
  embutido nela resolve normal (3 episódios de 3 animes, 2026-08-17).
- Os cabeçalhos do `LinkDeMidia` vêm da requisição observada, não de suposição:
  o `Referer` real medido é `https://animesdrive.online/` (só a origem, por
  causa do `referrer-policy` do embed) — não a URL do embed, como esta docstring
  previa antes de existir medição.
- Orçamento: `_TIMEOUT_CAPTURA_S` abaixo, coberto por
  `extractors/resiliencia.py::_TETO_ESPERA_NAVEGADOR_S`.

Como no AnimeFire, `buscar` vazio é caso normal, e erro de parsing vira
`EstruturaDoSiteMudou` via `except AttributeError`.
"""

import logging
import re
import urllib.parse
from collections.abc import Iterable

from bs4 import BeautifulSoup

from core.enums import VersaoEpisodio
from core.erros import EstruturaDoSiteMudou, FalhaDeExtracao, FonteNaoEncontrada
from extractors.base import EpisodioRemoto, ExtratorDeSite, LinkDeMidia, ResultadoBusca
from extractors.cliente import ClienteComCaptura, ClienteDeSite
from extractors.versao import inferir_versao

logger = logging.getLogger(__name__)

_TIMEOUT_S = 15
# Janela da captura de mídia no navegador. Medido ao vivo: 3s a 17s da navegação
# até a requisição de mídia. O excedente é folga pro caso patológico (overlay de
# anúncio engolindo os primeiros cliques), não expectativa de caso normal.
_TIMEOUT_CAPTURA_S = 90
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


class AnimesDriveProvider(ExtratorDeSite):
    BASE_URL = "https://animesdrive.online"

    @property
    def dominio(self) -> str:
        return "animesdrive.online"

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
            # Mesmo tratamento do AnimeFire (`extractors/animefire.py::buscar`),
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
                # Ausência da tag/atributo não é erro (imagem faltando num card
                # isolado não invalida o resultado) — `urljoin` absolutiza tanto
                # caminho relativo (`/capa.jpg`) quanto URL já absoluta, sem
                # precisar duplicar o tratamento manual de `//host/...` que
                # `resolver_midia` faz para iframes.
                # Classe real é `.thumbnail` (`.thumb` nunca bateu com nada,
                # confirmado ao vivo em 2026-08-17 — era a causa de capa
                # sempre vir `None` pra todo resultado do AnimesDrive).
                tag_capa = artigo.select_one(".thumbnail img")
                src_capa = tag_capa.get("src") if tag_capa else None
                capa_url = (
                    urllib.parse.urljoin(self.BASE_URL, src_capa.strip())
                    if src_capa and src_capa.strip()
                    else None
                )

                titulo_exibicao = " ".join(tag_titulo.get_text().split())
                identificador = _extrair_identificador(url_anime)
                resultados.append(
                    ResultadoBusca(
                        titulo_exibicao=titulo_exibicao,
                        identificador=identificador,
                        url=url_anime,
                        capa_url=capa_url,
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
                # (extractors/servico.py::buscar_em_todas_as_fontes), um título
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
        self, cliente: ClienteDeSite, identificador: str
    ) -> list[EpisodioRemoto]:
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
            # verdade (extractors/base.py::EpisodioRemoto).
            por_slug: dict[str, dict[str, EpisodioRemoto]] = {}
            for tag_a in soup.select(_SELETOR_LISTA_EPISODIOS):
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
                por_rotulo[rotulo] = EpisodioRemoto(rotulo=rotulo, numero=numero, url=href)
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
                return _ordenar_episodios(episodios_das_duas_versoes)

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

        return _ordenar_episodios(por_rotulo.values())

    def resolver_midia(self, cliente: ClienteDeSite, url_episodio: str) -> LinkDeMidia:
        """Confere que a página tem player e deixa o navegador tocá-la, devolvendo
        a URL de mídia que a própria página pediu.

        A conferência de iframes acontece antes da captura de propósito: página
        sem player é `EstruturaDoSiteMudou` (não retentável, aciona o fallback pro
        próximo site) e responde em ~1s, enquanto uma captura sem player só
        falharia depois de gastar `_TIMEOUT_CAPTURA_S` inteiro.
        """
        html = cliente.obter_html(url_episodio, timeout_s=_TIMEOUT_S)
        hosts_de_player = self._hosts_de_player(html, url_episodio)

        if not hosts_de_player:
            raise EstruturaDoSiteMudou(
                f"nenhum iframe de player em {url_episodio}", dominio=self.dominio
            )

        if not isinstance(cliente, ClienteComCaptura):
            # Contrato quebrado, não falha de site: `exige_navegador_para_midia`
            # é `True` aqui e `extractors/resiliencia.py` deveria ter entregue o
            # cliente de navegador. Retentar com o mesmo cliente repetiria o erro.
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


def _extrair_identificador(url_anime: str) -> str:
    return urllib.parse.urlparse(url_anime).path.split("/anime/", 1)[-1].strip("/")


# Marcador de versão isolado por `-` ou início/fim do slug — mesma fronteira
# de token de `extractors/versao.py`, só que aplicada a segmento de slug
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


def _ordenar_episodios(episodios: Iterable[EpisodioRemoto]) -> list[EpisodioRemoto]:
    """Numéricos em ordem crescente primeiro, rótulos não numéricos
    (numero=None) depois — sem seção separada na listagem (decisão do
    produto), só não intercalados entre os numéricos. Sem `rotulo` na chave:
    `sorted` é estável, então dois rótulos com o mesmo `numero` (ex. "7"/"07")
    mantêm a ordem em que apareceram na página — usar `rotulo` como
    desempate colocaria "07" antes de "7" (comparação lexicográfica,
    '0' < '7'), uma ordem arbitrária e não a "natural" da fonte."""
    return sorted(
        episodios,
        key=lambda episodio: (
            episodio.numero is None,
            episodio.numero if episodio.numero is not None else 0,
        ),
    )

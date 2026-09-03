"""Adapter MeusAnimes (ESPECIFICACAO.md §3A) — fonte WordPress + tema DooPlay,
mesma família do AnimesDrive, com prioridade de fallback intermediária: entra
depois do AnimeFire (padrão) e antes do AnimesDrive. Ao contrário do AnimesDrive,
nenhuma rota do site tem desafio Cloudflare — o cliente leve alcança busca,
listagem e resolução de mídia, então nenhum `exige_navegador*` é declarado.

A mídia sai de uma API aberta do player (`get-video.php` em
`serv01.meusdoramas.club`), que devolve um token do Blogger
(`blogger.com/video.g?token=...`); daí `extractors/blogger.py` resolve a URL
direta por HTTP puro, sem navegador, com teto de 720p (itag 22 — mp4 progressivo
muxado). As URLs de mídia do Google expiram em ~8h e ficam atadas ao IP que as
resolveu, então a resolução é sempre feita on-demand no momento do download,
nunca persistida.

Convenção de versão idêntica ao AnimeFire/AnimesDrive: dublado é outra entrada de
catálogo (slug com sufixo `-dublado`, título com " Dublado" no fim), então
`diferencia_versao=True` e a ausência de marcador nunca é indeterminada, é
`LEGENDADO`. Como nos demais adapters, `buscar` vazio é caso normal (título não
existe aqui) e erro de parsing vira `EstruturaDoSiteMudou` via
`except AttributeError`.
"""

import logging
import re
import urllib.parse

from bs4 import BeautifulSoup

from core.enums import VersaoEpisodio
from core.erros import EstruturaDoSiteMudou, FalhaDeExtracao, FonteNaoEncontrada
from extractors.base import EpisodioRemoto, ExtratorDeSite, LinkDeMidia, ResultadoBusca
from extractors.blogger import resolver_token
from extractors.cliente import ClienteDeSite
from extractors.versao import inferir_versao

logger = logging.getLogger(__name__)

_TIMEOUT_S = 15
# O site pagina a busca, mas a lista de prioridade de fallback só precisa do
# candidato certo, não da página inteira — teto e sem seguir paginação.
_MAX_RESULTADOS = 20

# Host da API de mídia (`get-video.php`) e do iframe que carrega o player.
# Desacoplado de `dominio`: pode rotacionar sem afetar dados já persistidos com
# `dominio="meusanimes"` como chave.
_HOST_PLAYER = "serv01.meusdoramas.club"
# `<iframe src="https://serv01.meusdoramas.club/#/video/{tmdb}/{temporada}/{episodio}/">`
_REGEX_PLAYER = re.compile(re.escape(_HOST_PLAYER) + r"/#/video/(\d+)/(\d+)/(\d+)")
# Número do episódio vem do path da URL (`/e/{slug}-{temporada}-episodio-{n}/`),
# não do texto do link (sempre "Episódio N", e ausente em rótulos não numéricos).
_REGEX_NUMERO_EPISODIO = re.compile(r"episodio-(\d+)")
# `blogger.com`/`*.blogger.com` + path `/video.g` — a forma de `videoUrl` que o
# `get-video.php` devolve na prática; qualquer outra string http(s) é usada
# direta, e qualquer outra estrutura vira `EstruturaDoSiteMudou`.
_HOST_BLOGGER = "blogger.com"


class MeusAnimesProvider(ExtratorDeSite):
    BASE_URL = "https://meusanimes.blog"

    @property
    def dominio(self) -> str:
        return "meusanimes"

    @property
    def exige_navegador(self) -> bool:
        return False

    @property
    def diferencia_versao(self) -> bool:
        return True

    def buscar(self, cliente: ClienteDeSite, titulo: str) -> list[ResultadoBusca]:
        consulta = " ".join(re.sub(r"[-_]+", " ", titulo).split())
        url = f"{self.BASE_URL}/?{urllib.parse.urlencode({'s': consulta})}"
        try:
            html = cliente.obter_html(url, timeout_s=_TIMEOUT_S)
        except FonteNaoEncontrada:
            # 404 numa busca sem resultado é "zero resultados", não falha —
            # mesmo desfecho do AnimeFire/AnimesDrive. `info`, não `warning`:
            # decidir se todas as variantes de busca se esgotaram é de quem as
            # itera (`extractors/busca/termos.py`), não deste método.
            logger.info("MeusAnimes: busca por %r não encontrou nada (404) em %s", titulo, url)
            return []

        try:
            soup = BeautifulSoup(html, "html.parser")
            resultados: list[ResultadoBusca] = []
            for artigo in soup.select("div.result-item article"):
                tag_link = artigo.select_one("div.details .title a[href]")
                if tag_link is None or "/a/" not in tag_link["href"]:
                    continue

                url_anime = urllib.parse.urljoin(self.BASE_URL, tag_link["href"])
                identificador = _extrair_identificador(url_anime)
                titulo_exibicao = " ".join(tag_link.get_text().split())
                if not identificador or not titulo_exibicao:
                    logger.warning(
                        "MeusAnimes: card de busca sem slug/título extraível (%s), ignorado",
                        url_anime,
                    )
                    continue

                tag_capa = artigo.select_one("div.image .thumbnail a img")
                src_capa = tag_capa.get("src") if tag_capa is not None else None
                capa_url = (
                    urllib.parse.urljoin(self.BASE_URL, src_capa.strip())
                    if src_capa and src_capa.strip()
                    else None
                )

                resultados.append(
                    ResultadoBusca(
                        titulo_exibicao=titulo_exibicao,
                        identificador=identificador,
                        url=url_anime,
                        capa_url=capa_url,
                        versao=(
                            inferir_versao(titulo_exibicao, identificador)
                            or VersaoEpisodio.LEGENDADO
                        ),
                    )
                )
            if not resultados:
                logger.info("MeusAnimes: nenhum resultado de busca encontrado em %s", url)
            return resultados[:_MAX_RESULTADOS]
        except AttributeError as excecao:
            raise EstruturaDoSiteMudou(
                f"estrutura da página de busca do MeusAnimes mudou: {excecao}",
                dominio=self.dominio,
            ) from excecao

    def listar_episodios(
        self, cliente: ClienteDeSite, identificador: str
    ) -> list[EpisodioRemoto]:
        url_anime = f"{self.BASE_URL}/a/{identificador}/"
        html = cliente.obter_html(url_anime, timeout_s=_TIMEOUT_S)

        try:
            soup = BeautifulSoup(html, "html.parser")
            bloco_seasons = soup.select_one("#seasons")
            temporadas = bloco_seasons.select("div.se-c") if bloco_seasons is not None else []
            vistos: set[str] = set()
            total_brutos = 0
            episodios: list[EpisodioRemoto] = []
            for temporada in temporadas:
                for tag_a in temporada.select("ul.episodios > li .episodiotitle a[href]"):
                    href = tag_a["href"]
                    total_brutos += 1
                    if href in vistos:
                        continue
                    vistos.add(href)

                    caminho = urllib.parse.urlparse(href).path
                    match = _REGEX_NUMERO_EPISODIO.search(caminho)
                    if match is not None:
                        rotulo = match.group(1)
                        numero = int(rotulo)
                    else:
                        rotulo = caminho.rstrip("/").rsplit("/", 1)[-1]
                        numero = None
                        logger.info(
                            "MeusAnimes: episódio com rótulo não numérico (%r) incluído"
                            " sem número em %s",
                            rotulo,
                            href,
                        )
                    episodios.append(EpisodioRemoto(rotulo=rotulo, numero=numero, url=href))
        except AttributeError as excecao:
            raise EstruturaDoSiteMudou(
                f"estrutura da listagem de episódios do MeusAnimes mudou: {excecao}",
                dominio=self.dominio,
            ) from excecao

        if bloco_seasons is None or not episodios:
            raise EstruturaDoSiteMudou(
                f"nenhum episódio encontrado para {identificador!r} no MeusAnimes"
                f" (#seasons {'ausente' if bloco_seasons is None else 'sem episódios'})",
                dominio=self.dominio,
            )

        if len(temporadas) > 1:
            # A maioria dos animes é temporada única (dub/leg são entradas
            # separadas, não temporadas). Havendo mais de uma, achata tudo em
            # ordem de documento — não tenta separar nem escolher uma.
            logger.info(
                "MeusAnimes: %d temporadas achatadas em ordem de documento para %r",
                len(temporadas),
                identificador,
            )

        logger.info(
            "MeusAnimes: %d episódio(s) brutos encontrados para %r, %d após dedup",
            total_brutos,
            identificador,
            len(episodios),
        )
        return _ordenar_episodios(episodios)

    def resolver_midia(self, cliente: ClienteDeSite, url_episodio: str) -> LinkDeMidia:
        """Resolve a mídia do episódio 100% por HTTP:

        1. lê `tmdb_id`/temporada/episódio do `src` do iframe do player;
        2. `GET get-video.php` (API aberta do player) → `{"success", "videoUrl"}`;
        3. `videoUrl` é um token do Blogger → `extractors/blogger.py` resolve a URL
           direta (teto 720p). Qualquer outra string http(s) é usada direta;
           estrutura que não seja nenhuma das duas vira `EstruturaDoSiteMudou`.
        """
        html = cliente.obter_html(url_episodio, timeout_s=_TIMEOUT_S)
        tmdb, temporada, episodio = self._ids_do_player(html, url_episodio)

        url_api = f"https://{_HOST_PLAYER}/posts/get-video.php?" + urllib.parse.urlencode(
            {"tmdb": tmdb, "season_number": temporada, "episode_number": episodio}
        )
        dados = cliente.obter_json(url_api, timeout_s=_TIMEOUT_S)
        video_url = self._video_url_de(dados, url_episodio)

        if _eh_token_blogger(video_url):
            return resolver_token(cliente, video_url, dominio=self.dominio)

        analisada = urllib.parse.urlparse(video_url)
        if analisada.scheme in ("http", "https") and analisada.netloc:
            logger.info(
                "MeusAnimes: videoUrl não é token do Blogger, usando direta em %s: %s",
                url_episodio,
                video_url,
            )
            return LinkDeMidia(url=video_url, cabecalhos={"User-Agent": cliente.user_agent()})

        raise EstruturaDoSiteMudou(
            f"get-video.php do MeusAnimes devolveu videoUrl não reconhecida para"
            f" {url_episodio}: {video_url!r}",
            dominio=self.dominio,
        )

    def _ids_do_player(self, html: str, url_episodio: str) -> tuple[str, str, str]:
        try:
            soup = BeautifulSoup(html, "html.parser")
            for iframe in soup.find_all("iframe", src=True):
                match = _REGEX_PLAYER.search(iframe["src"])
                if match is not None:
                    return match.group(1), match.group(2), match.group(3)
        except AttributeError as excecao:
            raise EstruturaDoSiteMudou(
                f"estrutura da página de episódio do MeusAnimes mudou: {excecao}"
                f" ({url_episodio})",
                dominio=self.dominio,
            ) from excecao
        raise EstruturaDoSiteMudou(
            f"nenhum iframe do player ({_HOST_PLAYER}) em {url_episodio}",
            dominio=self.dominio,
        )

    def _video_url_de(self, dados: dict | list, url_episodio: str) -> str:
        """`videoUrl` de `{"success": true, "videoUrl": ...}`.

        `success` ausente/falso ou `videoUrl` vazia é falha transitória
        (retentável — o player às vezes ainda não montou a fonte); `videoUrl`
        presente mas não-string (ex. lista `[{label, file}]`, nunca observada) é
        estrutura desconhecida → `EstruturaDoSiteMudou`.
        """
        bruto = dados.get("videoUrl") if isinstance(dados, dict) else None
        if isinstance(bruto, str):
            bruto = bruto.strip()
        if isinstance(dados, dict) and dados.get("success") is True and bruto:
            if isinstance(bruto, str):
                return bruto
            raise EstruturaDoSiteMudou(
                f"get-video.php do MeusAnimes devolveu videoUrl em formato inesperado"
                f" ({type(bruto).__name__}) para {url_episodio}",
                dominio=self.dominio,
            )
        raise FalhaDeExtracao(
            f"get-video.php do MeusAnimes não devolveu vídeo utilizável para"
            f" {url_episodio}: {dados!r}",
            dominio=self.dominio,
            permite_retentativa=True,
        )


def _extrair_identificador(url_anime: str) -> str:
    return urllib.parse.urlparse(url_anime).path.split("/a/", 1)[-1].strip("/")


def _eh_token_blogger(url: str) -> bool:
    analisada = urllib.parse.urlparse(url)
    hospedeiro = analisada.hostname or ""
    tem_host = hospedeiro == _HOST_BLOGGER or hospedeiro.endswith("." + _HOST_BLOGGER)
    return tem_host and analisada.path == "/video.g"


def _ordenar_episodios(episodios: list[EpisodioRemoto]) -> list[EpisodioRemoto]:
    """Numéricos em ordem crescente primeiro, rótulos não numéricos (numero=None)
    no fim — sem seção separada, só não intercalados. `sorted` é estável, então
    rótulos de mesmo número (temporadas achatadas) mantêm a ordem de documento."""
    return sorted(
        episodios,
        key=lambda episodio: (
            episodio.numero is None,
            episodio.numero if episodio.numero is not None else 0,
        ),
    )

"""Adapter MeusAnimes (ESPECIFICACAO.md §3A) — fonte WordPress + tema DooPlay,
mesma família do AnimesDrive, com prioridade de fallback intermediária: entra
depois do AnimeFire (padrão) e antes do AnimesDrive. Ao contrário do AnimesDrive,
nenhuma rota do site tem desafio Cloudflare — o cliente leve alcança busca,
listagem e resolução de mídia, então nenhum `exige_navegador*` é declarado.

A mídia sai de uma API aberta do player (`get-video.php` em
`serv01.meusdoramas.club`), que devolve um token do Blogger
(`blogger.com/video.g?token=...`); daí `fontes/adaptadores/blogger.py` resolve a URL
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
from dataclasses import replace

from bs4 import BeautifulSoup

from core.enums import VersaoEpisodio
from core.erros import EstruturaDoSiteMudou, FalhaDeExtracao, FonteNaoEncontrada
from fontes.adaptadores.base import (
    EpisodioRemoto,
    ExtratorDeSite,
    LinkDeMidia,
    ResultadoBusca,
    ordenar_episodios,
)
from fontes.adaptadores.blogger import resolver_token
from fontes.adaptadores.versao import inferir_versao
from fontes.rede.cliente import ClienteDeSite

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
# Temporada e número por temporada saem da MARCAÇÃO do tema DooPlay, não do
# texto do link (sempre "Episódio N", e ausente em rótulos não numéricos): cada
# `div.se-c` é uma temporada, com `<span class="se-t">{N}</span>` no cabeçalho
# (`div.se-q`), e cada `<li>` traz um `<div class="numerando">{temporada} -
# {episodio}</div>`. Antes o adapter lia isso do path da URL
# (`/e/{slug}-s{NN}-episodio-{n}/`), mas o MeusAnimes passou a servir
# `/e/{slug}-{temporada}-episodio-{n}/` (sem o `-s`) — a marcação do bloco é o
# sinal estável.
# Fallback pro número do episódio quando não há `div.numerando` legível.
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
            # itera (`fontes/busca/termos.py`), não deste método.
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

                resultados.append(
                    ResultadoBusca(
                        titulo_exibicao=titulo_exibicao,
                        identificador=identificador,
                        url=url_anime,
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
        self, cliente: ClienteDeSite, identificador: str, temporada: int | None
    ) -> list[EpisodioRemoto]:
        url_anime = f"{self.BASE_URL}/a/{identificador}/"
        html = cliente.obter_html(url_anime, timeout_s=_TIMEOUT_S)

        try:
            soup = BeautifulSoup(html, "html.parser")
            bloco_seasons = soup.select_one("#seasons")
            temporadas = bloco_seasons.select("div.se-c") if bloco_seasons is not None else []
            vistos: set[str] = set()
            total_brutos = 0
            # Uma lista por div.se-c (temporada), em ordem de documento. Cada
            # entrada é `(temporada, numero_na_temporada, EpisodioRemoto)` — a
            # temporada vem do cabeçalho do bloco (`.se-t`) e o número por
            # temporada do `.numerando`; só vivem nesta tupla interna:
            # `_numerar_absoluto` (sem `temporada`) e `_recortar_bloco` (com
            # `temporada`) as consomem e devolvem `EpisodioRemoto`s puros. O
            # dedup por href e a contagem de brutos são globais (atravessam os
            # blocos).
            blocos: list[list[tuple[int | None, int | None, EpisodioRemoto]]] = []
            for bloco_temporada in temporadas:
                temporada_do_bloco = _temporada_do_bloco(bloco_temporada)
                episodios_do_bloco: list[tuple[int | None, int | None, EpisodioRemoto]] = []
                for li in bloco_temporada.select("ul.episodios > li"):
                    tag_a = li.select_one(".episodiotitle a[href]")
                    if tag_a is None:
                        continue
                    href = tag_a["href"]
                    total_brutos += 1
                    if href in vistos:
                        continue
                    vistos.add(href)

                    caminho = urllib.parse.urlparse(href).path
                    # Temporada: cabeçalho do bloco (`.se-t`), com fallback pro
                    # 1º número do `.numerando` ("{T} - {E}"). Episódio dentro
                    # da temporada: último número do `.numerando`, com fallback
                    # pro `episodio-{n}` do path.
                    temp_numerando, numero_na_temporada = _temporada_e_episodio_do_numerando(li)
                    if numero_na_temporada is None:
                        match_numero = _REGEX_NUMERO_EPISODIO.search(caminho)
                        numero_na_temporada = (
                            int(match_numero.group(1)) if match_numero is not None else None
                        )
                    temporada_do_ep = (
                        temporada_do_bloco if temporada_do_bloco is not None else temp_numerando
                    )

                    if numero_na_temporada is not None:
                        rotulo = str(numero_na_temporada)
                        # Provisório (por temporada) — vira absoluto em
                        # `_numerar_absoluto`, ou fica assim no recorte.
                        numero = numero_na_temporada
                    else:
                        temporada_do_ep = None
                        rotulo = caminho.rstrip("/").rsplit("/", 1)[-1]
                        numero = None
                        logger.info(
                            "MeusAnimes: episódio com rótulo não numérico (%r) incluído"
                            " sem número em %s",
                            rotulo,
                            href,
                        )
                    tag_img = li.select_one(".imagen img")
                    src_thumb = tag_img.get("src", "").strip() if tag_img is not None else ""
                    episodios_do_bloco.append(
                        (
                            temporada_do_ep,
                            numero_na_temporada,
                            EpisodioRemoto(
                                rotulo=rotulo,
                                numero=numero,
                                url=href,
                                thumb_url=src_thumb or None,
                            ),
                        )
                    )
                blocos.append(episodios_do_bloco)
        except AttributeError as excecao:
            raise EstruturaDoSiteMudou(
                f"estrutura da listagem de episódios do MeusAnimes mudou: {excecao}",
                dominio=self.dominio,
            ) from excecao

        if bloco_seasons is None or not any(blocos):
            raise EstruturaDoSiteMudou(
                f"nenhum episódio encontrado para {identificador!r} no MeusAnimes"
                f" (#seasons {'ausente' if bloco_seasons is None else 'sem episódios'})",
                dominio=self.dominio,
            )

        if temporada is None:
            episodios = _numerar_absoluto(blocos, identificador)
        else:
            episodios = _recortar_bloco(blocos, temporada, identificador)

        logger.info(
            "MeusAnimes: %d episódio(s) brutos encontrados para %r, %d após dedup/recorte",
            total_brutos,
            identificador,
            len(episodios),
        )
        return ordenar_episodios(episodios)

    def resolver_midia(self, cliente: ClienteDeSite, url_episodio: str) -> LinkDeMidia:
        """Resolve a mídia do episódio 100% por HTTP:

        1. lê `tmdb_id`/temporada/episódio do `src` do iframe do player;
        2. `GET get-video.php` (API aberta do player) → `{"success", "videoUrl"}`;
        3. `videoUrl` é um token do Blogger → `fontes/adaptadores/blogger.py` resolve a URL
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


def _temporada_do_bloco(bloco: object) -> int | None:
    """Número da temporada de um `div.se-c` pelo `<span class="se-t">` do
    cabeçalho (`div.se-q`). `None` quando ausente ou não numérico."""
    tag = bloco.select_one(".se-q .se-t")
    if tag is None:
        return None
    match = re.search(r"\d+", tag.get_text())
    return int(match.group()) if match is not None else None


def _temporada_e_episodio_do_numerando(li: object) -> tuple[int | None, int | None]:
    """`(temporada, episodio)` do `div.numerando` de um `<li>` — o tema o
    renderiza como "{temporada} - {episodio}". Com só um número, é
    `(None, episodio)`; sem `div.numerando` ou sem dígito, `(None, None)`."""
    tag = li.select_one(".numerando")
    numeros = [int(n) for n in re.findall(r"\d+", tag.get_text())] if tag is not None else []
    if len(numeros) >= 2:
        return numeros[0], numeros[-1]
    if len(numeros) == 1:
        return None, numeros[0]
    return None, None


def _eh_token_blogger(url: str) -> bool:
    analisada = urllib.parse.urlparse(url)
    hospedeiro = analisada.hostname or ""
    tem_host = hospedeiro == _HOST_BLOGGER or hospedeiro.endswith("." + _HOST_BLOGGER)
    return tem_host and analisada.path == "/video.g"


# `(temporada, numero_na_temporada, EpisodioRemoto)` — a forma interna do parse
# de `listar_episodios`, antes de `_numerar_absoluto`/`_recortar_bloco`
# resolverem `numero` e descartarem os dois primeiros.
_BlocoDeParse = list[tuple[int | None, int | None, EpisodioRemoto]]


def _carimbo_confiavel(blocos: list[_BlocoDeParse]) -> list[int] | None:
    """As temporadas dos blocos (em ordem de documento) quando o marcador de
    temporada (`.se-t`/`.numerando`) é confiável, senão `None`. Confiável só
    quando TODO bloco `div.se-c` expõe exatamente uma temporada E as temporadas
    dos blocos são duas a duas distintas — é tudo-ou-nada de propósito: carimbar
    só alguns blocos numeraria episódios de forma inconsistente."""
    temporadas_por_bloco = [{t for t, _n, _ep in bloco if t is not None} for bloco in blocos]
    if not all(len(t) == 1 for t in temporadas_por_bloco):
        return None
    temporadas = [next(iter(t)) for t in temporadas_por_bloco]
    if len(set(temporadas)) != len(blocos):
        return None
    return temporadas


def _numerar_absoluto(blocos: list[_BlocoDeParse], identificador: str) -> list[EpisodioRemoto]:
    """Reescreve o `numero` provisório (por temporada) para o número ABSOLUTO
    contínuo entre temporadas, quando o marcador de temporada é confiável
    (`_carimbo_confiavel`); senão devolve a lista achatada em ordem de documento
    com o `numero` cru.

    O `numero` absoluto é `offset_do_bloco + numero_na_temporada`, com o
    `offset` acumulando `max(numero_na_temporada)` dos blocos anteriores em
    ordem de documento (contador por offset, não posicional — resiste a rótulo
    não numérico no meio e a buraco de numeração). Temporada única → `offset=0`
    → `numero` idêntico ao comportamento anterior.
    """
    blocos = [bloco for bloco in blocos if bloco]
    if not blocos:
        return []

    temporadas = _carimbo_confiavel(blocos)
    if temporadas is None:
        if len(blocos) > 1:
            logger.warning(
                "MeusAnimes: %d temporadas sem marcador confiável para %r —"
                " achatando em ordem de documento",
                len(blocos),
                identificador,
            )
        return [ep for bloco in blocos for _t, _n, ep in bloco]

    resultado: list[EpisodioRemoto] = []
    offset = 0
    for bloco in blocos:
        numeros_no_bloco = [n for _t, n, _ep in bloco if n is not None]
        for _t, n, ep in bloco:
            resultado.append(replace(ep, numero=offset + n) if n is not None else ep)
        offset += max(numeros_no_bloco) if numeros_no_bloco else 0
    logger.info(
        "MeusAnimes: %d temporada(s) reconhecida(s) para %r (temporadas: %s) —"
        " numeração absoluta contínua",
        len(blocos),
        identificador,
        sorted(temporadas),
    )
    return resultado


def _recortar_bloco(
    blocos: list[_BlocoDeParse], temporada: int, identificador: str
) -> list[EpisodioRemoto]:
    """Recorta para `temporada` usando o marcador de temporada do bloco
    (`.se-t`/`.numerando`). Contrato de degradação de
    `ExtratorDeSite.listar_episodios`: sem marcador confiável
    (`_carimbo_confiavel`) a fonte é tratada como "uma temporada só" e a
    listagem inteira volta numerada contínua; com marcador, devolve só o bloco
    da temporada pedida (com `numero` já por temporada), ou `[]`/listagem
    inteira conforme a temporada exista ou não entre as disponíveis."""
    blocos = [bloco for bloco in blocos if bloco]
    if not blocos:
        return []

    temporadas = _carimbo_confiavel(blocos)
    if temporadas is None:
        logger.info(
            "MeusAnimes: temporada %d pedida mas o marcador de temporada não é confiável"
            " para %r — devolvendo a listagem inteira",
            temporada,
            identificador,
        )
        return _numerar_absoluto(blocos, identificador)

    if temporada not in temporadas:
        if len(temporadas) == 1:
            logger.info(
                "MeusAnimes: temporada %d pedida não bate o marcador da fonte (única: %d)"
                " para %r — devolvendo a listagem inteira",
                temporada,
                temporadas[0],
                identificador,
            )
            return _numerar_absoluto(blocos, identificador)
        logger.warning(
            "MeusAnimes: temporada %d ausente na fonte para %r (disponíveis: %s) —"
            " devolvendo lista vazia",
            temporada,
            identificador,
            sorted(temporadas),
        )
        return []

    bloco_alvo = blocos[temporadas.index(temporada)]
    return [
        replace(ep, numero=n, recortado_pela_fonte=True) if n is not None else ep
        for _t, n, ep in bloco_alvo
    ]

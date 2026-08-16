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
import re

from bs4 import BeautifulSoup

from core.erros import EstruturaDoSiteMudou
from extractors.base import EpisodioRemoto, ExtratorDeSite, LinkDeMidia, ResultadoBusca
from extractors.cliente import ClienteDeSite

logger = logging.getLogger(__name__)

_TIMEOUT_S = 15
_SUFIXO_TODOS_EPISODIOS = "-todos-os-episodios"
_REGEX_SUFIXO_QUALIDADE = re.compile(r"\s+\d+\.\d+\s+[A-Z\d]+$")


class AnimeFireProvider(ExtratorDeSite):
    BASE_URL = "https://animefire.io"

    @property
    def dominio(self) -> str:
        return "animefire.io"

    @property
    def exige_navegador(self) -> bool:
        return False

    def buscar(self, cliente: ClienteDeSite, titulo: str) -> list[ResultadoBusca]:
        busca_formatada = titulo.strip().replace(" ", "-").lower()
        url = f"{self.BASE_URL}/pesquisar/{busca_formatada}"
        html = cliente.obter_html(url, timeout_s=_TIMEOUT_S)

        try:
            soup = BeautifulSoup(html, "html.parser")
            resultados = []
            for caixa in soup.find_all("div", class_="divCardUltimosEps"):
                tag_link = caixa.find("a")
                if tag_link is None:
                    continue
                href = tag_link.get("href")
                if not href:
                    continue

                titulo_bruto = tag_link.text.strip()
                titulo_limpo = _REGEX_SUFIXO_QUALIDADE.sub("", titulo_bruto).strip()
                titulo_limpo = titulo_limpo.replace("\xa0", " ")

                url_anime = self._absolutizar(href)
                resultados.append(
                    ResultadoBusca(
                        titulo_exibicao=titulo_limpo,
                        identificador=self._extrair_slug(url_anime),
                        url=url_anime,
                    )
                )
            return resultados
        except AttributeError as excecao:
            raise EstruturaDoSiteMudou(
                f"estrutura da página de busca do AnimeFire mudou: {excecao}",
                dominio=self.dominio,
            ) from excecao

    def listar_episodios(
        self, cliente: ClienteDeSite, identificador: str
    ) -> list[EpisodioRemoto]:
        url_anime = f"{self.BASE_URL}/animes/{identificador}{_SUFIXO_TODOS_EPISODIOS}"
        html = cliente.obter_html(url_anime, timeout_s=_TIMEOUT_S)
        marcador = f"/animes/{identificador}/"

        try:
            soup = BeautifulSoup(html, "html.parser")
            vistos: set[str] = set()
            episodios: list[EpisodioRemoto] = []
            for tag_a in soup.find_all("a", href=True):
                href = tag_a["href"]
                if marcador not in href or href in vistos:
                    continue
                vistos.add(href)

                numero_bruto = href.rstrip("/").rsplit("/", 1)[-1]
                try:
                    numero = int(numero_bruto)
                except ValueError:
                    logger.warning(
                        "AnimeFire: número de episódio não numérico ignorado (%r) em %s",
                        numero_bruto,
                        href,
                    )
                    continue

                episodios.append(EpisodioRemoto(numero=numero, url=self._absolutizar(href)))
        except AttributeError as excecao:
            raise EstruturaDoSiteMudou(
                f"estrutura da listagem de episódios do AnimeFire mudou: {excecao}",
                dominio=self.dominio,
            ) from excecao

        if not episodios:
            raise EstruturaDoSiteMudou(
                f"nenhum episódio encontrado para {identificador!r} no AnimeFire",
                dominio=self.dominio,
            )

        # AnimeFire já lista os episódios do mais antigo pro mais novo na página
        # (confirmado contra o site real) — sem reverter aqui.
        return episodios

    def resolver_midia(self, cliente: ClienteDeSite, url_episodio: str) -> LinkDeMidia:
        html = cliente.obter_html(url_episodio, timeout_s=_TIMEOUT_S)

        try:
            soup = BeautifulSoup(html, "html.parser")
            video_tag = soup.find("video")
            json_url = video_tag.get("data-video-src") if video_tag is not None else None
        except AttributeError as excecao:
            raise EstruturaDoSiteMudou(
                f"estrutura da página de episódio do AnimeFire mudou: {excecao}",
                dominio=self.dominio,
            ) from excecao

        if not json_url:
            raise EstruturaDoSiteMudou(
                f"AnimeFire não expôs data-video-src em {url_episodio}", dominio=self.dominio
            )

        dados = cliente.obter_json(json_url, timeout_s=_TIMEOUT_S)
        qualidades = dados.get("data") if isinstance(dados, dict) else None
        if not isinstance(qualidades, list) or not qualidades:
            raise EstruturaDoSiteMudou(
                f"AnimeFire não devolveu qualidades de vídeo para {url_episodio}",
                dominio=self.dominio,
            )

        ultima_qualidade = qualidades[-1]
        link_direto = (
            ultima_qualidade.get("src") if isinstance(ultima_qualidade, dict) else None
        )
        if not link_direto:
            raise EstruturaDoSiteMudou(
                f"AnimeFire não devolveu link de vídeo para {url_episodio}", dominio=self.dominio
            )

        return LinkDeMidia(
            url=link_direto,
            cabecalhos={"Referer": url_episodio, "User-Agent": cliente.user_agent()},
        )

    def _absolutizar(self, url: str) -> str:
        if url.startswith("http://") or url.startswith("https://"):
            return url
        return f"{self.BASE_URL}/{url.lstrip('/')}"

    def _extrair_slug(self, url_anime: str) -> str:
        segmento = url_anime.rstrip("/").rsplit("/", 1)[-1]
        if segmento.endswith(_SUFIXO_TODOS_EPISODIOS):
            segmento = segmento[: -len(_SUFIXO_TODOS_EPISODIOS)]
        return segmento

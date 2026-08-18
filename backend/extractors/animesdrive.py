"""Adapter AnimesDrive (ESPECIFICACAO.md §3A) — segundo site da lista de
prioridade de fallback (`extractors/registro.py`), atrás do AnimeFire.

Fecha só o lado de busca/catálogo (Strategy Pattern completo: `buscar` e
`listar_episodios`) — `resolver_midia` não resolve nada ainda. Achados abaixo,
testados ao vivo contra animesdrive.online (site de produção) em 2026-08-15:

- `blogger.com/video.g?token=...`: hoje é SPA do Google (framework "Wiz",
  `WIZ_global_data` no HTML) — sem URL de vídeo estática no HTML; a técnica
  antiga de HTML com config de vídeo embutida não existe mais nessa página.
- `animeshd.cloud` e `animes.strp2p.com`: mesmo player de terceiros (bundle
  JS de ~1MB idêntico nos dois). O player lê `window.location.hash.slice(1)`
  como id e chama `GET /api/v1/video?id=<hash>&...`; a resposta vem cifrada
  em AES-CBC via `crypto.subtle` — decifrar exige extrair chave/IV de um
  bundle minificado/ofuscado, reverse engineering real, fora do escopo desta
  fase.
- Caminhos conhecidos pra resolver isso no futuro: navegador executando o JS,
  ou reverse engineering do bundle. Ambos fora de escopo por decisão explícita
  do usuário em 2026-08-15 — registrado aqui pra não parecer esquecimento nem
  convite a implementar por conta própria depois.
- Restrição de orçamento pra quem implementar o primeiro resolver: precisa
  caber dentro do teto de `extractors/resiliencia.py::_TETO_ESPERA_S` (hoje
  45s) somado ao tempo já gasto no fetch do HTML do episódio (~15s), ou
  ajustar esse teto de forma consciente — não por acidente.
- Quando um resolver existir: o `Referer` do `LinkDeMidia` deve ser a URL do
  **embed** (não a do episódio) — diferente do AnimeFire, porque é a página
  que legitimamente tocaria aquele link de terceiro.

Como no AnimeFire, `buscar` vazio é caso normal, e erro de parsing vira
`EstruturaDoSiteMudou` via `except AttributeError`.
"""

import logging
import re
import urllib.parse

from bs4 import BeautifulSoup

from core.erros import EstruturaDoSiteMudou, FonteNaoEncontrada
from extractors.base import EpisodioRemoto, ExtratorDeSite, LinkDeMidia, ResultadoBusca
from extractors.cliente import ClienteDeSite

logger = logging.getLogger(__name__)

_TIMEOUT_S = 15
_HOSTS_YOUTUBE = ("youtube.com", "youtu.be")
# `/?` antes do `$`: URL de episódio com barra final (`.../episodio-7/`) é
# válida e comum (link relativo normalizado por navegador/CMS) — sem isso o
# `numero` some inteiro da listagem em vez de só perder a barra.
_REGEX_EPISODIO = re.compile(r"^/episodio/(?P<slug>.+?)-episodio-(?P<numero>[^/]+)/?$")

# Ponto de extensão nomeado para quando um resolver de mídia existir (ver
# docstring do módulo) — vazio de propósito, sem laço de despacho sobre uma
# tupla que ainda não tem nada a percorrer.
_RESOLVEDORES: tuple = ()


class AnimesDriveProvider(ExtratorDeSite):
    BASE_URL = "https://animesdrive.online"

    @property
    def dominio(self) -> str:
        return "animesdrive.online"

    @property
    def exige_navegador(self) -> bool:
        return False

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
                tag_capa = artigo.select_one(".thumb img")
                src_capa = tag_capa.get("src") if tag_capa else None
                capa_url = (
                    urllib.parse.urljoin(self.BASE_URL, src_capa.strip())
                    if src_capa and src_capa.strip()
                    else None
                )

                resultados.append(
                    ResultadoBusca(
                        titulo_exibicao=" ".join(tag_titulo.get_text().split()),
                        identificador=_extrair_identificador(url_anime),
                        url=url_anime,
                        capa_url=capa_url,
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
        prefixo_slug = identificador.removesuffix("-dublado")

        try:
            soup = BeautifulSoup(html, "html.parser")
            total_brutos = 0
            # Chave de dedup é o rótulo cru (string), não `int(numero)`: "7" e
            # "07" não são necessariamente o mesmo episódio, e colapsar os dois
            # por valor inteiro perderia um episódio de verdade (extractors/
            # base.py::EpisodioRemoto).
            por_rotulo: dict[str, EpisodioRemoto] = {}
            for tag_a in soup.find_all("a", href=True):
                href = tag_a["href"]
                match = _REGEX_EPISODIO.match(urllib.parse.urlparse(href).path)
                if match is None or not match.group("slug").startswith(prefixo_slug):
                    continue
                total_brutos += 1

                rotulo = match.group("numero")
                try:
                    numero = int(rotulo)
                except ValueError:
                    numero = None

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

        if not por_rotulo:
            raise EstruturaDoSiteMudou(
                f"nenhum episódio encontrado para {identificador!r} no AnimesDrive",
                dominio=self.dominio,
            )

        logger.info(
            "AnimesDrive: %d episódio(s) brutos encontrados para %r, %d após dedup",
            total_brutos,
            identificador,
            len(por_rotulo),
        )

        # Numéricos em ordem crescente primeiro, rótulos não numéricos
        # (numero=None) depois — sem seção separada na listagem (decisão do
        # produto), só não intercalados entre os numéricos. Sem `rotulo` na
        # chave: `sorted` é estável, então dois rótulos com o mesmo `numero`
        # (ex. "7"/"07") mantêm a ordem em que apareceram na página — usar
        # `rotulo` como desempate colocaria "07" antes de "7" (comparação
        # lexicográfica, '0' < '7'), uma ordem arbitrária e não a "natural"
        # da fonte.
        return sorted(
            por_rotulo.values(),
            key=lambda episodio: (
                episodio.numero is None,
                episodio.numero if episodio.numero is not None else 0,
            ),
        )

    def resolver_midia(self, cliente: ClienteDeSite, url_episodio: str) -> LinkDeMidia:
        html = cliente.obter_html(url_episodio, timeout_s=_TIMEOUT_S)

        try:
            soup = BeautifulSoup(html, "html.parser")
            candidatos = []
            for iframe in soup.find_all("iframe", src=True):
                src = iframe["src"].strip()
                if not src or src == "about:blank":
                    continue
                if src.startswith("//"):
                    src = f"https:{src}"
                host = urllib.parse.urlparse(src).netloc
                if any(marcador in host for marcador in _HOSTS_YOUTUBE):
                    continue
                candidatos.append(src)
        except AttributeError as excecao:
            raise EstruturaDoSiteMudou(
                f"estrutura da página de episódio do AnimesDrive mudou: {excecao}",
                dominio=self.dominio,
            ) from excecao

        if not candidatos:
            raise EstruturaDoSiteMudou(
                f"nenhum iframe de player em {url_episodio}", dominio=self.dominio
            )

        hosts = [urllib.parse.urlparse(candidato).netloc for candidato in candidatos]
        raise EstruturaDoSiteMudou(
            f"nenhum host de mídia suportado ainda em {url_episodio}: {hosts}",
            dominio=self.dominio,
        )


def _extrair_identificador(url_anime: str) -> str:
    return urllib.parse.urlparse(url_anime).path.split("/anime/", 1)[-1].strip("/")

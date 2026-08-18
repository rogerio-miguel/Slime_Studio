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

from core.erros import EstruturaDoSiteMudou, FonteNaoEncontrada
from core.texto import slugificar
from extractors.base import EpisodioRemoto, ExtratorDeSite, LinkDeMidia, ResultadoBusca
from extractors.cliente import ClienteDeSite

logger = logging.getLogger(__name__)

_TIMEOUT_S = 15
_SUFIXO_TODOS_EPISODIOS = "-todos-os-episodios"
_REGEX_SUFIXO_QUALIDADE = re.compile(r"\s+\d+\.\d+\s+[A-Z\d]+$")
# `/pesquisar/<termo>` do AnimeFire casa por prefixo do título principal, não
# por texto completo — qualquer palavra de um subtítulo depois de ":"/"~"/" - "
# já zera o resultado (confirmado ao vivo: título com subtítulo devolve 0
# resultados mesmo sem o ":" literal, mas o título truncado antes do separador
# encontra o card normalmente). Espaço obrigatório em pelo menos um lado do
# separador — evita cortar hífen interno de palavra composta (ex.
# "Keishou-sen") E evita tratar ":"/"~" colado ao texto (ex. "Re:Zero") como
# separador de subtítulo — esse segundo caso truncaria pra um prefixo curto
# demais ("Re") e arriscaria casar o card de outro anime por prefix-match,
# trocando silenciosamente "não encontrei" por "encontrei o errado".
_REGEX_SEPARADOR_SUBTITULO = re.compile(r"\s*[:~]\s+|\s+[:~]\s*|\s+[-–—]\s+")


class AnimeFireProvider(ExtratorDeSite):
    BASE_URL = "https://animefire.io"

    @property
    def dominio(self) -> str:
        return "animefire.io"

    @property
    def exige_navegador(self) -> bool:
        return False

    def buscar(self, cliente: ClienteDeSite, titulo: str) -> list[ResultadoBusca]:
        candidatos = _candidatos_de_busca(titulo)
        for i, candidato in enumerate(candidatos):
            e_ultimo = i == len(candidatos) - 1
            resultados = self._buscar_termo(cliente, candidato, e_ultimo=e_ultimo)
            if resultados:
                if i > 0:
                    logger.info(
                        "AnimeFire: busca por %r vazia, encontrado com título"
                        " truncado no subtítulo (%r)",
                        titulo,
                        candidato,
                    )
                return resultados
        return []

    def _buscar_termo(
        self, cliente: ClienteDeSite, termo: str, *, e_ultimo: bool
    ) -> list[ResultadoBusca]:
        # `slugificar` (não um `.replace(" ", "-")` manual): o slug real do
        # AnimeFire colapsa qualquer sequência de caracteres não-alfanuméricos
        # (vírgula, apostrofo, etc.) num único hífen, não só espaço — uma
        # busca com vírgula no título (ex. "... Kimi to, Me ni...") virava
        # `.../kimi-to,-me-ni...` (vírgula preservada) e nunca casava com o
        # card real `.../kimi-to-me-ni...`. Mesma convenção já usada em
        # `extractors/resolucao.py` pra casar candidato com slug local.
        busca_formatada = slugificar(termo)
        url = f"{self.BASE_URL}/pesquisar/{busca_formatada}"
        try:
            html = cliente.obter_html(url, timeout_s=_TIMEOUT_S)
        except FonteNaoEncontrada:
            # `/pesquisar/<termo>` do AnimeFire responde HTTP 404 quando a busca
            # não encontra nada (comportamento herdado do Slime_Shell_Web, que já
            # tratava isso explicitamente) — não é falha, é "zero resultados".
            # Cinto e suspensório: `FonteNaoEncontrada` já não conta como falha
            # no circuit breaker (`core/erros.py`), mas capturar aqui deixa
            # explícito por que esse 404 específico é normal. `warning` só na
            # última tentativa — título com subtítulo 404 no candidato completo
            # por design (`_candidatos_de_busca`), aí o fallback resolve; isso
            # é esperado, não um sinal de alerta.
            log = logger.warning if e_ultimo else logger.info
            log("AnimeFire: busca por %r não encontrou nada (404) em %s", termo, url)
            return []

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
                        # AnimeFire não expõe imagem nenhuma na página de busca
                        # (confirmado ao vivo e no código de referência
                        # Slime_Shell_Web) — `capa_url=None` via default do
                        # dataclass, não falta de parsing. Enriquecimento por
                        # metadado de provedor externo mora em
                        # `api/servicos/busca.py::enriquecer_capas`.
                    )
                )
            if not resultados:
                # info, não warning: com a busca em paralelo em todos os sites
                # (extractors/servico.py::buscar_em_todas_as_fontes), um título
                # existir só num dos dois é o caso comum, não uma falha — não dá
                # pra distinguir "não achei mesmo" de "estrutura mudou" só por
                # contagem zero, então não escala pra warning (isso viraria
                # ruído em toda busca parcial). Falha de parsing de verdade
                # ainda sobe como `EstruturaDoSiteMudou` via `except AttributeError`.
                logger.info("AnimeFire: nenhum card de resultado encontrado em %s", url)
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
            total_brutos = 0
            episodios: list[EpisodioRemoto] = []
            for tag_a in soup.find_all("a", href=True):
                href = tag_a["href"]
                if marcador not in href:
                    continue
                total_brutos += 1
                if href in vistos:
                    continue
                vistos.add(href)

                # `rotulo` é o próprio texto do path (não o texto visível do
                # link) — dedup acontece por `href` acima, não por este valor;
                # aqui só decide se o episódio tem `numero` capturável ou
                # segue com `numero=None` (rótulo não numérico, ex. "especial"
                # — aparece normalmente na lista, só não é capturável ainda).
                rotulo = href.rstrip("/").rsplit("/", 1)[-1]
                try:
                    numero = int(rotulo)
                except ValueError:
                    numero = None
                    logger.info(
                        "AnimeFire: episódio com rótulo não numérico (%r) incluído sem número"
                        " em %s",
                        rotulo,
                        href,
                    )

                episodios.append(
                    EpisodioRemoto(rotulo=rotulo, numero=numero, url=self._absolutizar(href))
                )
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

        logger.info(
            "AnimeFire: %d episódio(s) brutos encontrados para %r, %d após dedup",
            total_brutos,
            identificador,
            len(episodios),
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


def _candidatos_de_busca(titulo: str) -> list[str]:
    """Título completo primeiro (caso comum, sem subtítulo ou onde a busca já
    funciona); se houver separador de subtítulo, o título truncado antes dele
    entra como 2º candidato — só usado se o 1º não achar nada (`buscar`)."""
    titulo = titulo.strip()
    candidatos = [titulo]
    principal = _REGEX_SEPARADOR_SUBTITULO.split(titulo, maxsplit=1)[0].strip()
    if principal and principal != titulo:
        candidatos.append(principal)
    return candidatos

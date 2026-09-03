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

from core.enums import VersaoEpisodio
from core.erros import EstruturaDoSiteMudou, FonteNaoEncontrada
from core.texto import slugificar
from extractors.base import EpisodioRemoto, ExtratorDeSite, LinkDeMidia, ResultadoBusca
from extractors.cliente import ClienteDeSite
from extractors.qualidade import NivelDeQualidade, qualidade_do_rotulo
from extractors.versao import inferir_versao

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
            # explícito por que esse 404 específico é normal. Sempre `info` —
            # decidir se esgotou todas as variantes de busca (e por isso vale
            # `warning`) passou a ser responsabilidade de quem itera variantes
            # (`extractors/busca/termos.py::variantes_de_busca`), não deste método.
            logger.info("AnimeFire: busca por %r não encontrou nada (404) em %s", termo, url)
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
                identificador = self._extrair_slug(url_anime)
                resultados.append(
                    ResultadoBusca(
                        titulo_exibicao=titulo_limpo,
                        identificador=identificador,
                        url=url_anime,
                        # AnimeFire não expõe imagem nenhuma na página de busca
                        # (confirmado ao vivo e no código de referência
                        # Slime_Shell_Web) — `capa_url=None` via default do
                        # dataclass, não falta de parsing. Enriquecimento por
                        # metadado de provedor externo mora em
                        # `api/servicos/capas.py::enriquecer_capas`.
                        #
                        # Mesma convenção do AnimesDrive (`animesdrive.py`):
                        # dublado sempre marcado, ausência de marcador aqui
                        # nunca é indeterminado, é `LEGENDADO`.
                        versao=inferir_versao(titulo_limpo, identificador)
                        or VersaoEpisodio.LEGENDADO,
                    )
                )
            if not resultados:
                # info, não warning: com a busca em paralelo em todos os sites
                # (extractors/busca/servico.py::buscar_por_site_com_variantes), um título
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

                # Thumb do AnimeFire tem URL determinística (confirmada ao vivo):
                # `/img/video/{identificador}/{numero}.webp` — só montável quando
                # o rótulo é numérico, `None` para "Especial" e afins.
                thumb_url = (
                    f"{self.BASE_URL}/img/video/{identificador}/{numero}.webp"
                    if numero is not None
                    else None
                )
                episodios.append(
                    EpisodioRemoto(
                        rotulo=rotulo,
                        numero=numero,
                        url=self._absolutizar(href),
                        thumb_url=thumb_url,
                    )
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
        """Resolve a URL de vídeo de maior qualidade dentre `data[]`.

        Classifica cada entrada pelo `label` (`extractors/qualidade.py`) em vez
        de confiar em `qualidades[-1]` — suposição não verificada de que o
        array vem em ordem crescente; se o AnimeFire inverter a ordem um dia, a
        posição baixaria SD acreditando ser a melhor, silenciosamente.
        Desempate por posição (a última entre iguais vence), o que preserva o
        comportamento de hoje quando todos os rótulos empatam ou são
        desconhecidos.

        Sem piso mínimo de propósito (diverge do AnimesDrive): o AnimeFire é a
        fonte padrão e frequentemente só oferece SD para catálogo antigo —
        recusar isso transformaria "assiste em SD" em "não assiste", uma
        regressão de produto. Onde não há escolha, o piso só quebra o que
        funciona.
        """
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

        melhor_qualidade = _entrada_de_maior_qualidade(qualidades)
        link_direto = (
            melhor_qualidade.get("src") if isinstance(melhor_qualidade, dict) else None
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


def _entrada_de_maior_qualidade(qualidades: list) -> object:
    """Escolhe a entrada de `qualidades` de maior nível classificado (`label`),
    desempatando por posição — a última entre iguais vence, preservando o
    comportamento de hoje (`qualidades[-1]`) quando todos os rótulos empatam
    ou são desconhecidos."""
    melhor_entrada = qualidades[0]
    melhor_nivel = _nivel_da_entrada(melhor_entrada)
    for entrada in qualidades[1:]:
        nivel = _nivel_da_entrada(entrada)
        if nivel >= melhor_nivel:
            melhor_nivel = nivel
            melhor_entrada = entrada
    return melhor_entrada


def _nivel_da_entrada(entrada: object) -> NivelDeQualidade:
    rotulo = entrada.get("label", "") if isinstance(entrada, dict) else ""
    return qualidade_do_rotulo(rotulo if isinstance(rotulo, str) else "")

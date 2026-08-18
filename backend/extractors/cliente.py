"""Cliente HTTP para extratores de site (ESPECIFICACAO.md §3A).

`ClienteDeSite` é `Protocol` (colaborador estrutural que os adapters recebem
por injeção, não hierarquia — D2/D3 do plano) — `ClienteLeve` e
`ClienteNavegador` implementam o mesmo contrato sem herdar nada em comum.

Quem escolhe entre os dois é `extractors/resiliencia.py`, nunca o adapter: o
leve é o padrão (rápido, sem JS), o navegador entra quando o site exige
(`ExtratorDeSite.exige_navegador`/`exige_navegador_para_midia`) ou como escalada
de `SessaoRejeitada`.

Este módulo é a **única** fronteira onde exceção de `requests`/`cloudscraper`/
DrissionPage pode existir: tudo que sai daqui já é `FalhaDeExtracao` (ou
subclasse) — nenhum chamador precisa saber o que é `requests.Timeout`.
"""

import logging
import os
import shutil
import time
import urllib.parse
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import cloudscraper
import requests

from core.erros import FalhaDeExtracao, FonteNaoEncontrada, SessaoRejeitada

logger = logging.getLogger(__name__)

# Marcadores de desafio Cloudflare ainda em curso (ESPECIFICACAO.md §9, linha do
# risco "sessão de bypass expirada"): header `cf-mitigated`, `<title>Just a
# moment` e o parâmetro `cf_chl_opt` do script de verificação.
_MARCADOR_HEADER_CLOUDFLARE = "cf-mitigated"
_MARCADORES_CORPO_CLOUDFLARE = ("Just a moment", "cf_chl_opt")


class ClienteDeSite(Protocol):
    """Contrato estrutural que os adapters (`ExtratorDeSite`) recebem por injeção."""

    def obter_html(self, url: str, *, timeout_s: int) -> str: ...
    def obter_json(self, url: str, *, timeout_s: int) -> dict | list: ...
    def cookies(self) -> dict[str, str]: ...
    def user_agent(self) -> str: ...
    def fechar(self) -> None: ...


@dataclass(frozen=True, slots=True)
class MidiaCapturada:
    """URL de mídia observada saindo da própria página, com os cabeçalhos que o
    navegador de fato enviou nessa requisição — não uma reconstrução nossa do que
    o servidor *deveria* aceitar."""

    url: str
    cabecalhos: dict[str, str]


@runtime_checkable
class ClienteComCaptura(Protocol):
    """Capacidade extra que só o cliente de navegador tem (`ClienteLeve` não roda
    JS, então não tem como observar o player montando a mídia).

    Adapter que precisa disso declara `exige_navegador_para_midia = True` e
    confere a capacidade com `isinstance` antes de usar — o contrato base
    (`ClienteDeSite`) segue sendo o mínimo que todo adapter pode assumir."""

    def capturar_midia(
        self, url_pagina: str, *, hosts_ignorados: tuple[str, ...], timeout_s: int
    ) -> MidiaCapturada: ...


class ClienteLeve:
    """Sessão `cloudscraper` pré-carregada com cookies de `SessaoBypass`, se houver."""

    def __init__(
        self, *, cookies: dict[str, str] | None = None, user_agent: str | None = None
    ) -> None:
        self._sessao = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "windows", "desktop": True}
        )
        if cookies:
            self._sessao.cookies.update(cookies)
        if user_agent:
            self._sessao.headers["User-Agent"] = user_agent

    def obter_html(self, url: str, *, timeout_s: int) -> str:
        resposta = self._requisitar(url, timeout_s=timeout_s)
        return resposta.text

    def obter_json(self, url: str, *, timeout_s: int) -> dict | list:
        resposta = self._requisitar(url, timeout_s=timeout_s)
        try:
            return resposta.json()
        except requests.JSONDecodeError as excecao:
            raise FalhaDeExtracao(
                f"resposta de {url} não é JSON válido", permite_retentativa=True
            ) from excecao

    def cookies(self) -> dict[str, str]:
        return self._sessao.cookies.get_dict()

    def user_agent(self) -> str:
        return self._sessao.headers.get("User-Agent", "")

    def fechar(self) -> None:
        self._sessao.close()

    def _requisitar(self, url: str, *, timeout_s: int) -> requests.Response:
        try:
            resposta = self._sessao.get(url, timeout=timeout_s)
        except (requests.ConnectionError, requests.Timeout) as excecao:
            raise FalhaDeExtracao(
                f"falha de rede ao acessar {url}: {excecao}", permite_retentativa=True
            ) from excecao
        except requests.RequestException as excecao:
            raise FalhaDeExtracao(
                f"falha ao acessar {url}: {excecao}", permite_retentativa=True
            ) from excecao

        if resposta.status_code == 404:
            raise FonteNaoEncontrada(f"não encontrado: {url}")
        if resposta.status_code in (403, 503) and _eh_desafio_cloudflare(resposta):
            raise SessaoRejeitada(f"sessão rejeitada (desafio Cloudflare) em {url}")
        if not resposta.ok:
            raise FalhaDeExtracao(
                f"HTTP {resposta.status_code} em {url}", permite_retentativa=True
            )
        return resposta


# Binário do navegador: procurado no PATH, na ordem abaixo, ou apontado por
# `SLIME_NAVEGADOR_BIN`. Não passa por `core/config.py` de propósito — `Config`
# nunca chega em `extractors/resiliencia.py` (quem instancia o cliente), e
# plumbar Config até aqui só por causa de um caminho de binário acoplaria a
# camada de extração ao bootstrap da aplicação.
_VARIAVEL_BINARIO_NAVEGADOR = "SLIME_NAVEGADOR_BIN"
_BINARIOS_DE_NAVEGADOR = (
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
    "brave-browser",
    "microsoft-edge",
)
# UA de Chrome desktop real. Necessário: com o UA padrão do modo headless
# (`HeadlessChrome/...`) o player de terceiros do AnimesDrive interrompe o fluxo
# antes de pedir a mídia — confirmado ao vivo em 2026-08-17.
_USER_AGENT_NAVEGADOR = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko)"
    " Chrome/150.0.0.0 Safari/537.36"
)
_ARGUMENTOS_NAVEGADOR = (
    # Sem isso o player só busca a mídia depois de um gesto de usuário aceito
    # pela política de autoplay — com ele, a captura resolve em ~3s em vez de
    # depender de acertar o clique no botão certo.
    "--autoplay-policy=no-user-gesture-required",
    # Janela grande o bastante pro player caber inteiro na viewport: o clique de
    # fallback é por coordenada, e elemento fora da viewport não recebe clique.
    "--window-size=1280,900",
    # `navigator.webdriver=false`. Mesma razão do UA acima — sem isso o player
    # de terceiros abandona o fluxo antes de resolver a mídia.
    "--disable-blink-features=AutomationControlled",
    "--disable-dev-shm-usage",
)
# Sandbox do Chromium fica **ligada** (nenhum `--no-sandbox` acima): o navegador
# aqui carrega páginas de terceiros hostis por definição. Confirmado ao vivo que
# a captura funciona com a sandbox ativa.

# Extensões de segmento HLS/DASH: aparecem em rajada *depois* da playlist e não
# servem de fonte pro `ffmpeg` (é um pedaço, não o índice) — nunca são a captura.
_EXTENSOES_DE_SEGMENTO = (".ts", ".m4s", ".aac", ".vtt", ".key")
_EXTENSOES_DE_MIDIA = (".m3u8", ".mpd", ".mp4", ".mkv", ".webm")
_TIPO_RECURSO_MIDIA = "Media"
# Uma rodada de clique + escuta. Curto de propósito: quando o autoplay resolve,
# a mídia aparece na 1ª rodada; quando não, cada rodada é uma nova tentativa de
# clique (overlay de anúncio costuma engolir os primeiros).
_ESPERA_POR_RODADA_S = 2.5
_ESPERA_POR_PACOTE_S = 0.5
# Conferência de um candidato de mídia: 1 byte, só pra saber se a origem responde.
_TIMEOUT_CONFERENCIA_S = 10
# Localiza o maior elemento de player visível e devolve o centro dele, já
# rolado para dentro da viewport. Maior área (não o primeiro `<iframe>`) porque
# páginas de episódio carregam iframes de 1x1 px de rastreamento/anúncio.
_JS_CENTRO_DO_PLAYER = """
  const alvos = [...document.querySelectorAll('iframe, video')]
    .map(elemento => [elemento, elemento.getBoundingClientRect()])
    .filter(([, caixa]) => caixa.width > 100 && caixa.height > 100);
  if (!alvos.length) return null;
  alvos.sort((a, b) => b[1].width * b[1].height - a[1].width * a[1].height);
  alvos[0][0].scrollIntoView({block: 'center'});
  const caixa = alvos[0][0].getBoundingClientRect();
  return [Math.round(caixa.left + caixa.width / 2), Math.round(caixa.top + caixa.height / 2)];
"""


class ClienteNavegador:
    """Chromium real dirigido por DrissionPage — roda o JS da página como um
    usuário rodaria.

    Existe porque parte dos players do AnimesDrive só monta a URL de mídia em
    tempo de execução, no próprio JS da página (`extractors/animesdrive.py`).
    A estratégia aqui é **observar**, não reimplementar: o navegador carrega a
    página, ela executa o que executaria normalmente, e a gente lê a URL da
    requisição de mídia que ela mesma dispara.

    Sessão descartável (incógnito, sem cookie injetado): o navegador resolve o
    próprio desafio, e é o resultado *dele* que alimenta `SessaoBypass` de volta
    (`extractors/resiliencia.py`), não o contrário.
    """

    def __init__(self, *, headless: bool = True) -> None:
        # Nada de subir Chromium no `__init__`: `resiliencia.chamar` constrói o
        # cliente antes de saber se a operação vai mesmo usá-lo, e o processo
        # precisa nascer e morrer na mesma thread do `asyncio.to_thread`.
        self._headless = headless
        self._pagina = None

    def obter_html(self, url: str, *, timeout_s: int) -> str:
        pagina = self._obter_pagina()
        status = self._navegar(pagina, url, timeout_s=timeout_s)
        html = pagina.html

        if status == 404:
            raise FonteNaoEncontrada(f"não encontrado: {url}")
        if status in (403, 503) or any(
            marcador in html for marcador in _MARCADORES_CORPO_CLOUDFLARE
        ):
            # Não escala pra navegador (já é o navegador) — `resiliencia.chamar`
            # trata `SessaoRejeitada` vinda daqui como falha final.
            raise SessaoRejeitada(f"sessão rejeitada (desafio Cloudflare) em {url}")
        return html

    def obter_json(self, url: str, *, timeout_s: int) -> dict | list:
        pagina = self._obter_pagina()
        self._navegar(pagina, url, timeout_s=timeout_s)
        dados = pagina.json
        if dados is None:
            raise FalhaDeExtracao(
                f"resposta de {url} não é JSON válido", permite_retentativa=True
            )
        return dados

    def capturar_midia(
        self, url_pagina: str, *, hosts_ignorados: tuple[str, ...] = (), timeout_s: int
    ) -> MidiaCapturada:
        """Carrega `url_pagina`, deixa o player fazer o que faria com um usuário
        real e devolve a primeira requisição de mídia que a página dispara **e que
        responde de verdade**.

        Sempre navega de novo, mesmo que a página já esteja carregada: a escuta
        de rede precisa estar ativa *antes* da requisição acontecer, e reaproveitar
        uma carga anterior perderia o pacote por corrida.
        """
        pagina = self._obter_pagina()
        limite = time.monotonic() + timeout_s
        vistas: set[str] = set()
        descartadas: list[str] = []

        pagina.listen.start(True)
        try:
            pagina.get(url_pagina, retry=0, timeout=timeout_s)
            ponto = pagina.run_js(_JS_CENTRO_DO_PLAYER)
            while time.monotonic() < limite:
                pacote = self._esperar_pacote_de_midia(
                    pagina,
                    hosts_ignorados,
                    vistas,
                    limite=min(time.monotonic() + _ESPERA_POR_RODADA_S, limite),
                )
                if pacote is None:
                    if ponto is None:
                        break
                    # Clique no centro do player: alguns players só pedem a mídia
                    # depois de interação, e overlay de anúncio costuma engolir os
                    # primeiros cliques — daí repetir até o teto de tempo.
                    pagina.actions.move_to(tuple(ponto)).click()
                    continue

                cabecalhos = _cabecalhos_da_requisicao(pacote, self.user_agent())
                if _responde(pacote.url, cabecalhos):
                    return MidiaCapturada(url=pacote.url, cabecalhos=cabecalhos)
                descartadas.append(pacote.url)
                logger.info(
                    "navegador: %s não respondeu, seguindo à procura de outra origem",
                    pacote.url,
                )
        finally:
            pagina.listen.stop()

        detalhe = f" (descartadas por não responderem: {descartadas})" if descartadas else ""
        raise FalhaDeExtracao(
            f"nenhuma URL de mídia utilizável em {url_pagina} dentro de {timeout_s}s{detalhe}",
            permite_retentativa=True,
        )

    def cookies(self) -> dict[str, str]:
        if self._pagina is None:
            return {}
        return self._pagina.cookies().as_dict()

    def user_agent(self) -> str:
        return _USER_AGENT_NAVEGADOR

    def fechar(self) -> None:
        if self._pagina is None:
            return
        pagina, self._pagina = self._pagina, None
        pagina.quit()

    def _obter_pagina(self):
        if self._pagina is not None:
            return self._pagina

        # Import tardio: DrissionPage arrasta lxml/websocket-client e custa ~1s
        # de import. A API (`api/`) importa `extractors` inteiro e nunca usa
        # navegador — não faz sentido pagar isso em todo boot.
        from DrissionPage import ChromiumOptions, ChromiumPage
        from DrissionPage.errors import BaseError

        opcoes = ChromiumOptions()
        opcoes.set_browser_path(_localizar_binario_de_navegador())
        # `auto_port`: cada instância pega uma porta e um perfil temporário
        # próprios — sem isso, dois jobs simultâneos se conectariam ao *mesmo*
        # Chromium e um fecharia a página do outro.
        opcoes.auto_port()
        opcoes.headless(self._headless)
        opcoes.incognito(True)
        opcoes.mute(True)
        opcoes.set_user_agent(_USER_AGENT_NAVEGADOR)
        for argumento in _ARGUMENTOS_NAVEGADOR:
            opcoes.set_argument(argumento)

        try:
            self._pagina = ChromiumPage(opcoes)
        except BaseError as excecao:
            raise FalhaDeExtracao(
                f"falha ao subir o navegador: {excecao}", permite_retentativa=True
            ) from excecao
        return self._pagina

    def _navegar(self, pagina, url: str, *, timeout_s: int) -> int | None:
        """Navega e devolve o status HTTP do documento (`None` se a resposta não
        foi observada) — é o que dá a `ClienteNavegador` a mesma distinção de
        404/desafio que `ClienteLeve` faz pelo `status_code`."""
        from DrissionPage.errors import BaseError

        pagina.listen.start(url, method="GET")
        try:
            pagina.get(url, retry=0, timeout=timeout_s)
            pacote = pagina.listen.wait(timeout=_ESPERA_POR_PACOTE_S, raise_err=False)
        except BaseError as excecao:
            raise FalhaDeExtracao(
                f"falha de navegação em {url}: {excecao}", permite_retentativa=True
            ) from excecao
        finally:
            pagina.listen.stop()

        if not pacote or pacote.response is None:
            logger.info("navegador não observou a resposta de %s — seguindo pelo corpo", url)
            return None
        return pacote.response.status

    def _esperar_pacote_de_midia(
        self, pagina, hosts_ignorados: tuple[str, ...], vistas: set[str], *, limite: float
    ):
        while time.monotonic() < limite:
            pacote = pagina.listen.wait(timeout=_ESPERA_POR_PACOTE_S, raise_err=False)
            if not pacote or pacote.url in vistas:
                continue
            if _eh_midia(pacote) and not _host_ignorado(pacote.url, hosts_ignorados):
                # Marca só o que vai ser conferido: player pede a mesma URL em
                # várias faixas de bytes, e reconferir cada uma gastaria a janela.
                vistas.add(pacote.url)
                return pacote
        return None


def _localizar_binario_de_navegador() -> str:
    apontado = os.environ.get(_VARIAVEL_BINARIO_NAVEGADOR)
    if apontado:
        return apontado
    for nome in _BINARIOS_DE_NAVEGADOR:
        caminho = shutil.which(nome)
        if caminho:
            return caminho
    raise FalhaDeExtracao(
        "nenhum navegador Chromium encontrado no PATH"
        f" ({', '.join(_BINARIOS_DE_NAVEGADOR)}) —"
        f" instale um ou aponte {_VARIAVEL_BINARIO_NAVEGADOR} para o binário",
        permite_retentativa=False,
    )


def _responde(url: str, cabecalhos: dict[str, str]) -> bool:
    """Confere que a URL capturada responde, com os mesmos cabeçalhos (e sem
    cookie) que o `ffmpeg` do pipeline vai usar — `extractors/download.py`.

    Existe porque o player tenta mais de uma origem: no mesmo episódio, o
    primeiro `.mp4` pedido devolvia 404 e só o segundo tocava (confirmado ao vivo
    em 2026-08-17). Sem esta conferência a captura devolveria a URL morta, e o
    job só descobriria isso no download.

    Só status — a validação de isca (HTML/imagem no lugar de mídia) continua em
    `extractors/download.py::conferir_link_de_midia`, que roda no pipeline; não
    dá pra reusar aquela função aqui sem import circular (`download` → `base` →
    `cliente`).
    """
    try:
        with requests.get(
            url,
            headers={**cabecalhos, "Range": "bytes=0-0"},
            stream=True,
            timeout=_TIMEOUT_CONFERENCIA_S,
        ) as resposta:
            return resposta.ok
    except requests.RequestException as excecao:
        logger.info("conferência de %s falhou: %s", url, excecao)
        return False


def _eh_midia(pacote) -> bool:
    caminho = urllib.parse.urlparse(pacote.url).path.lower()
    if caminho.endswith(_EXTENSOES_DE_SEGMENTO):
        return False
    return caminho.endswith(_EXTENSOES_DE_MIDIA) or pacote.resourceType == _TIPO_RECURSO_MIDIA


def _host_ignorado(url: str, hosts_ignorados: tuple[str, ...]) -> bool:
    host = urllib.parse.urlparse(url).netloc
    return any(ignorado in host for ignorado in hosts_ignorados)


def _cabecalhos_da_requisicao(pacote, user_agent_padrao: str) -> dict[str, str]:
    """`Referer`/`User-Agent` exatamente como o navegador mandou na requisição de
    mídia — o host de mídia valida hotlink contra esses valores, e adivinhar qual
    deles o player usou (URL do embed? do episódio? só a origem?) foi justamente
    o que não funcionou antes."""
    brutos = getattr(pacote.request, "headers", None) or {}
    enviados = {chave.lower(): valor for chave, valor in brutos.items()}
    cabecalhos = {"User-Agent": enviados.get("user-agent") or user_agent_padrao}
    referer = enviados.get("referer")
    if referer:
        cabecalhos["Referer"] = referer
    return cabecalhos


def _eh_desafio_cloudflare(resposta: requests.Response) -> bool:
    if _MARCADOR_HEADER_CLOUDFLARE in resposta.headers:
        return True
    corpo = resposta.text
    return any(marcador in corpo for marcador in _MARCADORES_CORPO_CLOUDFLARE)

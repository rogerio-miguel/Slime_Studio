"""Cliente HTTP para extratores de site (ESPECIFICACAO.md §3A).

`ClienteDeSite` é `Protocol` (colaborador estrutural que os adapters recebem
por injeção, não hierarquia — D2/D3 do plano) — `ClienteLeve` e
`ClienteNavegador` implementam o mesmo contrato sem herdar nada em comum.

Quem escolhe entre os dois é `fontes/rede/resiliencia.py`, nunca o adapter: o
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
import sys
import time
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import cloudscraper
import requests

from core.erros import FalhaDeExtracao, FonteNaoEncontrada, SessaoRejeitada
from fontes.rede import rede_segura

logger = logging.getLogger(__name__)

# Marcadores de desafio Cloudflare ainda em curso (ESPECIFICACAO.md §9, linha do
# risco "sessão de bypass expirada"): header `cf-mitigated`, `<title>Just a
# moment`, o parâmetro `cf_chl_opt` do script de verificação e o caminho
# `/cdn-cgi/challenge-platform/` do loader do desafio. Este último é marcador
# estrutural, idioma-independente: o título localizado ("Um momento…", observado
# no AnimesDrive em 2026-09-02) não casa com `"Just a moment"`. Não incluir
# `"turnstile"` solto — genérico demais, com risco de falso positivo em página
# legítima que só usa o widget de Turnstile num formulário.
_MARCADOR_HEADER_CLOUDFLARE = "cf-mitigated"
_MARCADORES_CORPO_CLOUDFLARE = (
    "Just a moment",
    "cf_chl_opt",
    "/cdn-cgi/challenge-platform/",
)


# Beacon de "JavaScript Detections" do Cloudflare: vive sob o mesmo prefixo
# `/cdn-cgi/challenge-platform/` mas é injetado em página NORMAL já liberada (visto
# ao vivo no MeusAnimes em 2026-10-11, com `cf_clearance` válido e resultados na
# tela). Contá-lo como desafio fazia o navegador esperar 20s numa página boa e
# descartar a busca. O loader de desafio de verdade usa `.../h/<x>/orchestrate/...`.
_BEACON_JSD = "/cdn-cgi/challenge-platform/scripts/jsd/"


def _tem_marcador_de_desafio(html: str) -> bool:
    sem_beacon = html.replace(_BEACON_JSD, "")
    return any(marcador in sem_beacon for marcador in _MARCADORES_CORPO_CLOUDFLARE)


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
        self,
        url_pagina: str,
        *,
        hosts_ignorados: tuple[str, ...],
        seletor_para_ativar: str | None = None,
        timeout_s: int,
    ) -> MidiaCapturada: ...


@runtime_checkable
class ClienteComPost(Protocol):
    """Capacidade de POST de formulário que só `ClienteLeve` tem — o cliente de
    navegador observa o player montar a mídia, não fala o protocolo de RPC do
    site na mão.

    Mesmo contrato de uso de `ClienteComCaptura`: o helper que precisa disso
    (`fontes/adaptadores/blogger.py`) confere com `isinstance` antes de chamar; o
    contrato base (`ClienteDeSite`) segue sendo só GET."""

    def postar_formulario(self, url: str, campos: dict[str, str], *, timeout_s: int) -> str: ...


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
        resposta = self._requisitar(url, lambda: self._sessao.get(url, timeout=timeout_s))
        return resposta.text

    def obter_json(self, url: str, *, timeout_s: int) -> dict | list:
        resposta = self._requisitar(url, lambda: self._sessao.get(url, timeout=timeout_s))
        try:
            return resposta.json()
        except requests.JSONDecodeError as excecao:
            raise FalhaDeExtracao(
                f"resposta de {url} não é JSON válido", permite_retentativa=True
            ) from excecao

    def postar_formulario(self, url: str, campos: dict[str, str], *, timeout_s: int) -> str:
        """POST de formulário (`application/x-www-form-urlencoded`) com a MESMA
        tradução de erro do GET — ver `_requisitar`. Existe para o helper do
        Blogger (`fontes/adaptadores/blogger.py`) falar o protocolo `batchexecute` do
        player sem subir navegador; só o cliente leve implementa (`ClienteComPost`)."""
        resposta = self._requisitar(
            url, lambda: self._sessao.post(url, data=campos, timeout=timeout_s)
        )
        return resposta.text

    def cookies(self) -> dict[str, str]:
        return self._sessao.cookies.get_dict()

    def user_agent(self) -> str:
        return self._sessao.headers.get("User-Agent", "")

    def fechar(self) -> None:
        self._sessao.close()

    def _requisitar(
        self, url: str, enviar: Callable[[], requests.Response]
    ) -> requests.Response:
        """Executa `enviar` (o GET ou o POST já montado) e converte exceção de
        `requests` ou status de erro na exceção de domínio equivalente. Núcleo
        único de tradução: `obter_html`/`obter_json`/`postar_formulario` passam
        todos por aqui, então 404/desafio Cloudflare/timeout têm o mesmo
        tratamento seja qual for o método HTTP."""
        try:
            resposta = enviar()
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
# nunca chega em `fontes/rede/resiliencia.py` (quem instancia o cliente), e
# plumbar Config até aqui só por causa de um caminho de binário acoplaria a
# camada de extração ao bootstrap da aplicação.
_VARIAVEL_BINARIO_NAVEGADOR = "SLIME_NAVEGADOR_BIN"
# Modo de exibição do navegador: `SLIME_NAVEGADOR_HEADLESS` força (ver
# `_modo_headless`). Mesma razão de não passar por `core/config.py` que o
# binário acima.
_VARIAVEL_HEADLESS = "SLIME_NAVEGADOR_HEADLESS"
_BINARIOS_DE_NAVEGADOR = (
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
    "brave-browser",
    "microsoft-edge",
)
# UA de Chrome desktop real, aplicado **só no caminho headless**
# (`_user_agent_override`). Necessário lá: com o UA padrão do headless
# (`HeadlessChrome/...`) o player de terceiros do AnimesDrive interrompe o fluxo
# antes de pedir a mídia — confirmado ao vivo em 2026-08-17.
#
# Em modo visível esse override fica desligado de propósito: `set_user_agent()`
# troca só o header `User-Agent` e não alinha os client hints `Sec-CH-UA`, e essa
# inconsistência é sinal de bot pro Turnstile do Cloudflare. Confirmado ao vivo
# em 2026-09-02 que só a combinação GUI + UA nativo do binário limpa o desafio.
_USER_AGENT_NAVEGADOR = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko)"
    " Chrome/150.0.0.0 Safari/537.36"
)


def _modo_headless() -> bool:
    """Decide se o Chromium sobe headless. Três estados:

    - `SLIME_NAVEGADOR_HEADLESS` setada força o modo: `"0"`/`"false"`/`"nao"`/
      `"não"` (case-insensitive) = visível; qualquer outro valor não-vazio =
      headless.
    - Não setada, em Linux sem `DISPLAY` nem `WAYLAND_DISPLAY`: headless (não há
      alternativa), com aviso — o auto-solve do desafio Cloudflare não funciona
      headless e toda operação de navegador vai falhar em site com Turnstile.
    - Caso contrário (há display, ou não é Linux): visível — é o default, porque
      só GUI + UA nativo limpa o Turnstile (ver `_USER_AGENT_NAVEGADOR`).
    """
    forcado = os.environ.get(_VARIAVEL_HEADLESS, "").strip()
    if forcado:
        return forcado.lower() not in ("0", "false", "nao", "não")

    sem_display = (
        sys.platform == "linux"
        and not os.environ.get("DISPLAY")
        and not os.environ.get("WAYLAND_DISPLAY")
    )
    if sem_display:
        logger.warning(
            "sem servidor de display (DISPLAY/WAYLAND_DISPLAY) — o navegador vai"
            " rodar headless; nesse modo o bypass de desafio Cloudflare não"
            " funciona e operações de navegador vão falhar em sites com Turnstile."
            " Rode num ambiente gráfico ou defina %s=1 para silenciar este aviso.",
            _VARIAVEL_HEADLESS,
        )
        return True
    return False


def _user_agent_override(headless: bool) -> str | None:
    """UA a forçar via `set_user_agent`, ou `None` para deixar o binário usar o
    dele. Só o caminho headless precisa forçar (ver `_USER_AGENT_NAVEGADOR`)."""
    return _USER_AGENT_NAVEGADOR if headless else None


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
# Espera curta pelo botão de troca de servidor/qualidade: pode renderizar um
# instante depois do load da página.
_ESPERA_ELEMENTO_S = 5
# Espera pelo auto-solve de um desafio Cloudflare (Turnstile) em modo visível.
# Medido em ~2,5s no AnimesDrive em 2026-09-02; o teto é largo pro caso lento.
_ESPERA_DESAFIO_S = 20
_INTERVALO_DESAFIO_S = 0.5
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
    tempo de execução, no próprio JS da página (`fontes/adaptadores/animesdrive.py`).
    A estratégia aqui é **observar**, não reimplementar: o navegador carrega a
    página, ela executa o que executaria normalmente, e a gente lê a URL da
    requisição de mídia que ela mesma dispara.

    Sessão descartável (incógnito, sem cookie injetado): o navegador resolve o
    próprio desafio, e é o resultado *dele* que alimenta `SessaoBypass` de volta
    (`fontes/rede/resiliencia.py`), não o contrário.
    """

    def __init__(self, *, headless: bool | None = None) -> None:
        # Nada de subir Chromium no `__init__`: `resiliencia.chamar` constrói o
        # cliente antes de saber se a operação vai mesmo usá-lo, e o processo
        # precisa nascer e morrer na mesma thread do `asyncio.to_thread`.
        #
        # `headless=None` (default) resolve o modo do ambiente em
        # `_modo_headless()` — `resiliencia.py` instancia sem argumento e não
        # deve saber se há servidor de display.
        self._headless = _modo_headless() if headless is None else headless
        self._user_agent: str | None = None
        self._pagina = None

    def obter_html(self, url: str, *, timeout_s: int) -> str:
        pagina = self._obter_pagina()
        status = self._navegar(pagina, url, timeout_s=timeout_s)
        html = pagina.html

        if status == 404:
            raise FonteNaoEncontrada(f"não encontrado: {url}")
        if status in (403, 503) or _tem_marcador_de_desafio(html):
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
        self,
        url_pagina: str,
        *,
        hosts_ignorados: tuple[str, ...] = (),
        seletor_para_ativar: str | None = None,
        timeout_s: int,
    ) -> MidiaCapturada:
        """Carrega `url_pagina`, deixa o player fazer o que faria com um usuário
        real e devolve a primeira requisição de mídia que a página dispara **e que
        responde de verdade**.

        Sempre navega de novo, mesmo que a página já esteja carregada: a escuta
        de rede precisa estar ativa *antes* da requisição acontecer, e reaproveitar
        uma carga anterior perderia o pacote por corrida.

        Sem `seletor_para_ativar` o comportamento é o de sempre (primeiro player
        que a página monta sozinha). Com ele: clica no elemento (troca de
        servidor/qualidade) e **rearma a escuta de rede logo depois** — o servidor
        ativo por padrão pode já ter disparado a mídia dele antes da troca (o
        navegador roda com `--autoplay-policy=no-user-gesture-required`), e
        devolver aquele pacote seria devolver a qualidade errada. Elemento não
        encontrado falha o candidato (`FalhaDeExtracao`) em vez de seguir com o
        player default — qualidade errada silenciosa é pior que falha limpa.
        """
        pagina = self._obter_pagina()
        limite = time.monotonic() + timeout_s
        vistas: set[str] = set()
        descartadas: list[str] = []

        pagina.listen.start(True)
        try:
            pagina.get(url_pagina, retry=0, timeout=timeout_s)
            houve_desafio = self._aguardar_desafio_cloudflare(
                pagina, limite=min(time.monotonic() + _ESPERA_DESAFIO_S, limite)
            )
            if houve_desafio and self._ainda_em_desafio(pagina):
                # Interstitial de desafio que não limpou: sem este corte a captura
                # gastaria a janela inteira clicando na interstitial e falharia com
                # "nenhuma URL de mídia utilizável", mensagem enganosa pro que
                # aconteceu de fato.
                raise SessaoRejeitada(
                    f"sessão rejeitada (desafio Cloudflare) em {url_pagina}"
                )
            if seletor_para_ativar:
                self._ativar_servidor(pagina, seletor_para_ativar)
                pagina.listen.stop()
                pagina.listen.start(True)
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
                if responde(pacote.url, cabecalhos):
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
        # O UA reportado aqui precisa bater com o `cf_clearance` colhido:
        # `resiliencia.py` grava este valor no `sessao_cache` e o `ClienteLeve`
        # seguinte reusa o par cookie+UA — UA divergente invalida o cookie no
        # Cloudflare. `animesdrive.py`/`animefire.py` também montam o cabeçalho de
        # `responde()` com ele, contra host que valida hotlink. Em modo visível o
        # binário usa o UA nativo dele, não a constante — por isso lê do DOM.
        if self._user_agent is not None:
            return self._user_agent
        if self._pagina is None:
            return _USER_AGENT_NAVEGADOR

        from DrissionPage.errors import BaseError

        try:
            do_dom = self._pagina.run_js("return navigator.userAgent")
        except BaseError as excecao:
            logger.warning(
                "navegador: falha ao ler o UA real do DOM (%s) — usando o UA padrão", excecao
            )
            do_dom = None
        self._user_agent = do_dom if isinstance(do_dom, str) and do_dom else _USER_AGENT_NAVEGADOR
        return self._user_agent

    def fechar(self) -> None:
        if self._pagina is None:
            return
        pagina, self._pagina = self._pagina, None
        pagina.quit()

    def _obter_pagina(self):
        if self._pagina is not None:
            return self._pagina

        # Import tardio: DrissionPage arrasta lxml/websocket-client e custa ~1s
        # de import. A API (`api/`) importa `fontes` inteiro e nunca usa
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
        ua = _user_agent_override(self._headless)
        if ua is not None:
            opcoes.set_user_agent(ua)
        for argumento in _ARGUMENTOS_NAVEGADOR:
            opcoes.set_argument(argumento)

        try:
            self._pagina = ChromiumPage(opcoes)
        except BaseError as excecao:
            raise FalhaDeExtracao(
                f"falha ao subir o navegador: {excecao}", permite_retentativa=True
            ) from excecao
        return self._pagina

    def _ativar_servidor(self, pagina, seletor: str) -> None:
        """Clica no elemento de `seletor` pra trocar de servidor/qualidade —
        `<button>` real, não overlay coberto pelo player: clique por seletor,
        não por coordenada."""
        from DrissionPage.errors import BaseError

        try:
            elemento = pagina.ele(f"css:{seletor}", timeout=_ESPERA_ELEMENTO_S)
        except BaseError:
            elemento = None
        if not elemento:
            raise FalhaDeExtracao(
                f"elemento {seletor!r} não encontrado para ativar servidor",
                permite_retentativa=True,
            )
        elemento.click()

    def _navegar(self, pagina, url: str, *, timeout_s: int) -> int | None:
        """Navega e devolve o status HTTP do documento (`None` se a resposta não
        foi observada, ou se um desafio Cloudflare foi interceptado) — é o que dá
        a `ClienteNavegador` a mesma distinção de 404/desafio que `ClienteLeve`
        faz pelo `status_code`."""
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
            # `listen` para aqui: a espera de desafio abaixo lê o DOM, não a rede.
            pagina.listen.stop()

        if self._aguardar_desafio_cloudflare(
            pagina, limite=time.monotonic() + _ESPERA_DESAFIO_S
        ):
            # O pacote observado acima é o 403 da própria interstitial de desafio,
            # não o 200 da página real que o Cloudflare recarrega após o
            # auto-solve. Zerar o status ("não observado") joga a decisão 100% pro
            # corpo em `obter_html`, confiável nos dois desfechos: limpo → sem
            # marcador → devolve HTML; sujo → marcador → `SessaoRejeitada`.
            return None

        if not pacote or pacote.response is None:
            logger.info("navegador não observou a resposta de %s — seguindo pelo corpo", url)
            return None
        return pacote.response.status

    def _aguardar_desafio_cloudflare(self, pagina, *, limite: float) -> bool:
        """Se a página carregou numa interstitial de desafio Cloudflare
        (Turnstile), espera o auto-solve do navegador até `limite` (deadline
        monotônico absoluto, não duração). Só limpa em modo visível — headless
        fica em loop infinito no desafio (confirmado ao vivo em 2026-09-02).

        Devolve `True` se HAVIA marcador de desafio na primeira leitura do DOM,
        tenha limpado ou não dentro do prazo — quem decide o que fazer com uma
        página ainda suja é o chamador, relendo o corpo. `False` = sem desafio, o
        caminho normal, que paga só uma leitura de DOM.
        """
        from DrissionPage.errors import BaseError

        try:
            inicio = time.monotonic()
            if not _tem_marcador_de_desafio(pagina.html):
                return False

            while time.monotonic() < limite:
                time.sleep(_INTERVALO_DESAFIO_S)
                if not _tem_marcador_de_desafio(pagina.html):
                    logger.info(
                        "navegador: desafio Cloudflare limpou em %.1fs",
                        time.monotonic() - inicio,
                    )
                    return True
            logger.warning(
                "navegador: desafio Cloudflare ainda presente após %.1fs —"
                " provável bloqueio real (ou navegador headless sem GUI)",
                time.monotonic() - inicio,
            )
            return True
        except BaseError as excecao:
            # Leitura de DOM falhou no meio da espera: trata como "houve desafio e
            # não deu pra confirmar a limpeza" — o chamador relê o corpo e decide.
            logger.warning("navegador: erro ao observar desafio Cloudflare: %s", excecao)
            return True

    def _ainda_em_desafio(self, pagina) -> bool:
        """Relê o DOM e diz se o marcador de desafio segue lá. Erro de leitura
        conta como "ainda em desafio": página que não dá pra inspecionar é
        inutilizável do mesmo jeito."""
        from DrissionPage.errors import BaseError

        try:
            return _tem_marcador_de_desafio(pagina.html)
        except BaseError:
            return True

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


def responde(url: str, cabecalhos: dict[str, str]) -> bool:
    """Confere que a URL responde, com os mesmos cabeçalhos (e sem cookie) que o
    `ffmpeg` do pipeline vai usar — `captura/download.py`.

    Existe porque o player tenta mais de uma origem: no mesmo episódio, o
    primeiro `.mp4` pedido devolvia 404 e só o segundo tocava (confirmado ao vivo
    em 2026-08-17). Sem esta conferência a captura devolveria a URL morta, e o
    job só descobriria isso no download.

    Não é só pra URL observada saindo do navegador: também vale pra URL de
    `<source>` lida direto do HTML estático (`fontes/adaptadores/animesdrive.py`, painel
    de qualidade com vídeo direto) — mesma razão (o site serve URL morta), mesmo
    tratamento.

    Só status — a validação de isca (HTML/imagem no lugar de mídia) continua em
    `captura/download.py::conferir_link_de_midia`, que roda no pipeline; não
    dá pra reusar aquela função aqui sem import circular (`download` → `base` →
    `cliente`).
    """
    try:
        with rede_segura.get_validando_redirects(
            url,
            headers={**cabecalhos, "Range": "bytes=0-0"},
            stream=True,
            timeout=_TIMEOUT_CONFERENCIA_S,
        ) as resposta:
            return resposta.ok
    except (requests.RequestException, rede_segura.DestinoNaoPermitido) as excecao:
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
    return _tem_marcador_de_desafio(resposta.text)

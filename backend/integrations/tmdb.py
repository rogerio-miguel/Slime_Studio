"""Adapter TMDB (REST) — provedor PADRÃO de arte (banner de anime, still/
nome/sinopse de episódio) (`PLANO_ARTE_TMDB.md`). NÃO é um `ProvedorDeMetadados`
(D1 do plano): não resolve sinopse/ids/feed DO ANIME — implementa
`ProvedorDeArte`, com tupla de registro própria (`registro.PROVEDORES_DE_ARTE`).

Capa (pôster) NÃO é mais responsabilidade deste provedor: volta a ser
exclusiva da cadeia normal de `ProvedorDeMetadados` (AniList/Kitsu) — a
AniList modela cada temporada como uma `Media` própria e já resolve capa por
temporada corretamente por construção, ao contrário do TMDB, que agrupa a
série inteira sob um único id.

Síncrono via `requests`; ver `integrations/anilist.py` para a nota sobre onde
mora a fronteira de exceção HTTP e o `to_thread`/timeout externo
(`integrations/servico.py`).
"""

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from io import BytesIO

import requests
from PIL import Image

from core.temporada import separar_temporada
from core.texto import slugificar
from integrations.base import ArteDeAnime, InfoDeEpisodio, ProvedorDeArte

logger = logging.getLogger(__name__)

_URL_BASE = "https://api.themoviedb.org/3"
_URL_IMAGEM = "https://image.tmdb.org/t/p"
_TAMANHO_BACKDROP = "original"  # hero em tela cheia: w1280 ficava borrado
_TAMANHO_ANALISE = "w780"  # só pra medir espaço livre; o banner salvo é `original`
_LADO_DA_ANALISE = 160  # px do maior lado após reduzir (custo O(pixels) em Python puro)
_FAIXA_ESQUERDA = 0.45  # fração da largura onde o hero põe o bloco de conteúdo
_ESPESSURA_DE_TARJA = 0.04  # fração da altura/largura inspecionada nas bordas
_LUMINANCIA_DE_TARJA = 12  # média (0-255) abaixo da qual a borda conta como preta
_TOPO_MINIMO_RELATIVO = 0.5  # detalhe do topo direito / detalhe da metade direita
_FINALISTAS_DE_BACKDROP = 6  # candidatos medidos (1 download cada) por anime
_LARGURA_MINIMA_BACKDROP = 1920
_LARGURA_ALTA_BACKDROP = 2500  # 4K/quase-4K; abaixo disso, FHD borra em tela grande
_PROPORCAO_16_9 = 16 / 9
_TOLERANCIA_DE_PROPORCAO = 0.1
_NOTA_A_PRIORI = 5.0  # prior bayesiano da nota de backdrop (escala TMDB 0-10)
_PESO_A_PRIORI = 3  # "votos" fictícios do prior
_TAMANHO_STILL = "original"  # thumb de episódio (Fatia 5). `still_sizes` do TMDB só
# tem w92/w185/w300/original (sem w500/w780/w1280, que só existem pra poster/backdrop)
# — w300 ficava borrado no card grande da grade de episódios/"Continuar assistindo"
# (renderizado a ~440-560px CSS, `/api/thumb` não faz resize). `original` também
# iguala a qualidade da thumb ao vivo (TMDB) com a persistida em `capa_path` na
# captura, que já usa `still_src` cru do extractor (mesma URL "original").
_IDIOMA = "pt-BR"  # TMDB cai pro pôster default quando não há arte pt-BR
# Fallback de TEXTO (nome/sinopse de episódio) quando o TMDB não tem tradução
# pt-BR — comum em anime: `name` costuma vir traduzido, `overview` muitas
# vezes só no episódio 1 da temporada inteira. Nunca usado pra imagem (still/
# backdrop/pôster não dependem de idioma). Ver `TmdbProvider.info_da_temporada`.
_IDIOMA_FALLBACK = "en-US"
# Sem título cadastrado, o TMDB não devolve `name` vazio: devolve o placeholder
# localizado ("Episódio 7" / "Episode 7"). Tratado como ausente — senão o
# fallback en-US nunca preenche o nome real e o placeholder é persistido.
_NOME_PLACEHOLDER = re.compile(r"^(?:epis[óo]dio|episode)\s*\d+$", re.IGNORECASE)
# Estritamente < `integrations/servico.py::_TIMEOUT_POR_PROVEDOR_S` (8s) —
# mesma razão de `integrations/anilist.py::_TIMEOUT_S`.
_TIMEOUT_S = 6

# Item sem `first_air_date` pontua como distância máxima no desempate por ano
# (D3) — nunca vence um candidato com ano conhecido, mesmo que perto do alvo.
_DISTANCIA_DE_ANO_DESCONHECIDA = 9999


@dataclass(frozen=True, slots=True)
class TabelaDeTemporadas:
    """Id da série no TMDB + tabela `(numero_da_temporada, primeiro_episodio_
    absoluto, episode_count)` de cada temporada NORMAL (`season_number >= 1`
    — especiais do TMDB, `season_number == 0`, ficam fora da numeração
    absoluta), em ordem crescente de temporada. Produzida por
    `TmdbProvider.tabela_de_temporadas` (Fatia 5), consumida por
    `buscar_info_de_episodio` e por `integrations/servico.py` (memo
    `_memo_temporadas`) — pública (não `_`-prefixada) porque atravessa esse
    limite de módulo, mesmo padrão de `TmdbNaoAutorizado` abaixo."""

    id_da_serie: int
    temporadas: list[tuple[int, int, int]]


def localizar_temporada(
    temporadas: list[tuple[int, int, int]], numero_absoluto: int
) -> tuple[int, int] | None:
    """Acha, em `TabelaDeTemporadas.temporadas`, a temporada cujo intervalo
    `[primeiro_episodio_absoluto, primeiro_episodio_absoluto + episode_count)`
    contém `numero_absoluto`; devolve `(numero_da_temporada,
    numero_do_episodio_dentro_da_temporada)`. `None` quando `numero_absoluto`
    cai fora de toda temporada conhecida — risco aceito do plano (numeração
    absoluta local pode não bater 1:1 com a divisão de temporada do TMDB)."""
    for numero_da_temporada, primeiro_absoluto, contagem in temporadas:
        ultimo_absoluto = primeiro_absoluto + contagem - 1
        if primeiro_absoluto <= numero_absoluto <= ultimo_absoluto:
            return numero_da_temporada, numero_absoluto - primeiro_absoluto + 1
    return None


class TmdbNaoAutorizado(RuntimeError):
    """Token inválido/revogado (HTTP 401/403). Subclasse de `RuntimeError` de
    propósito: já cai em `integrations/servico.py::_ERROS_DE_PROVEDOR` sem
    alterar aquela tupla, mas permite ao serviço capturar separado e ligar o
    latch de "arte desabilitada" (D2/D4 do plano) em vez de logar warning por
    chamada — um token errado não pode gerar dezenas de warnings por feed."""


class TmdbProvider(ProvedorDeArte):
    def __init__(self, token: str) -> None:
        self._token = token
        # `id_da_serie -> file_path` do backdrop já MEDIDO (só grava quando ao menos
        # um finalista foi analisado: falha de rede não congela escolha ruim). A
        # escolha só depende da série, então as temporadas (que chegam com `ano`
        # diferente ao memo de `servico.py`) e o feed reaproveitam a mesma medição
        # em vez de refazer ~6 downloads — e o overlay do feed cabe no timeout de 8s.
        self._backdrop_medido: dict[int, str] = {}

    @property
    def nome(self) -> str:
        return "tmdb"

    def buscar_arte_por_titulo(self, titulo: str, ano: int | None) -> ArteDeAnime | None:
        """Banner e sinopse pt-BR da série — capa (pôster) não é mais
        responsabilidade deste método, ver docstring de módulo. Prefere o melhor
        backdrop de `/tv/{id}/images` (`_melhor_backdrop`: sem texto sobreposto, mais votado) ao
        `backdrop_path` "primário" da série, que o TMDB às vezes fixa numa arte
        com logo/texto ou de temporada aleatória."""
        serie = self._resolver_serie(titulo, ano)
        if serie is None:
            return None

        id_da_serie = serie.get("id")
        melhor = self._melhor_backdrop(id_da_serie) if isinstance(id_da_serie, int) else None
        banner_url = _url_imagem(melhor or serie.get("backdrop_path"), _TAMANHO_BACKDROP)
        # `overview` da busca já vem em `_IDIOMA` (idêntico ao de `GET /tv/{id}`,
        # medido); vazio quando o TMDB não tem tradução — fica `None`, nunca o inglês.
        sinopse_serie = (serie.get("overview") or "").strip() or None
        if banner_url is None and sinopse_serie is None:
            return None
        return ArteDeAnime(
            banner_url=banner_url,
            sinopse_serie=sinopse_serie,
            ano_da_serie=_ano_de_estreia(serie),
        )

    def sinopse_da_temporada(self, titulo: str, ano: int | None, temporada: int) -> str | None:
        """Sinopse pt-BR da TEMPORADA (`GET /tv/{id}/season/{n}`); `None` quando
        a série não é achada ou a temporada não tem tradução (a maioria)."""
        serie = self._resolver_serie(titulo, ano)
        id_da_serie = serie.get("id") if serie else None
        if not isinstance(id_da_serie, int):
            return None
        dados = self._executar(f"/tv/{id_da_serie}/season/{temporada}", {"language": _IDIOMA})
        return (dados.get("overview") or "").strip() or None

    def _melhor_backdrop(self, id_da_serie: int) -> str | None:
        """`file_path` do melhor backdrop de `GET /tv/{id}/images`: prefere os
        SEM texto sobreposto (`iso_639_1` nulo — o hero já põe título e gradiente
        por cima) e, entre esses, o de maior `vote_average`. `None` quando o
        endpoint não traz backdrop utilizável — o chamador cai no `backdrop_path`
        default da série."""
        if id_da_serie in self._backdrop_medido:
            return self._backdrop_medido[id_da_serie]
        dados = self._executar(
            f"/tv/{id_da_serie}/images", {"include_image_language": "null,en"}
        )
        backdrops = dados.get("backdrops")
        if not isinstance(backdrops, list) or not backdrops:
            return None

        so_dicts = [b for b in backdrops if isinstance(b, dict) and b.get("file_path")]
        sem_texto = [b for b in so_dicts if b.get("iso_639_1") is None]
        candidatos = sem_texto or so_dicts
        if not candidatos:
            return None
        # Sem nenhum backdrop limpo em resolução decente, arte com texto (idioma
        # en) e alta resolução ganha de arte limpa borrada.
        if all(_faixa_de_resolucao(b) == 0 for b in candidatos):
            com_texto_boa = [b for b in so_dicts if _faixa_de_resolucao(b) > 0]
            candidatos = com_texto_boa or candidatos

        ordenados = sorted(candidatos, key=_pontuacao_de_backdrop, reverse=True)
        melhor_faixa = _pontuacao_de_backdrop(ordenados[0])[:2]
        finalistas = [b for b in ordenados if _pontuacao_de_backdrop(b)[:2] == melhor_faixa]
        escolhido, medido = self._mais_livre_a_esquerda(finalistas[:_FINALISTAS_DE_BACKDROP])
        if medido:
            self._backdrop_medido[id_da_serie] = escolhido["file_path"]
        return escolhido["file_path"]

    def _mais_livre_a_esquerda(self, finalistas: list[dict]) -> tuple[dict, bool]:
        """Dos `finalistas` (já em ordem de `_pontuacao_de_backdrop` e todos da
        mesma faixa de resolução/proporção), o de menor detalhe visual na faixa
        esquerda — é onde o hero põe o bloco de conteúdo, então arte com
        personagens à direita e fundo liso à esquerda não briga com o texto.
        Imagens que `_aproveitavel` recusa (tarja preta, recorte sem o topo do
        personagem) ficam fora, e falha de download/decodificação também descarta
        o finalista (logada). Se nenhum sobrar, vence o primeiro pela pontuação. O
        `bool` diz se algum finalista foi de fato medido (resultado memoizável).
        Downloads em paralelo: em série, 6 × latência estourava o timeout de 8s do
        overlay de feed (`integrations/servico.py::_chamar`)."""
        with ThreadPoolExecutor(max_workers=len(finalistas)) as pool:
            analises = list(pool.map(lambda b: self._analisar(b["file_path"]), finalistas))
        medidos = [
            (analise.detalhe_esquerda, posicao, backdrop)
            for posicao, (backdrop, analise) in enumerate(zip(finalistas, analises, strict=True))
            if analise is not None and _aproveitavel(analise)
        ]
        if not medidos:
            return finalistas[0], any(a is not None for a in analises)
        return min(medidos, key=lambda m: (m[0], m[1]))[2], True

    def _analisar(self, caminho: str) -> "AnaliseDeBackdrop | None":
        try:
            resposta = requests.get(
                f"{_URL_IMAGEM}/{_TAMANHO_ANALISE}{caminho}", timeout=_TIMEOUT_S
            )
            resposta.raise_for_status()
            return analisar_backdrop(resposta.content)
        except (requests.RequestException, OSError) as erro:
            logger.warning("TMDB: não foi possível medir o backdrop %s: %s", caminho, erro)
            return None

    def buscar_info_de_episodio(
        self, titulo: str, ano: int | None, numero: int, temporada: int | None
    ) -> InfoDeEpisodio | None:
        """Still/nome/sinopse do episódio `numero`. Com `temporada` dada, vai
        direto a `GET /tv/{id}/season/{temporada}` (via `info_da_temporada_
        por_titulo`), sem a volta por `TabelaDeTemporadas`/numeração absoluta.
        Com `temporada is None`, `numero` é a numeração absoluta local e a
        temporada é resolvida por `tabela_de_temporadas`/`localizar_temporada`
        (fallback quando `Anime.numero_temporada` é desconhecido).

        `None` em qualquer passo LÓGICO que não resolva (série não encontrada,
        temporada fora do range, episódio ausente da temporada); exceções de
        rede/autenticação de `_executar` propagam pro chamador
        (`integrations/servico.py`), não são engolidas aqui."""
        if temporada is not None:
            info = self.info_da_temporada_por_titulo(titulo, ano, temporada)
            return info.get(numero) if info is not None else None

        tabela = self.tabela_de_temporadas(titulo, ano)
        if tabela is None:
            return None

        localizacao = localizar_temporada(tabela.temporadas, numero)
        if localizacao is None:
            return None
        numero_da_temporada, numero_na_temporada = localizacao

        info = self.info_da_temporada(tabela.id_da_serie, numero_da_temporada)
        if info is None:
            return None
        return info.get(numero_na_temporada)

    def info_da_temporada_por_titulo(
        self, titulo: str, ano: int | None, temporada: int
    ) -> dict[int, InfoDeEpisodio] | None:
        """Still/nome/sinopse de TODOS os episódios da `temporada` (número real
        da temporada) da série que casa `titulo`/`ano` — resolve a série
        (`_resolver_serie`, mesma busca de `buscar_arte_por_titulo`) e chama
        `GET /tv/{id}/season/{temporada}` direto. Usado quando o chamador já
        sabe o número da temporada (`Anime.numero_temporada`), dispensando a
        `TabelaDeTemporadas`. `integrations/servico.py` popula o memo da
        temporada inteira com o dict devolvido."""
        serie = self._resolver_serie(titulo, ano)
        if serie is None:
            return None
        id_da_serie = serie.get("id")
        if not isinstance(id_da_serie, int):
            return None
        return self.info_da_temporada(id_da_serie, temporada)

    def tabela_de_temporadas(self, titulo: str, ano: int | None) -> TabelaDeTemporadas | None:
        """`GET /tv/{id}` -> `seasons[]` -> tabela "primeiro episódio absoluto
        por temporada", acumulando `episode_count` das temporadas anteriores —
        mesma aritmética que `extractors/animefire.py::
        _mapa_primeiro_episodio_por_temporada` já resolve do lado do
        AnimeFire (útil só como referência), aqui resolvida puramente do lado
        do TMDB. Pública (não `_`-prefixada): reusada por
        `buscar_info_de_episodio` E por `integrations/servico.py` (memo
        `_memo_temporadas`, Fatia 5) — não duplicar esta consulta por
        episódio."""
        serie = self._resolver_serie(titulo, ano)
        if serie is None:
            return None
        id_da_serie = serie.get("id")
        if not isinstance(id_da_serie, int):
            return None

        dados = self._executar(f"/tv/{id_da_serie}", {"language": _IDIOMA})
        temporadas_brutas = dados.get("seasons")
        if not isinstance(temporadas_brutas, list):
            return None

        normais = sorted(
            (
                t
                for t in temporadas_brutas
                if isinstance(t, dict)
                and isinstance(t.get("season_number"), int)
                and t["season_number"] > 0
                and isinstance(t.get("episode_count"), int)
                and t["episode_count"] > 0
            ),
            key=lambda t: t["season_number"],
        )
        temporadas: list[tuple[int, int, int]] = []
        primeiro_absoluto = 1
        for temporada in normais:
            contagem = temporada["episode_count"]
            temporadas.append((temporada["season_number"], primeiro_absoluto, contagem))
            primeiro_absoluto += contagem

        if not temporadas:
            return None
        return TabelaDeTemporadas(id_da_serie=id_da_serie, temporadas=temporadas)

    def info_da_temporada(
        self, id_da_serie: int, numero_da_temporada: int
    ) -> dict[int, InfoDeEpisodio] | None:
        """`GET /tv/{id}/season/{n}` -> `episode_number -> InfoDeEpisodio`
        (still/nome/sinopse) de TODOS os episódios daquela temporada, numa
        única chamada — usada por `buscar_info_de_episodio` e por
        `integrations/servico.py` pra popular o cache de uma temporada
        inteira de uma vez (Fatia 5/6), em vez de repescar esta URL por
        episódio. `nome`/`sinopse` vêm de `name`/`overview` no idioma
        `_IDIOMA` — string vazia do TMDB (comum sem tradução pt-BR) vira
        `None`, nunca string vazia (`or None`). Quando sobra algum `None`
        depois disso, `_preencher_com_fallback_en` completa com `_IDIOMA_
        FALLBACK` (um único GET extra pra temporada inteira, não por
        episódio) — nunca sobrescreve o que já veio em pt-BR; é o ponto de
        encaixe pra um futuro sistema de tradução (só precisaria traduzir o
        que ficou marcado como fallback, não a temporada inteira)."""
        dados = self._executar(
            f"/tv/{id_da_serie}/season/{numero_da_temporada}", {"language": _IDIOMA}
        )
        episodios = dados.get("episodes")
        if not isinstance(episodios, list):
            return None

        info: dict[int, InfoDeEpisodio] = {}
        falta_traducao = False
        for episodio in episodios:
            if not isinstance(episodio, dict):
                continue
            numero = episodio.get("episode_number")
            if not isinstance(numero, int):
                continue
            nome = _nome_de_episodio(episodio)
            sinopse = episodio.get("overview") or None
            if nome is None or sinopse is None:
                falta_traducao = True
            info[numero] = InfoDeEpisodio(
                still_url=_url_imagem(episodio.get("still_path"), _TAMANHO_STILL),
                nome=nome,
                sinopse=sinopse,
            )
        if not info:
            return None
        if falta_traducao:
            self._preencher_com_fallback_en(id_da_serie, numero_da_temporada, info)
        return info

    def _preencher_com_fallback_en(
        self, id_da_serie: int, numero_da_temporada: int, info: dict[int, InfoDeEpisodio]
    ) -> None:
        """Completa, em `info` (mutado in-place), `nome`/`sinopse` que
        ficaram `None` sem tradução pt-BR, com o mesmo GET em `_IDIOMA_
        FALLBACK` — um por temporada, não por episódio (só chamado quando
        `info_da_temporada` já viu que falta algo). Erro de rede/auth aqui
        propaga igual ao `_executar` do pt-BR (não é engolido nesta camada,
        ver docstring de `buscar_info_de_episodio`); `still_url` nunca muda
        (imagem não depende de idioma)."""
        dados = self._executar(
            f"/tv/{id_da_serie}/season/{numero_da_temporada}", {"language": _IDIOMA_FALLBACK}
        )
        episodios = dados.get("episodes")
        if not isinstance(episodios, list):
            return
        for episodio in episodios:
            if not isinstance(episodio, dict):
                continue
            numero = episodio.get("episode_number")
            atual = info.get(numero) if isinstance(numero, int) else None
            if atual is None:
                continue
            nome_en = None if atual.nome else _nome_de_episodio(episodio)
            sinopse_en = None if atual.sinopse else (episodio.get("overview") or None)
            info[numero] = InfoDeEpisodio(
                still_url=atual.still_url,
                nome=atual.nome or nome_en,
                sinopse=atual.sinopse or sinopse_en,
                nome_em_fallback=nome_en is not None,
                sinopse_em_fallback=sinopse_en is not None,
            )

    def _resolver_serie(self, titulo: str, ano: int | None) -> dict | None:
        """Busca `GET /search/tv` por `titulo` e escolhe o melhor candidato
        (`_melhor_resultado`). Privado e reusado por `buscar_arte_por_titulo`
        e, na Fatia 5, por `buscar_info_de_episodio` — não duplicar a busca.

        Sem `first_air_date_year` (D3): a AniList modela cada temporada como
        uma `Media` própria, o TMDB modela a série inteira numa entrada só —
        filtrar por ano de estreia devolveria zero resultados pra sequel/split
        -cour. O ano entra só como desempate, dentro de `_melhor_resultado`.

        O título é reduzido ao BASE (`separar_temporada`) antes da busca: a
        `/search/tv` do TMDB não casa o romaji por-temporada da AniList
        ("... 2nd Season", "... Season 3") com a entrada única da série e
        devolve zero resultados. `buscar_arte_por_titulo` (nível de serviço)
        já entrega o base; para os callers de still/nome/sinopse (`info_da_temporada_por_
        titulo`, `tabela_de_temporadas`) esta é a única redução — sem ela o
        overlay de still não resolvia nenhuma temporada >= 2. Descascar de
        novo um título já base é no-op (identidade).
        """
        titulo_base, _derivado = separar_temporada(titulo)
        dados = self._executar(
            "/search/tv",
            {"query": titulo_base, "include_adult": "false", "page": 1, "language": _IDIOMA},
        )
        resultados = dados.get("results")
        if not isinstance(resultados, list) or not resultados:
            return None
        return _melhor_resultado(resultados, titulo_base, ano)

    def _executar(self, caminho: str, params: dict) -> dict:
        resposta = requests.get(
            f"{_URL_BASE}{caminho}",
            params=params,
            headers={"Authorization": f"Bearer {self._token}", "accept": "application/json"},
            timeout=_TIMEOUT_S,
        )
        if resposta.status_code == 404:
            return {}
        if resposta.status_code in (401, 403):
            raise TmdbNaoAutorizado(f"TMDB: token rejeitado (HTTP {resposta.status_code})")
        resposta.raise_for_status()

        corpo = resposta.json()
        if not isinstance(corpo, dict):
            raise RuntimeError("TMDB: resposta não é um objeto JSON")
        return corpo


def _melhor_resultado(resultados: list, titulo: str, ano: int | None) -> dict | None:
    """Escolhe o melhor item de `Page.results`:

    1. descarta itens sem `poster_path` E sem `backdrop_path` (arte nenhuma
       pra oferecer);
    2. entre os que sobram, prefere os cujo `name`/`original_name` (slug)
       bate com o slug de `titulo` — cai pro pool inteiro se ninguém bater;
    3. dentro do pool, vence o de maior `popularity`; empate desempata pela
       menor distância entre `first_air_date` e `ano` (quando `ano` é conhecido).

    Mudança em relação ao plano original (D3, que usava distância de ano como
    critério primário): o TMDB modela a franquia inteira numa entrada só, então
    a 4ª temporada de um anime (ano recente) fica ANOS distante do
    `first_air_date` da série (2018) e a distância de ano elegia um spin-off
    recente ("The Slime Diaries", 2021) no lugar da série principal (2018).
    `popularity` separa a série principal dos spin-offs de forma robusta; o ano
    só entra pra desempatar dois candidatos igualmente populares (raro)."""
    candidatos = [
        item
        for item in resultados
        if isinstance(item, dict) and (item.get("poster_path") or item.get("backdrop_path"))
    ]
    if not candidatos:
        return None

    slug_titulo = slugificar(titulo)
    pool = [
        item
        for item in candidatos
        if slugificar(item.get("name") or "") == slug_titulo
        or slugificar(item.get("original_name") or "") == slug_titulo
    ] or candidatos

    def _pontuacao(item: dict) -> tuple[float, int]:
        popularidade = item.get("popularity") or 0.0
        proximidade = -_distancia_do_ano(item, ano) if ano is not None else 0
        return popularidade, proximidade

    return max(pool, key=_pontuacao)


@dataclass(frozen=True, slots=True)
class AnaliseDeBackdrop:
    detalhe_esquerda: float  # gradiente médio (0-255) na faixa do bloco de conteúdo
    detalhe_direita: float  # idem, metade direita (onde ficam os personagens)
    detalhe_topo_direita: float  # idem, terço superior da metade direita
    tem_tarja_preta: bool  # letterbox/pillarbox assado na própria imagem


def analisar_backdrop(conteudo: bytes) -> AnaliseDeBackdrop:
    """Mede o backdrop em miniatura. Pública para teste isolado."""
    with Image.open(BytesIO(conteudo)) as imagem:
        cinza = imagem.convert("L")
        cinza.thumbnail((_LADO_DA_ANALISE, _LADO_DA_ANALISE))
        largura, altura = cinza.size
        pixels = cinza.load()

    def gradiente(x0: int, x1: int, y0: int, y1: int) -> float:
        soma = 0
        for y in range(y0, min(y1, altura - 1)):
            for x in range(x0, min(x1, largura - 1)):
                atual = pixels[x, y]
                soma += abs(atual - pixels[x + 1, y]) + abs(atual - pixels[x, y + 1])
        area = max(1, (min(x1, largura - 1) - x0) * (min(y1, altura - 1) - y0))
        return soma / area

    def luminancia(x0: int, x1: int, y0: int, y1: int) -> float:
        valores = [pixels[x, y] for y in range(y0, y1) for x in range(x0, x1)]
        return sum(valores) / len(valores)

    corte = max(2, int(largura * _FAIXA_ESQUERDA))
    terco = altura // 3
    borda_v = max(1, int(altura * _ESPESSURA_DE_TARJA))
    borda_h = max(1, int(largura * _ESPESSURA_DE_TARJA))
    tarja_vertical = (
        luminancia(0, largura, 0, borda_v) < _LUMINANCIA_DE_TARJA
        and luminancia(0, largura, altura - borda_v, altura) < _LUMINANCIA_DE_TARJA
    )
    tarja_horizontal = (
        luminancia(0, borda_h, 0, altura) < _LUMINANCIA_DE_TARJA
        and luminancia(largura - borda_h, largura, 0, altura) < _LUMINANCIA_DE_TARJA
    )
    return AnaliseDeBackdrop(
        detalhe_esquerda=gradiente(0, corte, 0, altura),
        detalhe_direita=gradiente(largura // 2, largura, 0, altura),
        detalhe_topo_direita=gradiente(largura // 2, largura, 0, terco),
        tem_tarja_preta=tarja_vertical or tarja_horizontal,
    )


def _aproveitavel(analise: AnaliseDeBackdrop) -> bool:
    """Recusa tarja preta assada na imagem e recortes sem o topo do personagem
    (ex.: só as pernas): o terço superior da metade direita precisa ter uma
    fração mínima do detalhe da metade direita inteira."""
    if analise.tem_tarja_preta:
        return False
    return analise.detalhe_topo_direita >= analise.detalhe_direita * _TOPO_MINIMO_RELATIVO


def _faixa_de_resolucao(backdrop: dict) -> int:
    """2 = alta (>= `_LARGURA_ALTA_BACKDROP`), 1 = aceitável (>= mínima), 0 = baixa."""
    largura = backdrop.get("width") or 0
    if largura >= _LARGURA_ALTA_BACKDROP:
        return 2
    return 1 if largura >= _LARGURA_MINIMA_BACKDROP else 0


def _pontuacao_de_backdrop(backdrop: dict) -> tuple[int, bool, float]:
    """Chave de ordenação de um backdrop de `/tv/{id}/images` (maior vence):

    1. faixa de resolução (`_faixa_de_resolucao`) — o hero renderiza em tela
       cheia, arte pequena fica borrada mesmo bem votada;
    2. proporção próxima de 16:9 — fora disso o `object-cover` corta o
       enquadramento;
    3. nota média com prior bayesiano — `vote_average` cru deixa um backdrop
       com 1 voto 10.0 vencer um com 40 votos 8.0."""
    proporcao = backdrop.get("aspect_ratio") or 0.0
    votos = backdrop.get("vote_count") or 0
    nota = backdrop.get("vote_average") or 0.0
    nota_bayesiana = (nota * votos + _NOTA_A_PRIORI * _PESO_A_PRIORI) / (votos + _PESO_A_PRIORI)
    return (
        _faixa_de_resolucao(backdrop),
        abs(proporcao - _PROPORCAO_16_9) <= _TOLERANCIA_DE_PROPORCAO,
        nota_bayesiana,
    )


def _distancia_do_ano(item: dict, ano: int) -> int:
    ano_item = _ano_de_estreia(item)
    if ano_item is None:
        return _DISTANCIA_DE_ANO_DESCONHECIDA
    return abs(ano_item - ano)


def _ano_de_estreia(item: dict) -> int | None:
    data = item.get("first_air_date")
    if not isinstance(data, str) or len(data) < 4:
        return None
    prefixo = data[:4]
    return int(prefixo) if prefixo.isdigit() else None


def _nome_de_episodio(episodio: dict) -> str | None:
    """`name` do episódio, ou `None` quando vazio ou placeholder do TMDB."""
    nome = (episodio.get("name") or "").strip()
    if not nome or _NOME_PLACEHOLDER.match(nome):
        return None
    return nome


def _url_imagem(caminho: str | None, tamanho: str) -> str | None:
    """`poster_path`/`backdrop_path` do TMDB já vêm com `/` inicial."""
    if not caminho:
        return None
    return f"{_URL_IMAGEM}/{tamanho}{caminho}"

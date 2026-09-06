"""Adapter TMDB (REST) — provedor PADRÃO de arte (banner de anime, still de
episódio) (`PLANO_ARTE_TMDB.md`). NÃO é um `ProvedorDeMetadados` (D1 do
plano): só resolve imagem, nunca sinopse/ids/feed — implementa
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

from dataclasses import dataclass

import requests

from core.texto import slugificar
from integrations.base import ArteDeAnime, ProvedorDeArte

_URL_BASE = "https://api.themoviedb.org/3"
_URL_IMAGEM = "https://image.tmdb.org/t/p"
_TAMANHO_BACKDROP = "w1280"  # equivalente ao bannerImage
_TAMANHO_STILL = "original"  # thumb de episódio (Fatia 5). `still_sizes` do TMDB só
# tem w92/w185/w300/original (sem w500/w780/w1280, que só existem pra poster/backdrop)
# — w300 ficava borrado no card grande da grade de episódios/"Continuar assistindo"
# (renderizado a ~440-560px CSS, `/api/thumb` não faz resize). `original` também
# iguala a qualidade da thumb ao vivo (TMDB) com a persistida em `capa_path` na
# captura, que já usa `still_src` cru do extractor (mesma URL "original").
_IDIOMA = "pt-BR"  # TMDB cai pro pôster default quando não há arte pt-BR
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
    `buscar_still_de_episodio` e por `integrations/servico.py` (memo
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

    @property
    def nome(self) -> str:
        return "tmdb"

    def buscar_arte_por_titulo(self, titulo: str, ano: int | None) -> ArteDeAnime | None:
        """Só banner (`backdrop_path` da série) — capa (pôster) não é mais
        responsabilidade deste método, ver docstring de módulo."""
        serie = self._resolver_serie(titulo, ano)
        if serie is None:
            return None

        banner_url = _url_imagem(serie.get("backdrop_path"), _TAMANHO_BACKDROP)
        if banner_url is None:
            return None
        return ArteDeAnime(banner_url=banner_url)

    def buscar_still_de_episodio(
        self, titulo: str, ano: int | None, numero_absoluto: int
    ) -> str | None:
        """Thumb do episódio `numero_absoluto` (numeração absoluta local, não
        por temporada) — Fatia 5 do plano. Reusa `tabela_de_temporadas`/
        `stills_da_temporada` (que por sua vez reusam `_resolver_serie`, não
        duplicam a busca da Fatia 1). `None` em qualquer passo LÓGICO que não
        resolva (série não encontrada, temporada fora do range coberto,
        `still_path` nulo); exceções de rede/autenticação de `_executar`
        seguem a mesma convenção de `buscar_arte_por_titulo` — propagam pro
        chamador (`integrations/servico.py`), não são engolidas aqui."""
        tabela = self.tabela_de_temporadas(titulo, ano)
        if tabela is None:
            return None

        localizacao = localizar_temporada(tabela.temporadas, numero_absoluto)
        if localizacao is None:
            return None
        numero_da_temporada, numero_na_temporada = localizacao

        stills = self.stills_da_temporada(tabela.id_da_serie, numero_da_temporada)
        if stills is None:
            return None
        return stills.get(numero_na_temporada)

    def tabela_de_temporadas(self, titulo: str, ano: int | None) -> TabelaDeTemporadas | None:
        """`GET /tv/{id}` -> `seasons[]` -> tabela "primeiro episódio absoluto
        por temporada", acumulando `episode_count` das temporadas anteriores —
        mesma aritmética que `extractors/animefire.py::
        _mapa_primeiro_episodio_por_temporada` já resolve do lado do
        AnimeFire (útil só como referência), aqui resolvida puramente do lado
        do TMDB. Pública (não `_`-prefixada): reusada por
        `buscar_still_de_episodio` E por `integrations/servico.py` (memo
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

    def stills_da_temporada(
        self, id_da_serie: int, numero_da_temporada: int
    ) -> dict[int, str | None] | None:
        """`GET /tv/{id}/season/{n}` -> `episode_number -> still_path`
        (prefixado) de TODOS os episódios daquela temporada, numa única
        chamada — usada por `buscar_still_de_episodio` e por
        `integrations/servico.py` pra popular o cache de uma temporada
        inteira de uma vez (Fatia 5), em vez de repescar esta URL por
        episódio."""
        dados = self._executar(
            f"/tv/{id_da_serie}/season/{numero_da_temporada}", {"language": _IDIOMA}
        )
        episodios = dados.get("episodes")
        if not isinstance(episodios, list):
            return None

        stills: dict[int, str | None] = {}
        for episodio in episodios:
            if not isinstance(episodio, dict):
                continue
            numero = episodio.get("episode_number")
            if not isinstance(numero, int):
                continue
            stills[numero] = _url_imagem(episodio.get("still_path"), _TAMANHO_STILL)
        return stills or None

    def _resolver_serie(self, titulo: str, ano: int | None) -> dict | None:
        """Busca `GET /search/tv` por `titulo` e escolhe o melhor candidato
        (`_melhor_resultado`). Privado e reusado por `buscar_arte_por_titulo`
        e, na Fatia 5, por `buscar_still_de_episodio` — não duplicar a busca.

        Sem `first_air_date_year` (D3): a AniList modela cada temporada como
        uma `Media` própria, o TMDB modela a série inteira numa entrada só —
        filtrar por ano de estreia devolveria zero resultados pra sequel/split
        -cour. O ano entra só como desempate, dentro de `_melhor_resultado`.
        """
        dados = self._executar(
            "/search/tv",
            {"query": titulo, "include_adult": "false", "page": 1, "language": _IDIOMA},
        )
        resultados = dados.get("results")
        if not isinstance(resultados, list) or not resultados:
            return None
        return _melhor_resultado(resultados, titulo, ano)

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
    """Escolhe o melhor item de `Page.results` (D3 do plano):

    1. descarta itens sem `poster_path` E sem `backdrop_path` (arte nenhuma
       pra oferecer);
    2. entre os que sobram, prefere os cujo `name`/`original_name` (slug)
       bate com o slug de `titulo` — cai pro pool inteiro se ninguém bater;
    3. dentro do pool escolhido, com `ano` conhecido, vence o de menor
       distância entre `first_air_date` e `ano` (empate mantém a ordem de
       relevância do TMDB, já que `min` preserva o primeiro em empates e o
       pool não é reordenado); sem `ano`, vence o primeiro.
    """
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

    if ano is None:
        return pool[0]
    return min(pool, key=lambda item: _distancia_do_ano(item, ano))


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


def _url_imagem(caminho: str | None, tamanho: str) -> str | None:
    """`poster_path`/`backdrop_path` do TMDB já vêm com `/` inicial."""
    if not caminho:
        return None
    return f"{_URL_IMAGEM}/{tamanho}{caminho}"

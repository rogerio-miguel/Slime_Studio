"""Inferência de versão (legendado/dublado) a partir de título/slug de fonte
remota — domínio puro, sem `requests`/framework/I/O (mesma regra de
`integrations/base.py`).

Ancorado no achado confirmado ao vivo: nos sites, dublado não é uma aba do
mesmo anime — é outra entrada de catálogo com identificador/slug próprio (ex.
`tensei-shitara-slime-datta-ken` vs `tensei-shitara-slime-datta-ken-dublado`).
A versão vive no slug/título já capturado pelo extractor, sem exigir scraping
novo — esta função só lê o texto que já atravessa a fronteira.
"""

import re

from core.enums import VersaoEpisodio

# Fronteira de token obrigatória — nunca substring solta: o marcador precisa
# estar isolado por `-`, espaço, ou início/fim de string (cobre fim de path,
# ex. `-dublado-episodio-5` e `-dublado` no fim do slug). Sem isso, um título
# como "Legend of the Galactic Heroes" casaria com "leg" por acaso.
_REGEX_DUBLADO = re.compile(r"(?:^|[-\s])(?:dublado|dub)(?:$|[-\s])", re.IGNORECASE)
_REGEX_LEGENDADO = re.compile(r"(?:^|[-\s])(?:legendado|leg)(?:$|[-\s])", re.IGNORECASE)


def inferir_versao(titulo_exibicao: str, identificador: str) -> VersaoEpisodio | None:
    """Detecta marcador de versão em `titulo_exibicao` ou `identificador`.

    `None` quando nenhum marcador é encontrado — o chamador decide se ausência
    equivale a legendado por convenção do site; esta função não assume isso.
    """
    textos = (titulo_exibicao, identificador)
    if any(_REGEX_DUBLADO.search(texto) for texto in textos):
        return VersaoEpisodio.DUBLADO
    if any(_REGEX_LEGENDADO.search(texto) for texto in textos):
        return VersaoEpisodio.LEGENDADO
    return None


def remover_marcador_de_versao(texto: str) -> str:
    """Remove o marcador de versão (dublado/dub/legendado/leg) de `texto`,
    reaproveitando a mesma fronteira de token de `inferir_versao` (sem
    duplicar a regra). Usado por `extractors/resolucao.py` para normalizar
    título/slug antes de comparar com o slug base do anime — sem isso, "Nome
    Dublado" nunca casaria com o slug do anime cadastrado (que não carrega o
    marcador).
    """
    sem_marcador = _REGEX_DUBLADO.sub(" ", texto)
    sem_marcador = _REGEX_LEGENDADO.sub(" ", sem_marcador)
    return " ".join(sem_marcador.split())

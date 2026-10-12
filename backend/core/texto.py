"""Utilitários de texto de domínio — sem dependências externas (Escada de Minimalismo)."""

import re
import unicodedata

# Letras que o NFKD não decompõe em base + acento (sem esta tabela sumiriam:
# "Bjørn" -> "bjrn"). O `×` entra porque títulos o usam como o "x" de
# "Hunter × Hunter"/"Kakegurui ××", que o site grafa com a letra. Aspas
# tipográficas viram o apóstrofo ASCII pra "Can’t" e "Can't" darem o mesmo slug
# (a AniList entrega a tipográfica; o título digitado e os sites, a ASCII).
_SINAL_DE_MULTIPLICACAO = {"×": "x"}
_APOSTROFES_TIPOGRAFICOS = dict.fromkeys("’‘ʼ′", "'")
_TRANSLITERACAO = str.maketrans(
    {
        **_SINAL_DE_MULTIPLICACAO,
        "ø": "o",
        "æ": "ae",
        "œ": "oe",
        "ß": "ss",
        "đ": "d",
        "ł": "l",
        "þ": "th",
        **_APOSTROFES_TIPOGRAFICOS,
    }
)


def slugificar(texto: str) -> str:
    """Converte texto livre num slug ASCII (`a-z0-9-`), usado tanto pelo CLI
    produtor de jobs quanto pelo layout de diretório HLS.

    Ex.: "Tensei Shitara Slime Datta Ken 2" -> "tensei-shitara-slime-datta-ken-2"

    O slug é gravado em `Anime.slug`: o resultado de um título ASCII não pode
    mudar. Depois do NFKD, o acento (marca combinante) some colado à letra,
    enquanto qualquer outro caractere não-ASCII — símbolo (★ ♪ ∞), kanji — vira
    separador, pra "Magical★Explorer" não colar as palavras.
    """
    decomposto = unicodedata.normalize("NFKD", texto.lower().translate(_TRANSLITERACAO))
    legivel = "".join(
        caractere
        if caractere.isascii()
        else "" if unicodedata.combining(caractere) else " "
        for caractere in decomposto
    )
    return re.sub(r"[^a-z0-9]+", "-", legivel).strip("-")


_SO_SINAL_DE_TITULO = str.maketrans(_SINAL_DE_MULTIPLICACAO | _APOSTROFES_TIPOGRAFICOS)


def termo_de_consulta(termo: str) -> str:
    """Termo de busca como o campo de pesquisa de um site WordPress o espera:
    mesma limpeza de símbolos de `slugificar`, mas preservando letras e acentos
    (o site os indexa). Hífen e sublinhado viram espaço; `×` vira "x" e aspas
    tipográficas viram ASCII; símbolo e pontuação não-ASCII ("Magical★Explorer",
    "「…」") viram espaço, que o campo de busca não casaria."""
    limpo = termo.translate(_SO_SINAL_DE_TITULO)
    sem_simbolo = "".join(
        " " if not c.isascii() and unicodedata.category(c)[0] in "SP" else c for c in limpo
    )
    return " ".join(re.sub(r"[-_]+", " ", sem_simbolo).split())


def sem_simbolo_final(texto: str) -> str:
    """Tira a última palavra quando é só símbolo não-ASCII ("Kakegurui ××",
    "Go-toubun no Hanayome ∬"): a AniList marca assim a sequência de uma obra, e
    o site a cataloga sob o nome sem o símbolo. Só palavra solta, separada por
    espaço — "Gintama°" e "Magical★Explorer" são o nome. Nunca esvazia o título.
    Símbolo ASCII ("+", "~") fica de fora: é pontuação de título comum."""
    base, _, ultima = texto.rpartition(" ")
    eh_simbolo = bool(ultima) and all(
        not c.isascii() and unicodedata.category(c).startswith("S") for c in ultima
    )
    return base.strip() if eh_simbolo and base.strip() else texto

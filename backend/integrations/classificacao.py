"""Decide se uma `Media` é SÉRIE (ganha `numero_temporada` e entra no walk de
franquia) ou EXTRA (filme/OVA/especial agrupado sob a série-mãe, ver
`Anime.formato_midia`). Domínio puro: sem HTTP nem banco — recebe os campos já
extraídos pelo adapter.

O vocabulário de `format` é o cru da AniList, o mesmo que `Anime.formato_midia`
persiste. As regras vêm de uma amostra de 400 itens reais (100 de cada ONA/OVA/
SPECIAL/MOVIE, 2026-10-03), não de intuição:
- ONA é série em ~92% dos casos (12 eps × 24 min, inclusive cadeias ONA↔ONA e
  TV↔ONA como Baki e Sakamoto Days) — marcar ONA como extra por padrão estava
  errado;
- só a aresta `PARENT` indica extra de forma confiável. `SIDE_STORY`/`SPIN_OFF`
  ligam temporadas inteiras de séries reais (Shuumatsu no Valkyrie, Baki), e
  duração sozinha não separa (Aggressive Retsuko 10×15 é série, Emiya-san 13×14
  é extra);
- há OVA que é série de verdade (Hellsing, FLCL, Ginga Eiyuu Densetsu).
"""

# Formatos que o walk de `PREQUEL`/`SEQUEL` e a busca de série-mãe aceitam como
# nó de franquia. ONA entra: série de streaming/donghua encadeia ONA↔ONA e
# TV↔ONA. Filme/OVA/especial/música continuam fora — recap e extra não avançam
# o ordinal narrativo.
FORMATOS_DE_TEMPORADA = frozenset({"TV", "TV_SHORT", "ONA"})

_FORMATOS_SEMPRE_EXTRA = frozenset({"MOVIE", "MUSIC", "SPECIAL"})
_OVA_MINIMO_DE_EPISODIOS = 6
_OVA_MINIMO_DE_MINUTOS = 20
_ONA_MAXIMO_DE_EPISODIOS_DE_EXTRA = 2


def eh_serie(
    formato: str | None, episodios: int | None, duracao_min: int | None, tem_pai: bool
) -> bool:
    """`True` quando a mídia é série. `tem_pai`: a AniList declara aresta `PARENT`
    para outro anime (é "extra de" alguém).

    Dado ausente decide pro lado de série: o erro barato é um card a mais na
    grade, o caro é uma série fora do catálogo — caso de ONA recém-anunciado,
    que a AniList publica sem `episodes`/`duration`."""
    if formato is None or formato in ("TV", "TV_SHORT"):
        return True
    if tem_pai or formato in _FORMATOS_SEMPRE_EXTRA:
        return False
    if formato == "OVA":
        return (
            episodios is not None
            and episodios >= _OVA_MINIMO_DE_EPISODIOS
            and duracao_min is not None
            and duracao_min >= _OVA_MINIMO_DE_MINUTOS
        )
    if formato == "ONA":
        return episodios is None or episodios > _ONA_MAXIMO_DE_EPISODIOS_DE_EXTRA
    return True

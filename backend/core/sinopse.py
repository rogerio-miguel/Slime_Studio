"""Escolha da sinopse de um anime entre a do provedor de metadados (AniList/Kitsu,
inglês) e as do TMDB (pt-BR) — regra pura, sem I/O."""

# "The third season of X." tem 30-55 caracteres; as sinopses curtas mas
# específicas medidas no catálogo (≥116) ficam de fora.
_LIMITE_GENERICA = 80

# O TMDB modela a franquia numa série só; a AniList, cada temporada num registro.
# Ano de estreia do item a até 1 ano do da série => é a 1ª temporada.
_TOLERANCIA_DE_ANO = 1


def eh_generica(sinopse: str | None) -> bool:
    return sinopse is None or len(sinopse.strip()) < _LIMITE_GENERICA


def eh_primeira_temporada(ano_da_serie: int | None, ano_do_item: int | None) -> bool:
    """Palpite pelo ano, para quando o número da temporada não é conhecido (feed,
    metadados recém-buscados). Ano desconhecido conta como continuação: o lado
    conservador, que só troca texto genérico."""
    if ano_da_serie is None or ano_do_item is None:
        return False
    return abs(ano_da_serie - ano_do_item) <= _TOLERANCIA_DE_ANO


def escolher_sinopse(
    atual: str | None,
    *,
    serie_ptbr: str | None,
    temporada_ptbr: str | None = None,
    primeira_temporada: bool,
) -> str | None:
    """Sinopse a exibir. Nunca cria uma onde `atual` é `None` (o gate de
    enriquecimento lazy em `api/servicos/descoberta.py` usa `sinopse is None`).

    - 1ª temporada: a da série em pt-BR (é a premissa da própria temporada).
    - Continuação: a da temporada em pt-BR, se existir; senão a da série, só
      quando `atual` é genérica ("The second season of X."); senão `atual`, que
      é específica da temporada e vale mais que a premissa geral."""
    if atual is None:
        return None
    if primeira_temporada:
        return serie_ptbr or atual
    if temporada_ptbr:
        return temporada_ptbr
    if serie_ptbr and eh_generica(atual):
        return serie_ptbr
    return atual

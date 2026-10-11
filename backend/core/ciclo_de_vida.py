"""Política do ciclo de vida de um anime: quando vale consultar o status na
AniList e quando vale sondar a fonte real (site).

Domínio puro — sem I/O, relógio nem framework: `hoje` entra por parâmetro. É o
único lugar com a regra "este anime merece verificação?"; `api/servicos/
sondagem.py` (fonte) e `api/servicos/descoberta.py` (status) só executam. TTL de
carimbo e dedupe de tarefas em voo continuam nos chamadores — são mecânica de
execução, não política.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum

from core.enums import ResultadoDeVerificacao, StatusLancamento

# Folga após a data prevista do último episódio (estreia + 1 semana por
# episódio) em que um `FINALIZADO` incompleto ainda é re-sondado — o fansub
# atrasa o(s) último(s) episódio(s), mas não por anos.
JANELA_POS_FIM = timedelta(days=45)


class Fase(StrEnum):
    DESCONHECIDA = "desconhecida"  # status ainda não aquecido (nulo)
    PRE_ESTREIA = "pre_estreia"
    EM_LANCAMENTO = "em_lancamento"
    POS_FIM = "pos_fim"  # FINALIZADO cuja fonte ainda não alcançou o total
    ARQUIVO = "arquivo"  # FINALIZADO completo/antigo, CANCELADO, HIATO


@dataclass(frozen=True)
class RetratoDoAnime:
    """O mínimo do `Anime` de que a política precisa — mantém o domínio sem
    importar `models/`."""

    status_lancamento: StatusLancamento | None
    estreia_em: date | None
    total_episodios_anilist: int | None
    episodios_na_fonte: int | None

    @classmethod
    def de(cls, anime) -> "RetratoDoAnime":
        return cls(
            anime.status_lancamento,
            anime.estreia_em,
            anime.total_episodios_anilist,
            anime.episodios_na_fonte,
        )


def _em_janela_pos_fim(retrato: RetratoDoAnime, hoje: date) -> bool:
    """`True` quando a AniList já marcou `FINALIZADO`, mas a contagem da fonte
    ainda não alcançou o total que ela declara e a exibição terminou há pouco.

    Caso real (2026-09-19): o fansub sobe o(s) último(s) episódio(s) depois de a
    AniList fechar o status. Sem a janela, anime antigo cuja fonte nunca teve
    todos os episódios (ex. 12 de 13 por causa de um especial contado no total)
    era re-sondado, abrindo o navegador de bypass, a cada abertura da Galeria.
    `total_episodios_anilist` ou `estreia_em` ausentes não reabrem: sem eles não
    dá pra saber se falta episódio nem se ainda é recente."""
    if (
        retrato.total_episodios_anilist is None
        or retrato.estreia_em is None
        or (retrato.episodios_na_fonte or 0) >= retrato.total_episodios_anilist
    ):
        return False
    fim_previsto = retrato.estreia_em + timedelta(weeks=retrato.total_episodios_anilist)
    return hoje <= fim_previsto + JANELA_POS_FIM


def fase_do_anime(retrato: RetratoDoAnime, hoje: date) -> Fase:
    status = retrato.status_lancamento
    if status is None:
        return Fase.DESCONHECIDA
    if status is StatusLancamento.NAO_LANCADO:
        return Fase.PRE_ESTREIA
    if status is StatusLancamento.EM_LANCAMENTO:
        return Fase.EM_LANCAMENTO
    if status is StatusLancamento.FINALIZADO and _em_janela_pos_fim(retrato, hoje):
        return Fase.POS_FIM
    return Fase.ARQUIVO


# Sondar a fonte só faz sentido quando há episódio novo a contar. Fase
# desconhecida não sonda: o status é aquecido primeiro (`FASES_COM_STATUS_VIVO`)
# e, se for o caso, o anime entra na sondagem na passada seguinte.
_FASES_COM_FONTE_VIVA = frozenset({Fase.EM_LANCAMENTO, Fase.POS_FIM})

# O status da AniList só muda nestas fases: `NAO_LANCADO` precisa seguir sendo
# reconsultado até estrear (senão a data congela e o anime nunca vira
# `EM_LANCAMENTO`); `FINALIZADO`/`CANCELADO`/`HIATO` não ganham episódios.
_FASES_COM_STATUS_VIVO = frozenset({Fase.DESCONHECIDA, Fase.PRE_ESTREIA, Fase.EM_LANCAMENTO})


def deve_sondar_fonte(retrato: RetratoDoAnime, hoje: date) -> bool:
    return fase_do_anime(retrato, hoje) in _FASES_COM_FONTE_VIVA


def deve_atualizar_status(retrato: RetratoDoAnime, hoje: date) -> bool:
    return fase_do_anime(retrato, hoje) in _FASES_COM_STATUS_VIVO


def deve_resolver_fonte(
    retrato: RetratoDoAnime, hoje: date, *, tem_episodios: bool, temporada_nova: bool
) -> bool:
    """Anime SEM nenhuma fonte mapeada: vale a varredura cara (busca em todos os
    sites) para achar uma? Três motivos, todos "o usuário vai precisar dela":
    - `tem_episodios`: fonte perdida (migração apagou o mapeamento) — o badge de
      versão e as contagens ficam cegos até reencontrar o anime;
    - `temporada_nova`: continuação de franquia que o usuário terminou
      (`lancamentos.temporadas_novas`), sem episódio local ainda;
    - fase de fonte viva (`deve_sondar_fonte`): estreia ou anime em exibição que
      nunca foi aberto — sem isto, um bookmark que vira `EM_LANCAMENTO` ficaria
      sem fonte para sempre, porque só quem já tem fonte é sondado.
    O backoff por falha (`verificacao_de_anime`) é de quem executa, não daqui."""
    return tem_episodios or temporada_nova or deve_sondar_fonte(retrato, hoje)


# --- Backoff entre tentativas ---

INTERVALO_APOS_SUCESSO = timedelta(hours=6)
_ESPERA_SITE_INDISPONIVEL = timedelta(minutes=15)  # o breaker do site manda; aqui é só folga
_ESPERA_PRECISA_SESSAO = timedelta(hours=3)
_ESPERA_AMBIGUO = timedelta(days=7)  # só o usuário desfaz; nada a ganhar retentando
_BASE_NAO_ENCONTRADO, _TETO_NAO_ENCONTRADO = timedelta(hours=6), timedelta(days=7)
_BASE_ERRO, _TETO_ERRO = timedelta(hours=1), timedelta(hours=24)

# Falha que não conta contra o anime: o culpado é o site, e o breaker dele já
# segura as tentativas.
CONTA_COMO_FALHA_DO_ANIME = frozenset(ResultadoDeVerificacao) - {
    ResultadoDeVerificacao.OK,
    ResultadoDeVerificacao.SITE_INDISPONIVEL,
}


def _exponencial(base: timedelta, teto: timedelta, falhas_consecutivas: int) -> timedelta:
    expoente = min(max(falhas_consecutivas - 1, 0), 16)  # 16: evita overflow, teto já vem antes
    return min(base * 2**expoente, teto)


def proxima_tentativa(
    resultado: ResultadoDeVerificacao, falhas_consecutivas: int, agora: datetime
) -> datetime:
    """Quando tentar de novo, dado o desfecho e as falhas seguidas (já contando
    esta). Backoff exponencial só onde repetir pode mudar o resultado."""
    match resultado:
        case ResultadoDeVerificacao.OK:
            espera = INTERVALO_APOS_SUCESSO
        case ResultadoDeVerificacao.SITE_INDISPONIVEL:
            espera = _ESPERA_SITE_INDISPONIVEL
        case ResultadoDeVerificacao.PRECISA_SESSAO:
            espera = _ESPERA_PRECISA_SESSAO
        case ResultadoDeVerificacao.AMBIGUO:
            espera = _ESPERA_AMBIGUO
        case ResultadoDeVerificacao.NAO_ENCONTRADO:
            espera = _exponencial(_BASE_NAO_ENCONTRADO, _TETO_NAO_ENCONTRADO, falhas_consecutivas)
        case ResultadoDeVerificacao.ERRO:
            espera = _exponencial(_BASE_ERRO, _TETO_ERRO, falhas_consecutivas)
    return agora + espera

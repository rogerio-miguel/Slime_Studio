"""Modelo `Anime` — cada linha é uma temporada (ESPECIFICACAO.md §4/§3F)."""

from datetime import UTC, date, datetime

from sqlalchemy import Date, Integer, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from core.enums import StatusLancamento
from models.base import Base, ColunaDataHoraUTC


class Anime(Base):
    __tablename__ = "anime"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    titulo: Mapped[str] = mapped_column(String, nullable=False)
    slug: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    # Nullable: o cadastro pelo busca-e-confirma do AniList (§3F, Fase 3) preenche
    # ano/capa_path/sinopse/anilist_id depois da criação; o produtor de jobs da
    # Fase 1 (scripts/enfileirar_local.py) cria o Anime só com titulo/slug.
    ano: Mapped[int | None] = mapped_column(Integer, nullable=True)
    anilist_id: Mapped[int | None] = mapped_column(Integer, unique=True, nullable=True)
    kitsu_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Nome enganoso (herdado do schema original) — guarda uma URL do
    # provedor de metadados (AniList/Kitsu), não um caminho em disco local.
    # `Episodio.capa_path` segue a mesma convenção; renomear os dois
    # expandiria o escopo desta leva, então só documentado aqui.
    capa_path: Mapped[str | None] = mapped_column(String, nullable=True)
    sinopse: Mapped[str | None] = mapped_column(String, nullable=True)
    total_episodios_anilist: Mapped[int | None] = mapped_column(Integer, nullable=True)
    criado_em: Mapped[datetime] = mapped_column(
        ColunaDataHoraUTC(), nullable=False, default=lambda: datetime.now(UTC)
    )
    # Detector de episódios novos (badge no catálogo). Duas origens distintas,
    # nunca misturadas: a AniList alimenta as colunas de lançamento abaixo
    # (via `db.catalogo._aplicar_lancamento_no_anime`); a sondagem da fonte
    # real alimenta as colunas `fonte_verificada_*` (via
    # `api.servicos.sondagem`). Todas nullable, sem default: animes já
    # cadastrados ficam NULL até o primeiro refresh/sondagem — nunca há backfill.
    status_lancamento: Mapped[StatusLancamento | None] = mapped_column(
        SAEnum(StatusLancamento, native_enum=False, validate_strings=True), nullable=True
    )
    # AniList `nextAiringEpisode`: número do próximo episódio a ir ao ar e
    # quando. `proximo_ep_em` no futuro é o sinal PRINCIPAL do detector de
    # "episódios novos" (perna 1 de
    # `api/servicos/lancamentos.py::episodios_novos`): anime realmente no ar tem
    # o próximo episódio agendado. `proximo_ep_numero` segue só como dado
    # exibível ("próximo ep em X dias").
    proximo_ep_numero: Mapped[int | None] = mapped_column(Integer, nullable=True)
    proximo_ep_em: Mapped[datetime | None] = mapped_column(ColunaDataHoraUTC(), nullable=True)
    # Data de estreia (AniList `startDate`) — só gravada quando ano+mês+dia
    # vieram completos; alimenta o rótulo do card de bookmark no catálogo
    # (`CartaoDeEstreia`, rota `/animes` do frontend). Date pura, sem tz.
    estreia_em: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Carimbo do último refresh de lançamento — decide se o refresh lazy ao
    # abrir a página de um anime `EM_LANCAMENTO` trata o dado como velho.
    lancamento_atualizado_em: Mapped[datetime | None] = mapped_column(
        ColunaDataHoraUTC(), nullable=True
    )
    # Sondagem da fonte real (`api.servicos.sondagem`): quantos episódios
    # regulares distintos o site que o usuário usa neste anime expõe hoje.
    # `episodios_novos = max(0, episodios_na_fonte - maior_numero_capturado)`,
    # desde que o anime passe no gate de sinal de lançamento
    # (`api/servicos/lancamentos.py::episodios_novos`: `proximo_ep_em` no futuro,
    # ou `EM_LANCAMENTO` com a fonte ainda atrás de `total_episodios_anilist`).
    # `fonte_verificada_em` é carimbado
    # SÓ em sondagem bem-sucedida (falha de site não mexe em nada) e decide o
    # TTL; `fonte_verificada_dominio` guarda qual site produziu a contagem
    # (proveniência — divergência de contagem por fonte errada é o modo de
    # falha mais provável, ver `EpisodiosRemotosSaida.dominio`).
    episodios_na_fonte: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fonte_verificada_em: Mapped[datetime | None] = mapped_column(
        ColunaDataHoraUTC(), nullable=True
    )
    fonte_verificada_dominio: Mapped[str | None] = mapped_column(String, nullable=True)

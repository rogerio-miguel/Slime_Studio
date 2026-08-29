"""animesdrive migra dominio para animesdrive.cloud

O site "AnimesDrive" migrou de domínio: `animesdrive.online` →
`animesdrive.cloud`. Em paralelo, `extractors/animesdrive.py` desacopla a
identidade persistida do host real:
- `BASE_URL` (host real, usado só pra montar requests) vira
  `"https://animesdrive.cloud"`.
- `dominio` (identificador estável, persistido, NUNCA usado como URL) vira
  `"animesdrive"` (sem TLD — desacoplado de propósito, pra próxima troca de
  domínio não exigir mais nenhuma migration).

Esta migration é uma fotografia intencional desta revisão: os valores
`"animesdrive.online"`, `"animesdrive"` e `"animesdrive.cloud"` estão
hardcoded aqui de propósito, não importados de `extractors/animesdrive.py`
em runtime — isso deixaria a migration acoplada a um módulo que pode mudar
depois por razões que nada têm a ver com este backfill, e uma migration
auto-contida é mais reproduzível.

Duas categorias de coluna, tratadas de formas diferentes:
- Colunas de **identidade** (`fonte_anime.site_dominio`, `episodio.site_origem`,
  `estado_site.site_dominio`, `sessao_bypass.site_dominio`): chave opaca,
  nunca uma URL — migram o valor inteiro para `"animesdrive"`.
- Coluna de **URL real** (`episodio.url_fonte`): precisa continuar sendo uma
  URL válida e fetchável — migra só o host para `"animesdrive.cloud"`,
  preservando o path.

`estado_site` e `sessao_bypass` são cache descartável (circuit breaker e
sessão de bypass anti-bot, respectivamente) — as linhas do domínio antigo são
**apagadas**, não renomeadas, pra não deixar uma entrada "fantasma" com nome
novo e dado irrelevante do host antigo. O sistema recria essas linhas sob
demanda no próximo uso.

Nenhuma das 4 tabelas envolvidas tem mudança de schema — só UPDATE/DELETE de
dado, sem `op.batch_alter_table`.

Revision ID: 74dcc7485153
Revises: 7a3f8c1e9d4b
Create Date: 2026-08-25 12:38:26.925224

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '74dcc7485153'
down_revision: Union[str, None] = '7a3f8c1e9d4b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Fotografia intencional desta revisão — ver docstring do módulo.
_DOMINIO_ANTIGO = "animesdrive.online"
_DOMINIO_NOVO = "animesdrive"
_BASE_URL_ANTIGA = "https://animesdrive.online/"
_BASE_URL_NOVA = "https://animesdrive.cloud/"


def upgrade() -> None:
    _renomear_dominio_em_fonte_anime()
    _renomear_dominio_em_episodio()
    _trocar_host_em_url_fonte(de=_BASE_URL_ANTIGA, para=_BASE_URL_NOVA)
    _descartar_cache_do_dominio_antigo()


def _renomear_dominio_em_fonte_anime() -> None:
    """`site_dominio` é parte da PK composta `(anime_id, site_dominio, versao)`
    — antes do UPDATE, apaga qualquer linha `'animesdrive.online'` redundante
    (mesmo `anime_id`/`versao` já mapeado sob `'animesdrive'`), pra não
    estourar `IntegrityError` de UNIQUE ao renomear. Não deveria acontecer
    num banco real, mas é o tipo de guarda que o precedente
    (`0cfc12357433`) já usa por segurança.
    """
    bind = op.get_bind()
    fonte_anime = sa.table(
        "fonte_anime",
        sa.column("anime_id", sa.Integer),
        sa.column("site_dominio", sa.String),
        sa.column("versao", sa.String),
    )

    bind.execute(
        sa.text(
            "DELETE FROM fonte_anime WHERE site_dominio = :antigo"
            " AND EXISTS ("
            "   SELECT 1 FROM fonte_anime f2"
            "   WHERE f2.anime_id = fonte_anime.anime_id"
            "     AND f2.versao = fonte_anime.versao"
            "     AND f2.site_dominio = :novo"
            " )"
        ),
        {"antigo": _DOMINIO_ANTIGO, "novo": _DOMINIO_NOVO},
    )

    bind.execute(
        fonte_anime.update()
        .where(fonte_anime.c.site_dominio == _DOMINIO_ANTIGO)
        .values(site_dominio=_DOMINIO_NOVO)
    )


def _renomear_dominio_em_episodio() -> None:
    """`episodio.site_origem` não é PK/unique — UPDATE direto, sem guarda de
    colisão.
    """
    bind = op.get_bind()
    episodio = sa.table(
        "episodio",
        sa.column("site_origem", sa.String),
    )

    bind.execute(
        episodio.update()
        .where(episodio.c.site_origem == _DOMINIO_ANTIGO)
        .values(site_origem=_DOMINIO_NOVO)
    )


def _trocar_host_em_url_fonte(*, de: str, para: str) -> None:
    """Troca só o host de `episodio.url_fonte`, preservando o path — essa
    coluna precisa continuar sendo uma URL fetchável. O `LIKE`/prefixo
    completo (com `://` e barra final) é proposital: evita tocar em hosts
    parecidos mas diferentes, como `https://cdn.animesdrive.online/...`.
    """
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE episodio SET url_fonte = replace(url_fonte, :de, :para)"
            " WHERE url_fonte LIKE :prefixo"
        ),
        {"de": de, "para": para, "prefixo": f"{de}%"},
    )


def _descartar_cache_do_dominio_antigo() -> None:
    """`estado_site` (circuit breaker) e `sessao_bypass` (sessão de bypass
    anti-bot) são cache descartável, sem estado útil de longo prazo —
    apaga em vez de renomear, o sistema recria sob demanda no próximo uso.
    """
    bind = op.get_bind()
    bind.execute(
        sa.text("DELETE FROM estado_site WHERE site_dominio = :antigo"),
        {"antigo": _DOMINIO_ANTIGO},
    )
    bind.execute(
        sa.text("DELETE FROM sessao_bypass WHERE site_dominio = :antigo"),
        {"antigo": _DOMINIO_ANTIGO},
    )


def downgrade() -> None:
    # As linhas de `estado_site`/`sessao_bypass` apagadas no upgrade NÃO
    # voltam — são cache (circuit breaker / sessão de bypass anti-bot),
    # perda sem consequência funcional (o sistema recria sob demanda), mas
    # isso torna este downgrade incompleto para essas duas tabelas: não há
    # como reconstruir `falhas_consecutivas`/`cooldown_ate`/cookies que
    # existiam antes do upgrade.
    _renomear_dominio_em_fonte_anime_para_antigo()
    _renomear_dominio_em_episodio_para_antigo()
    _trocar_host_em_url_fonte(de=_BASE_URL_NOVA, para=_BASE_URL_ANTIGA)


def _renomear_dominio_em_fonte_anime_para_antigo() -> None:
    """Espelha `_renomear_dominio_em_fonte_anime`, com a mesma guarda de
    colisão invertida.
    """
    bind = op.get_bind()
    fonte_anime = sa.table(
        "fonte_anime",
        sa.column("anime_id", sa.Integer),
        sa.column("site_dominio", sa.String),
        sa.column("versao", sa.String),
    )

    bind.execute(
        sa.text(
            "DELETE FROM fonte_anime WHERE site_dominio = :novo"
            " AND EXISTS ("
            "   SELECT 1 FROM fonte_anime f2"
            "   WHERE f2.anime_id = fonte_anime.anime_id"
            "     AND f2.versao = fonte_anime.versao"
            "     AND f2.site_dominio = :antigo"
            " )"
        ),
        {"antigo": _DOMINIO_ANTIGO, "novo": _DOMINIO_NOVO},
    )

    bind.execute(
        fonte_anime.update()
        .where(fonte_anime.c.site_dominio == _DOMINIO_NOVO)
        .values(site_dominio=_DOMINIO_ANTIGO)
    )


def _renomear_dominio_em_episodio_para_antigo() -> None:
    """Espelha `_renomear_dominio_em_episodio`."""
    bind = op.get_bind()
    episodio = sa.table(
        "episodio",
        sa.column("site_origem", sa.String),
    )

    bind.execute(
        episodio.update()
        .where(episodio.c.site_origem == _DOMINIO_NOVO)
        .values(site_origem=_DOMINIO_ANTIGO)
    )

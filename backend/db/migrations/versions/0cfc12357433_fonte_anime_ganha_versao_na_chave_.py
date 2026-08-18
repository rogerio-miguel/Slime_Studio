"""fonte_anime ganha versao na chave primaria

Fase 2 da modelagem dublado/legendado (`extractors/resolucao.py`): uma mesma
fonte (anime, site) passa a poder ter até duas linhas confirmadas (uma por
`VersaoDeFonte.LEGENDADO`/`DUBLADO`) mais, opcionalmente, uma linha
`NAO_DIFERENCIADA` para sites que não separam versão no próprio markup.

Backfill dos dados existentes (§9 do plano de arquitetura, fotografia do
estado do projeto nesta revisão — não importa `extractors/registro.py`, que
pode mudar depois sem que esta migration precise mudar junto):
- Domínio que já era conhecido por diferenciar versão no slug
  (`animesdrive.online`): infere `LEGENDADO`/`DUBLADO` a partir do marcador em
  `identificador_no_site`, reaproveitando `extractors.versao.inferir_versao`
  (mesma regra de fronteira de token usada em tempo de execução — não
  duplicada aqui).
- Qualquer outro domínio: `NAO_DIFERENCIADA` (site não sabia diferenciar
  quando a linha foi gravada).

`episodio.versao` só amplia o conjunto de valores aceitos (ganha
`DESCONHECIDA`) — é um `VARCHAR` sem `CHECK` no SQLite (`native_enum=False`,
sem `create_constraint`), então não há dado existente para migrar ali.

Revision ID: 0cfc12357433
Revises: 4f449b167e89
Create Date: 2026-08-18 10:20:34.846982

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0cfc12357433'
down_revision: Union[str, None] = '4f449b167e89'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Domínios conhecidos por diferenciar legendado/dublado no próprio slug, no
# momento desta migration — fotografia intencional, ver docstring do módulo.
_DOMINIOS_QUE_DIFERENCIAM = {"animesdrive.online"}


def upgrade() -> None:
    # `episodio.versao` ganha `DESCONHECIDA` no conjunto de valores aceitos.
    # VARCHAR sem CHECK constraint no SQLite: puramente cosmético/bookkeeping
    # do Alembic, não requer rebuild de dado nenhum.
    with op.batch_alter_table('episodio', schema=None) as batch_op:
        batch_op.alter_column('versao',
               existing_type=sa.VARCHAR(length=9),
               type_=sa.Enum('LEGENDADO', 'DUBLADO', 'DESCONHECIDA', name='versaoepisodio', native_enum=False),
               existing_nullable=False)

    # `fonte_anime` ganha `versao` na PK. `server_default` é só andaime desta
    # migration: preenche as linhas existentes durante o rebuild do SQLite
    # (batch mode copia dado old->new; coluna nova sem valor explícito por
    # linha exigiria default). Removido no fim da função, depois do backfill
    # real — o modelo (`models/fonte_anime.py`) não quer default nenhum.
    with op.batch_alter_table('fonte_anime', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'versao',
                sa.Enum('LEGENDADO', 'DUBLADO', 'NAO_DIFERENCIADA', name='versaodefonte', native_enum=False),
                nullable=False,
                server_default='NAO_DIFERENCIADA',
            )
        )
        batch_op.drop_constraint('pk_fonte_anime', type_='primary')
        batch_op.create_primary_key('pk_fonte_anime', ['anime_id', 'site_dominio', 'versao'])

    _backfill_versao_por_marcador_no_identificador()

    with op.batch_alter_table('fonte_anime', schema=None) as batch_op:
        batch_op.alter_column(
            'versao',
            existing_type=sa.Enum('LEGENDADO', 'DUBLADO', 'NAO_DIFERENCIADA', name='versaodefonte', native_enum=False),
            server_default=None,
            existing_nullable=False,
        )


def _backfill_versao_por_marcador_no_identificador() -> None:
    """Corrige, para os domínios que já diferenciavam versão no slug, o valor
    de `versao` das linhas que o `server_default='NAO_DIFERENCIADA'` acabou de
    popular — reaproveita `inferir_versao` (mesma regra usada em tempo de
    execução) em vez de reimplementar a heurística em SQL puro.
    """
    from core.enums import VersaoEpisodio
    from extractors.versao import inferir_versao

    bind = op.get_bind()
    fonte_anime = sa.table(
        'fonte_anime',
        sa.column('anime_id', sa.Integer),
        sa.column('site_dominio', sa.String),
        sa.column('identificador_no_site', sa.String),
        sa.column('versao', sa.String),
    )

    linhas = bind.execute(
        sa.select(
            fonte_anime.c.anime_id,
            fonte_anime.c.site_dominio,
            fonte_anime.c.identificador_no_site,
        ).where(fonte_anime.c.site_dominio.in_(_DOMINIOS_QUE_DIFERENCIAM))
    ).fetchall()

    for anime_id, site_dominio, identificador in linhas:
        versao = inferir_versao(identificador, identificador) or VersaoEpisodio.LEGENDADO
        bind.execute(
            fonte_anime.update()
            .where(
                fonte_anime.c.anime_id == anime_id,
                fonte_anime.c.site_dominio == site_dominio,
            )
            .values(versao=versao.name)
        )


def _colapsar_versoes_antes_de_remover_coluna() -> None:
    """Mantém só 1 linha por `(anime_id, site_dominio)`, na ordem de
    preferência `LEGENDADO > DUBLADO > NAO_DIFERENCIADA`, apagando as demais
    — necessário antes de recriar a PK de 2 colunas (ver comentário em
    `downgrade`). Perda de dado é inerente a este downgrade (a PK de 2
    colunas não consegue representar duas versões do mesmo site); a ordem de
    preferência só decide qual sobrevive.
    """
    bind = op.get_bind()
    fonte_anime = sa.table(
        'fonte_anime',
        sa.column('anime_id', sa.Integer),
        sa.column('site_dominio', sa.String),
        sa.column('versao', sa.String),
    )
    _PREFERENCIA = {'LEGENDADO': 0, 'DUBLADO': 1, 'NAO_DIFERENCIADA': 2}

    linhas = bind.execute(
        sa.select(fonte_anime.c.anime_id, fonte_anime.c.site_dominio, fonte_anime.c.versao)
    ).fetchall()

    vencedora_por_par: dict[tuple[int, str], str] = {}
    for anime_id, site_dominio, versao in linhas:
        chave = (anime_id, site_dominio)
        atual = vencedora_por_par.get(chave)
        if atual is None or _PREFERENCIA[versao] < _PREFERENCIA[atual]:
            vencedora_por_par[chave] = versao

    for (anime_id, site_dominio), versao_vencedora in vencedora_por_par.items():
        bind.execute(
            fonte_anime.delete().where(
                fonte_anime.c.anime_id == anime_id,
                fonte_anime.c.site_dominio == site_dominio,
                fonte_anime.c.versao != versao_vencedora,
            )
        )


def downgrade() -> None:
    # A PK de 3 colunas existe pra permitir MAIS DE UMA linha por
    # (anime_id, site_dominio) — uma LEGENDADO, uma DUBLADO e/ou uma
    # NAO_DIFERENCIADA (`_resolver_no_site_que_diferencia` grava as duas
    # partições da mesma busca, "dado grátis"). Rebuild de tabela em batch do
    # SQLite popula a PK alvo via `INSERT INTO nova SELECT ... FROM antiga` —
    # sem colapsar essas duplicatas antes, a PK de 2 colunas alvo (sem
    # `versao`) estoura `IntegrityError` (UNIQUE) pra qualquer anime que já
    # tenha as duas versões mapeadas no mesmo site, que não é caso raro, é o
    # uso comum da feature com um site que diferencia. Mantém 1 linha por
    # (anime_id, site_dominio), preferindo a mais informativa: confirmada
    # (LEGENDADO antes de DUBLADO, convenção "sem marcador = legendado" já
    # usada no resto do sistema) sobre NAO_DIFERENCIADA.
    _colapsar_versoes_antes_de_remover_coluna()

    with op.batch_alter_table('fonte_anime', schema=None) as batch_op:
        batch_op.drop_constraint('pk_fonte_anime', type_='primary')
        batch_op.create_primary_key('pk_fonte_anime', ['anime_id', 'site_dominio'])
        batch_op.drop_column('versao')

    with op.batch_alter_table('episodio', schema=None) as batch_op:
        batch_op.alter_column('versao',
               existing_type=sa.Enum('LEGENDADO', 'DUBLADO', 'DESCONHECIDA', name='versaoepisodio', native_enum=False),
               type_=sa.VARCHAR(length=9),
               existing_nullable=False)

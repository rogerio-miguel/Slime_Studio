"""Hierarquia de exceções de domínio do Slime Studio.

Este módulo não importa nada de framework, banco de dados ou I/O — é domínio puro
(ver regra de dependência da Clean Architecture no CLAUDE.md, seção 1).
"""


class ErroSlimeStudio(Exception):
    """Raiz da hierarquia de exceções de domínio do projeto."""


class ErroDeConfiguracao(ErroSlimeStudio):
    """Configuração ausente ou inválida (`.env`, PATH de ferramentas, permissões)."""


class FonteInvalida(ErroSlimeStudio):
    """Arquivo de origem não existe, não decodifica, ou tem duração fora do esperado."""


class FalhaDeFerramenta(ErroSlimeStudio):
    """`ffmpeg`/`ffprobe` (ou outro subprocesso externo) retornou código de saída != 0.

    Carrega a cauda do stderr do processo para diagnóstico, sem precisar
    reexecutar o comando para saber o que houve.
    """

    def __init__(self, mensagem: str, *, cauda_stderr: str = "") -> None:
        super().__init__(mensagem)
        self.cauda_stderr = cauda_stderr


class WorkerJaEmExecucao(ErroSlimeStudio):
    """Já existe uma instância do worker rodando (lock de instância única)."""


class FalhaDeExtracao(ErroSlimeStudio):
    """Falha ao extrair dados/mídia de um site (ESPECIFICACAO.md §3A).

    `permite_retentativa` distingue falhas transitórias (rede, sessão expirada)
    de falhas definitivas (estrutura do site mudou) — o executor do worker usa
    essa distinção para decidir entre reagendar o job ou marcá-lo como precisando
    de intervenção humana.
    """

    def __init__(
        self, mensagem: str, *, dominio: str = "", permite_retentativa: bool = True
    ) -> None:
        super().__init__(mensagem)
        self.dominio = dominio
        self.permite_retentativa = permite_retentativa


class SiteEmCooldown(FalhaDeExtracao):
    """Circuit breaker do site está aberto (§3A item 2) — tente o próximo site da lista.

    Nunca retentável: o site já está em cooldown, então repetir a mesma tentativa
    só espera o próprio cooldown — o certo é `baixar_com_fallback_de_site` pular
    direto para o próximo site da lista.
    """

    def __init__(
        self, mensagem: str, *, dominio: str = "", permite_retentativa: bool = False
    ) -> None:
        super().__init__(mensagem, dominio=dominio, permite_retentativa=permite_retentativa)


class SessaoRejeitada(FalhaDeExtracao):
    """Cookies cacheados de `SessaoBypass` foram recusados pelo site — invalidar e escalar
    para o cliente de navegador."""


class EstruturaDoSiteMudou(FalhaDeExtracao):
    """Parsing encontrou uma página válida mas com formato inesperado (DOM/JSON mudou).

    Não é transitório — retentar sem o adapter ser corrigido só repete a falha.
    """

    def __init__(
        self, mensagem: str, *, dominio: str = "", permite_retentativa: bool = False
    ) -> None:
        super().__init__(mensagem, dominio=dominio, permite_retentativa=permite_retentativa)


class FonteNaoEncontrada(FalhaDeExtracao):
    """Anime/episódio não existe neste site (HTTP 404 ou equivalente)."""


class FonteAmbigua(ErroSlimeStudio):
    """`extractors.resolucao.resolver_fonte_do_anime` devolveu `ConfirmacaoNecessaria`
    (mais de um candidato, sem match exato de título) — a API mapeia isto para 409
    com `{"motivo": "fonte_ambigua", "dominio": ..., "candidatos": [...]}`.

    `candidatos` já vem serializado (lista de `dict`), não como `ResultadoBusca` —
    este módulo é domínio puro e não importa `extractors` (regra de dependência da
    Clean Architecture, CLAUDE.md §1).
    """

    def __init__(self, dominio: str, candidatos: list[dict[str, str]]) -> None:
        super().__init__(f"fonte ambígua em {dominio}: {len(candidatos)} candidato(s)")
        self.dominio = dominio
        self.candidatos = candidatos


class EpisodioJaExiste(ErroSlimeStudio):
    """Episódio já cadastrado com a mesma identidade (`anime_id`, `numero`, `tipo`,
    `versao` — `uq_episodio_identidade`). A API mapeia isto para 409."""

    def __init__(self, episodio_id: int | None = None) -> None:
        super().__init__(f"episódio já cadastrado, id={episodio_id}")
        self.episodio_id = episodio_id


class JobEmExecucao(ErroSlimeStudio):
    """Existe um `Job` em `ESTADOS_EM_EXECUCAO` associado ao anime/episódio que se
    tentou remover — remover agora deixaria o worker escrevendo num diretório/
    registro que acabou de sumir (`ondelete="CASCADE"` apaga o `Job` por baixo,
    sem o worker perceber). A API mapeia isto para 409; o cliente precisa
    cancelar o job antes de remover."""

    def __init__(self, job_id: int) -> None:
        super().__init__(f"job {job_id} em execução — cancele antes de remover")
        self.job_id = job_id

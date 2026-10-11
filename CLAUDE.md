# Projeto Slime Studio — Diretrizes de Desenvolvimento

Guia de contexto e regras para o Claude Code neste projeto.

> **Nome do projeto**: Slime Studio (repositório `Slime_Studio`, decidido em 2026-08-10). O nome de trabalho "novo-projeto-anime4k" foi aposentado junto com os dois documentos de spec antigos, consolidados em `ESPECIFICACAO.md`.
>
> **Estado do projeto**: fora do estágio de scaffold. `backend/` tem API FastAPI, worker assíncrono e extractors (Strategy Pattern) funcionais, mais a camada `integrations/` de metadados de provedor externo (AniList/Kitsu, adicionada em 2026-08-16) com `uv run pytest`/`uv run ruff check` passando. `frontend/` é um projeto Vite+Tailwind funcional com rotas, home dirigida por provedor externo e fluxo de captura on-demand ponta a ponta (`npm run lint`/`npm run build` passando). O protótipo original do player WebGPU permanece isolado em `teste/` (sandbox, sem lint/teste) — não confirmado nesta passada se já foi portado pro pipeline real do `frontend/`, ver seção 3E de `ESPECIFICACAO.md`. `ESPECIFICACAO.md` está desatualizado em relação às decisões descritas abaixo (o usuário vai atualizá-lo separadamente — não edite esse arquivo sem pedido explícito). Consulte-o mesmo assim para o racional histórico de cada decisão antes de implementar.
>
> **Gatilho de hardware**: a GPU atual é uma Radeon RX 580 (8GB) e várias decisões do projeto existem só por causa dela (ramo GAN excluído, presets mais leves, pipeline em lote adiado, chunks pequenos por VRAM). Se o usuário mencionar em qualquer conversa que trocou de GPU — RTX 5060 Ti ou qualquer RTX 50xx/superior —, **pare e trate isso como gatilho de replanejamento de arquitetura**: leia a seção 12 de `ESPECIFICACAO.md` e siga o procedimento de lá antes de seguir com a tarefa em curso.

## 1. Arquitetura
- **Estrutura:** Monorepo com dois escopos principais: `backend/` (Python + FastAPI para a API, worker `asyncio` nativo como **processo separado**, SQLAlchemy + SQLite em modo WAL, `uv` como gerenciador de pacotes) e `frontend/` (React + Vite + Tailwind). Estrutura de pastas completa proposta na seção 10.1 do documento de especificação. **Onde mora a qualidade de imagem hoje:** no frontend (Anime4K/WebGPU por frame, seção 3E) — o backend é baixador, empacotador HLS, catálogo e agregador de metadados de provedor externo (capa/sinopse/lançamentos via `integrations/`, seção 2). O upscaling em lote no worker só entra depois do gatilho de hardware (seção 12).
- **Duas famílias de adapter, não confunda:** `extractors/` resolve **vídeo** em sites de streaming (scraping, bypass anti-bot, sessão/cookie, circuit breaker) e alimenta o pipeline de captura. `integrations/` resolve **metadados** (capa, sinopse, lançamentos) em APIs JSON públicas (AniList, Kitsu) e alimenta a home/catálogo. Mesmo Strategy Pattern nos dois, infraestrutura de resiliência bem diferente — ver seção 2.
- **Escopo:** trabalhe estritamente dentro do escopo da tarefa (backend, frontend); não misture contextos nem faça buscas globais desnecessárias.
- **Regra de dependência (Clean Architecture):** código de domínio/regras de negócio não importa nada de framework, banco de dados, UI ou I/O externo — esses detalhes dependem do domínio, nunca o contrário. Antes de adicionar um import ou acoplar uma camada a outra, confirme de que lado da fronteira cada uma está.

---

## 2. Padrões do Backend (`/backend`)
- **Stack:** Python + FastAPI (API) e `asyncio` nativo (worker, processo separado — decisão fechada na seção 2.1 do documento: API e worker comunicam só via a tabela `Job` no SQLite, polling, sem Celery/Redis). SQLAlchemy + SQLite (modo WAL). Alembic para migrations. `uv` como gerenciador de pacotes.
- **Dois entry points, um pacote:** `api/` (sempre no ar, serve player/painel/WebSocket) e `worker/` (roda o pipeline, pode levar horas por job) vivem no mesmo pacote Python mas rodam como processos separados — um crash/restart de um não derruba o outro. Não acople os dois além do que já é compartilhado via `models/`.
- **Scripts:** `uv run pytest` (testes), `uv run ruff check` (lint), `uv run alembic upgrade head` (migrations, planejado — ainda não existe).
- **Convenções de nomenclatura:** snake_case tanto no banco (SQLAlchemy) quanto no código Python — o schema do documento (seção 4) já usa nomes em português nesse padrão (`anime_id`, `titulo`, `criado_em`); manter consistência com isso, não inventar tradução para inglês/camelCase.
- **Extratores por site:** seguem Strategy Pattern (`extractors/base.py` + uma classe por site, ex. `animefire.py`). Cada adapter ganha a camada de cache de sessão/retry/circuit breaker (seção 3A do documento) — não reimplementar isso por site.
- **Integrações de metadados (`integrations/`):** mesmo Strategy Pattern (`integrations/base.py`, domínio puro, sem `requests`/framework — os adapters `anilist.py`/`kitsu.py` é que trazem HTTP), orquestrados em `integrations/servico.py` (único lugar com `asyncio.to_thread`+`wait_for`, cadeia de fallback AniList→Kitsu, cache do feed em memória de processo com TTL e stale-while-revalidate). **Não reaproveitar `extractors/resiliencia.py`** aqui — ele é acoplado a `SessaoBypass`/`ClienteNavegador`/`EstadoSite` por domínio, que fazem sentido pra site com bypass anti-bot, não pra API JSON pública. Metadado confirmado (capa/sinopse/ids) **persiste** nas colunas de `Anime` que já existem pra isso (`capa_path` guarda URL do provedor, não caminho em disco); feed volátil ("em alta" e demais feeds da Home) vive em cache de memória com TTL, **espelhado na tabela `cache_de_feed`** (descartável, não é fonte de verdade): `integrations/` não conhece banco, então a API injeta a persistência no lifespan (`api/servicos/cache_de_feeds.py`, `instalar_persistencia_de_feeds`/`restaurar_feeds_persistidos`). Após reinício o feed persistido volta como cache expirado — servido na hora e revalidado em segundo plano — porque a cache fria (busca AniList + overlay de arte TMDB por item) levava dezenas de segundos. Ao medir feed fora da API, chame `instalar_provedores_de_arte`, senão o TMDB não entra e a medição sai ~10x mais rápida.
- **`/api/admin/*` é rótulo de escrita/descoberta, não fronteira de autenticação.** A API não tem gate de auth hoje (uso local/pessoal) — várias rotas `admin` já são chamadas direto de página pública do frontend (ex. resolução de fonte, criação de anime). Se autenticação entrar no projeto, é aí que a separação passa a importar; até lá, não deduza controle de acesso a partir do prefixo.
- **Pipeline de vídeo (`worker/pipeline/`):** roda `ffmpeg`/`realesrgan-ncnn-vulkan` como subprocessos. **Processar sempre em chunks** (500–1000 frames) — nunca extrair/manter o episódio inteiro em disco de uma vez (seção 3C do documento: risco real e documentado de estourar disco/VRAM). Este pipeline está **condicionado à troca de GPU** (seção 12 do documento) — não implementar antes disso.

---

## 3. Padrões do Frontend (`/frontend`)
- **Stack:** React + Vite + Tailwind. Player via `hls.js` (obrigatório — só Safari toca HLS nativo) alimentando um `<video>` **oculto**; o elemento visível é um `<canvas>` WebGPU rodando o pipeline Anime4K por frame (seção 3E do documento). Controles nativos do `<video>` não se aplicam — o canvas os cobre: a barra de controles é própria, com navegação por teclado e ARIA obrigatórios.
- **Scripts:** `npm run lint`, `npm run build`.
- **Home dirigida por provedor:** a página inicial (`paginas/Inicio.jsx`) não é o catálogo local — é só a grade "Destaques da temporada", alimentada pelo feed de provedor externo (`GET /api/animes/em-alta`). Clicar num item do feed ainda não catalogado localmente **materializa** o anime (`POST /api/admin/animes`) antes de navegar pra `/anime/:id`. O catálogo local (listar, abrir, **remover** via `DELETE /api/admin/animes/{id}`) mora inteiro em `paginas/Galeria.jsx` (rota `/animes`, linkada na navbar) e também em `PaginaDoAnime.jsx`; a Inicio não duplica essa gestão.
- **Reaproveitamento:** componentes visuais do projeto `Slime_Shell_Web` (ex: `AnimeCard`) devem ser portados, não recriados do zero — validar compatibilidade com o novo modelo de dados (seção 4 do documento) antes de portar direto. O mesmo vale pro *padrão* de acesso a provedor (AniList principal, Kitsu fallback) que alimenta `backend/integrations/` — foi portado do `Slime_Shell_Web`, não reinventado.

---

## 4. Padrões de Código
- **Nomes e funções:** nomes que revelam intenção; funções pequenas, de responsabilidade única.
- **Sem redundância:** ao notar o mesmo trecho pela 2ª vez, sinalize; na 3ª, extraia. Antes de escrever código novo, percorra a Escada de Minimalismo: precisa existir? → já existe no projeto? → a stdlib resolve? → uma dependência já instalada resolve? → cabe em uma linha clara? → só então o mínimo necessário.
- **Erros:** explícitos, nunca silenciosos. Valide entrada nas fronteiras do sistema.
- **Comentários:** só o porquê (decisão, restrição, armadilha), nunca o que o código já diz.
- **Mínimo não é menos que o correto:** economia de código nunca justifica cortar validação de entrada, tratamento de erro, segurança ou acessibilidade.

---

## 5. Segurança
Baseline de fundamentos; para revisão e endurecimento use a skill `security`.
- **API HTTP:** valide entrada na fronteira com schema (Pydantic); não vaze stack trace nem detalhe interno em erros (a mensagem crua vai pro log). A ausência de auth em `/api/admin/*` é decisão de uso local (seção 2), sustentada por `TrustedHostMiddleware` + `ProtecaoDeOrigem` (`api/seguranca.py`): `Host` só `localhost`/`127.0.0.1` e `Origin` exata (`_ORIGENS_PERMITIDAS`) em escrita e WebSocket — Vite em porta diferente de 5173 exige ajustar a lista. Se a API for exposta além do localhost, auth vem antes.
- **Banco:** SQLAlchemy/consulta parametrizada, nunca concatenar entrada em SQL.
- **Frontend:** nunca renderize HTML não sanitizado (sinopse/título vindos de provedor são entrada de terceiros); sem segredo no bundle. O CSP roda em Report-Only (`frontend/vite.config.js`, dev e preview): violação só aparece no console; promover a `Content-Security-Policy` quando o console estiver limpo no uso real.
- **URLs de terceiros:** URL vinda de scraping ou provedor (AniList/Kitsu/TMDB) e repassada a `ffmpeg`/`yt-dlp`/`requests` passa por allowlist de destino (evita SSRF); mídia passa por `exigir_url_de_midia_segura` e os GETs por `get_validando_redirects` (`extractors/rede_segura.py`), que barram IP interno, nome que resolve pra IP interno e redirect pra destino interno; resta a janela de DNS rebinding entre verificar e usar (ffmpeg/yt-dlp resolvem por conta própria). Nunca interpole em shell — subprocesso sempre com lista de argumentos. O modo `local` não existe na API: arquivo local só via `scripts/enfileirar_local.py`.
- **Caminhos e nomes de arquivo:** título/episódio vindo de scraping ou provedor que vira caminho em disco (`media/`, chunks do `ffmpeg`) usa nome gerado ou slug sanitizado; nunca aceite `..` nem caminho absoluto de fora.
- **Segredos:** chaves de API (ex. TMDB) só em `.env` fora do git, nunca no repositório nem no bundle do frontend; se vazou, rotacione. O hook `.githooks/pre-commit` roda `gitleaks` nos arquivos em stage (ativar por clone: `git config core.hooksPath .githooks`).
- **Dependências:** lockfiles (`uv.lock`, `package-lock.json`) versionados; auditoria periódica (`pip-audit`/`osv-scanner` no backend, `npm audit` no frontend), atenção especial a `yt-dlp` (o worker loga a versão no start e avisa acima de 90 dias), `cloudscraper` e `drissionpage`. `ruff` roda com a regra `S` (bandit; `tests/` ignora S101/S105/S108) e `frontend/.npmrc` usa `ignore-scripts=true`.

---

## 6. Comportamento do Agente
- **Foco cirúrgico:** use `@arquivo` em vez de varrer pastas.
- **Conciso:** não explique conceitos básicos a menos que peçam; entregue código funcional e direto.
- **Dependências:** ao instalar ou atualizar pacotes, respeite as versões dos manifestos do projeto.
- **Commit:** a skill `commit` não se auto-invoca. Ao fechar cada unidade de trabalho — antes de começar a próxima —, sugira-a em uma linha (assunto fechado, `git status` acumulando, código estável); se o usuário adiar, siga sem insistir.
- **Terminal:** peça permissão antes de qualquer comando, exceto `uv run ruff check`, `npm run lint` (análise estática, sem `--fix`) e `uv run pytest` (suíte offline, ~16 s; o `addopts` do `pyproject.toml` já exclui `-m rede`), liberados no `.claude/settings.json`. Peça sempre para `-m rede` (scraping real), para jobs de GPU (upscaling) e para servidores ou build — comandos podem envolver scraping/bypass anti-bot ou GPU de longa duração, nunca dispare isso sem confirmação explícita. O `settings.json` não trava argumentos, então essa restrição a `-m rede` é regra de texto. `gh pr merge` só depois do "pode mesclar" do usuário no chat.

---

## 7. Comandos de Validação
Lidos pela skill `checkpoint`. O build só roda mediante permissão; lint e `uv run pytest` são as exceções (ver Comportamento do Agente).

| Escopo | Comando |
|---|---|
| backend | `uv run pytest` (testes) e `uv run ruff check` (lint) |
| frontend | `npm run lint && npm run build` |

> `uv` instalado em 2026-08-10 (`~/.local/bin/uv`), `backend/pyproject.toml` inicializado (`uv init --bare --name slime-studio`). `frontend/` é um projeto Vite+Tailwind inicializado e funcional (não é mais só estrutura de pastas).

---

## 8. Orquestração
**Execute você mesmo (padrão).** Delegar abre um contexto frio que recarrega tudo do zero; só compensa quando o subagente lê muito e devolve pouco. Delegue apenas nestes casos:
- **`explorer`** — responder exigiria muitas leituras/buscas que virariam ruído no seu contexto (mapear convenção espalhada, achar todos os usos, entender subsistema desconhecido). Paralelize escopos independentes; se a informação já está na conversa, não delegue.
- **`implementer`** — trabalho em vários arquivos ou refactor definido, grande demais para fazer inline. Passe a lista de arquivos e o plano (ele não re-explora). Bugfix pontual e mudança de 1-2 arquivos: faça direto.
- **`architect`** (Opus, o mais caro) — só se um critério do próprio agente bater e depois de uma tentativa direta que falhou.

Correção depois de um subagente concluído: faça direto ou abra um novo, estreito; não o retome via `SendMessage` (recarrega o histórico inteiro). Ambiguidade de design sinalizada por subagente vai ao `architect`. Sem `reviewer` separado: o `implementer` autorrevisa o diff, e no caminho direto essa revisão é sua.

Fatie o trabalho do `implementer` por unidade natural (arquivo, rota, endpoint, componente), uma chamada por fatia: escopo grande ("a Fase X inteira") acumula contexto turno a turno (medido aqui: 354 turnos / 53M numa cadeia) e o `maxTurns` do frontmatter não corta isso (bug conhecido do Claude Code).

---

## 9. Debug Visual (Chrome)
`claude-in-chrome` só para inspeção visual pontual: cada screenshot ou frame de GIF custa muito mais tokens que texto.
- **Quando abrir:** a pedido explícito ("testa no navegador", "abre no chrome", "verifica visualmente"), ou se o problema for visual e 2-3 correções por código falharam (avise antes de abrir).
- **Uma tarefa, uma navegação:** vá direto à rota do componente e reuse a mesma aba.
- **Texto antes de imagem:** para erro de JS, leia o console em vez de tirar screenshot. Sem GIF por padrão; no máximo uma rodada de checagem por ativação.
- **Login/CAPTCHA:** pare e avise; não tente contornar.

---

_Gerado pela skill `bootstrap` do kit `claude-toolkit` (versão 0.16.0) em 2026-09-30, atualizando o CLAUDE.md gerado na versão 0.3.0 em 2026-08-10._

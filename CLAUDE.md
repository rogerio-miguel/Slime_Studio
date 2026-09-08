# Projeto Slime Studio - Diretrizes de Desenvolvimento

Este arquivo serve como guia de contexto e restrições para o Claude Code. Siga estas regras rigorosamente para otimizar o consumo de tokens e manter a consistência do código.

> **Nome do projeto**: Slime Studio (repositório `Slime_Studio`, decidido em 2026-08-10). O nome de trabalho "novo-projeto-anime4k" foi aposentado junto com os dois documentos de spec antigos, consolidados em `ESPECIFICACAO.md`.
>
> **Estado do projeto**: fora do estágio de scaffold. `backend/` tem API FastAPI, worker assíncrono e extractors (Strategy Pattern) funcionais, mais a camada `integrations/` de metadados de provedor externo (AniList/Kitsu, adicionada em 2026-08-16) com `uv run pytest`/`uv run ruff check` passando. `frontend/` é um projeto Vite+Tailwind funcional com rotas, home dirigida por provedor externo e fluxo de captura on-demand ponta a ponta (`npm run lint`/`npm run build` passando). O protótipo original do player WebGPU permanece isolado em `teste/` (sandbox, sem lint/teste) — não confirmado nesta passada se já foi portado pro pipeline real do `frontend/`, ver seção 3E de `ESPECIFICACAO.md`. `ESPECIFICACAO.md` está desatualizado em relação às decisões descritas abaixo (o usuário vai atualizá-lo separadamente — não edite esse arquivo sem pedido explícito). Consulte-o mesmo assim para o racional histórico de cada decisão antes de implementar.
>
> **Gatilho de hardware**: a GPU atual é uma Radeon RX 580 (8GB) e várias decisões do projeto existem só por causa dela (ramo GAN excluído, presets mais leves, pipeline em lote adiado, chunks pequenos por VRAM). Se o usuário mencionar em qualquer conversa que trocou de GPU — RTX 5060 Ti ou qualquer RTX 50xx/superior —, **pare e trate isso como gatilho de replanejamento de arquitetura**: leia a seção 12 de `ESPECIFICACAO.md` e siga o procedimento de lá antes de seguir com a tarefa em curso.

## 1. Arquitetura do Sistema
- **Estrutura:** Monorepo com dois escopos principais: `backend/` (Python + FastAPI para a API, worker `asyncio` nativo como **processo separado**, SQLAlchemy + SQLite em modo WAL, `uv` como gerenciador de pacotes) e `frontend/` (React + Vite + Tailwind). Estrutura de pastas completa proposta na seção 10.1 do documento de especificação. **Onde mora a qualidade de imagem hoje:** no frontend (Anime4K/WebGPU por frame, seção 3E) — o backend é baixador, empacotador HLS, catálogo e agregador de metadados de provedor externo (capa/sinopse/lançamentos via `integrations/`, seção 2). O upscaling em lote no worker só entra depois do gatilho de hardware (seção 12).
- **Duas famílias de adapter, não confunda:** `extractors/` resolve **vídeo** em sites de streaming (scraping, bypass anti-bot, sessão/cookie, circuit breaker) e alimenta o pipeline de captura. `integrations/` resolve **metadados** (capa, sinopse, lançamentos) em APIs JSON públicas (AniList, Kitsu) e alimenta a home/catálogo. Mesmo Strategy Pattern nos dois, infraestrutura de resiliência bem diferente — ver seção 2.
- **Escopo Base:** Ao receber uma tarefa, opere estritamente dentro do escopo correspondente (backend, frontend). Não misture contextos ou faça buscas globais desnecessárias.
- **Clean Architecture (regra de dependência):** código de domínio/regras de negócio não importa nada de framework, banco de dados, UI ou I/O externo — esses detalhes dependem do domínio, nunca o contrário. Antes de adicionar um import ou acoplar uma camada a outra, confirme de que lado da fronteira cada uma está.

---

## 2. Padrões do Backend (`/backend`)
- **Stack:** Python + FastAPI (API) e `asyncio` nativo (worker, processo separado — decisão fechada na seção 2.1 do documento: API e worker comunicam só via a tabela `Job` no SQLite, polling, sem Celery/Redis). SQLAlchemy + SQLite (modo WAL). Alembic para migrations. `uv` como gerenciador de pacotes.
- **Dois entry points, um pacote:** `api/` (sempre no ar, serve player/painel/WebSocket) e `worker/` (roda o pipeline, pode levar horas por job) vivem no mesmo pacote Python mas rodam como processos separados — um crash/restart de um não derruba o outro. Não acople os dois além do que já é compartilhado via `models/`.
- **Scripts:** `uv run pytest` (testes), `uv run ruff check` (lint), `uv run alembic upgrade head` (migrations, planejado — ainda não existe).
- **Convenções de nomenclatura:** snake_case tanto no banco (SQLAlchemy) quanto no código Python — o schema do documento (seção 4) já usa nomes em português nesse padrão (`anime_id`, `titulo`, `criado_em`); manter consistência com isso, não inventar tradução para inglês/camelCase.
- **Extratores por site:** seguem Strategy Pattern (`extractors/base.py` + uma classe por site, ex. `animefire.py`). Cada adapter ganha a camada de cache de sessão/retry/circuit breaker (seção 3A do documento) — não reimplementar isso por site.
- **Integrações de metadados (`integrations/`):** mesmo Strategy Pattern (`integrations/base.py`, domínio puro, sem `requests`/framework — os adapters `anilist.py`/`kitsu.py` é que trazem HTTP), orquestrados em `integrations/servico.py` (único lugar com `asyncio.to_thread`+`wait_for`, cadeia de fallback AniList→Kitsu, cache do feed em memória de processo com TTL). **Não reaproveitar `extractors/resiliencia.py`** aqui — ele é acoplado a `SessaoBypass`/`ClienteNavegador`/`EstadoSite` por domínio, que fazem sentido pra site com bypass anti-bot, não pra API JSON pública. Metadado confirmado (capa/sinopse/ids) **persiste** nas colunas de `Anime` que já existem pra isso (`capa_path` guarda URL do provedor, não caminho em disco); feed volátil ("em alta") fica só em cache de memória.
- **`/api/admin/*` é rótulo de escrita/descoberta, não fronteira de autenticação.** A API não tem gate de auth hoje (uso local/pessoal) — várias rotas `admin` já são chamadas direto de página pública do frontend (ex. resolução de fonte, criação de anime). Se autenticação entrar no projeto, é aí que a separação passa a importar; até lá, não deduza controle de acesso a partir do prefixo.
- **Pipeline de vídeo (`worker/pipeline/`):** roda `ffmpeg`/`realesrgan-ncnn-vulkan` como subprocessos. **Processar sempre em chunks** (500–1000 frames) — nunca extrair/manter o episódio inteiro em disco de uma vez (seção 3C do documento: risco real e documentado de estourar disco/VRAM). Este pipeline está **condicionado à troca de GPU** (seção 12 do documento) — não implementar antes disso.

---

## 3. Padrões do Frontend (`/frontend`)
- **Stack:** React + Vite + Tailwind. Player via `hls.js` (obrigatório — só Safari toca HLS nativo) alimentando um `<video>` **oculto**; o elemento visível é um `<canvas>` WebGPU rodando o pipeline Anime4K por frame (seção 3E do documento). Controles nativos do `<video>` não se aplicam — o canvas os cobre: a barra de controles é própria, com navegação por teclado e ARIA obrigatórios.
- **Scripts:** `npm run lint`, `npm run build`.
- **Home dirigida por provedor:** a página inicial (`paginas/Inicio.jsx`) não é o catálogo local — é só a grade "Destaques da temporada", alimentada pelo feed de provedor externo (`GET /api/animes/em-alta`). Clicar num item do feed ainda não catalogado localmente **materializa** o anime (`POST /api/admin/animes`) antes de navegar pra `/anime/:id`. O catálogo local (listar, abrir, **remover** via `DELETE /api/admin/animes/{id}`) mora inteiro em `paginas/Galeria.jsx` (rota `/animes`, linkada na navbar) e também em `PaginaDoAnime.jsx`; a Inicio não duplica essa gestão.
- **Reaproveitamento:** componentes visuais do projeto `Slime_Shell_Web` (ex: `AnimeCard`) devem ser portados, não recriados do zero — validar compatibilidade com o novo modelo de dados (seção 4 do documento) antes de portar direto. O mesmo vale pro *padrão* de acesso a provedor (AniList principal, Kitsu fallback) que alimenta `backend/integrations/` — foi portado do `Slime_Shell_Web`, não reinventado.

---

## 4. Regras de Comportamento para o Agente (Claude Code)
- **Foco Cirúrgico:** Sempre que for criar ou alterar código, use a referência exata do arquivo utilizando `@nome_do_arquivo` para evitar varrer pastas completas.
- **Modo Silencioso de Token:** Não explique conceitos básicos de programação ou arquitetura a menos que explicitamente solicitado. Foque em entregar código funcional, limpo e direto ao ponto.
- **Não quebre o Ecossistema:** Ao instalar ou atualizar pacotes, respeite as versões/dependências já estabelecidas nos arquivos de manifesto do projeto.
- **Clean Code:** nomes que revelam intenção, funções pequenas com responsabilidade única, sem duplicação, tratamento de erro explícito (nunca silencioso), comentários só onde o código não consegue falar por si.
- **Escada de Minimalismo (código mínimo, nunca menos que o correto):** Antes de escrever qualquer código novo, percorra em ordem: (1) isso precisa existir? — se não, não escreva; (2) já existe algo no projeto que resolve? — reutilize; (3) a stdlib da linguagem resolve? — use; (4) uma dependência já instalada resolve? — use; (5) cabe em uma linha clara? — uma linha; (6) só então escreva o mínimo necessário. Esta regra reduz código e tokens, mas **nunca** justifica cortar validação de entrada, tratamento de erro, segurança ou acessibilidade.
- **Timing de commit:** a skill `commit` não se auto-invoca (`disable-model-invocation`), então só quem pode notar o momento certo de rodá-la é você, aqui, com o contexto vivo. Ao terminar cada unidade de trabalho — antes de começar a próxima — avalie se é hora de sugerir `commit`: assunto fechado, `git status` acumulando arquivos, ou trecho de código chegando a um estado estável. Anuncie a sugestão em uma linha; se o usuário preferir adiar, siga para o próximo passo sem insistir.
- **Controle Rígido de Testes e Terminal:** É ESTRITAMENTE PROIBIDO executar ferramentas de bash, rodar testes ou iniciar servidores de validação por conta própria. Ao finalizar a escrita ou alteração de um código, NUNCA enfileire comandos no terminal sem a permissão explícita do usuário. Apenas entregue o código e pergunte: "Deseja que eu rode os testes agora?". Isso vale em dobro aqui: comandos podem envolver scraping/bypass anti-bot ou jobs de GPU de longa duração (upscaling), nunca dispare isso sem confirmação explícita.

---

## 5. Comandos de Validação
A skill `checkpoint` lê esta seção para saber o que rodar ao gerar um checkpoint.

| Escopo | Comando |
|---|---|
| backend | `uv run pytest` (testes) e `uv run ruff check` (lint) |
| frontend | `npm run lint && npm run build` |

> `uv` instalado em 2026-08-10 (`~/.local/bin/uv`), `backend/pyproject.toml` inicializado (`uv init --bare --name slime-studio`). `frontend/` é um projeto Vite+Tailwind inicializado e funcional (não é mais só estrutura de pastas).

---

## 6. Orquestração (Custo/Desempenho)

**O executor padrão é a sessão principal.** Delegar a subagente é a exceção, não a regra —
cada delegação abre um contexto frio que recarrega tudo do zero, e a medição mostrou que
delegar por padrão saía mais caro (em tokens e em tempo) do que executar direto. Ao receber
um pedido, execute-o você mesmo se consegue enxergar a mudança inteira e o padrão a seguir.
Só saia desse caminho pelos gatilhos objetivos abaixo.

### Princípio de custo (o que decide tudo abaixo)
Duas coisas custam, e uma não anula a outra:
- **Contexto grande na sessão principal** — cobrado em todo turno seguinte. Ler 20 arquivos
  inline para uma decisão pontual infla o custo de toda a sessão dali para frente.
- **Cada hop de subagente** — recarrega contexto frio, o subagente re-deriva o que você já
  sabia, e o resultado ainda volta para você conferir.

Delegar só vale quando o subagente **lê muito e devolve pouco**. É o caso do `explorer`:
varre 20 arquivos, devolve um resumo de 200 linhas. Não é o caso de mandar um subagente
fazer uma edição de 2 arquivos que você mesmo faria em 3 turnos.

### Caminho direto (padrão)
A sessão principal executa, sem `explorer` e sem `architect`. Use sempre que:
- Você consegue enxergar a mudança inteira e o padrão que ela segue — mesmo que toque
  vários arquivos, contanto que seja mecânico/repetitivo.
- O contexto necessário já está na conversa, ou dá para obter com poucas leituras
  direcionadas (`@arquivo`, um `grep`, abrir 2-3 arquivos).
- É um bugfix pontual, um ajuste localizado, uma feature pequena que segue padrão existente.

### Quando delegar (exceção)
- **`explorer`** — quando responder ao pedido exigiria muitas leituras/buscas (mapear uma
  convenção espalhada, achar todos os usos de algo, entender um subsistema que você não
  conhece) e esse material vira ruído no contexto depois. Paralelize escopos independentes
  (um `explorer` cada, na mesma leva). Se a informação já está na conversa, não delegue.
- **`implementer`** — só para trabalho que toca **vários arquivos** ou é um **refactor/feature
  definido** grande o bastante para inflar demais o seu contexto se feito inline. Passe a ele
  a lista de arquivos e o plano — ele não deve re-explorar. Bugfix pontual e mudança de 1-2
  arquivos **não** vão para o `implementer`: é mais barato no caminho direto.
- **`architect`** — só quando um critério objetivo do próprio agente bate (mais de uma camada
  sem padrão para replicar, decisão de design nova, ou bug sem causa óbvia **após** uma
  tentativa direta que falhou). É o agente mais caro do kit (Opus, ~2,05x Sonnet). Escopo já
  claro nunca passa por aqui. Na dúvida, o loop principal tenta direto primeiro.

Sem `reviewer` separado: o `implementer` autorrevisa o próprio diff (edge cases, segurança,
validação de entrada) antes de reportar. No caminho direto, essa revisão cética do diff é
sua.

### Fatiamento e reentrada
- Um `implementer` com escopo grande demais ("implemente a Fase X inteira") acumula contexto
  turno a turno como o loop principal faria (medido neste projeto: 354 turnos / 53M numa
  cadeia; o `maxTurns` do frontmatter **não** corta isso — bug conhecido do Claude Code).
  Fatie por unidade natural (arquivo, rota, endpoint, componente), uma chamada por fatia.
- Rodada de correção depois de um subagente concluído → abra um `implementer` novo focado só
  no achado, ou faça no caminho direto. Não retome o agente antigo via `SendMessage`:
  recarrega o histórico inteiro a cada vez.
- Subagente sinalizou ambiguidade de design → `architect`, não improvise.

---

## 7. Integração com Chrome (Debug Visual)
A integração `claude-in-chrome` só deve ser usada para inspeção/depuração visual pontual. Cada screenshot ou frame de GIF é imagem e custa muito mais tokens que texto — trate o navegador como recurso caro, não como reflexo automático.
- **Dois gatilhos, não um:**
  1. **Manual:** só abra o navegador quando solicitado explicitamente ("testa no navegador", "abre no chrome", "verifica visualmente", "vê se ficou bom").
  2. **Automático por esgotamento:** se o problema for de natureza visual/frontend e já houve 2-3 tentativas de correção via código sem resolver, pode abrir o navegador por conta própria para inspecionar — avise que está fazendo isso porque tentativas anteriores não resolveram, antes de agir.
- **Uma tarefa, uma navegação:** vá direto para a URL/rota do componente em questão.
- **Reuse de aba:** mantenha a mesma aba/sessão aberta durante toda a tarefa de verificação.
- **Prefira texto a imagem quando possível:** para erros de JS, leia o console via DevTools em vez de tirar screenshot.
- **Sem GIF por padrão:** nunca grave GIF de interação a menos que solicitado explicitamente.
- **Sem loop de verificação:** no máximo uma rodada de checagem por ativação.
- **Login/CAPTCHA:** se a integração pausar pedindo login ou CAPTCHA, pare e avise — não insista tentando contornar.

---

_Gerado pela skill `bootstrap` do kit `claude-toolkit` (versão 0.3.0) em 2026-08-10.
Seção 6 (Orquestração) atualizada manualmente em 2026-08-25 para o pipeline sem `reviewer`
separado (fundido ao `implementer` na v0.7.0 do kit), e em 2026-09-07 para a doutrina da
v0.9.0 — caminho direto vira o padrão, delegar é exceção por gatilho objetivo._

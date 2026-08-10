# Projeto Slime Studio - Diretrizes de Desenvolvimento

Este arquivo serve como guia de contexto e restrições para o Claude Code. Siga estas regras rigorosamente para otimizar o consumo de tokens e manter a consistência do código.

> **Nome do projeto**: Slime Studio (repositório `Slime_Studio`, decidido em 2026-08-10 — antes referenciado como "novo-projeto-anime4k", nome de trabalho do documento de especificação).
>
> **Estado do projeto**: scaffold inicial criado (`backend/` com `pyproject.toml` via `uv init`, `frontend/`, `media/`, `scripts/`, `.env.example`) — ainda sem código de aplicação. As seções abaixo descrevem a arquitetura já fechada no documento de especificação (`novo-projeto-anime4k.md`, seção 2.1). Consulte o documento para o racional completo de cada decisão antes de implementar.

## 1. Arquitetura do Sistema
- **Estrutura:** Monorepo com dois escopos principais: `backend/` (Python + FastAPI para a API, worker `asyncio` nativo como **processo separado**, SQLAlchemy + SQLite em modo WAL, `uv` como gerenciador de pacotes) e `frontend/` (React + Vite + Tailwind). Estrutura de pastas completa proposta na seção 10.1 do documento de especificação.
- **Escopo Base:** Ao receber uma tarefa, opere estritamente dentro do escopo correspondente (backend, frontend). Não misture contextos ou faça buscas globais desnecessárias.
- **Clean Architecture (regra de dependência):** código de domínio/regras de negócio não importa nada de framework, banco de dados, UI ou I/O externo — esses detalhes dependem do domínio, nunca o contrário. Antes de adicionar um import ou acoplar uma camada a outra, confirme de que lado da fronteira cada uma está.

---

## 2. Padrões do Backend (`/backend`)
- **Stack:** Python + FastAPI (API) e `asyncio` nativo (worker, processo separado — decisão fechada na seção 2.1 do documento: API e worker comunicam só via a tabela `Job` no SQLite, polling, sem Celery/Redis). SQLAlchemy + SQLite (modo WAL). Alembic para migrations. `uv` como gerenciador de pacotes.
- **Dois entry points, um pacote:** `api/` (sempre no ar, serve player/painel/WebSocket) e `worker/` (roda o pipeline, pode levar horas por job) vivem no mesmo pacote Python mas rodam como processos separados — um crash/restart de um não derruba o outro. Não acople os dois além do que já é compartilhado via `models/`.
- **Scripts (planejados, ainda não existem):** `uv run pytest` (testes), `uv run ruff check` (lint), `uv run alembic upgrade head` (migrations).
- **Convenções de nomenclatura:** snake_case tanto no banco (SQLAlchemy) quanto no código Python — o schema do documento (seção 4) já usa nomes em português nesse padrão (`anime_id`, `titulo`, `criado_em`); manter consistência com isso, não inventar tradução para inglês/camelCase.
- **Extratores por site:** seguem Strategy Pattern (`extractors/base.py` + uma classe por site, ex. `animefire.py`). Cada adapter ganha a camada de cache de sessão/retry/circuit breaker (seção 3A do documento) — não reimplementar isso por site.
- **Pipeline de vídeo (`worker/pipeline/`):** roda `ffmpeg`/`realesrgan-ncnn-vulkan` como subprocessos. **Processar sempre em chunks** (500–1000 frames) — nunca extrair/manter o episódio inteiro em disco de uma vez (seção 3C do documento: risco real e documentado de estourar disco/VRAM).

---

## 3. Padrões do Frontend (`/frontend`)
- **Stack:** React + Vite + Tailwind. Player via `hls.js` (obrigatório — só Safari toca HLS nativo) com controles nativos do `<video>`.
- **Scripts (planejados, ainda não existem):** `npm run lint`, `npm run build`.
- **Reaproveitamento:** componentes visuais do projeto `Slime_Shell_Web` (ex: `AnimeCard`) devem ser portados, não recriados do zero — validar compatibilidade com o novo modelo de dados (seção 4 do documento) antes de portar direto.

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
A skill `transicao` lê esta seção para saber o que rodar ao gerar um checkpoint.

| Escopo | Comando |
|---|---|
| backend | `uv run pytest` (testes) e `uv run ruff check` (lint) |
| frontend | `npm run lint && npm run build` |

> `uv` instalado em 2026-08-10 (`~/.local/bin/uv`) e `backend/pyproject.toml` já inicializado (`uv init --bare --name slime-studio`). `frontend/` ainda não foi inicializado como projeto Vite — só a estrutura de pastas existe.

---

## 6. Orquestração (Custo/Desempenho)

A sessão principal orquestra; ela não é o executor padrão. Ao receber um pedido, faça a triagem
e siga **um** dos dois caminhos abaixo. Anuncie qual escolheu, em uma linha, antes de agir.

### Princípio de custo (o que decide tudo abaixo)
O contexto da sessão principal é cobrado em **todo** turno seguinte. Output de tool lido inline
fica lá para sempre; output de tool de um subagente não entra — só o resumo entra. Por isso:
**delegue o que precisa ser lido mas não precisa ser lembrado.** Um mapeamento de código que
serve para uma decisão e depois vira ruído é o caso clássico: vale mais um relatório de
200 linhas do `explorer` do que 20 arquivos despejados no contexto principal.
O inverso também vale: o que a sessão principal *já tem* em contexto não deve ser re-lido por
ninguém — repassar ao subagente é mais barato que mandá-lo redescobrir.

### Caminho direto
Use quando **todas** forem verdadeiras:
- A mudança é trivial e de escopo óbvio (poucas linhas, 1 arquivo).
- Segue padrão já estabelecido no projeto — não há decisão de design a tomar.
- O contexto necessário já está na conversa ou em arquivos referenciados via `@arquivo`.

Nesse caminho a sessão principal executa direto, sem `explorer`, sem `architect` e sem `reviewer`.
Orquestrar uma tarefa de 3 linhas custa três contextos onde um resolveria.

### Caminho orquestrado
Qualquer coisa que não passe no teste acima. Sequência:

1. **`explorer`** — só se faltar contexto. Se a informação já está na conversa, pule.
   Paralelize: escopos independentes viram um `explorer` cada, na mesma leva, não em série.
2. **`architect`** — só se ao menos um critério objetivo do agente for atendido (mais de uma
   camada afetada, ausência de padrão estabelecido, ou bug sem causa óbvia **após** uma tentativa
   direta do `implementer`). Não escalar "por segurança": escopo já claro vai direto ao passo 3.
3. **`implementer`** — sempre. Recebe o plano do `architect` quando houve um, ou a instrução
   direta quando não houve. Repasse o contexto que você já tem em vez de deixá-lo redescobrir.
4. **`reviewer`** — sempre neste caminho, sobre o diff.

### Falhas e reentrada
- `implementer` sinalizou escopo ambíguo → volte ao passo 2 (`architect`), não improvise a decisão.
- `implementer` falhou uma tentativa direta em bug → agora o `architect` é justificado (causa-raiz).
- `reviewer` apontou problema → volte ao `implementer` com os achados; só re-invoque o `reviewer`
  se a correção mudou o desenho, não a cada ajuste pontual.

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

_Gerado pela skill `bootstrap` do kit `claude-toolkit` (versão 0.3.0) em 2026-08-10._

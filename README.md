<div align="center">
  <img src="frontend/src/assets/logo2.png" alt="Slime Studio" width="420" />

  <p>
    Catálogo pessoal de animes com captura, empacotamento HLS e um player
    WebGPU com upscaling Anime4K por frame.
  </p>
</div>

---


<div align="center">
  <img src="frontend/src/assets/inicio.png" alt="Demo da home do Slime Studio" width="640" />
</div>

## O que é

Slime Studio é uma aplicação full-stack para montar e assistir um catálogo pessoal de
animes. É a evolução do [Slime Shell Web](https://github.com/rogerio-miguel/Slime_Shell_Web),
que por sua vez é a evolução do projeto original [Slime Shell](https://github.com/rogerio-miguel/Slime_Shell).

- A **home** mostra os destaques da temporada a partir de um feed de metadados externo
  (AniList, com fallback Kitsu) — não é o catálogo local.
- Escolher um item da home **materializa** o anime no catálogo (persiste no banco) antes
  de abrir a página dele.
- A **página do anime** resolve a fonte de vídeo entre os sites suportados (AnimeFire,
  MeusAnimes e AnimesDrive, nessa ordem de prioridade) e lista os episódios disponíveis
  para captura sob demanda — nada é baixado até o usuário clicar em **Capturar**.
- Episódios capturados são empacotados em HLS e assistidos num **player próprio**:
  `hls.js` alimenta um `<video>` oculto, e o quadro visível é um `<canvas>` WebGPU
  rodando o pipeline Anime4K frame a frame, com barra de controles própria (sem os
  controles nativos do `<video>`).
- O **catálogo local** (listar, abrir, remover) vive na Galeria e na página do anime.

As duas maiores melhorias de experiência do player, feitas de forma independente uma da
outra:

- **Upscaling Anime4K (imagem):** pipeline WebGPU por frame, descrito acima.
- **Áudio Cinema (som):** grafo Web Audio próprio no `<video>` — realce de grave,
  compressor/limiter e crossfeed para fone — ligado/desligado direto na barra de
  controles, sem tocar no pipeline de imagem.

## Screenshots

<table>
  <tr>
    <td align="center" colspan="2"><b>Catálogo</b></td>
  </tr>
  <tr>
    <td colspan="2" align="center"><img src="frontend/src/assets/catalogo.png" width="600" /></td>
  </tr>
  <tr>
    <td align="center" colspan="2"><b>Página do Anime</b></td>
  </tr>
  <tr>
    <td colspan="2" align="center"><img src="frontend/src/assets/anime-page.png" width="600" /></td>
  </tr>
  <tr>
    <td align="center" colspan="2"><b>Player</b></td>
  </tr>
  <tr>
    <td colspan="2" align="center"><img src="frontend/src/assets/player.png" width="600" /></td>
  </tr>
  <tr>
    <td colspan="2" align="center"><img src="frontend/src/assets/player2.png" width="600" /></td>
  </tr>
  <tr>
    <td colspan="2" align="center"><img src="frontend/src/assets/player3.png" width="600" /></td>
  </tr>
  <tr>
    <td colspan="2" align="center"><img src="frontend/src/assets/player4.png" width="600" /></td>
  </tr>
</table>

## Arquitetura

Monorepo com dois escopos independentes, comunicando-se só por HTTP/WebSocket:

```
Slime_Studio/
├── backend/     API FastAPI + worker assíncrono + extractors + integrations
└── frontend/    React + Vite + Tailwind + player WebGPU
```

### Backend (`backend/`)

- **Stack:** Python, FastAPI (API), `asyncio` nativo (worker, processo separado),
  SQLAlchemy + SQLite (modo WAL), Alembic, `uv`.
- **API e worker não são acoplados diretamente** — trocam estado só via a tabela `Job`
  no SQLite (polling), sem fila externa (Celery/Redis).
- **`extractors/`** — um adapter por site de streaming (Strategy Pattern), resolve
  vídeo com cache de sessão, retry e circuit breaker (bypass anti-bot). A resolução
  de fonte tenta os sites em cadeia de fallback (AnimeFire → MeusAnimes → AnimesDrive);
  `blogger.py` é um helper compartilhado para players do Blogger embutidos, e o
  download cai para `yt-dlp` quando a CDN serve manifesto DASH.
- **`integrations/`** — mesmo padrão, mas para metadados: AniList como provedor
  principal e Kitsu como fallback, com cache em memória do feed "em alta".
- **`worker/pipeline/`** — encapsula `ffmpeg` como subprocesso para empacotar os
  episódios capturados em HLS e gerar o storyboard de prévia de cena usado no player.

```
backend/
├── api/           # rotas FastAPI, serviços, WebSocket
├── worker/        # loop assíncrono + pipeline de vídeo
├── extractors/     # adapters de site (vídeo)
├── integrations/   # adapters de metadados (AniList/Kitsu)
├── core/          # domínio puro — enums, erros, config, texto
├── models/        # SQLAlchemy
└── db/migrations/ # Alembic
```

### Frontend (`frontend/`)

- **Stack:** React 19, Vite, Tailwind, React Router, `hls.js`, `anime4k-webgpu`.

```
frontend/src/
├── paginas/    # Inicio, Galeria, PaginaDoAnime, player (HLS e vídeo local)
├── player/     # canvas WebGPU, controles, hooks do Anime4K e do Áudio Cinema
├── inicio/     # grade de destaques dirigida pelo feed externo
├── api/        # cliente HTTP para o backend (materializar/remover inclusos)
└── components/ # UI compartilhada (navbar, cards, etc.)
```

## Rodando localmente

Pré-requisitos: [`uv`](https://docs.astral.sh/uv/), Node.js, `ffmpeg` no PATH, e um
navegador com suporte a WebGPU (Chrome/Brave recentes).

### 1. Clonar o repositório

```bash
git clone https://github.com/rogerio-miguel/Slime_Studio.git
cd Slime_Studio
```

### 2. Instalar as dependências

```bash
cd backend && uv sync && cd ..
cd frontend && npm install && cd ..
```

### 3. Subir os serviços

```bash
# backend — API
cd backend && uv run python -m api

# backend — worker (processo separado)
cd backend && uv run python -m worker

# frontend
cd frontend && npm run dev
```

Ou, para subir os três de uma vez (e abrir o navegador já apontado para o dev server):

```bash
./scripts/dev.sh
```

Depois de subir, acesse `http://localhost:5173`. A API sobe em `http://127.0.0.1:8000`.

## Testes e lint

| Escopo   | Comando                        |
|----------|---------------------------------|
| backend  | `uv run pytest` · `uv run ruff check` |
| frontend | `npm run lint` · `npm run build` |

## Stack

**Backend:** FastAPI · `asyncio` · SQLAlchemy · SQLite (WAL) · Alembic · `uv` ·
BeautifulSoup4 · cloudscraper/DrissionPage (bypass anti-bot) · `yt-dlp`

**Frontend:** React 19 · Vite · Tailwind CSS 4 · React Router · `hls.js` ·
`anime4k-webgpu` · lucide-react

---

<div align="center">
  <sub>Projeto pessoal — sem afiliação com os sites de origem do conteúdo.</sub>
</div>

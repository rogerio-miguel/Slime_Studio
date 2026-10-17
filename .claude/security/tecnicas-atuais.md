# Base de técnicas de segurança atuais — Slime Studio

- **Consulta:** 2026-09-30 (válida até ~2026-12-29; depois `/security refresh`).
- **Stack consultada:** Python 3.12, FastAPI 0.141.1, Starlette 1.6.0, Pydantic 2.13.4, Uvicorn 0.52.3, SQLAlchemy 2.0.52 + SQLite (aiosqlite 0.22.1), yt-dlp 2026.8.19, requests 2.34.2, cloudscraper 1.2.71, DrissionPage 4.1.1.4, React 19, react-router-dom 6.30, Vite 6, hls.js 1.5.
- **Método:** só documentação pública (WebSearch/WebFetch por subagente). O fetch resume com modelo pequeno: as citações são paráfrases, confira a fonte antes de citar. "(inferência)" = dedução do pesquisador, não afirmação da fonte.
- **Colunas:** técnica | como adotar | esforço | fonte | confiança.

## 1. API HTTP (FastAPI/Starlette/Uvicorn)
| # | Técnica | Como adotar | Esf. | Fonte | Conf. |
|---|---|---|---|---|---|
| 1.1 | Allowlist de `Host` (DNS rebinding) | `TrustedHostMiddleware(allowed_hosts=["localhost","127.0.0.1","[::1]"])`. Starlette ≥1.0.1 valida `Host` (CVE-2026-48710). Em checagens de segurança use `request.scope["path"]`. | baixo | starlette.dev/middleware ; x41-dsec.de/lab/advisories/x41-2026-002-starlette/ | alta |
| 1.2 | Anti-CSRF em rotas de escrita sem auth | Middleware: rejeitar `Sec-Fetch-Site: cross-site`; exigir `Origin` exato da allowlist (ex. `http://localhost:5173`); exigir `Content-Type: application/json`. `localhost:5173`→`:8000` é `same-site` (inferência), então o `Origin` exato é o discriminante. | baixo | cheatsheetseries.owasp.org (CSRF Prevention) ; developer.mozilla.org (CORS, Sec-Fetch-Site) | alta |
| 1.3 | CORS mínimo | `allow_origins` exatas, métodos/headers explícitos, `allow_credentials=False`, nunca `*` com credenciais. | baixo | fastapi.tiangolo.com/tutorial/cors ; starlette.dev/middleware | alta |
| 1.4 | Bind e proxy | Uvicorn em `127.0.0.1`, nunca `0.0.0.0`; `--forwarded-allow-ips` no padrão. Chrome ≥142 (Local Network Access) é camada extra só para Chromium. | baixo | uvicorn.dev/settings ; developer.chrome.com/blog/local-network-access | alta (LNA: média) |
| 1.5 | Erros opacos e cabeçalhos | Sobrescrever `RequestValidationError` sem `exc.body`; handler de `Exception` → 500 genérico + log interno; `--no-server-header`; `X-Content-Type-Options: nosniff`, `Referrer-Policy`, `Cross-Origin-Resource-Policy: same-site`, CSP `frame-ancestors 'none'`. | baixo | fastapi.tiangolo.com/tutorial/handling-errors ; cheatsheetseries.owasp.org (HTTP Headers) | alta |
| 1.6 | Limites de recurso | Rate limit (token bucket) nas rotas caras (resolução de fonte, criação); timeouts em todo I/O externo; `--limit-concurrency`; Pydantic com `max_length`/`extra="forbid"`; evitar `Form`/multipart (Starlette <1.3.1 ignorava limites, CVE-2026-54283). | médio | github.com/advisories/GHSA-82w8-qh3p-5jfq ; OWASP API4:2023 | média |
| — | Se auth entrar | Token em header `Authorization`, escopo separado para `/api/admin/*`; CSRF só se houver cookie. | — | — | — |

## 2. Banco (SQLAlchemy 2.0 + SQLite)
| # | Técnica | Como adotar | Esf. | Fonte | Conf. |
|---|---|---|---|---|---|
| 2.1 | Só parâmetros vinculados | ORM/Core; `text()` só com `:param`; nunca f-string em `text()`/`literal_column()`/`order_by`; ordenação dinâmica via mapa allowlist; `ruff S608`. | baixo | docs.sqlalchemy.org/en/20/core/sqlelement.html ; docs.python.org/3.12/library/sqlite3.html | alta |
| 2.2 | PRAGMAs por conexão | `@event.listens_for(engine.sync_engine,"connect")`: `foreign_keys=ON; trusted_schema=OFF; cell_size_check=ON; busy_timeout=5000; synchronous=NORMAL`. | baixo | sqlite.org/pragma.html ; docs.sqlalchemy.org/en/20/dialects/sqlite.html | alta |
| 2.3 | Modo defensivo | `setconfig(SQLITE_DBCONFIG_DEFENSIVE, True)` (Py 3.12); compatibilidade com aiosqlite não confirmada. Evita corrupção, não é anti-SQLi. | médio | sqlite.org/security.html | alta (compat.: não confirmada) |
| 2.4 | Permissões do arquivo | `umask(0o077)` na API e no worker; `.db`/`-wal`/`-shm` só do dono (o `chmod 600` é recomendação do pesquisador, não da doc). | baixo | sqlite.org/security.html | alta/média |
| 2.5 | Logs sem parâmetros | `create_engine(..., echo=False, hide_parameters=True)`; sanitizar CR/LF de dado externo em logs. | baixo | docs.sqlalchemy.org/en/20/core/engines.html ; OWASP Logging | alta |
| 2.6 | Limitar o que se persiste | Pydantic na fronteira: `max_length`, `HttpUrl`, NFKC antes do `INSERT` (vale p/ `capa_path`, que guarda URL de provedor). | baixo | OWASP Input Validation ; pydantic.dev (networks) | alta |

## 3. Frontend (React 19 + Vite 6 + hls.js)
| # | Técnica | Como adotar | Esf. | Fonte | Conf. |
|---|---|---|---|---|---|
| 3.1 | Sem `dangerouslySetInnerHTML` com dado de provedor | Renderizar como texto; se precisar de HTML, limpar no backend ou DOMPurify com allowlist; ESLint `react/no-danger` (regra não verificada na doc). | baixo | react.dev ; OWASP XSS Prevention | alta |
| 3.2 | Allowlist de esquema em URLs | `urlSegura(u)`: `new URL(u)` e só `http:`/`https:` em todo `href`/`src`/`poster` vindo de API; repetir no backend (`HttpUrl` não faz SSRF). | baixo | OWASP XSS Prevention ; pydantic.dev | alta |
| 3.3 | CSP no build de produção | Começar em `Report-Only`: `default-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; connect-src 'self'; media-src 'self' blob:; worker-src 'self' blob:`; `img-src` só com CDNs dos provedores. `blob:` p/ hls.js/WebGPU é inferência: testar. | médio | developer.mozilla.org (CSP) | alta/média |
| 3.4 | Segredos fora do bundle | `VITE_*` vai pro bundle; TMDB só no backend; `gitleaks dir frontend/dist` após build. | baixo | vite.dev/guide/env-and-mode | alta |
| 3.5 | hls.js só com URL própria | Nunca `loadSource()` com URL de provedor/scraping; só HLS empacotado pelo backend (mesma origem); sem credenciais em `xhrSetup`/`fetchSetup`. | baixo | hlsjs.video-dev.org/api-docs | média |
| 3.6 | Dev server endurecido | Sem `server.allowedHosts: true` nem `server.cors: true`; `server.host` local; `fs.strict` ligado; Vite atualizado (advisories 2026 de `fs.deny` e WebSocket). | baixo | vite.dev/config/server-options ; github.com/vitejs/vite/security | alta |

## 4. URLs de terceiros, SSRF, ffmpeg, yt-dlp, subprocessos
| # | Técnica | Como adotar | Esf. | Fonte | Conf. |
|---|---|---|---|---|---|
| 4.1 | Validador central de URL externa | `validar_url_externa()`: esquema http/https; host em allowlist por adapter (extractors: seus domínios; integrations: `graphql.anilist.co`, `kitsu.io`, `api.themoviedb.org` + CDNs de imagem); portas 80/443; também p/ navegação do DrissionPage. | médio | OWASP SSRF Prevention ; OWASP API7:2023 | alta |
| 4.2 | Bloqueio de IP não público com resolução fixada | Resolver host; exigir `ipaddress.ip_address(x).is_global` em todos os A/AAAA; desembrulhar `ipv4_mapped`; conectar no IP validado; revalidar a cada hop. Testar `::ffff:127.0.0.1` no 3.12 (correções documentadas como "3.13"). | alto | docs.python.org/3/library/ipaddress.html ; OWASP SSRF | alta/média |
| 4.3 | Redirecionamentos e `requests` | `allow_redirects=False` + laço manual (~5 hops) validando cada `Location`; `Session.trust_env=False`; timeout `(connect, read)` sempre; `stream=True` com teto de bytes; `ruff S113`, `S310`. | médio | OWASP SSRF ; openwall.com/lists/oss-security/2025/06/04/6 | alta/média |
| 4.4 | ffmpeg com manifesto hostil | Baixar manifesto em Python, validar cada URI de segmento (4.2), reescrever playlist com nomes locais; rodar `-protocol_whitelist file,crypto,data -format_whitelist hls,mpegts,mov,mp4,matroska -allowed_extensions ts,m4s,mp4,aac,key -nostdin` (lista de formatos é sugestão, ajustar); se remoto: `-protocol_whitelist http,https,tcp,tls,crypto`; saída com prefixo `./`. O ffmpeg não filtra IP. | médio-alto | ffmpeg.org/ffmpeg-protocols.html ; ffmpeg.org/ffmpeg-formats.html ; ffmpeg.org/security.html | alta (opções) / baixa (exploração: blogs) |
| 4.5 | yt-dlp endurecido | 2026.8.19 já inclui correções de 2026 (`--exec`, aria2c/manifesto RCE, `.desktop/.url/.webloc`, cookie/curl, `--write-link`; fixed ≥2026.7.4). Como lib: sem `enable_file_urls`, `allowed_extractors` restrito, sem `external_downloader`/postprocessor `exec`, `restrictfilenames`, `outtmpl`/`paths` fixos por você, `max_filesize`, `socket_timeout`, `noplaylist`. CLI: `--ignore-config --no-plugin-dirs`, `--` antes da URL. | baixo | github.com/yt-dlp/yt-dlp/security (GHSA-69qj, vx4q, c6mh, f7j3, 6v4j) | alta |
| 4.6 | Subprocesso sem injeção de argumento | Lista, `shell=False`; validar que a URL começa com `http(s)://` antes de passar; `--` quando suportado; `env=` mínimo (sem `TMDB_*`); `cwd` do job; `timeout` + `kill()`. Chromium: `--user-data-dir` dedicado, debug só em loopback, sem `--no-sandbox`. `ruff S602/S603/S607`. | baixo | docs.python.org/3/library/subprocess.html ; OWASP OS Command Injection ; developer.chrome.com/blog/remote-debugging-port | alta |

## 5. Caminhos e nomes de arquivo
| # | Técnica | Como adotar | Esf. | Fonte | Conf. |
|---|---|---|---|---|---|
| 5.1 | Nome no disco vem do servidor | `media/{anime_id}/{ep_id}/...` por ID/UUID; título só no banco. | baixo | OWASP Input Validation | alta |
| 5.2 | Sanitizador allowlist (se nome legível for inevitável) | NFKC; só `[A-Za-z0-9._-]`; sem ponto/espaço no fim, sem ponto no início; truncar (255 bytes típico); nomes reservados Windows só se volume NTFS/exFAT (`PureWindowsPath(n).is_reserved()` no 3.12). | baixo | docs.python.org/3/library/pathlib.html ; OWASP Input Validation | alta |
| 5.3 | Contenção com `resolve()` + `is_relative_to` | `p=(base/rel).resolve(); if not p.is_relative_to(base.resolve()): raise`; `is_relative_to` é lexical, resolver antes; TOCTOU permanece. | baixo | docs.python.org/3/library/pathlib.html | alta |
| 5.4 | Sem seguir symlinks | `StaticFiles(follow_symlink=False)` (padrão); não criar symlinks no pipeline; cuidado com `concat`/`subfile` do ffmpeg. | baixo | starlette.dev/staticfiles | alta |
| 5.5 | Allowlist de extensão e limpeza pós-job | Após cada job, apagar o que não estiver em {`.mp4`,`.mkv`,`.ts`,`.m4s`,`.m3u8`,`.vtt`,`.jpg`,...}; sem bit de execução. | baixo | GHSA-c6mh-fpjc-4pr3 (yt-dlp) | alta |
| 5.6 | Servir mídia por ID | Rota recebe ID, consulta o banco, monta caminho fixo; nunca path do cliente; Starlette atualizado (advisories em `FileResponse`/`StaticFiles`). | baixo | github.com/Kludex/starlette/security | alta |

## 6. Dependências e cadeia de suprimentos
| # | Técnica | Como adotar | Esf. | Fonte | Conf. |
|---|---|---|---|---|---|
| 6.1 | Auditoria Python | `uv audit` (preview, OSV) ou `pip-audit`; `[tool.uv.audit] ignore-until-fixed`; rodar antes de cada merge. | baixo | astral.sh/blog/uv-audit ; docs.astral.sh/uv/reference/settings | alta |
| 6.2 | Malware check e travas | `UV_MALWARE_CHECK=1`/`malware-check=true`; `uv sync --locked`; `exclude-newer="7 days"` com `exclude-newer-package` liberando `yt-dlp`. | baixo | astral.sh/blog/uv-audit | alta |
| 6.3 | Política para yt-dlp | Nunca <`2026.7.4`; logar `yt_dlp.version.__version__` no start do worker e avisar se velho (ideia do pesquisador); acompanhar advisories. | baixo | github.com/yt-dlp/yt-dlp/security | alta |
| 6.4 | Higiene do npm | `npm ci`; `npm audit --audit-level=high` e `npm audit signatures`; `.npmrc`: `min-release-age=3`, `ignore-scripts=true` (testar), `allow-git=none`. `min-release-age` exige npm 11.10+ (fonte secundária). | baixo | docs.npmjs.com/cli/v11 | alta/média |
| 6.5 | Pacotes com pouca manutenção | `cloudscraper` 1.2.71 (abr/2023, sem CVE conhecido) e `DrissionPage` 4.1.1.4 (sem SECURITY.md; licença pessoal/não comercial): isolar no worker, perfil Chromium dedicado, hashes no `uv.lock`, ler changelog a cada update. | médio | pypi.org ; security.snyk.io/package/pip/cloudscraper | média |
| 6.6 | Análise estática | `ruff check --select S` (S113, S310, S501, S602, S603, S607, S608, S110) com ignores documentados. | baixo | docs.astral.sh/ruff/rules | alta |

## 7. Segredos
| # | Técnica | Como adotar | Esf. | Fonte | Conf. |
|---|---|---|---|---|---|
| 7.1 | `.env` fora do git e carga explícita | `.gitignore` com `.env`, `.env.*` (exceto `.env.example`), `*.local`; `load_dotenv(dotenv_path=<caminho fixo>)` (o padrão sobe diretórios); `chmod 600 .env`. | baixo | github.com/theskumar/python-dotenv ; vite.dev/guide/env-and-mode | alta |
| 7.2 | Scanner de segredos | `gitleaks` pre-commit; `gitleaks git` uma vez no histórico; `gitleaks dir frontend/dist` após build; baseline p/ legado. | baixo | github.com/gitleaks/gitleaks | alta |
| 7.3 | Não logar chaves | Preferir `Authorization: Bearer` a `?api_key=` (TMDB não consultado, baixa confiança); filtro de logging que mascara valor; sanitizar CR/LF de títulos nos logs. | médio | OWASP Logging ; OWASP Secrets Management | alta/baixa |
| 7.4 | Não herdar segredos em subprocessos | `env={...}` mínimo em `subprocess` (o padrão herda tudo). | baixo | docs.python.org/3/library/subprocess.html | alta |
| 7.5 | Resposta a vazamento | Revogar → rotacionar → remover do histórico → checar logs (ordem OWASP); TMDB: nova chave e revogar a antiga. | baixo | OWASP Secrets Management | alta |

## Divergências e lacunas
- `TrustedHostMiddleware` e IPv6: issues antigas dizem que não casava `[::1]:porta`; a doc atual usa colchetes. Testar `Host: [::1]:8000`.
- `min-release-age` do npm: doc diz "npm 7+", blogs dizem 11.10.0 (baixa confiança). Confirmar com `npm --version`.
- `ipaddress` no Python 3.12: correções de `is_private`/`is_global` documentadas como "3.13"; retroporte não confirmado.
- Versões corrigidas ausentes: advisories do Vite (2026) e do Starlette (mai–jun/2026: host/UNC/HTTPEndpoint). Presume-se que Starlette 1.6.0 cobre; verificar com `uv audit`/`npm audit`.
- `Sec-Fetch-Site` entre `localhost:5173` e `:8000` ser `same-site` é inferência.
- Local Network Access: só Chromium confirmado.
- ffmpeg vs manifesto hostil: docs não descrevem filtro de IP nem recusa de `file:` em playlist remoto; a recomendação vem de raciocínio + blogs.
- hls.js: busca rasa, sem advisory encontrado; CSP necessária p/ hls.js/WebGPU não confirmada.
- `DBCONFIG_DEFENSIVE` via aiosqlite: não confirmado.
- Não consultados: OWASP ASVS/Top 10, NIST, CISA, Dependabot/secret scanning do GitHub, docs do TMDB, regra `react/no-danger`.

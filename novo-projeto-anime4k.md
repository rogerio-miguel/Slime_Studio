# Documento de Especificação de Projeto
## Orquestrador Automatizado de Streaming de Anime em 4K

> Evolução do [Slime_Shell_Web](https://github.com/rogerio-miguel/Slime_Shell_Web): sai do modelo "automatizar o navegador e tocar localmente via MPV" para um modelo "baixar, processar em lote com IA e re-hospedar via HLS para web". Essa mudança de modelo é o ponto mais importante do documento — está detalhada na seção 2.
>
> **Repositório**: novo, separado do Slime Shell Web (justificativa: seção 2 já mostra que a postura legal e a arquitetura mudam de categoria — separar deixa isso explícito). **Nome definitivo**: `Slime Studio` (repositório `Slime_Studio`, decidido em 2026-08-10 — este documento manteve o nome de trabalho `novo-projeto-anime4k` durante a redação e por isso o arquivo continua com esse nome; o conteúdo abaixo vale para o Slime Studio).

---

## 1. Visão Geral

Sistema de ponta a ponta, de **uso pessoal e single-user**, que recebe links de fontes externas, contorna proteções anti-bot, extrai a mídia original, faz upscaling para 4K via IA (Real-ESRGAN, otimizado para anime), empacota em HLS e distribui para um frontend React com player web. O objetivo de experiência é assistir anime em alta qualidade direto no navegador com adaptação de qualidade à rede/dispositivo — como plataformas de streaming de alta resolução fazem — sem sobrecarregar o hardware local (ver 3C/3D para os limites de concorrência e o ladder de bitrate que sustentam isso). Uso mobile foi considerado e fica deliberadamente fora de escopo por ora (a web app deve funcionar razoavelmente em navegador mobile via HLS, mas nada além disso é planejado nesta fase).

Reaproveita do Slime Shell Web: o padrão de scrapers por site (Strategy Pattern), o motor de bypass híbrido (DrissionPage + Cloudscraper), a stack FastAPI + React/Vite/Tailwind, e a integração com AniList/Kitsu para metadados e capas.

Não reaproveita: o modelo de reprodução em tempo real via MPV+shader (aqui o upscaling é offline, em lote, com Real-ESRGAN rodando sobre frames extraídos) e o storage em JSON puro (aqui precisa de um banco relacional de verdade — ver seção 4).

---

## 2. O que muda em relação ao Slime Shell Web (e por que isso importa)

| Aspecto | Slime Shell Web | Este projeto |
|---|---|---|
| Upscaling | Shader Anime4K em tempo real, durante a reprodução, via MPV+Vulkan | Real-ESRGAN em lote, offline, sobre frames extraídos |
| Conteúdo armazenado | Nenhum — é um navegador automatizado que toca e descarta | Vídeo 4K processado é persistido em disco e re-servido via HLS |
| Storage | Arquivos JSON locais | Banco relacional (SQLite) + arquivos de mídia em disco |
| Distribuição | Local, um usuário, um processo MPV | Web, HLS, potencialmente multiusuário |
| Autenticação | Nenhuma | Necessária pelo menos para o painel admin (ver seção 8) |
| Postura legal | Explicitamente descrito como ferramenta educacional que "não armazena conteúdo protegido" | Passa a armazenar e redistribuir cópias processadas — risco de direitos autorais muda de categoria (ver seção 8.3) |

Essa tabela existe porque é fácil copiar a arquitetura antiga sem perceber que a mudança de "tocar" para "armazenar e redistribuir" não é um detalhe de implementação — é uma mudança de escopo que afeta banco de dados, autenticação e exposição legal do projeto. Recomendo tratar isso como decisão consciente (ver 8.3), não como consequência acidental do pipeline de vídeo.

---

## 2.1 Stack Tecnológica e Decisões de Arquitetura

Decisões fechadas em discussão de arquitetura, com o porquê resumido:

| Camada | Escolha | Por quê (resumo) |
|---|---|---|
| Linguagem backend/worker | Python (`asyncio`) | Não há hot-path de CPU em Python neste design — `ffmpeg`/`realesrgan-ncnn-vulkan` fazem o trabalho pesado como subprocessos; `DrissionPage` não tem equivalente direto em outra linguagem, trocar de stack significaria re-resolver o bypass anti-bot do zero |
| Extrator/bypass | DrissionPage + Cloudscraper (mantidos do Slime Shell Web) | Já funcionam hoje; fallback documentado, não substituição imediata: Playwright + stealth (`patchright`) se algum site evoluir a proteção e DrissionPage parar de furar |
| Fila/worker | `asyncio` nativo + tabela `Job` no SQLite — **sem Celery/Redis** | Concorrência é estritamente 1 por decisão de hardware (seção 6); fila distribuída não traz benefício aqui, só mais um serviço pra manter rodando nos dois túneis |
| Topologia de processos | **Dois processos**: API (FastAPI, sempre no ar, serve player/painel/WebSocket) e worker (roda o pipeline, pode levar horas num único job) | Comunicam só via a tabela `Job` (polling); um crash ou restart de um não derruba o outro — reiniciar a API pra testar algo não mata um upscaling de 3h em andamento |
| Upscaling | `realesrgan-ncnn-vulkan` (modelo `realesr-animevideov3`) | Vulkan é agnóstico de fabricante — evita depender de ROCm, que tem suporte capenga em GPUs Polaris como a RX 580. Comparar com `realcugan-ncnn-vulkan` (tunado pra anime) no PoC da Fase 0 — decisão empírica, não a priori |
| Banco de dados | SQLite (modo WAL) | Padrão de acesso é exatamente 1 writer (worker) + N readers (API); Postgres só valeria a pena com multiusuário real |
| Frontend | React + Vite + Tailwind (mantido do Slime Shell Web) | Reuso direto de componentes já prontos (`AnimeCard`, etc.) |
| Player | `hls.js` (obrigatório — só Safari toca HLS nativo) + controles nativos do `<video>` | Prioriza simplicidade agora; evoluir pra um player customizado (ex. Vidstack) depois é troca de camada de UI, não mudança de arquitetura |
| Empacotamento HLS | `ffmpeg` nativo | Shaka Packager só compensaria com DRM — irrelevante para uso pessoal |
| Containers | Não, por enquanto — worker de GPU roda direto na máquina | Passthrough de Vulkan em container é fricção real, pior ainda sendo multiplataforma (rogerio-win11/rogerio-zorin); reconsiderar só para API/frontend depois, se fizer sentido |
| Gerenciador de pacotes Python | `uv` | Resolução de dependências rápida, padrão de fato emergente no ecossistema Python |

---

## 3. Arquitetura do Sistema e Fluxo de Trabalho

### A. Módulo Extrator e Bypass — projetado para não exigir supervisão
Hoje, no Slime Shell Web, o bypass roda no caminho síncrono: você precisa saber na hora se funcionou. A ideia aqui é inverter isso — o extrator roda em segundo plano, raramente precisa de você e, quando precisa, avisa sem travar o resto da fila. Isso não se resolve "resolvendo captcha melhor" — se resolve reduzindo quantas vezes o caminho frágil (browser completo) precisa rodar, e tornando as falhas assíncronas em vez de bloqueantes:

1. **Cache de sessão/cookies por site** — depois que o DrissionPage resolve o desafio do Cloudflare uma vez, os cookies resultantes (`cf_clearance` + sessão) são salvos por domínio com uma expiração estimada. As próximas extrações do mesmo site tentam primeiro um cliente HTTP leve (Cloudscraper/requests) reaproveitando esses cookies, e só sobem o navegador completo — mais lento e mais sujeito a travar — se a sessão cacheada for rejeitada. Isso reduz bastante a frequência com que o caminho frágil precisa rodar: a maioria das extrações vira uma requisição HTTP simples.
2. **Retry com backoff + circuit breaker por site** — falha não gera retry imediato (parece mais bot ainda); usa backoff crescente (ex: 30s → 2min → 10min, até N tentativas). Se um site falhar M vezes seguidas, ele é marcado "degradado" e entra em cooldown (ex: 1h) sem novas tentativas automáticas — evita martelar um site que já está bloqueando ativamente, o que só pioraria a detecção.
3. **Fila não-bloqueante** — um job que falha na extração não trava os outros. Ele vai para `aguardando_intervencao` (ou `falhou_extracao` enquanto ainda há backoff pendente) e o worker segue para o próximo item. Uma fila de "5 animes pra processar de madrugada" nunca fica presa atrás de 1 que deu problema.
4. **Notificação na página, não vigilância ativa** — via o WebSocket já previsto (`/ws/admin`, seção 5), o painel mostra um toast em tempo real se a aba estiver aberta, e um indicador persistente ("2 jobs precisam de atenção") sempre que o painel for aberto, mesmo que o problema tenha ocorrido horas antes com a aba fechada. Não precisa estar olhando no momento em que acontece — só conferir quando for conveniente.

Isso resolve diretamente a questão de "não querer saber se conseguiu ou se precisa de mim": a maioria das extrações usa sessão cacheada e nem chega perto de precisar de intervenção; quando algo trava de verdade (captcha que a automação não resolve), aparece numa lista ao abrir o painel, resolve-se manualmente só aquele item, e o resto da fila continua rodando.

Deliberadamente fora de escopo: serviços de resolução automática de captcha (2captcha, anti-captcha etc.) — não são necessários aqui, porque o fluxo acima já trata o caso raro de captcha como notificação assíncrona, não como algo a vencer algoritmicamente.

- Entrada: você insere URL do site + nome do anime em área administrativa autenticada.
- Extração: localiza a página do episódio, intercepta tráfego de rede, captura link direto do vídeo original (idealmente a maior resolução disponível na fonte, tipicamente 1080p).
- Adapters por site seguem Strategy Pattern (`api/extractors/base.py` + uma classe por site, ex. `animefire.py`, `animesdrive.py`), portados/adaptados do projeto original — mas aqui o extrator **baixa** o arquivo em vez de servir a URL direta para o player, e cada adapter ganha a camada de cache/retry/circuit breaker acima em vez de reimplementar isso por site.

### B. Fila de Processamento Assíncrono (Worker Nativo)
- Worker roda como **processo separado** da API (decisão em 2.1), em background com `asyncio`, concorrência estrita de **um vídeo por vez** (respeita 16GB RAM / 8GB VRAM).
- Estado de cada job é persistido em banco relacional (não em memória) — ver seção 5 — para que um crash do processo não perca o progresso de um job que já rodou horas.
- Estados: `Na fila → Baixando → Extraindo frames → Upscaling → Remontando → Empacotando HLS → Pronto` (mais `falhou_extracao`, `aguardando_intervencao` e `Cancelado` — ver seção 3A: uma falha de extração não bloqueia os demais jobs da fila).

### C. Pipeline de Tratamento de Vídeo (o motor 4K)

**Atenção ao disco:** extrair todos os frames de um episódio inteiro antes de começar o upscaling é o erro mais comum aqui e pode estourar o disco. Um episódio de ~24 min a ~24fps tem ~34.500 frames; em PNG lossless a 1080p isso facilmente passa de dezenas de GB só na entrada, e os frames de **saída** em 4x (7680×4320) são de 4 a 10x maiores cada — o total pode chegar a centenas de GB por episódio se todo o episódio for mantido em disco simultaneamente. Duas mitigações, recomendo as duas:

1. **Processar em chunks** (ex. blocos de 500–1000 frames): extrai um chunk → upscala o chunk → escreve no vídeo de saída (ou guarda os frames upscalados do chunk) → apaga os frames (originais e upscalados) daquele chunk → passa para o próximo. Mantém o pico de disco limitado a poucos GB por vez, e permite retomar do último chunk concluído se o worker cair no meio (o estado do chunk também fica no banco).
2. **Formato intermediário mais leve**: usar `-f webp` ou `-f jpg` no `realesrgan-ncnn-vulkan` para os frames de saída dos estágios intermediários (não para o entregável final, que continua sendo H.264/HEVC depois do remux). PNG lossless não traz benefício de qualidade perceptível numa etapa que será recodificada em seguida, e custa disco caro.

**Resolução final alvo: 4K real (3840×2160), não 8K.** O modelo `realesr-animevideov3` usado aqui escala 4x — partindo de 1080p (1920×1080), isso dá 7680×4320, que é **8K**, não 4K: custaria ~4x mais espaço e tempo de GPU sem necessidade, e nenhum dispositivo comum decodifica 8K sem esforço. O passo de remontagem (abaixo) faz o downscale de volta pra 3840×2160 — na prática, "upscale 4x e depois downscale pra 4K" tende a dar resultado mais nítido que upscalar direto 2x (funciona como supersampling), então não é desperdício, é técnica. Comparar essa abordagem contra 2x direto (se o binário suportar `-s 2`) fica no PoC da Fase 0, junto da comparação com `realcugan-ncnn-vulkan`.

Etapas via linha de comando:
1. **Separação**: `ffmpeg` extrai o áudio (`-vn -c:a copy`) e separa os frames do chunk atual em PNG/WebP.
2. **Upscaling (Vulkan)**: `realesrgan-ncnn-vulkan` com o modelo `realesr-animevideov3` (otimizado para vídeo de anime, mais rápido que `realesrgan-x4plus-anime` para essa finalidade), escala 4x. Usar `-t <tile-size>` para tiling automático e evitar estouro de VRAM nos 8GB da RX 580; usar `-j load:proc:save` para calibrar throughput sem saturar RAM.
3. **Remontagem**: `ffmpeg` reconstrói o vídeo a partir dos frames upscalados, aplicando o downscale pra 3840×2160 nesse passo (`-vf scale=3840:2160`), no framerate original (extraído via `ffprobe`, não assumido) e remuxa com o áudio original.

**Validar no PoC (item já previsto na seção 10)**: fps real de upscaling na RX 580 com `realesr-animevideov3`. GPUs Polaris como a RX 580 não têm aceleração dedicada para esse tipo de rede neural — é esperado throughput baixo (ordem de poucos frames/segundo), o que pode significar **horas** de processamento por episódio de 24 min. Isso não invalida o projeto, mas deve moldar expectativas de UX (fila overnight, ETA visível, não "upscaling instantâneo") e a decisão de layout do pipeline (chunking citado acima também ajuda a dar progresso incremental visível em vez de barra travada por horas).

### D. Transcodificação para Web (HLS)
- Vídeo 4K final é segmentado em `.ts` de 5–10s + manifesto `.m3u8` (`ffmpeg -hls_time 8 -hls_playlist_type vod`).
- Recomendo **HLS multi-bitrate** (ladder com 4K + 1080p + 720p via `-var_stream_map`) em vez de servir só a renditions 4K nativa: nem toda rede/dispositivo aguenta 4K direto, e sem ladder o player não tem fallback — a experiência quebra em qualquer rede mais lenta.
- Arquivo original 1080p e frames temporários (de cada chunk, ou os que ainda restarem) são apagados após a etapa correspondente concluir (Garbage Collection), não só no final — reforça o ponto de disco da seção C.

### E. Frontend e Armazenamento
- Banco relacional atualizado com status "Pronto" e caminho do HLS.
- Arquivos físicos (`.ts`/`.m3u8`) servidos localmente no MVP; Object Storage (S3-compatível/MinIO) fica como evolução futura (seção 10, Fase 6) — não é bloqueante para a primeira versão funcional.
- Frontend consome o HLS via `hls.js` (necessário para a maioria dos navegadores, que não suportam HLS nativamente — só Safari suporta) com controles nativos do `<video>` por enquanto (decisão em 2.1 — dá pra evoluir a UI do player depois sem mexer na arquitetura), reaproveitando os componentes visuais (`AnimeCard`, etc.) do Slime Shell Web.

### F. Metadados e Matching (AniList/Kitsu) — como o sistema sabe "isso é o episódio 5 de Slime"
Diferente do extrator (seção 3A), isso não precisa da camada de resiliência assíncrona — é uma chamada HTTP normal e rápida a uma API pública, feita de forma síncrona no próprio fluxo de cadastro (você já está no painel digitando; esperar 1s por uma resposta não é problema).

**Nível anime — busca-e-confirma uma vez, não fuzzy-match automático.** Ao cadastrar um anime novo, o sistema busca no AniList (GraphQL, `Media(search: ...)`) pelo nome digitado e mostra uma lista curta de candidatos (capa + título + ano) pra você confirmar qual é o certo. Kitsu entra como fallback só se o AniList não achar nada (cobertura de títulos obscuros/recentes varia entre os dois). Um match errado aqui contamina sinopse, capa e numeração de *todos* os episódios futuros daquele anime — por isso vale o clique extra de confirmar uma vez, em vez de confiar num score de similaridade automático. Depois de confirmado, o `anilist_id` fica salvo em `Anime` e os próximos episódios do mesmo anime reaproveitam sem perguntar de novo. Metadados são **cacheados** na tabela `Anime`, não buscados ao vivo a cada carregamento — se o AniList cair, você continua assistindo seu próprio acervo sem depender de API externa no caminho crítico (mesma lógica de "media server pessoal" da seção 8.3).

**O problema real: numeração absoluta vs. por temporada.** É o que mais quebra esse tipo de sistema na prática — inclusive Sonarr/Plex/Jellyfin têm exatamente essa dor com anime. O site de origem às vezes lista episódios numa sequência contínua (ex: "episódio 48"), enquanto o AniList trata cada temporada como uma obra separada (ex: Slime Temporada 2 = episódios 1 a 24). Resolver isso com conversão automática genérica é complexo e frágil — a solução mais simples, e que já se encaixa no fluxo manual deste projeto, é: **cada temporada é um `Anime` separado no banco** (mesma granularidade que o AniList já usa, sem inventar uma camada de "franquia" por cima), e o número do episódio **é confirmado por você ao enfileirar o job** — o sistema pré-preenche com o número que o site mostrou, como sugestão, não como verdade absoluta. Você já sabe que está enfileirando "Slime T2 Episódio 3"; o sistema não precisa adivinhar isso a partir de um número absoluto ambíguo.

**Sanity check, não bloqueio.** Se o número informado exceder a contagem oficial de episódios da temporada no AniList, o sistema avisa mas não impede o job — pode ser contagem desatualizada, filme/OVA numerado à parte, etc. Vira mais um item do padrão de notificação da seção 3A, não uma trava rígida.

**Especiais/OVAs/filmes**: campo `tipo` no episódio (`regular / ova / especial / filme`) em vez de forçar esse conteúdo na sequência numérica principal — evita que um "episódio 0" ou "25.5" bagunce a ordenação.

**Dublado vs. legendado**: se as duas versões do mesmo episódio forem processadas, um campo `versao` evita que uma sobrescreva o caminho HLS da outra sem querer.

**Capa por episódio**: AniList raramente tem thumbnail por episódio individual (só por anime/temporada). Em vez de depender de um metadado externo que provavelmente não existe, reaproveitar a técnica do Slime Shell Web: gerar a capa via `ffmpeg` a partir de um frame do próprio vídeo já processado (ex: captura em ~20% da duração).

### G. Gestão de Armazenamento de Longo Prazo (o catálogo, não os temporários)
Diferente do GC de arquivos temporários (seção 3D, já resolvido durante o processamento), isso é sobre o crescimento do catálogo HLS **já pronto** ao longo do tempo. Com menos de 500GB livres disponíveis (confirmado) e um episódio de 24min em 4K real (seção 3C) ocupando ~3–6GB já com o ladder multi-bitrate, o espaço prático dá pra poucas temporadas completas antes de precisar de uma política ativa — isso não é "problema pra depois", é praticamente dia 1.

- Campo `assistido_em` no `Episodio` (seção 4) — timestamp da última vez que você assistiu, base pra sugestão de retenção.
- Painel admin mostra uso de disco atual (seção 7) e, quando o espaço livre cruzar um limite configurável, dispara uma notificação (reaproveitando o padrão assíncrono da seção 3A/F) sugerindo candidatos a limpar, priorizando episódios assistidos há mais tempo.
- **Nunca deletar automaticamente sem confirmação** — é sua coleção pessoal; mesma filosofia de "avisa, não decide por você" já estabelecida pro extrator (seção 3A).
- Opção de manter só o 1080p original (bem mais leve) descartando a versão 4K de algo já assistido, em vez de apagar tudo — reprocessar depois custa tempo de GPU, mas não perde a obra.

---

## 4. Modelo de Dados

Banco relacional (SQLite via SQLAlchemy — arquivo único, zero-config, adequado para um nó local; migrar para Postgres só se houver necessidade real de acesso concorrente multiusuário mais adiante).

**Anime** (cada linha = uma temporada, mesma granularidade do AniList — ver seção 3F)
| campo | tipo | nota |
|---|---|---|
| id | PK | |
| titulo, slug | str | |
| anilist_id | int, nullable | confirmado uma vez no cadastro (busca-e-confirma, 3F) |
| kitsu_id | int, nullable | só preenchido se usado como fallback do AniList |
| capa_url, sinopse | str | cacheados a partir do AniList/Kitsu, não buscados ao vivo |
| total_episodios_anilist | int, nullable | usado no sanity check da seção 3F |
| site_origem | str | qual scraper foi usado |
| criado_em | datetime | |

**Episodio**
| campo | tipo | nota |
|---|---|---|
| id | PK | |
| anime_id | FK | |
| numero, titulo | | número confirmado por você ao enfileirar (3F), não o bruto do site |
| numero_fonte | int, nullable | número original como o site mostrou, mantido pra auditoria/debug |
| tipo | enum | `regular / ova / especial / filme` (3F) |
| versao | enum, nullable | `legendado / dublado` (3F) |
| status | enum | `pendente / pronto / falhou` |
| hls_path | str | caminho do `.m3u8` final |
| duracao_s | int | |
| assistido_em | datetime, nullable | base pra sugestão de retenção (seção 3G) |

**Job**
| campo | tipo | nota |
|---|---|---|
| id | PK | |
| episodio_id | FK | |
| status | enum | ver estados da seção 3B |
| etapa_atual, progresso_pct | | para UI de fila |
| chunk_atual, total_chunks | int | permite retomada |
| erro_msg, tentativas | | para retry/observabilidade |
| iniciado_em, finalizado_em | datetime | |

A tabela `Job` é o que falta hoje no rascunho e é o que permite: (a) sobreviver a um crash do worker sem perder horas de GPU, (b) mostrar progresso real na UI em vez de um spinner, (c) implementar retry sem reprocessar do zero.

**SessaoBypass** (suporta o item 1 da seção 3A)
| campo | tipo | nota |
|---|---|---|
| site_dominio | PK | ex. `animefire.plus` |
| cookies_json | text | `cf_clearance` + demais cookies de sessão |
| user_agent | str | fixado junto com a sessão |
| criado_em, expira_estimado_em | datetime | expiração é estimativa — se a sessão for rejeitada antes disso, invalida na hora |

**EstadoSite** (suporta o circuit breaker do item 2 da seção 3A)
| campo | tipo | nota |
|---|---|---|
| site_dominio | PK | |
| status | enum | `ok / degradado` |
| falhas_consecutivas | int | |
| cooldown_ate | datetime | enquanto ativo, extrator pula o site sem tentar |

---

## 5. API (rascunho de endpoints)

```
GET    /api/admin/animes/buscar?q=...           busca candidatos no AniList (fallback Kitsu) — busca-e-confirma da seção 3F
POST   /api/admin/animes                        confirma um candidato e cria o Anime (grava anilist_id/kitsu_id)
POST   /api/admin/jobs                        cria job (url, anime_id, número do episódio, tipo, versão)
GET    /api/admin/jobs                         lista fila com status
GET    /api/admin/jobs/{id}                    detalhe/progresso de um job
DELETE /api/admin/jobs/{id}                     cancela job
GET    /api/admin/notificacoes                  jobs em aguardando_intervencao (para o indicador persistente da seção 3A)
WS     /ws/jobs/{id}                            progresso em tempo real de um job (evita polling)
WS     /ws/admin                                 eventos globais da fila (job concluído/precisa de atenção) — alimenta o toast da seção 3A

GET    /api/animes                             lista de animes prontos (uso pessoal — ver seção 8.2, fica atrás de autenticação)
GET    /api/animes/{id}/episodios/{n}/playlist.m3u8   serve o HLS
```

Todos os endpoints exigem autenticação (seção 8.1) — dado o escopo confirmado de uso pessoal (seção 8.3), não há endpoint público sem login.

---

## 6. Hardware e Ambiente de Desenvolvimento

- **Hardware alvo**: upscaling via API Vulkan na RX 580 (8GB VRAM); FFmpeg e gerenciamento de fila no Ryzen 7 7500x. Curvas de ventoinha e frequência de memória da GPU devem ser monitoradas sob 100% de uso sustentado por horas (não só picos curtos) — recomendo logar temperatura/uso via `radeontop`/`rocm-smi` durante o job, não só observar manualmente.
- **Onde o worker de GPU pode rodar**: o upscaling via Vulkan precisa de acesso direto à RX 580. Se o desenvolvimento/deploy acontecer via túnel remoto em `rogerio-win11` ou `rogerio-zorin`, confirmar explicitamente que o ambiente que efetivamente executa o `realesrgan-ncnn-vulkan` enxerga a GPU (nativo, ou com passthrough Vulkan configurado) — isso não é garantido automaticamente num ambiente acessado remotamente/containerizado. Trate como item a validar no PoC, não como premissa.
- **Ambiente**: código multiplataforma para permitir dev fluido nos dois túneis, mas a **execução do pipeline de upscaling** deve ficar amarrada à máquina com a GPU física — separar isso explicitamente evita subir o worker num ambiente sem Vulkan por engano.

---

## 7. Observabilidade e Testes

- Logging estruturado por etapa do pipeline (download, extração, upscaling, remux, HLS), incluindo tempo gasto por etapa — necessário para calibrar as estimativas de fps/tempo por episódio citadas na seção 3C.
- Progresso incremental exposto via WebSocket (`/ws/jobs/{id}`), não só polling — jobs de horas precisam de feedback melhor que "processando...".
- Testes:
  - Unitário: interface `base.py` do Strategy Pattern dos extratores (contrato comum entre scrapers).
  - Integração: pipeline completo com clipe de 5s (já previsto na seção 10, Fase 0) — cobre extração de frames → upscaling → remux → HLS de ponta a ponta antes de rodar em episódio real.
  - Smoke test por scraper: sites de anime mudam DOM/proteção com frequência; um teste periódico simples que verifica se cada extrator ainda consegue localizar o link do episódio evita descobrir a quebra só quando um job falha em produção.

---

## 8. Segurança e Aspectos Legais

### 8.1 Autenticação
O Slime Shell Web não tem autenticação porque nunca armazena nada. Este projeto passa a armazenar e servir vídeo processado, então pelo menos o painel admin (submissão de jobs, fila) precisa de autenticação — um gate simples (usuário/senha único, token/JWT) é suficiente para uso pessoal; não é necessário OAuth completo nesta fase.

### 8.2 Acesso ao acervo processado
**Confirmado**: uso pessoal, single-user. `/api/animes` e o player ficam atrás de autenticação, sem exposição pública — não é uma "plataforma", é a sua própria coleção processada, acessível só por você. Isso simplifica a seção 8.1: um único usuário/senha (ou token fixo) é suficiente, não é necessário sistema de contas.

### 8.3 Direitos autorais — mudança de postura em relação ao projeto original
O Slime Shell Web se descreve como ferramenta educacional que funciona como navegador automatizado **sem armazenar conteúdo protegido**. Este projeto armazena o vídeo processado em disco e o redistribui via HLS — isso é uma categoria de exposição diferente, não uma extensão natural do mesmo argumento. Com o escopo confirmado em 8.2 (uso pessoal, sem acesso externo), o risco fica equivalente ao de qualquer setup pessoal de media server (ex. Jellyfin/Plex com conteúdo próprio): documentar o propósito pessoal/educacional no README, como o projeto original já faz, e não expor a instância publicamente.

---

## 9. Riscos e Mitigações

| Risco | Mitigação |
|---|---|
| Estouro de disco por frames PNG de episódio inteiro | Pipeline em chunks + formato intermediário leve (seção 3C) |
| Estouro de VRAM (8GB) durante upscaling | Tiling automático (`-t`) do `realesrgan-ncnn-vulkan` |
| GPU trava/superaquece sob 100% por horas | Monitorar temp/uso continuamente, não só em picos; considerar limite de tempo contínuo com pausa |
| Worker cai no meio de um job de horas | Estado do job + chunk persistido em DB, pipeline resumível (seção 4/5) |
| Site-fonte muda DOM/anti-bot e quebra o scraper | Strategy Pattern isola por site; smoke test periódico por scraper (seção 7) |
| SQLite com escrita concorrente worker+API | Modo WAL; migrar para Postgres só se necessário |
| Exposição legal por armazenar/redistribuir conteúdo protegido | Ver 8.3 — decisão consciente de escopo, não acidente de arquitetura |
| Match errado de anime no AniList/Kitsu contamina sinopse/capa/numeração | Busca-e-confirma manual uma vez por anime, não fuzzy-match automático (seção 3F) |
| Numeração de episódio ambígua (absoluta vs. por temporada) | Cada temporada = `Anime` separado; número confirmado manualmente ao enfileirar, com sanity check contra a contagem do AniList (seção 3F) |
| Upscaling 4x sem downscale gera 8K por acidente (4x mais espaço/tempo que o necessário) | Downscale explícito pra 3840×2160 no passo de remontagem (seção 3C) |
| Disco (<500GB) enche com o catálogo 4K já pronto, não só temporários | Notificação de uso de disco + sugestão de retenção baseada em `assistido_em`, nunca deleção automática (seção 3G) |

---

## 10. Roadmap

- **Fase 0 — PoC**: validar upscaling em lote com clipe de 5s na RX 580; medir fps real, uso de VRAM e tempo por frame com `realesr-animevideov3` **e comparar com `realcugan-ncnn-vulkan`** (2.1); comparar 4x+downscale vs. 2x direto pra chegar em 4K real (3C); decidir tile size e formato intermediário (PNG vs WebP/JPG) com base em dados reais, não estimativa.
- **Fase 1 — Extrator resiliente**: portar/adaptar os scrapers do Slime Shell Web (Strategy Pattern) para baixar o arquivo em vez de servir URL direta ao player, já com cache de sessão/cookies, retry+backoff e circuit breaker por site (seção 3A) desde o início — é mais fácil nascer com isso do que remendar depois.
- **Fase 2 — Worker & Pipeline**: worker como processo separado da API (2.1), fila persistida em SQLite, pipeline em chunks (FFmpeg + Real-ESRGAN), GC automático por chunk.
- **Fase 3 — Empacotamento Web**: HLS multi-bitrate, endpoints REST + `WS /ws/admin` de notificação/progresso.
- **Fase 4 — Frontend**: painel admin (fila, tela de busca-e-confirma de anime no AniList/Kitsu — seção 3F, indicador persistente de "precisa de atenção", toast em tempo real) + player (`hls.js`), reaproveitando componentes visuais do projeto original.
- **Fase 5 — Hardening**: autenticação, monitoramento de hardware, smoke tests dos scrapers, logging estruturado.
- **Fase 6 — Futuro/opcional**: Object Storage/CDN, múltiplos workers se o hardware permitir, uso mobile dedicado (fora de escopo por ora — ver seção 1).

---

## 10.1 Estrutura de Repositório e Checklist de Pré-Implementação

**Repositório**: novo, separado do Slime Shell Web (ver nota no topo do documento). Estrutura de pastas proposta:

```
novo-projeto-anime4k/
├── backend/
│   ├── api/                    # FastAPI: rotas, WebSocket, auth
│   ├── worker/                 # processo separado (2.1) — entrypoint + pipeline
│   │   └── pipeline/           # separacao.py, upscaling.py, remontagem.py, hls.py, gc.py (3C/3D)
│   ├── extractors/             # Strategy Pattern (3A): base.py + animefire.py, animesdrive.py...
│   │                           #   + sessao_cache.py, circuit_breaker.py (resiliência, 3A)
│   ├── integrations/           # anilist.py, kitsu.py (3F)
│   ├── models/                 # SQLAlchemy: Anime, Episodio, Job, SessaoBypass, EstadoSite (seção 4)
│   ├── db/                     # engine, sessão, migrations (Alembic)
│   ├── core/config.py          # .env, paths de mídia, tile size etc.
│   └── pyproject.toml          # uv (2.1)
├── frontend/                   # React + Vite + Tailwind
│   └── src/{admin,player,components}/
├── media/                      # runtime, fora do git — raw/, frames/, hls/{anime_id}/{episodio_id}/
├── scripts/                    # start-dev.sh — equivalente ao `slimeWEB` original, sobe API+worker+Vite
└── .env.example
```

**Checklist bloqueante antes da Fase 0:**
- [ ] Repositório criado.
- [ ] `ffmpeg` e `realesrgan-ncnn-vulkan` instalados e testados **manualmente** na máquina com a RX 580 — um comando de cada, fora do projeto, só pra confirmar que o Vulkan enxerga a GPU antes de escrever código em volta disso.
- [ ] Confirmar que `animefire.py`/`animesdrive.py` (herdados do Slime Shell Web) ainda furam a proteção dos sites hoje — sites de anime mudam de domínio/proteção com frequência; não vale construir a resiliência da seção 3A em cima de um scraper que já pode estar quebrado.
- [ ] Alembic configurado pro schema inicial (as 5 tabelas da seção 4).
- [ ] `.env.example` com os placeholders necessários (token de acesso, paths de `media/`, tile size default).
- [ ] Decisão de autenticação: em vez de usuário/senha + JWT completo (over-engineering pra 1 usuário), um **token fixo único** gerado uma vez, guardado no `.env`, comparado num cookie/header — tela de "desbloquear", não de login. Evolui depois se algum dia virar multiusuário.

---

## 11. Próximos Passos Imediatos

1. Validar a prova de conceito do upscaling em lote com um clipe de 5 segundos — medir fps, VRAM e tempo real na RX 580 (dado concreto que hoje falta e que dimensiona todo o resto do plano).
2. Desenvolver a interface abstrata do extrator de links (Strategy Pattern), portando o motor de bypass do Slime Shell Web para o modelo de download, já com cache de sessão e circuit breaker por site (seção 3A) — não como camada adicionada depois.
3. Estruturar o loop assíncrono do Worker em Python com estado persistido em SQLite (não em memória) desde o início, para já nascer resumível.

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
| Distribuição | Local, um usuário, um processo MPV | Web, HLS, single-user (mesmo escopo de uso pessoal do original — ver seção 8.2) |
| Autenticação | Nenhuma | Necessária em toda a aplicação — painel admin e acervo/player (ver seção 8) |
| Postura legal | Explicitamente descrito como ferramenta educacional que "não armazena conteúdo protegido" | Passa a armazenar e redistribuir cópias processadas — risco de direitos autorais muda de categoria (ver seção 8.3) |

Essa tabela existe porque é fácil copiar a arquitetura antiga sem perceber que a mudança de "tocar" para "armazenar e redistribuir" não é um detalhe de implementação — é uma mudança de escopo que afeta banco de dados, autenticação e exposição legal do projeto. Recomendo tratar isso como decisão consciente (ver 8.3), não como consequência acidental do pipeline de vídeo.

---

## 2.1 Stack Tecnológica e Decisões de Arquitetura

Decisões fechadas em discussão de arquitetura, com o porquê resumido:

| Camada | Escolha | Por quê (resumo) |
|---|---|---|
| Linguagem backend/worker | Python (`asyncio`) | Não há hot-path de CPU em Python neste design — `ffmpeg`/`realesrgan-ncnn-vulkan` fazem o trabalho pesado como subprocessos; `DrissionPage` não tem equivalente direto em outra linguagem, trocar de stack significaria re-resolver o bypass anti-bot do zero |
| Extrator/bypass | DrissionPage + Cloudscraper (mantidos do Slime Shell Web) | Já funcionam hoje; fallback documentado, não substituição imediata: Playwright + stealth (`patchright`) se algum site evoluir a proteção e DrissionPage parar de furar |
| Fila/worker | `asyncio` nativo + tabela `Job` no SQLite — **sem Celery/Redis** | Concorrência é estritamente 1 por decisão de hardware (seção 6); fila distribuída não traz benefício aqui, só mais um serviço a manter rodando sem necessidade |
| Topologia de processos | **Dois processos**: API (FastAPI, sempre no ar, serve player/painel/WebSocket) e worker (roda o pipeline, pode levar horas num único job) | Comunicam só via a tabela `Job` (polling); um crash ou restart de um não derruba o outro — reiniciar a API pra testar algo não mata um upscaling de 3h em andamento |
| Prefetch de jobs | Não — o worker só busca o próximo job da fila depois que o atual termina | Jobs de horas não ganham nada com prefetch; só complicaria a máquina de estados do worker e podia estourar disco/scratch com dois jobs em voo ao mesmo tempo |
| Upscaling | `realesrgan-ncnn-vulkan` (modelo `realesr-animevideov3`) | Vulkan é agnóstico de fabricante — evita depender de ROCm, que tem suporte capenga em GPUs Polaris como a RX 580. Comparar com `realcugan-ncnn-vulkan` (tunado pra anime) no PoC da Fase 0 — decisão empírica, não a priori |
| Banco de dados | SQLite (modo WAL), driver `sqlite+aiosqlite` (assíncrono — condiz com API/worker rodando em `asyncio`) | Padrão de acesso é 1 writer pesado (worker) + 1 writer leve (API) + N readers, não exatamente 1+N (seção 4/9, I4); Postgres só valeria a pena com multiusuário real. Arquivo do banco fica em ext4, nunca no mount NTFS de mídia — WAL depende de shared-memory mapping e locks POSIX que `ntfs-3g`/FUSE só emula (seção 6, B1) |
| Frontend | React + Vite + Tailwind (mantido do Slime Shell Web) | Reuso direto de componentes já prontos (`AnimeCard`, etc.) |
| Player | `hls.js` (obrigatório — só Safari toca HLS nativo) + controles nativos do `<video>` | Prioriza simplicidade agora; evoluir pra um player customizado (ex. Vidstack) depois é troca de camada de UI, não mudança de arquitetura |
| Empacotamento HLS | `ffmpeg` nativo | Shaka Packager só compensaria com DRM — irrelevante para uso pessoal |
| Containers | Não, por enquanto — worker de GPU roda direto na máquina (sob Zorin — seção 6) | Passthrough de Vulkan em container é fricção real mesmo rodando só sob Linux (acesso a `/dev/dri`, drivers do host); reconsiderar só para API/frontend depois, se fizer sentido |
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
- Adapters por site seguem Strategy Pattern (`backend/extractors/base.py` + uma classe por site, ex. `animefire.py`, `animesdrive.py`), portados/adaptados do projeto original — mas aqui o extrator **baixa** o arquivo em vez de servir a URL direta para o player, e cada adapter ganha a camada de cache/retry/circuit breaker acima em vez de reimplementar isso por site.

### B. Fila de Processamento Assíncrono (Worker Nativo)
- Worker roda como **processo separado** da API (decisão em 2.1), em background com `asyncio`, concorrência estrita de **um vídeo por vez** (respeita 16GB RAM / 8GB VRAM).
- Estado de cada job é persistido em banco relacional (não em memória) — ver seção 5 — para que um crash do processo não perca o progresso de um job que já rodou horas.
- Estados: `na_fila → baixando → validando_fonte → extraindo_frames → upscaling → remontando → empacotando_hls → pronto` (mais `falhou_extracao` e `aguardando_intervencao` — ver seção 3A: uma falha de extração não bloqueia os demais jobs da fila —, `falhou` genérico para as demais etapas, com `etapa_atual`+`erro_msg` localizando onde, `cancelando`/`cancelado` — cancelamento cooperativo, abaixo —, e `pausado` — reservado para uma eventual pausa automática por limite de tempo contínuo de GPU (seção 9), ainda sem gatilho/endpoint definido: tratar como estado reservado para essa mitigação futura, não implementado no MVP; campos que sustentam isso estão na seção 4).
- **Validação da fonte antes da GPU**: depois do download, o job passa por `validando_fonte` — `ffprobe` confere que o arquivo decodifica e que a duração bate aproximadamente com o esperado, antes de entrar na fila de upscaling. GPU é o recurso caro aqui; falhar nesta etapa é muito mais barato que falhar depois de horas de upscaling. O download suporta retomada por HTTP Range e reusa os mesmos cookies/`Referer` da sessão de bypass (seção 3A).
- **Claim atômico de job**: o worker reivindica um job com `UPDATE job SET status='baixando', worker_id=? WHERE id=? AND status='na_fila'`, conferindo `rowcount` — nunca um `SELECT` seguido de `UPDATE`. Evita que duas instâncias do worker rodando por engano façam claim do mesmo job; complementado por um lock de instância única no boot do worker (lockfile com PID, ou tabela `WorkerLock` de uma linha).
- **Cancelamento cooperativo**: a API não consegue matar o subprocesso do worker só via a tabela `Job` (decisão 2.1) — cancelar é pedir, não forçar. `POST /jobs/{id}/cancelar` (seção 5) seta `cancelamento_solicitado=1` e status `cancelando`; o worker roda o polling dessa flag numa corrotina separada da corrotina do pipeline, pra observar o pedido no meio de um chunk (não só entre chunks) — senão a latência de cancelamento é um chunk inteiro.

### C. Pipeline de Tratamento de Vídeo (o motor 4K)

**Atenção ao disco:** extrair todos os frames de um episódio inteiro antes de começar o upscaling é o erro mais comum aqui e pode estourar o disco. Um episódio de ~24 min a ~24fps tem ~34.500 frames; em PNG lossless a 1080p isso facilmente passa de dezenas de GB só na entrada, e os frames de **saída** em 4x (7680×4320) ocupam 16x mais área de pixels cada (4x em cada dimensão) — o total chega à ordem de **~1TB** por episódio se todo o episódio for mantido em disco simultaneamente. Duas mitigações, recomendo as duas:

1. **Processar em chunks** (ex. blocos de 500–1000 frames): extrai um chunk → upscala o chunk → codifica o chunk como um **segmento de vídeo intermediário próprio** (nunca fica em frames soltos) → apaga os frames (originais e upscalados) daquele chunk → passa para o próximo. Mantém o pico de disco limitado a poucos GB por vez, e permite retomar do último segmento concluído se o worker cair no meio (o estado do chunk também fica no banco — ver "Remontagem" abaixo para como os segmentos viram o episódio final).
2. **Formato intermediário mais leve**: usar `-f webp` ou `-f jpg` no `realesrgan-ncnn-vulkan` para os frames de saída dos estágios intermediários (não para o entregável final — ver escolha de codec abaixo). PNG lossless não traz benefício de qualidade perceptível numa etapa que será recodificada em seguida, e custa disco caro.

**Separação de paths por durabilidade e filesystem** (ver seção 6 para o porquê do filesystem importar): `MEDIA_ROOT` guarda os arquivos grandes e duráveis (`raw/`, `hls/`) e vive no mount NTFS onde já está `media/`; um novo `SCRATCH_ROOT` guarda só o pico de frames de um chunk em voo e deve ficar em **ext4 ou tmpfs**, nunca no mount NTFS — `ntfs-3g`/FUSE é lento demais e não garante rename atômico para as ~69 mil criações/deleções de arquivo pequeno que um episódio gera (34.500 frames de entrada + 34.500 de saída). Com formato intermediário lossy e chunk de 500 frames, `SCRATCH_ROOT` em tmpfs é viável (pico de ~1–2,5GB) e elimina esse gargalo de I/O — validar no PoC da Fase 0 (comparar `ntfs-3g` vs ext4 vs tmpfs nos alvos reais). **Ressalva se `SCRATCH_ROOT` for tmpfs:** isso vale só para os frames soltos de um chunk em voo, que podem ser refeitos a qualquer momento — nunca para os segmentos de vídeo já comitados (passo 3 abaixo), que precisam sobreviver a um reboot completo (a seção 6 trata reboot pro Windows com job em andamento como cenário esperado, e tmpfs some inteiro num reboot). Segmentos comitados sempre são promovidos para um diretório em ext4, mesmo quando `SCRATCH_ROOT` aponta pra tmpfs.

**Resolução final alvo: 4K real (3840×2160), não 8K.** O modelo `realesr-animevideov3` usado aqui escala 4x — partindo de 1080p (1920×1080), isso dá 7680×4320, que é **8K**, não 4K: custaria ~4x mais espaço e tempo de GPU sem necessidade, e nenhum dispositivo comum decodifica 8K sem esforço. O passo de remontagem (abaixo) faz o downscale de volta pra 3840×2160, **por chunk** (não no final) — na prática, "upscale 4x e depois downscale pra 4K" tende a dar resultado mais nítido que upscalar direto 2x (funciona como supersampling), então não é desperdício, é técnica. Comparar essa abordagem contra 2x direto (se o binário suportar `-s 2`) fica no PoC da Fase 0, junto da comparação com `realcugan-ncnn-vulkan`.

**Codec do entregável: H.264 (x264, em CPU), fixo — não HEVC.** HEVC via MSE não toca em Chrome/Firefox no Linux, e é justamente nesses navegadores que o `hls.js` do próprio painel roda — escolher HEVC quebraria o player que o projeto depende. HEVC fica como otimização futura, só se o navegador alvo provar suporte real (item de go/no-go da Fase 0). Encode roda em **CPU** (Ryzen 7 5700X) via x264 — a GPU (RX 580) fica reservada exclusivamente pro upscaler; usar `h264_vaapi` (VCE) disputaria a mesma GPU/VRAM que o Real-ESRGAN já usa no limite.

Etapas via linha de comando, executadas **por chunk**:
1. **Separação**: uma única vez no início do episódio, `ffmpeg` extrai o áudio inteiro (`-vn -c:a copy`) — nunca por chunk, pra não precisar remuxar áudio fatiado depois. A extração de frames roda por chunk, forçando CFR (`-fps_mode cfr` no fps real obtido via `ffprobe`, nunca assumido) — fonte VFR quebra a contagem de frames por chunk e desincroniza áudio na montagem final.
2. **Upscaling (Vulkan)**: `realesrgan-ncnn-vulkan` com o modelo `realesr-animevideov3` (otimizado para vídeo de anime, mais rápido que `realesrgan-x4plus-anime` para essa finalidade), escala 4x, sobre os frames do chunk atual. Usar `-t <tile-size>` para tiling automático e evitar estouro de VRAM nos 8GB da RX 580; usar `-j load:proc:save` para calibrar throughput sem saturar RAM. Timeout por chunk + retry **no nível do chunk** (com máximo de tentativas) — sob RADV/Polaris um hang de compute pode gerar `amdgpu: GPU reset` e matar o processo sem estado de falha explícito; retry no nível do job inteiro jogaria fora horas de progresso já comitado. Capturar exit code e contexto em `erro_msg`.
3. **Remontagem do chunk**: `ffmpeg` reconstrói um segmento de vídeo a partir dos frames upscalados do chunk, aplicando o downscale pra 3840×2160 (`-vf scale=3840:2160`) e codificando em H.264 com **parâmetros de encode idênticos em todos os chunks** (senão o demuxer `concat` do ffmpeg falha ou gera drift). O segmento é escrito em nome temporário e promovido com `os.replace()` para um diretório em ext4 (nunca tmpfs, mesmo que `SCRATCH_ROOT` esteja em tmpfs — ver ressalva acima) — atômico em ext4, não confiável sob `ntfs-3g` (mais um motivo pro `SCRATCH_ROOT` ficar fora do NTFS) — só ao concluir.
4. **Montagem final**: depois do último chunk, o `ffmpeg` concatena os segmentos via `concat` demuxer e mux com o áudio extraído no passo 1. Validação por `ffprobe` da contagem de frames de cada segmento antes do concat pega falha parcial de chunk cedo. Retomada = maior segmento comitado; no boot, o worker varre e apaga scratch de chunk em voo (não comitado) antes de retomar.

**Validar no PoC (item já previsto na seção 10)**: fps real de upscaling na RX 580 com `realesr-animevideov3`. GPUs Polaris como a RX 580 (e mais ainda a variante 2048SP desta máquina — ver seção 6) não têm aceleração dedicada para esse tipo de rede neural — é esperado throughput baixo (ordem de poucos frames/segundo), o que pode significar **horas** de processamento por episódio de 24 min. Isso não invalida o projeto, mas deve moldar expectativas de UX (fila overnight, ETA visível, não "upscaling instantâneo") e a decisão de layout do pipeline (chunking citado acima também ajuda a dar progresso incremental visível em vez de barra travada por horas).

### D. Transcodificação para Web (HLS)
- Vídeo 4K final é segmentado em `.ts` de 5–10s + manifesto `.m3u8` (`ffmpeg -hls_time 8 -hls_playlist_type vod`).
- Recomendo **HLS multi-bitrate** (ladder com 4K + 1080p + 720p via `-var_stream_map`) em vez de servir só a renditions 4K nativa: nem toda rede/dispositivo aguenta 4K direto, e sem ladder o player não tem fallback — a experiência quebra em qualquer rede mais lenta.
- **Ordem de empacotamento**: as renditions 1080p/720p do ladder são geradas a partir do **arquivo original 1080p** (baixado da fonte), não por downscale do 4K upscalado — mais barato, e não herdam a alucinação que um upscaler por IA pode introduzir. Isso implica empacotar 1080p/720p **antes** do GC apagar o original, não depois.
- Frames temporários (de cada chunk, ou os que ainda restarem no `SCRATCH_ROOT`) são apagados após a etapa correspondente concluir (Garbage Collection), não só no final — reforça o ponto de disco da seção C. O arquivo original 1080p baixado também é apagado (GC) depois que suas renditions já foram empacotadas no ladder — **"1080p original" (arquivo baixado, descartado) e "rendition 1080p do ladder HLS" (mantida, é o que o player serve) são coisas diferentes**; ver seção 3G para a política de retenção, que atua sobre o ladder já pronto, não sobre o original.

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
Diferente do GC de arquivos temporários (seção 3D, já resolvido durante o processamento), isso é sobre o crescimento do catálogo HLS **já pronto** ao longo do tempo. Com **316GB livres na partição NTFS** onde vive `media/` (711GB total, 56% usado — ver seção 6) e um episódio de 24min em 4K real (seção 3C) ocupando ~3–6GB já com o ladder multi-bitrate, o espaço prático dá pra algo como **~50–100 episódios** antes de precisar de uma política ativa. Não é a emergência de dia 1 que um cálculo em cima de "poucas temporadas" sugeriria, mas também não é problema distante — vale ter a política desde cedo, só sem urgência de bloquear o PoC por causa disso.

- Campo `assistido_em` no `Episodio` (seção 4) — timestamp da última vez que você assistiu, base pra sugestão de retenção.
- Painel admin mostra uso de disco atual (seção 7) e, quando o espaço livre cruzar um limite configurável, dispara uma notificação (reaproveitando o padrão assíncrono da seção 3A/F) sugerindo candidatos a limpar, priorizando episódios assistidos há mais tempo.
- **Nunca deletar automaticamente sem confirmação** — é sua coleção pessoal; mesma filosofia de "avisa, não decide por você" já estabelecida pro extrator (seção 3A).
- **Ação de retenção: remover a rendition 4K do ladder HLS**, mantendo as renditions 1080p/720p já empacotadas — o episódio continua tocável em qualidade menor, e reprocessar de fato exige novo download (o 1080p original já foi apagado pelo GC da seção 3D; ver lá a distinção entre ele e a rendition 1080p do ladder, que é a que sobrevive aqui). Remover a rendition 4K exige reescrever o master manifest do HLS, não é só apagar `.ts` — tratar como passo explícito do endpoint `POST /api/admin/episodios/{id}/reduzir` (seção 5), não implícito.

---

## 4. Modelo de Dados

Banco relacional (SQLite via SQLAlchemy — arquivo único, zero-config, adequado para um nó local; migrar para Postgres só se houver necessidade real de acesso concorrente multiusuário mais adiante).

> `PRAGMA foreign_keys=ON` precisa ser setado por conexão — SQLite não aplica FK por padrão sem isso. Pragmas fixados: `journal_mode=WAL`, `busy_timeout=5000`, `synchronous=NORMAL`, `foreign_keys=ON`. Regra de acesso: nunca manter uma transação de escrita aberta atravessando uma chamada de subprocesso `ffmpeg`/`realesrgan-ncnn-vulkan`; sessões curtas por request na API. Cascade em nível de banco (`ON DELETE CASCADE`) apaga linhas, não arquivos em disco — o fluxo de deleção de anime/episódio precisa apagar os arquivos de mídia primeiro e as linhas depois, em nível de aplicação, senão sobra lixo órfão em `MEDIA_ROOT`.

**Anime** (cada linha = uma temporada, mesma granularidade do AniList — ver seção 3F)
| campo | tipo | nota |
|---|---|---|
| id | PK | |
| titulo, slug | str | `slug` UNIQUE |
| ano | int | `seasonYear` do AniList — evita ambiguidade entre temporadas do mesmo título na UI |
| anilist_id | int, nullable, UNIQUE | confirmado uma vez no cadastro (busca-e-confirma, 3F) |
| kitsu_id | int, nullable | só preenchido se usado como fallback do AniList |
| capa_path, sinopse | str | capa baixada e guardada localmente (não depende do CDN externo continuar no ar — condiz com "funciona sem AniList" da 3F); sinopse cacheada a partir do AniList/Kitsu, não buscada ao vivo |
| total_episodios_anilist | int, nullable | usado no sanity check da seção 3F |
| criado_em | datetime | |

**Episodio**
| campo | tipo | nota |
|---|---|---|
| id | PK | |
| anime_id | FK | `ON DELETE CASCADE` |
| numero, titulo | | número confirmado por você ao enfileirar (3F), não o bruto do site |
| numero_fonte | int, nullable | número original como o site mostrou, mantido pra auditoria/debug |
| tipo | enum | `regular / ova / especial / filme` (3F) |
| versao | enum, NOT NULL, default `legendado` | `legendado / dublado` (3F) — NOT NULL porque múltiplos NULL são valores distintos no SQLite e quebrariam a unique constraint abaixo |
| url_fonte | str | URL de origem do episódio — sem ela, retry/retomada de job é impossível |
| site_origem | str | qual scraper foi usado (movido de `Anime` — circuit breaker e falha são por site, e isso é por episódio: o caso comum, não a exceção) |
| status | enum | `pendente / pronto / falhou / somente_1080p` — `somente_1080p` após redução de retenção (seção 3G/B4) |
| hls_path | str | caminho do `.m3u8` final |
| renditions_disponiveis | str/json | quais renditions do ladder ainda estão empacotadas (ex. `["1080p","720p"]` após redução — seção 3G); remover a 4K reescreve o master manifest, é passo explícito, não implícito |
| capa_path | str, nullable | thumbnail gerada via `ffmpeg` (3F) |
| tamanho_bytes | int | soma dos arquivos do episódio em disco — evita varrer a árvore inteira a cada request no painel de disco (3G) |
| duracao_s | int | |
| assistido_em | datetime, nullable | base pra sugestão de retenção (seção 3G) |
| criado_em | datetime | |

Constraint: **UNIQUE (`anime_id`, `numero`, `tipo`, `versao`)** — é essa constraint que impede job duplicado do mesmo episódio/versão, resolvendo o problema que a própria seção 3F levanta.

**Job**
| campo | tipo | nota |
|---|---|---|
| id | PK | |
| episodio_id | FK | `ON DELETE CASCADE` |
| status | enum | `na_fila / baixando / validando_fonte / extraindo_frames / upscaling / remontando / empacotando_hls / pronto / falhou / falhou_extracao / aguardando_intervencao / cancelando / cancelado / pausado` (seção 3B); índice em `status` — é a coluna mais consultada (fila, polling do worker) |
| etapa_atual, progresso_pct | | para UI de fila; `etapa_atual` também localiza onde um `falhou` genérico aconteceu |
| chunk_atual, total_chunks | int | permite retomada |
| erro_msg, tentativas | | para retry/observabilidade |
| criado_em | datetime | ordena a fila FIFO — sem isso não há critério de ordem |
| iniciado_em, finalizado_em | datetime | |
| proxima_tentativa_em | datetime, nullable | onde mora o backoff 30s→2min→10min da seção 3A |
| heartbeat_em | datetime, nullable | atualizado periodicamente pelo worker; no boot, job em execução com heartbeat velho é resetado pra `na_fila` (seção 9, I7 — cobre crash e reboot pro Windows, seção 6) |
| worker_id | str, nullable | identifica qual instância do worker fez o claim (claim atômico — seção 3B) |
| cancelamento_solicitado | bool, default false | cancelamento cooperativo (seção 3B/5) |

A tabela `Job` é o que falta hoje no rascunho e é o que permite: (a) sobreviver a um crash do worker sem perder horas de GPU, (b) mostrar progresso real na UI em vez de um spinner, (c) implementar retry sem reprocessar do zero.

**SessaoBypass** (suporta o item 1 da seção 3A)
| campo | tipo | nota |
|---|---|---|
| site_dominio | PK | ex. `animefire.plus` |
| cookies_json | text | `cf_clearance` + demais cookies de sessão, em texto puro — risco baixo dado o escopo single-user (8.2), mas vale registrar explicitamente (ver 8.1) |
| user_agent | str | fixado junto com a sessão |
| criado_em, expira_estimado_em | datetime | expiração é estimativa — se a sessão for rejeitada antes disso, invalida na hora |

**EstadoSite** (suporta o circuit breaker do item 2 da seção 3A)
| campo | tipo | nota |
|---|---|---|
| site_dominio | PK | |
| falhas_consecutivas | int | |
| cooldown_ate | datetime | enquanto no futuro, extrator pula o site sem tentar; "degradado" é estado **derivado** (`cooldown_ate > now()`), não um campo próprio — evita drift entre os dois |
| ultima_falha_em | datetime, nullable | depuração |
| ultimo_erro | str, nullable | depuração |

---

## 5. API (rascunho de endpoints)

```
GET    /api/admin/animes/buscar?q=...           busca candidatos no AniList (fallback Kitsu) — busca-e-confirma da seção 3F
POST   /api/admin/animes                        confirma um candidato e cria o Anime (grava anilist_id/kitsu_id)
POST   /api/admin/jobs                        cria job (url, anime_id, número do episódio, tipo, versão)
GET    /api/admin/jobs                         lista fila com status
GET    /api/admin/jobs/{id}                    detalhe/progresso de um job
POST   /api/admin/jobs/{id}/cancelar            cancelamento cooperativo (seção 3B/9, B7) — 202, não 204: é assíncrono; DELETE sugeria que a linha some, perdendo erro_msg/histórico
POST   /api/admin/jobs/{id}/retry               retoma job a partir do último chunk comitado
GET    /api/admin/notificacoes                  jobs em aguardando_intervencao (para o indicador persistente da seção 3A)
WS     /ws/jobs/{id}                            progresso em tempo real de um job (evita polling)
WS     /ws/admin                                 eventos globais da fila (job concluído/precisa de atenção) — alimenta o toast da seção 3A

GET    /api/admin/sites                         estado de cada site (cooldown_ate, falhas_consecutivas — "degradado" é derivado, seção 4); sem isso jobs somem da fila sem explicação visível
POST   /api/admin/sites/{dominio}/reset         força saída do cooldown manualmente

PATCH  /api/admin/episodios/{id}                corrige número/tipo/versão depois do cadastro, caso o valor confirmado ao enfileirar (3F) esteja errado — hoje não há como corrigir sem apagar e recriar
DELETE /api/admin/episodios/{id}                remove episódio (arquivos + linha) — ação de limpeza da 3G
POST   /api/admin/episodios/{id}/reduzir        remove a rendition 4K do ladder, mantém 1080p/720p (ação de retenção da 3G — ver B4)

GET    /api/admin/disco                         uso de disco, espaço livre, threshold, candidatos a limpeza (base da 3G)
GET    /api/admin/worker                        heartbeat/estado do worker atual (seção 4/9, I7)
GET    /api/health                              liveness da API

GET    /api/animes                             lista de animes prontos (uso pessoal — ver seção 8.2, fica atrás de autenticação)
GET    /api/animes/{id}/episodios                lista episódios de um anime — falta hoje, impossível montar a tela do anime sem isso
POST   /api/episodios/{id}/assistido            grava assistido_em (nada no sistema preenche esse campo hoje, e a 3G inteira depende dele)
GET    /api/episodios/{id}/playlist.m3u8         serve o manifesto HLS — endereçado por episodio_id, não por número: a constraint UNIQUE (anime_id, numero, tipo, versao) da seção 4 permite mais de um episódio com o mesmo número (dublado vs. legendado, por ex.), então {n} sozinho seria ambíguo
GET    /api/episodios/{id}/{segmento}.ts         serve os segmentos HLS (hoje só existia o .m3u8 — sem isso o hls.js não toca nada)

DELETE /api/admin/animes/{id}                    remove um anime inteiro (arquivos de todos os episódios + linhas, cascade — seção 4 já prevê ON DELETE CASCADE nas linhas; arquivos são responsabilidade da aplicação)
```

Todos os endpoints exigem autenticação (seção 8.1) — dado o escopo confirmado de uso pessoal (seção 8.3), não há endpoint público sem login.

**Transporte de autenticação: cookie, não header.** WebSocket não permite headers customizados no handshake feito pelo navegador, e os segmentos `.ts` são buscados pelo `hls.js` via URLs geradas a partir do manifest — um cookie (HttpOnly, `SameSite=Lax`) autentica manifest, segmentos e WS de forma uniforme, sem precisar assinar URL por URL. Comparação do token deve usar `hmac.compare_digest` (evita timing attack). Se `media/hls/` for exposto via `StaticFiles` do FastAPI, isso contorna a dependency de auth das rotas — o mount estático também precisa estar atrás do gate, não só as rotas de API. O WebSocket é canal de notificação, não fonte de verdade: nenhum estado deve existir só em mensagem de WS — um cliente que reconecta depois de horas precisa conseguir buscar o estado atual via REST (`GET /api/admin/jobs/{id}`, `GET /api/admin/worker` etc.).

---

## 6. Hardware e Ambiente de Desenvolvimento

**Topologia: uma única máquina física, dual-boot.** `rogerio-win11` e `rogerio-zorin` não são hosts distintos — são o mesmo hardware, alternando entre Windows 11 e Zorin (Linux) via dual-boot. Isso muda a leitura do resto desta seção: não existe cenário de "ambiente remoto sem acesso à GPU" nem passthrough Vulkan a configurar/validar — quando a máquina está booted num sistema, ela *é* aquele sistema, com acesso direto ao hardware.

**Decisão: o worker/pipeline roda exclusivamente sob Zorin.** GPU Vulkan/AMDGPU, `ffmpeg` e todo o pipeline de upscaling só devem ser iniciados com a máquina booted em Linux. Constraint explícita, não sugestão: **nunca iniciar o worker enquanto booted em Windows.** Código de API/frontend pode ser desenvolvido em qualquer um dos dois boots (não depende de GPU), mas o worker não. Se a máquina for rebootada pro Windows com um job em andamento, o worker Linux simplesmente para de rodar — a mitigação de heartbeat (`heartbeat_em` no `Job`, seção 4/9, item I7) cobre esse caso como rede de segurança: no próximo boot em Zorin, o worker reseta pra `na_fila` qualquer job preso com heartbeat velho, sem intervenção manual.

**Hardware confirmado (Zorin):**
| Componente | Especificação |
|---|---|
| GPU | Radeon RX 580 **2048SP** (Polaris 20 XL) — variante reduzida da RX 580 "padrão" (2304 SP), ~10–15% mais lenta na prática, equivalente a uma RX 570 rebadgeada. VRAM 8192 MiB. |
| CPU | Ryzen 7 5700X (AM4, Zen 3) |
| RAM | 16GB, **swap = 0** — recomendado não rodar encode (ffmpeg/x264) e upscaling concorrentes sem swap, ou criar um swapfile de 8–16GB antes da Fase 0 |
| Disco (mídia, NTFS) | 316GB livres de 711GB total (56% usado) — mount via `ntfs-3g`; ver seção 3C/B1 para as implicações no pipeline |
| Disco (sistema, ext4 `/`) | 60GB livres — onde o banco SQLite (seção 4) e o `SCRATCH_ROOT` (seção 3C) devem ficar |

- Curvas de ventoinha, clock e temperatura da GPU devem ser monitorados sob 100% de uso sustentado por 20+ minutos (não só picos curtos) — usar `radeontop` para uso/clock e leitura direta de `/sys/class/drm/card*/device/hwmon/hwmon*/temp1_input` para temperatura (`rocm-smi` não se aplica: não está instalado, e contradiz a própria escolha de Vulkan-sobre-ROCm da tabela 2.1).

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

`SessaoBypass.cookies_json` (seção 4) guarda o `cf_clearance` do Cloudflare em texto puro no banco — risco baixo dado o escopo single-user (8.2), mas registrado aqui explicitamente em vez de deixar implícito.

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
| GPU trava/superaquece sob 100% por horas | Monitorar temp/uso continuamente, não só em picos; considerar limite de tempo contínuo com pausa automática (estado `pausado` do Job reservado pra isso — seção 3B/4, ainda sem gatilho definido) |
| GPU reseta/mata o processo sem gerar falha explícita (RADV/Polaris, hang de compute) | Timeout + retry no nível do **chunk**, nunca do job inteiro; captura exit code/contexto em `erro_msg` (seção 3C, I9) |
| Worker cai no meio de um job de horas | Estado do job + chunk persistido em DB, pipeline resumível (seção 4/5) |
| Job preso em execução após crash do worker (ou reboot pro Windows — seção 6) | `heartbeat_em` no `Job`, atualizado periodicamente; no boot, worker reseta pra `na_fila` todo job com heartbeat velho (seção 4, I7) |
| Duas instâncias do worker fazem claim do mesmo job | Claim atômico (`UPDATE ... WHERE status='na_fila'` conferindo `rowcount`, nunca SELECT-depois-UPDATE) + lock de instância única no boot (seção 3B, B6) |
| API não consegue matar o subprocesso do worker via tabela `Job` só | Cancelamento cooperativo: `cancelamento_solicitado` + status `cancelando`, 202 em `POST /jobs/{id}/cancelar`; polling da flag numa corrotina separada da do pipeline (seção 3B/5, B7) |
| Site-fonte muda DOM/anti-bot e quebra o scraper | Strategy Pattern isola por site; smoke test periódico por scraper (seção 7) |
| Sessão de bypass expirada não é detectada (Cloudflare pode responder challenge com HTTP 200) | Detector `is_challenge()` compartilhado (header `cf-mitigated`, `<title>Just a moment`, `cf_chl_opt`); sessão expirada invalida o cache sem contar pro circuit breaker — só falha após sessão nova conta pra `falhas_consecutivas`; `cf_clearance` é vinculado a IP+UA, egress trocado invalida o cache por definição (seção 3A, I5) |
| Download corrompido/incompleto só é descoberto na etapa de GPU (cara) | Etapa `validando_fonte`: `ffprobe` confere decodabilidade e duração antes de enfileirar pra GPU; retomada por HTTP Range; reusa cookies/`Referer` da sessão de bypass (seção 3B, I6) |
| SQLite com escrita concorrente worker+API | Na prática são 2 writers (worker pesado + API leve) + N readers, não 1+N; pragmas fixados (`journal_mode=WAL`, `busy_timeout=5000`, `synchronous=NORMAL`, `foreign_keys=ON` — seção 4); migrar para Postgres só se necessário (I4) |
| Exposição legal por armazenar/redistribuir conteúdo protegido | Ver 8.3 — decisão consciente de escopo, não acidente de arquitetura |
| Match errado de anime no AniList/Kitsu contamina sinopse/capa/numeração | Busca-e-confirma manual uma vez por anime, não fuzzy-match automático (seção 3F) |
| Numeração de episódio ambígua (absoluta vs. por temporada) | Cada temporada = `Anime` separado; número confirmado manualmente ao enfileirar, com sanity check contra a contagem do AniList (seção 3F) |
| Upscaling 4x sem downscale gera 8K por acidente (4x mais espaço/tempo que o necessário) | Downscale explícito pra 3840×2160, por chunk, no passo de remontagem (seção 3C) |
| Codec do entregável indefinido (H.264/HEVC ambíguo) — HEVC via MSE não toca em Chrome/Firefox no Linux | Fixar H.264 (x264, CPU) como padrão; HEVC só como otimização futura com suporte de navegador comprovado (seção 3C, B9) |
| Comparação entre modelos de upscaling sem critério nomeado (nitidez de frame parado engana — flicker temporal em áreas planas é o problema real) | Critério de comparação = estabilidade temporal em movimento, avaliado na Fase 0 (seção 10, I10) |
| Disco (316GB NTFS + 60GB ext4) enche com o catálogo 4K já pronto, não só temporários | Notificação de uso de disco + sugestão de retenção baseada em `assistido_em`, nunca deleção automática (seção 3G) |

---

## 10. Roadmap

- **Fase 0 — PoC**: validar upscaling em lote com clipe de 5s na RX 580; medir fps real, uso de VRAM e tempo por frame com `realesr-animevideov3` **e comparar com `realcugan-ncnn-vulkan`** (2.1); comparar 4x+downscale vs. 2x direto pra chegar em 4K real (3C); decidir tile size e formato intermediário (PNG vs WebP/JPG) com base em dados reais, não estimativa. **Critério de go/no-go explícito:**
  - (a) fps e tempo total extrapolado por episódio, com limiar de reavaliação de escopo (ex. ">8h por episódio de 24min → repensar");
  - (b) custo de I/O do churn de frames medido nos alvos reais — `ntfs-3g` vs ext4 vs tmpfs, decide onde fica `SCRATCH_ROOT` (seção 3C, B2);
  - (c) tamanho de chunk como saída medida, não palpite;
  - (d) temperatura/clock **sustentados** por 20+min, não só pico (seção 6);
  - (e) teste de playback real do codec escolhido (H.264) no navegador alvo (seção 3C, B9);
  - (f) critério de qualidade = estabilidade temporal em movimento, não nitidez de frame parado (seção 3C, I10) — incluindo o teste honesto "prefiro isso ao 1080p original numa TV real", a hipótese de valor do projeto inteiro.
- **Fase 1 — Worker & Pipeline**: worker como processo separado da API (2.1), fila persistida em SQLite, pipeline em chunks (FFmpeg + Real-ESRGAN), GC automático por chunk, empacotamento HLS multi-bitrate (seção 3D) como etapa final do próprio pipeline. Fonte do job nesta fase: **caminho de arquivo local** (um episódio baixado manualmente) — valida o pipeline 4K completo, a pergunta que decide o projeto, sem depender de scrapers de terceiros que já podem estar quebrados. Esse modo "job de arquivo local" **permanece no sistema depois**, como caminho de debug/fallback pra quando um site estiver quebrado — não é só um atalho de bootstrap.
- **Fase 2 — Extrator resiliente**: portar/adaptar os scrapers do Slime Shell Web (Strategy Pattern) para baixar o arquivo em vez de servir URL direta ao player, já com cache de sessão/cookies, retry+backoff e circuit breaker por site (seção 3A) desde o início — é mais fácil nascer com isso do que remendar depois. Passa a alimentar o worker da Fase 1 com URLs reais, complementando (não substituindo) o modo de arquivo local.
- **Fase 3 — API (REST + WS) e Autenticação**: endpoints REST + `WS /ws/admin` de notificação/progresso sobre os jobs já produzidos pela Fase 1, **e o gate de autenticação** (token fixo, cookie — seção 5/8.1) desde os primeiros endpoints reais — a escolha do transporte de auth determina como HLS e WS são servidos, é decisão de arquitetura, não hardening tardio; o `.env.example` já tem o placeholder do token, a decisão já está tomada.
- **Fase 4 — Frontend**: painel admin (fila, tela de busca-e-confirma de anime no AniList/Kitsu — seção 3F, indicador persistente de "precisa de atenção", toast em tempo real) + player (`hls.js`), reaproveitando componentes visuais do projeto original.
- **Fase 5 — Hardening**: monitoramento de hardware, smoke tests dos scrapers, logging estruturado (autenticação já entregue na Fase 3).
- **Fase 6 — Futuro/opcional**: Object Storage/CDN, múltiplos workers se o hardware permitir, uso mobile dedicado (fora de escopo por ora — ver seção 1).

---

## 10.1 Estrutura de Repositório e Checklist de Pré-Implementação

**Repositório**: novo, separado do Slime Shell Web (ver nota no topo do documento). Estrutura de pastas proposta:

```
Slime_Studio/
├── backend/
│   ├── api/                    # FastAPI: rotas, WebSocket, auth
│   ├── worker/                 # processo separado (2.1) — entrypoint + pipeline
│   │   └── pipeline/           # separacao.py, upscaling.py, remontagem.py, hls.py, gc.py (3C/3D)
│   ├── extractors/             # Strategy Pattern (3A): base.py + animefire.py, animesdrive.py...
│   │                           #   + sessao_cache.py, circuit_breaker.py (resiliência, 3A)
│   ├── integrations/           # anilist.py, kitsu.py (3F)
│   ├── models/                 # SQLAlchemy: Anime, Episodio, Job, SessaoBypass, EstadoSite (seção 4)
│   ├── db/                     # engine, sessão, migrations (Alembic) — arquivo .db fica fora daqui, em ext4 (DATABASE_URL, seção 6/2.1)
│   ├── core/config.py          # .env, paths de mídia, tile size etc.
│   └── pyproject.toml          # uv (2.1)
├── frontend/                   # React + Vite + Tailwind
│   └── src/{admin,player,components}/
├── media/                      # MEDIA_ROOT, runtime, fora do git, no mount NTFS — raw/, hls/{anime_slug}/{numero}/ (recomendado, sobrevive a reset/restore do banco — não obrigatório)
├── scripts/                    # start-dev.sh — equivalente ao `slimeWEB` original, sobe API+worker+Vite
└── .env.example                 # SCRATCH_ROOT (ext4/tmpfs) e DATABASE_URL (ext4) apontam pra fora deste diretório — ver seção 6
```

**Checklist bloqueante antes da Fase 0:**
- [ ] Repositório criado.
- [ ] `ffmpeg` e `realesrgan-ncnn-vulkan` instalados e testados **manualmente** na máquina com a RX 580 — um comando de cada, fora do projeto, só pra confirmar que o Vulkan enxerga a GPU antes de escrever código em volta disso.
- [ ] Confirmar que `animefire.py`/`animesdrive.py` (herdados do Slime Shell Web) ainda furam a proteção dos sites hoje — sites de anime mudam de domínio/proteção com frequência; não vale construir a resiliência da seção 3A em cima de um scraper que já pode estar quebrado.
- [ ] Alembic configurado pro schema inicial (as 5 tabelas da seção 4).
- [ ] `.env.example` com os placeholders necessários (token de acesso, `MEDIA_ROOT`, `SCRATCH_ROOT`, `DATABASE_URL`, tile size default).
- [ ] Decisão de autenticação: em vez de usuário/senha + JWT completo (over-engineering pra 1 usuário), um **token fixo único** gerado uma vez, guardado no `.env`, comparado num cookie/header — tela de "desbloquear", não de login. Evolui depois se algum dia virar multiusuário.

---

## 11. Próximos Passos Imediatos

1. Validar a prova de conceito do upscaling em lote com um clipe de 5 segundos — medir fps, VRAM e tempo real na RX 580 (dado concreto que hoje falta e que dimensiona todo o resto do plano).
2. Estruturar o loop assíncrono do Worker em Python com estado persistido em SQLite (não em memória) desde o início, aceitando um caminho de arquivo local como fonte do job (seção 10, Fase 1) — para já nascer resumível e validar o pipeline sem depender de scraper nenhum.
3. Desenvolver a interface abstrata do extrator de links (Strategy Pattern), portando o motor de bypass do Slime Shell Web para o modelo de download, já com cache de sessão e circuit breaker por site (seção 3A) — não como camada adicionada depois.

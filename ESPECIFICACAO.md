# Documento de Especificação de Projeto
## Slime Studio — Orquestrador de Streaming de Anime com Upscaling por IA

> Evolução do [Slime_Shell_Web](https://github.com/rogerio-miguel/Slime_Shell_Web): sai do modelo "automatizar o navegador e tocar localmente via MPV" para um modelo "baixar, re-hospedar via HLS e aplicar upscaling por IA". Essa mudança de modelo é o ponto mais importante do documento — está detalhada na seção 2.
>
> **Repositório**: `Slime_Studio`, separado do Slime Shell Web (justificativa: seção 2 já mostra que a postura legal e a arquitetura mudam de categoria — separar deixa isso explícito). Nome decidido em 2026-08-10.
>
> **Estado do projeto**: scaffold inicial (`backend/`, `frontend/`, `media/`, `scripts/`, `.env.example`), sem código de aplicação além do protótipo de player em `teste/` (seção 11). Este documento é a especificação de referência; `CLAUDE.md` aponta pra ele.
>
> **Como ler este documento — a convenção "hoje / pós-gatilho".** O sistema tem dois modos de upscaling, e a fronteira entre eles é a GPU disponível, não uma escolha de gosto:
> - **Modo em tempo real — hoje, hardware atual: Radeon RX 580 8GB.** Anime4K roda em WebGPU, por frame, no navegador, sobre o vídeo já baixado e re-empacotado — zero espera. **Já validado**: a seção 11 registra um protótipo funcional e medido, que fecha a Fase 0 deste modo.
> - **Modo em lote — pós-gatilho, hardware planejado: RTX 5060 Ti 16GB ou superior.** Real-ESRGAN roda offline sobre frames extraídos, qualidade máxima, ~40 min/episódio estimados (não medidos). **Condicionado à troca de GPU** — a seção 12 define o gatilho exato e proíbe implementar este modo antes dele.
>
> Os dois modos alimentam o mesmo catálogo e o mesmo master manifest HLS: a rendition `1080p` (fonte re-empacotada, sem IA no servidor — a qualidade nasce no player, seção 3E) é o modo em tempo real; `1080p_ia` (saída do Real-ESRGAN) é o modo em lote. Onde uma seção não distingue "hoje" de "pós-gatilho" explicitamente, ela vale para os dois. Texto marcado **pós-gatilho** é planejamento antecipado, não implementação liberada (regra completa em 12.4).
>
> O que vale para os dois modos sem alteração: Strategy Pattern dos extratores (3A), autenticação (8), AniList/Kitsu (3F), topologia de dois processos (2.1/3B).

---

## 1. Visão Geral

Sistema de ponta a ponta, de **uso pessoal e single-user**, que recebe links de fontes externas, contorna proteções anti-bot, extrai a mídia original, aplica upscaling por IA e entrega em **1920×1080**, empacotado em HLS, para um frontend React com player web. O objetivo de experiência é único nos dois modos (cabeçalho): assistir anime com **mais detalhe e menos artefato do que a fonte entrega**, direto no navegador — não "em 4K". A tela é 1920×1080 (confirmado, seção 9.1/S2) e a contagem de pixels exibidos não aumenta em nenhum dos dois modos. Fallback de qualidade menor para rede fraca é tratado por modo (3D). Uso mobile foi considerado e fica deliberadamente fora de escopo por ora (a web app deve funcionar razoavelmente em navegador mobile via HLS, mas nada além disso é planejado nesta fase).

**O que "mais detalhe" significa, já que não significa "mais pixels".** Nos dois modos, o CNN reconstrói linhas e gradientes que a compressão da fonte destruiu, dentro dos mesmos 1920×1080 exibidos. No modo em lote isso é literal: upscale 4x seguido de downscale Lanczos funciona como antialiasing de até 16 amostras por pixel de saída (seção 3C). No modo em tempo real é o mesmo princípio um degrau abaixo: upscale-e-downscale a 1:1 via Anime4K (seção 3E). O teste honesto que decide se isso vale a pena, para qualquer um dos dois modos, é o mesmo: *"prefiro isso ao 1080p original na minha tela real?"* — não "tem mais pixels?" (Fase 0 de cada modo, seção 10).

**Por que dois modos, e não um só.** O modo em lote foi desenhado para "construir um acervo aos poucos, sem pressa". O uso real inclui também "acompanhar lançamentos" — episódio novo sai, quer assistir logo depois de disponível. No hardware atual (RX 580, sem núcleo tensor) os dois requisitos são incompatíveis dentro do mesmo pipeline: a aritmética que prova isso está no Bloco A da seção 2.2. O modo em tempo real é a resposta a essa incompatibilidade — zero espera, qualidade já validada por medição (seção 11) — e continua sendo a resposta para "quero assistir agora" mesmo depois da troca de GPU (12.2). O modo em lote é o teto de qualidade, hoje descartado por tempo de processamento (2.3, opção A) e reaberto pelo gatilho de hardware (seção 12).

**Baseline herdado (verificado no código do Slime Shell Web).** `Slime_Shell_Web/backend/player.py` já monta o Anime4K Mode A com variantes VL — `Clamp_Highlights`, `Restore_CNN_VL`, `Upscale_CNN_x2_VL`, `AutoDownscalePre_x2/x4`, `Upscale_CNN_x2_M` — via MPV+Vulkan. Ou seja, esta máquina já rodava CNN de upscaling em tempo real antes deste projeto começar; é o piso de qualidade que o modo em tempo real precisa **superar**, não igualar — com a ressalva de que esse baseline nunca foi medido, só configurado (S1, seção 9.1).

Reaproveita do Slime Shell Web: o padrão de scrapers por site (Strategy Pattern), o motor de bypass híbrido (DrissionPage + Cloudscraper), a stack FastAPI + React/Vite/Tailwind, e a integração com AniList/Kitsu para metadados e capas. O upscaling em tempo real via shader também é reaproveitado como *princípio* — mas trocando MPV+Vulkan nativo por WebGPU no navegador (seção 3E), porque o alvo passou a ser servir web, não só tocar localmente.

Não reaproveita: o storage em JSON puro (aqui precisa de um banco relacional de verdade — ver seção 4) e a postura de "nunca armazenar conteúdo" (aqui o vídeo baixado é persistido e re-servido — ver seção 8.3).

---

## 2. O que muda em relação ao Slime Shell Web (e por que isso importa)

| Aspecto | Slime Shell Web | Slime Studio |
|---|---|---|
| Upscaling | Shader Anime4K em tempo real, durante a reprodução, via MPV+Vulkan nativo, sobre URL hotlinkada | **Hoje**: Anime4K em tempo real via WebGPU no navegador, sobre arquivo baixado. **Pós-gatilho**: Real-ESRGAN em lote, offline, sobre frames extraídos (soma-se ao modo em tempo real, não o substitui) |
| Conteúdo armazenado | Nenhum — é um navegador automatizado que toca e descarta | Vídeo 1080p (re-empacotado hoje; processado por IA pós-gatilho) é persistido em disco e re-servido via HLS |
| Storage | Arquivos JSON locais | Banco relacional (SQLite) + arquivos de mídia em disco |
| Distribuição | Local, um usuário, um processo MPV | Web, HLS, single-user (mesmo escopo de uso pessoal do original — ver seção 8.2) |
| Autenticação | Nenhuma | Necessária em toda a aplicação — painel admin e acervo/player (ver seção 8) |
| Postura legal | Explicitamente descrito como ferramenta educacional que "não armazena conteúdo protegido" | Passa a armazenar e redistribuir cópias — risco de direitos autorais muda de categoria (ver seção 8.3) |

Essa tabela existe porque é fácil copiar a arquitetura antiga sem perceber que a mudança de "tocar" para "armazenar e redistribuir" não é um detalhe de implementação — é uma mudança de escopo que afeta banco de dados, autenticação e exposição legal do projeto. Recomendo tratar isso como decisão consciente (ver 8.3), não como consequência acidental do pipeline de vídeo.

**Cinco ganhos concretos sobre o Slime Shell Web**, além da tabela acima — os dois primeiros não dependem de qual modo de upscaling está ativo:

1. **Fonte estável em vez de hotlink.** O original tocava uma URL de CDN de terceiro: sujeita a throttling, rebuffer, expiração de token no meio do episódio e seek lento. Aqui o arquivo está em disco local, servido pela própria máquina. Isso é ganho de *qualidade entregue* mesmo com o mesmo shader.
2. **Nenhum concorrente pelo hardware durante a reprodução.** Rede + TLS + rebuffer de um stream remoto custam CPU e podem estagnar o pipeline de decode. Aqui o download já terminou antes de a reprodução começar. Todo o headroom da GPU vai para o shader — o que abriu espaço, medido no protótipo (seção 11), para subir de preset dentro do Mode A, não para empilhar um segundo passe (ver a correção registrada em 11.2, item 5).
3. **Preset calibrável com medição, não com chute.** HUD de frame time + seletor de preset + (pós-MVP) degradação automática por `droppedVideoFrames`. O MPV original dropava frames em silêncio.
4. **Catálogo real.** Metadados AniList, capa, `assistido_em`, retomada — o original tinha JSON solto (`historico.json`, `cache_animes.json` na raiz do repo).
5. **Caminho de upgrade sem retrabalho.** Master manifest desde o dia 1 (3D): quando o gatilho de hardware (seção 12) acontecer, a rendition `1080p_ia` entra no mesmo manifesto, na mesma URL, no mesmo player. Não se troca de sistema, se acrescenta uma variante.

**Onde o modo em tempo real é honestamente pior que o MPV original**: o navegador adiciona overhead que o MPV+Vulkan não tem (compositor, apresentação de canvas, possível cópia de textura decodificada). Era risco registrado antes do protótipo; a seção 11 mede que, para o preset escolhido, esse overhead não compromete a experiência nesta GPU.

---

## 2.1 Stack Tecnológica e Decisões de Arquitetura

Decisões fechadas em discussão de arquitetura, com o porquê resumido:

| Camada | Escolha | Por quê (resumo) |
|---|---|---|
| Linguagem backend/worker | Python (`asyncio`) | Continua não havendo hot-path de CPU em Python: `ffmpeg` roda como subprocesso e o TensorRT executa em C++ atrás de um binding fino. A rota TensorRT **coloca** Python no laço por frame (alimentar/drenar tensores), o que não existia com um binário CLI — mas a ~15 fps o orçamento é de ~66 ms/frame e o overhead de binding é da ordem de microssegundos. Se a medição da Fase 0(g) contrariar isso, a saída é batching, não troca de linguagem. `DrissionPage` não tem equivalente direto em outra linguagem, trocar de stack significaria re-resolver o bypass anti-bot do zero |
| Extrator/bypass | DrissionPage + Cloudscraper (mantidos do Slime Shell Web) | Já funcionam hoje; fallback documentado, não substituição imediata: Playwright + stealth (`patchright`) se algum site evoluir a proteção e DrissionPage parar de furar |
| Fila/worker | `asyncio` nativo + tabela `Job` no SQLite — **sem Celery/Redis** | Concorrência é estritamente 1 por decisão de hardware (seção 6); fila distribuída não traz benefício aqui, só mais um serviço a manter rodando sem necessidade |
| Topologia de processos | **Dois processos**: API (FastAPI, sempre no ar, serve player/painel/WebSocket) e worker (roda o pipeline, pode levar horas num único job) | Comunicam só via a tabela `Job` (polling); um crash ou restart de um não derruba o outro — reiniciar a API pra testar algo não mata um upscaling de 3h em andamento |
| Prefetch de jobs | Não — o worker só busca o próximo job da fila depois que o atual termina | Jobs de horas não ganham nada com prefetch; só complicaria a máquina de estados do worker e podia estourar disco/scratch com dois jobs em voo ao mesmo tempo |
| Upscaling — **hoje** | **Anime4K (Mode A) em WebGPU, client-side**, via a lib `anime4k-webgpu` (2.3) | GPU atual (RX 580, Polaris) não tem núcleo tensor: Real-ESRGAN em lote custa ~10–16h/episódio nela (Bloco A, 2.2), fora de cogitação para "assistir logo". O orçamento de 41ms/frame cabe numa classe de rede muito menor (Anime4K/CNN leve), não numa rede do porte do Real-ESRGAN — não existe meio-termo nesta GPU (2.2). Validado por medição, não só estimativa: seção 11 |
| Upscaling — **pós-gatilho** | **TensorRT (FP16) sobre ONNX exportado do `realesr-animevideov3`**, servido por um processo residente do worker — `realesrgan-ncnn-vulkan` fica como rota de fallback | Só entra em cogitação quando a GPU for trocada (seção 12). Numa Blackwell com tensor cores, TensorRT FP16 mede ~4x o throughput do ncnn-Vulkan, e é esse 4x que levaria o episódio de ~3h para ~40min estimados — o que mudaria a natureza do produto, não só o relógio (Bloco B, 2.2). Comparar com `realcugan` e com o `xsx2` (2x nativo) no PoC da Fase 0 pós-gatilho — a escolha de *modelo* seguirá empírica, só a de *runtime* já está fechada como planejamento |
| Banco de dados | SQLite (modo WAL), driver `sqlite+aiosqlite` (assíncrono — condiz com API/worker rodando em `asyncio`) | Padrão de acesso é 1 writer pesado (worker) + 1 writer leve (API) + N readers, não exatamente 1+N (seção 4/9, I4); Postgres só valeria a pena com multiusuário real. Arquivo do banco fica em ext4, nunca no mount NTFS de mídia — WAL depende de shared-memory mapping e locks POSIX que `ntfs-3g`/FUSE só emula (seção 6, B1) |
| Frontend | React + Vite + Tailwind (mantido do Slime Shell Web) | Reuso direto de componentes já prontos (`AnimeCard`, etc.) |
| Player | `hls.js` (obrigatório — só Safari toca HLS nativo), alimentando um `<video>` **oculto**; elemento visível é um `<canvas>` WebGPU (3E) | `hls.js` continua necessário para servir HLS na maioria dos navegadores. **Controles nativos do `<video>` não sobrevivem**: o canvas cobre a UI nativa, então uma barra de controles própria (teclado + ARIA) deixou de ser opcional — corrigido a partir do que o protótipo (seção 11) exigiu na prática |
| Empacotamento HLS | `ffmpeg` nativo | Shaka Packager só compensaria com DRM — irrelevante para uso pessoal |
| Containers | Não, por enquanto — worker de GPU roda direto na máquina | O argumento antigo (passthrough de Vulkan é fricção) **enfraqueceu**: o NVIDIA Container Toolkit é maduro e passthrough de CUDA em container é rotina. A decisão fica de pé por outro motivo, mais fraco e honesto: é uma máquina, um usuário, e containerizar não resolve problema nenhum que exista hoje. Reconsiderar quando houver um segundo ambiente de execução, não antes |
| Gerenciador de pacotes Python | `uv` | Resolução de dependências rápida, padrão de fato emergente no ecossistema Python |

---

## 2.2 Orçamento de Compute

Dois blocos. O Bloco A é a aritmética que decide o modo em tempo real, na GPU **atual** — é o que sustenta a escolha de upscaling em 2.1. O Bloco B é a aritmética do modo em lote, na GPU **planejada** — condicionado ao gatilho de hardware (seção 12), e nunca medido nesta máquina.

### Bloco A — hoje (Radeon RX 580 2048SP, Polaris)

Toda a decisão de rodar Anime4K em vez de Real-ESRGAN em tempo real decorre de uma única aritmética. Os números são **estimativa de ordem de grandeza**, não medição de fps — quem mede fps de fato é o protótipo da seção 11, que valida a conclusão qualitativa abaixo (meio-termo não existe nesta GPU) sem depender destes números exatos.

**Capacidade da GPU.** RX 580 2048SP (Polaris 20 XL): 2048 shaders × 2 × ~1,28 GHz ≈ **5,3 TFLOPS FP32 de pico**. Polaris não tem *rapid packed math* (FP16 a 2x só a partir de Vega) nem núcleo tensor. Eficiência realista em convolução via Vulkan/ncnn na faixa de 30–50% → **~1,6–2,6 TFLOP/s efetivos**.

**Custo do modelo em lote, por frame (para contraste — é o que o modo em tempo real evita pagar).** `realesr-animevideov3` é uma `SRVGGNetCompact` (64 canais, 16 convs) e roda **na resolução de entrada** — o upsample é só o pixel-shuffle final. Por frame 1080p: ~18 convs × (1920×1080 × 64×64×9×2) ≈ **~2,6 TFLOP/frame**.

> ~2,6 TFLOP/frame ÷ ~2 TFLOP/s ≈ **0,6–1,0 fps**. Um episódio de 24min (~34.500 frames a 24fps) → **~10–16 horas**.

Isso confirma, por aritmética independente, a estimativa de 0,5–3 fps e coloca o resultado muito acima de qualquer orçamento de tempo real — é o motivo pelo qual a opção A da seção 2.3 (Real-ESRGAN em lote nesta GPU) é descartada, não uma preferência de gosto.

**Orçamento em tempo real.** Para não derrubar frame a 24fps: **≤ 41 ms/frame**. A ~2 TFLOP/s efetivos, isso é um teto de **~80–100 GFLOP/frame**.

**A conclusão que fecha o espectro de opções (base da tabela 2.3).** A distância entre o que cabe em tempo real (~10² GFLOP/frame) e o que o Real-ESRGAN custa (~10³·⁴ GFLOP/frame) é de **mais de uma ordem de grandeza**. Não existe "modelo intermediário" que atravesse esse vão nesta GPU: qualquer rede que caiba em 41 ms/frame já está, por construção, na classe de tamanho do Anime4K/ArtCNN/FSRCNN — não na classe do Real-ESRGAN. **O meio-termo não existe neste hardware; ele existe no hardware futuro** (Bloco B).

**Por que "just-in-time por segmento HLS" não resolve.** Processar sob demanda com um buffer à frente não cria compute — só permite gastar uma espera inicial. Com `r` = razão de throughput (segundos de vídeo processados por segundo de relógio) e `D` = duração do episódio, a espera mínima para nunca travar é:

```
espera = D × (1 − r) / r
```

- `r = 0,04` (Real-ESRGAN, ~1 fps sobre conteúdo a 24fps) → espera ≈ **9,6 h**. Inútil.
- `r = 0,5` → espera ≈ 24 min, mas `r = 0,5` significa 12 fps ≈ 83 ms/frame ≈ ~170 GFLOP/frame: apenas ~2x acima do orçamento em tempo real. Ganho de qualidade marginal, e ainda paga encode H.264 + segmentação + disco + máquina de estados.
- `r ≥ 1` → espera zero, mas aí é exatamente o orçamento em tempo real — e nesse caso não há motivo para fazer no servidor.

**E o argumento decisivo:** o dispositivo de reprodução **é a mesma máquina** que hospeda o backend (uso pessoal, single-user, uma máquina física — seção 6). Qualquer processamento server-side disputa **a mesma RX 580** que o shader client-side usaria, e ainda paga encode, segmentação e I/O por cima. Server-side JIT é, neste cenário, **estritamente pior** que client-side em tempo real — só ganharia se a reprodução acontecesse em outro dispositivo sem GPU capaz (TV, celular), o que já está fora de escopo (seção 1).

### Bloco B — pós-gatilho (RTX 5060 Ti 16GB ou superior; estimativa, não medição)

Esta conta só passa a valer **quando** a troca de GPU acontecer (seção 12). Enquanto isso não acontece, ela é planejamento antecipado, não orçamento vigente — o Bloco A é o que rege o sistema hoje. Há aqui um ganho de confiabilidade sobre uma extrapolação ingênua: existe **medição pública** deste modelo, nesta resolução, neste runtime, em outras GPUs — não só aritmética.

**Custo do modelo, por frame.** Mesmo modelo do Bloco A, mesma independência do fator de escala: 1 conv 3→64 (~7 GFLOP) + 16 convs 64→64 (~153 GFLOP cada) + 1 conv 64→48 (~115 GFLOP) ≈ **~2,57 TFLOP/frame**. Consequência que vale fixar: **mudar o fator de escala quase não muda o custo** — um modelo 2x nativo custa praticamente o mesmo que o 4x, porque só a última conv difere.

**Âncoras medidas** ([vs-mlrt](https://github.com/AmusementClub/vs-mlrt/wiki), TensorRT FP16, modelo `real-esrgan (v2/v3, xsx2)` — mesma `SRVGGNetCompact` 64/16, diferindo só no pixel-shuffle —, entrada 1920×1080):

| GPU | FP32 pico | Banda | TRT FP16, 1 stream | TRT FP16, 3 streams | TFLOP/s efetivos |
|---|---|---|---|---|---|
| RTX 3090 | 35,6 TFLOPS | 936 GB/s | 16,65 fps | ~22,5 fps | ~58 |
| RTX 4090 | 82,6 TFLOPS | 1008 GB/s | 17,06 fps | ~38,3 fps | ~98 |

Dois fatos que essas medições entregam de graça:

- **Multi-stream não é detalhe.** De 1 para 3 streams o 4090 mais que dobra (17 → 38 fps). A 1 stream a rede é limitada por latência de lançamento de kernel e ida-e-volta à memória, não por compute. Isso será item de calibração da Fase 0 pós-gatilho, e **não** conflitaria com a decisão de "concorrência 1" da tabela 2.1: aquilo é um *job* por vez; isto são streams de inferência dentro do mesmo job.
- **TensorRT vs. as alternativas CUDA, no mesmo 3090:** TRT 16,65 fps · ORT-CUDA NHWC 11,2 · ORT-CUDA 8,99 · PyTorch-CUDA ~3,4. A rota importa quase tanto quanto a GPU.

**Especificações da GPU planejada** (GB206-300-A1, Blackwell, TSMC 4N, 21,9 bi de transistores): 4608 CUDA cores, **144 tensor cores de 5ª geração**, boost 2572 MHz → **23,7 TFLOPS FP32** (4608 × 2 × 2,572 GHz). Tensor FP16 denso na ordem de **~190 TFLOPS** (a marca "759 AI TOPS" da NVIDIA é FP4 com sparsity; INT8 denso ≈ 190 TOPS). 16 GB GDDR7, 128 bits a 28 Gbps → **448 GB/s**. TDP 180 W.

**A extrapolação, e por que ela seria conservadora.** Em compute a 5060 Ti ficaria confortável — ~190 TFLOPS FP16 densos, entre o 3090 e o 4090. O que ela **não** tem é banda: 448 GB/s são ~48% do 3090 e ~44% do 4090. E este workload é pesado em banda: um mapa de ativação de 64 canais a 1080p em FP16 ocupa **~265 MB**, muito além dos 32 MB de L2 do GB206 — cada uma das 16 convs do corpo faz round-trip à VRAM. Escalando as âncoras por banda (o fator que limita), não por FLOPS:

> 58 × 0,48 ≈ 28 TFLOP/s · 98 × 0,44 ≈ 43 TFLOP/s → **~11–17 fps**, ordem de **~15 fps**.
>
> Episódio de 24 min ≈ 34.500 frames → **~35–55 min de GPU**, centro em **~40 min**.

Contra as **10–16 h** do Bloco A, isso seria um ganho de **~15–25x**. E é o que fecharia a decisão de runtime pós-gatilho da tabela 2.1: pela mesma conta, **ncnn-Vulkan na mesma placa** não usaria tensor core algum e rodaria a ~30–50% dos 23,7 TFLOPS FP32 → ~7–12 TFLOP/s → ~2,8–4,6 fps → **~2,1–3,4 h/episódio**.

**A consequência que justificaria pagar o custo do TensorRT.** Não seria "3h vira 40min" — seria o que 40min habilitaria. Aplicando a mesma fórmula de head-start do Bloco A, com `r` = segundos de vídeo processados por segundo de relógio e `D` = 24 min:

| Rota | fps | `r` | `espera = D × (1−r)/r` |
|---|---|---|---|
| TensorRT FP16 | ~15 | ~0,63 | **~14 min** |
| ncnn-Vulkan | ~3,5 | ~0,15 | ~2,3 h |

Como o pipeline em lote emitiria segmentos comitados **em ordem** (chunking, 3C), 14 minutos de head start significariam que o lote passaria a ser assistível quase ao vivo — degrau extra do modelo híbrido (Fase 5b, seção 10). A ~2,3 h, não. É essa diferença qualitativa, não o relógio, que fecharia a decisão de runtime.

**O que custaria a rota TensorRT** (registrado para não parecer escolha gratuita): CUDA + TensorRT instalados, export para ONNX, e um *build de engine* específico por GPU/driver/resolução, que leva minutos e precisaria ser cacheado e **invalidado quando o driver mudar**. Em troca, some o spawn de um processo CLI por chunk: a engine ficaria residente no worker. Risco e fallback na seção 9; validação empírica seria item (g) da Fase 0 pós-gatilho.

> **Estes números são estimativa, não medição** — âncoras medidas em *outras* GPUs, extrapoladas por banda, para uma GPU que ainda não foi comprada. A Fase 0 pós-gatilho os substituiria por medição nesta placa. A conclusão estrutural (ordem de dezenas de minutos, não de horas) aguentaria erro de 2x; o número exato, não.

---

## 2.3 Opções avaliadas e descartadas

| # | Opção | Onde roda | Espera antes de assistir | Qualidade esperada | Veredito |
|---|---|---|---|---|---|
| A | Real-ESRGAN em lote, 4x→1080p supersampled (3C) | Worker/GPU | ~10–16 h/episódio **nesta GPU** (Bloco A, 2.2) | Máxima | **Descartado no hardware atual.** Reaberto pelo gatilho de hardware (seção 12), não por software. Na RTX 5060 Ti a espera estimada cai para ~40 min — Bloco B, 2.2 |
| B | Real-ESRGAN just-in-time por segmento HLS | Worker/GPU | ~9,6 h de *head start* (fórmula do Bloco A) | Máxima | **Descartado.** JIT não cria compute; a espera continua |
| C | Modelo SR leve server-side (FSRCNN/ESPCN/compact) JIT | Worker/GPU | minutos a horas, conforme `r` | Média | **Descartado.** Disputa a mesma GPU do cliente, soma encode + disco + máquina de estados, para um ganho de ~2x sobre o que o cliente já faz de graça |
| D | Reduzir alvo (2x direto / 1440p) no pipeline em lote | Worker/GPU | ainda horas | Alta | **Descartado.** `animevideov3` roda na resolução de *entrada*; mudar o fator de escala quase não muda o custo. Só reduzir a entrada reduziria — e aí se perde o ponto |
| E | **Anime4K CNN em WebGPU, client-side, sobre o `<video>`** | Navegador (mesma RX 580) | **Zero** | CNN em tempo real, ≥ baseline do Slime Shell Web | **✅ ESCOLHIDO** — seção 3E |
| F | FSR 1.0 (EASU + RCAS) | Navegador | Zero | Heurística espacial (Lanczos adaptativo); pior que CNN para *line art* | **Descartado como upscaler principal.** `RCAS` fica disponível como passe opcional de *sharpen* final, custo ~1 ms |
| G | FSR 2 / 3 / 4 | — | — | — | **Inaplicável.** São upscalers *temporais*: exigem motion vectors e depth buffer de uma engine 3D, que vídeo não tem. FSR 4 ainda exige RDNA4 |
| H | WebSR (`sb2702/websr`) | Navegador | Zero | Subconjunto do Anime4K (`cnn-2x-s/m/l`), retreinado | **Descartado.** Menos completo que a opção E e auto-declarado pré-produção ("shouldn't be used yet in production") |
| I | Portar ArtCNN (`C4F16`/`C4F32`) para WGSL | Navegador | Zero | Potencialmente **melhor** que Anime4K por FLOP | **Não agora.** Não existe porte WebGPU público; é trabalho de pesquisa. Fica como *stretch* pós-MVP (Fase 5) |
| J | Manter MPV + Anime4K nativo (status quo) | MPV local | Zero | Baseline | **Descartado como parte do produto.** Serve só de referência de medição externa (S1, 9.1) — o projeto não integra nem expõe um caminho de MPV ao usuário |

**Decisão vigente hoje: opção E**, com F (RCAS) como knob opcional e I como evolução. **Opção A é o alvo pós-gatilho** (seção 12); B, C e D permanecem descartadas mesmo depois da troca de GPU — os argumentos que as eliminam (disputa de hardware, custo por FLOP do modelo) não dependem de qual GPU está instalada.

**Biblioteca escolhida: [`anime4k-webgpu`](https://github.com/Anime4KWebBoost/Anime4K-WebGPU)** (npm: `anime4k-webgpu`). Implementa os presets A/B/C/AA/BB/CA e as famílias completas de Restore (`CNNM`…`CNNUL`, `GANUUL`) e Upscale (`CNNx2M`…`CNNx2UL`, `GANx3L`, `GANx4UUL`), com um wrapper `render(video, canvas, pipelineBuilder)` além do acesso direto aos pipelines. Cobre o preset exato que o `player.py` do Slime Shell Web usa hoje — o que tornou a comparação com o baseline direta, e não uma aposta (seção 11).

**Por que não escrever os shaders do zero** (Escada de Minimalismo, passo 2/4): os `.wgsl` são porte mecânico dos `.glsl` do Anime4K; reimplementar seria reescrever ~30 shaders com pesos embutidos, sem ganho. Riscos de dependência tratados na seção 9.

---

## 3. Arquitetura do Sistema e Fluxo de Trabalho

**Fluxo do modo em tempo real (hoje)** — o backend é baixador, empacotador e catálogo; a qualidade de imagem nasce inteira no player:

```
[Painel admin] URL do episódio
      │
      ▼
[Extrator + bypass]  ← 3A
      │  baixa o arquivo na maior resolução da fonte (tipicamente 1080p)
      ▼
[validando_fonte]  ffprobe: decodifica? duração bate? codec é H.264/AAC?
      │
      ├─ sim ──► [empacotando_hls]  ffmpeg -c copy  → segundos
      └─ não ──► [transcodificando] x264 CPU 1080p  → ~5–12 min (5700X), só neste caso
      │
      ▼
[pronto]  master.m3u8 (rendition `1080p`) + segmentos, em MEDIA_ROOT
      │
      ▼
[Navegador]  hls.js → MSE → <video> (oculto)
                              │  requestVideoFrameCallback
                              ▼
                        [WebGPU: Anime4K CNN]  ← a "IA", por frame (3E)
                              │
                              ▼
                        <canvas> na resolução do display
```

Tempo entre "colar a URL" e "poder assistir" = tempo de download + segundos de empacotamento — minutos, não horas, para um episódio de ~0,5–1,5 GB. **No modo em lote (pós-gatilho), o mesmo fluxo ganha um ramo extra** entre `validando_fonte` e `pronto` — extração de frames, upscaling, remontagem (3C) — que produz a rendition adicional `1080p_ia` no mesmo manifesto, sem substituir o ramo acima.

### A. Módulo Extrator e Bypass — projetado para não exigir supervisão
Hoje, no Slime Shell Web, o bypass roda no caminho síncrono: você precisa saber na hora se funcionou. A ideia aqui é inverter isso — o extrator roda em segundo plano, raramente precisa de você e, quando precisa, avisa sem travar o resto da fila. Isso não se resolve "resolvendo captcha melhor" — se resolve reduzindo quantas vezes o caminho frágil (browser completo) precisa rodar, e tornando as falhas assíncronas em vez de bloqueantes:

1. **Cache de sessão/cookies por site** — depois que o DrissionPage resolve o desafio do Cloudflare uma vez, os cookies resultantes (`cf_clearance` + sessão) são salvos por domínio com uma expiração estimada. As próximas extrações do mesmo site tentam primeiro um cliente HTTP leve (Cloudscraper/requests) reaproveitando esses cookies, e só sobem o navegador completo — mais lento e mais sujeito a travar — se a sessão cacheada for rejeitada. Isso reduz bastante a frequência com que o caminho frágil precisa rodar: a maioria das extrações vira uma requisição HTTP simples.
2. **Retry com backoff + circuit breaker por site** — falha não gera retry imediato (parece mais bot ainda); usa backoff crescente (ex: 30s → 2min → 10min, até N tentativas). Se um site falhar M vezes seguidas, ele é marcado "degradado" e entra em cooldown (ex: 1h) sem novas tentativas automáticas — evita martelar um site que já está bloqueando ativamente, o que só pioraria a detecção.
3. **Fila não-bloqueante** — um job que falha na extração não trava os outros. Ele vai para `aguardando_intervencao` (ou `falhou_extracao` enquanto ainda há backoff pendente) e o worker segue para o próximo item. Uma fila de "5 animes pra processar de madrugada" nunca fica presa atrás de 1 que deu problema.
4. **Notificação na página, não vigilância ativa** — via o WebSocket já previsto (`/ws/admin`, seção 5), o painel mostra um toast em tempo real se a aba estiver aberta, e um indicador persistente ("2 jobs precisam de atenção") sempre que o painel for aberto, mesmo que o problema tenha ocorrido horas antes com a aba fechada. Não precisa estar olhando no momento em que acontece — só conferir quando for conveniente.

Isso resolve diretamente a questão de "não querer saber se conseguiu ou se precisa de mim": a maioria das extrações usa sessão cacheada e nem chega perto de precisar de intervenção; quando algo trava de verdade (captcha que a automação não resolve), aparece numa lista ao abrir o painel, resolve-se manualmente só aquele item, e o resto da fila continua rodando.

Deliberadamente fora de escopo: serviços de resolução automática de captcha (2captcha, anti-captcha etc.) — não são necessários aqui, porque o fluxo acima já trata o caso raro de captcha como notificação assíncrona, não como algo a vencer algoritmicamente.

- **Entrada: clique, não URL colada.** O ponto de entrada é a galeria de capas do próprio Slime Studio (dados do `Anime`, já cadastrado via busca-e-confirma no AniList — 3F) → página do anime, que lista `total_episodios_anilist` posições (prontas ou não) → clicar numa posição ainda não capturada dispara a resolução automática de fonte (abaixo) e cria o `Job`. Colar uma URL manualmente continua existindo, mas como caminho de depuração/fallback (mesmo modo "arquivo local" da Fase 1, roadmap 10) — não é mais o fluxo normal.
- Extração: localiza a página do episódio, intercepta tráfego de rede, captura link direto do vídeo original (idealmente a maior resolução disponível na fonte, tipicamente 1080p).
- Adapters por site seguem Strategy Pattern (`backend/extractors/base.py` + uma classe por site, ex. `animefire.py`, `animesdrive.py`), portados/adaptados do projeto original — mas aqui o extrator **baixa** o arquivo em vez de servir a URL direta para o player, cada adapter ganha a camada de cache/retry/circuit breaker acima em vez de reimplementar isso por site, e o contrato de `base.py` ganha busca por título (`search`) e listagem de episódios (`get_episodes`) — não só "extrai dado uma URL de episódio já conhecida". É o mesmo contrato que o `AnimeProvider`/`orchestrator.py` do Slime Shell Web já implementa; a mudança aqui é só onde o resultado da busca é usado (abaixo).

**Resolução automática de fonte, com fallback entre sites.** Reaproveita o padrão do Slime Shell Web (`orchestrator.py`: busca em paralelo nos providers, cada um retorna candidatos, você clica no certo) com uma diferença que fecha a lacuna que lá não existia: aqui o resultado fica **cacheado por anime**, não repetido a cada sessão.

1. **Primeira captura de um anime**: o backend busca `Anime.titulo` no site padrão (AnimeFire). Busca com exatamente um candidato plausível resolve direto, sem perguntar nada. Mais de um candidato (nome ambíguo, remake, etc.) mostra a lista curta pra você confirmar uma vez — mesmo padrão de UI do busca-e-confirma do AniList (3F), mesmo motivo: errar aqui contamina os episódios seguintes do mesmo anime.
2. **Site padrão sem o anime, ou em cooldown**: se a busca não achar nada, ou o site já estiver degradado (`EstadoSite`, circuit breaker do item 2 acima — pulado direto, sem gastar tentativa nele), tenta o próximo site da lista de prioridade (ex.: AnimeFire → AnimesDrive → ...), com a mesma lógica de busca-e-confirma se necessário.
3. **Cache do mapeamento**: resolvido uma vez (automático ou confirmado por você), o par `(anime_id, site)` fica salvo em `FonteAnime` (seção 4), junto com o identificador do anime naquele site. Todo episódio seguinte do mesmo anime resolve direto dali, sem nova busca. É a melhoria concreta sobre o Slime Shell Web: lá a busca por nome rodava sempre em tempo real, sem cache algum (nem de sessão de busca); aqui roda uma vez por anime.
4. **Falha depois de resolvido**: se um episódio falhar de extração (`falhou_extracao`) num site já mapeado — página mudou, vídeo saiu do ar, etc. — o sistema tenta automaticamente o próximo site da lista de prioridade pra aquele anime, repetindo a resolução ali (confirmação só se ambígua), antes de desistir. Só cai em `aguardando_intervencao` depois de esgotar todos os sites da lista.

### B. Fila de Processamento Assíncrono (Worker Nativo)
- Worker roda como **processo separado** da API (decisão em 2.1), em background com `asyncio`, concorrência estrita de **um vídeo por vez**.
- **Por que dois processos — fundamento que vale nos dois modos, não só um.** Hoje, sem upscaling em lote, um job raramente leva mais que minutos — mas o motor de bypass sobe um **Chromium completo via DrissionPage**, que trava, vaza memória e pode ser morto pelo OOM killer (16GB RAM, `swap=0`); isso não pode viver dentro do processo que serve o player e o WebSocket. Pós-gatilho, soma-se o motivo original da topologia: um job de upscaling em lote pode levar dezenas de minutos (2.2, Bloco B), e reiniciar a API pra testar algo não pode derrubar um job em andamento. Os dois motivos coexistem; nenhum dos dois sozinho seria suficiente para justificar a separação em todos os cenários, mas juntos a tornam inequívoca nos dois modos.
- Estado de cada job é persistido em banco relacional (não em memória) — ver seção 5 — para que um crash do processo não perca progresso.
- **Estados — hoje**: `na_fila → baixando → validando_fonte → [transcodificando] → empacotando_hls → pronto`, mais `falhou_extracao` e `aguardando_intervencao` (ver 3A: uma falha de extração não bloqueia os demais jobs da fila), `falhou` genérico com `etapa_atual`+`erro_msg` localizando onde, `cancelando`/`cancelado` (cancelamento cooperativo, abaixo). `transcodificando` só entra se `ffprobe` reprovar o `-c copy` do empacotamento (3D).
- **Estados — pós-gatilho, ganham o ramo de upscaling**: entre `validando_fonte` e `empacotando_hls` entram `extraindo_frames → upscaling → remontando` (3C), e some-se `pausado` — reservado para uma eventual pausa automática por limite de tempo contínuo de GPU (seção 9), ainda sem gatilho/endpoint definido. Os campos `chunk_atual`/`total_chunks` (seção 4) já existem no schema hoje mas ficam sem uso até este ramo entrar em produção — não removê-los.
- **Validação da fonte antes da GPU**: depois do download, o job passa por `validando_fonte` — `ffprobe` confere que o arquivo decodifica e que a duração bate aproximadamente com o esperado, antes de entrar na fila de upscaling. GPU é o recurso caro aqui; falhar nesta etapa é muito mais barato que falhar depois de horas de upscaling. O download suporta retomada por HTTP Range e reusa os mesmos cookies/`Referer` da sessão de bypass (seção 3A).
- **Claim atômico de job**: o worker reivindica um job com `UPDATE job SET status='baixando', worker_id=? WHERE id=? AND status='na_fila'`, conferindo `rowcount` — nunca um `SELECT` seguido de `UPDATE`. Evita que duas instâncias do worker rodando por engano façam claim do mesmo job; complementado por um lock de instância única no boot do worker (lockfile com PID, ou tabela `WorkerLock` de uma linha).
- **Cancelamento cooperativo**: a API não consegue matar o subprocesso do worker só via a tabela `Job` (decisão 2.1) — cancelar é pedir, não forçar. `POST /jobs/{id}/cancelar` (seção 5) seta `cancelamento_solicitado=1` e status `cancelando`; o worker roda o polling dessa flag numa corrotina separada da corrotina do pipeline, pra observar o pedido no meio de um chunk (não só entre chunks) — senão a latência de cancelamento é um chunk inteiro.

### C. Pipeline de Tratamento de Vídeo (o motor de upscaling)

> **Esta subseção inteira é pós-gatilho.** Descreve o pipeline em lote com Real-ESRGAN — condicionado à troca de GPU (seção 12) e não implementado antes disso (regra em 12.4). O conteúdo técnico abaixo é planejamento antecipado, preservado integralmente para que a rodada de replanejamento do gatilho (12.2) comece com o raciocínio pronto, não com a página em branco.

**Atenção ao disco:** extrair todos os frames de um episódio inteiro antes de começar o upscaling é o erro mais comum aqui e pode estourar o disco. Um episódio de ~24 min a ~24fps tem ~34.500 frames; em PNG lossless a 1080p isso facilmente passa de dezenas de GB só na entrada, e os frames de **saída** em 4x (7680×4320) ocupam 16x mais área de pixels cada (4x em cada dimensão) — o total chega à ordem de **~1TB** por episódio se todo o episódio for mantido em disco simultaneamente.

> **Este número não mudou com o alvo passando de 4K para 1080p, e é um erro fácil supor que sim.** O pico de scratch é determinado pelos frames *intermediários*, que saem do modelo em 7680×4320 porque o `animevideov3` escala 4x — não pela resolução do entregável, que só é aplicada no downscale da remontagem. Entregar 1080p em vez de 4K não economiza **nada** de scratch. O que economizaria é **trocar o modelo por um 2x nativo** (`RealESRGANv2-animevideo-xsx2`): aí os intermediários caem para 3840×2160, ou seja, **4x menos scratch pelo mesmo custo de GPU** (seção 2.2: o custo roda na resolução de *entrada*, o fator de escala é quase de graça). Esse trade-off — 16 amostras/pixel contra 4, ao preço de 4x de disco — é exatamente o que o item de comparação da Fase 0 tem de decidir agora, e ele deixou de ser acadêmico: com alvo 4K a escolha era entre 4 e 1 amostra/pixel; com alvo 1080p é entre 16 e 4.

Duas mitigações, recomendo as duas:

1. **Processar em chunks** (ex. blocos de 500–1000 frames): extrai um chunk → upscala o chunk → codifica o chunk como um **segmento de vídeo intermediário próprio** (nunca fica em frames soltos) → apaga os frames (originais e upscalados) daquele chunk → passa para o próximo. Mantém o pico de disco limitado a poucos GB por vez, e permite retomar do último segmento concluído se o worker cair no meio (o estado do chunk também fica no banco — ver "Remontagem" abaixo para como os segmentos viram o episódio final).
2. **Formato intermediário mais leve**: gravar os frames de saída dos estágios intermediários em WebP ou JPG, não em PNG lossless (isso vale para o entregável **nenhum** — ver escolha de codec abaixo). PNG não traz benefício de qualidade perceptível numa etapa que será recodificada em seguida, e custa disco caro. Nota sobre a rota TensorRT: com a engine residente no worker, existe a opção de **nunca escrever os frames upscalados em disco** — passar o tensor de saída direto para o `stdin` do `ffmpeg` do passo 3, via pipe raw. Isso eliminaria metade do churn de arquivos pequenos de uma vez. Vale medir na Fase 0 antes de assumir que é melhor: o pipe serializa GPU e encode, enquanto escrever em disco os desacopla. É otimização candidata, não decisão tomada.

**Separação de paths por durabilidade e filesystem** (ver seção 6 para o porquê do filesystem importar): `MEDIA_ROOT` guarda os arquivos grandes e duráveis (`raw/`, `hls/`) e vive no mount NTFS onde já está `media/`; um novo `SCRATCH_ROOT` guarda só o pico de frames de um chunk em voo e deve ficar em **ext4 ou tmpfs**, nunca no mount NTFS — `ntfs-3g`/FUSE é lento demais e não garante rename atômico para as ~69 mil criações/deleções de arquivo pequeno que um episódio gera (34.500 frames de entrada + 34.500 de saída). Com formato intermediário lossy e chunk de 500 frames, `SCRATCH_ROOT` em tmpfs é viável (pico de ~1–2,5GB) e elimina esse gargalo de I/O — validar no PoC da Fase 0 (comparar `ntfs-3g` vs ext4 vs tmpfs nos alvos reais). **Ressalva se `SCRATCH_ROOT` for tmpfs:** isso vale só para os frames soltos de um chunk em voo, que podem ser refeitos a qualquer momento — nunca para os segmentos de vídeo já comitados (passo 3 abaixo), que precisam sobreviver a um reboot completo (a seção 6 trata reboot pro Windows com job em andamento como cenário esperado, e tmpfs some inteiro num reboot). Segmentos comitados sempre são promovidos para um diretório em ext4, mesmo quando `SCRATCH_ROOT` aponta pra tmpfs.

**Resolução final alvo: 1920×1080.** Não 4K, não 8K. O modelo `realesr-animevideov3` escala 4x — partindo de 1080p, a saída bruta é 7680×4320 (8K). O passo de remontagem (abaixo) faz o downscale direto para **1920×1080**, **por chunk** (não no final).

Por que não parar em 4K, já que o pipeline chega lá: **porque a tela não passa de 1920×1080** (confirmado — seção 9.1/S2). Uma rendition 3840×2160 seria decodificada com esforço, transferida com 4x o bitrate, e então descartada pelo scaler do próprio monitor. Fazer o downscale no worker, uma vez, com um filtro bom (Lanczos), é estritamente melhor que deixar o monitor fazer em tempo real, toda vez, com o filtro que ele tiver.

**E o argumento de supersampling fica mais forte, não mais fraco.** Ele já era a justificativa para o 4x+downscale; a mudança de alvo só aumenta a razão:

| | Alvo antigo (4K) | Alvo novo (1080p) |
|---|---|---|
| Saída do modelo | 7680×4320 | 7680×4320 |
| Downscale | 2x linear | **4x linear** |
| Amostras por pixel entregue | 4 | **16** |

Ou seja: cada pixel de 1080p entregue passa a ser a média de 16 pixels reconstruídos pela rede. É antialiasing e supressão de ruído/alucinação de graça — o downscale agressivo perdoa justamente o tipo de erro que um upscaler por IA comete (detalhe inventado em área plana). Não é desperdício de compute: o custo de GPU **é o mesmo** com qualquer fator de escala (seção 2.2), então os 16x saem grátis em tempo — só custam scratch.

**A ressalva honesta:** 16 amostras/pixel pode passar do ponto de retorno decrescente e virar suavização. A comparação da Fase 0 contra o **2x nativo** (`xsx2` → 3840×2160 → downscale 2x → 4 amostras/pixel, com 4x menos scratch) deixa de ser uma curiosidade e vira a decisão central do PoC. Comparar também com `realcugan`.

**Codec do entregável: H.264 (x264, em CPU), fixo — não HEVC.** HEVC via MSE não toca em Chrome/Firefox no Linux, e é justamente nesses navegadores que o `hls.js` do próprio painel roda — escolher HEVC quebraria o player que o projeto depende. HEVC fica como otimização futura, só se o navegador alvo provar suporte real (item de go/no-go da Fase 0).

**Encode planejado em CPU (x264, Ryzen 7 5700X) — o motivo muda de peso quando a GPU trocar.** Se este pipeline rodasse na GPU **atual** (RX 580), usar `h264_vaapi`/VCE roubaria a mesma GPU que o upscaler já usaria no limite — mas isso é hipotético, porque o pipeline inteiro está condicionado ao gatilho (banner no topo desta seção). Na RTX 5060 Ti planejada isso **deixaria de valer** — o NVENC é bloco de hardware dedicado e não consumiria SM nem tensor core, então `h264_nvenc` rodaria de graça em paralelo à inferência. Mesmo assim, a decisão de manter x264 fica de pé por dois motivos independentes da GPU: (1) x264 entrega melhor qualidade por bit que o NVENC no mesmo bitrate, e este é um acervo que se assiste mais de uma vez; (2) não haveria gargalo a resolver — x264 a **1080p** num 5700X faz ~100+ fps, contra os ~15 fps estimados de GPU (Bloco B, 2.2), então a CPU ficaria ociosa esperando a GPU e encodar nela é usar recurso que sobra. Isso é consequência direta do alvo ter caído para 1080p: encodar **4K** em x264 daria ~25 fps e a folga desapareceria. `h264_nvenc` fica registrado como alavanca disponível caso a Fase 0 pós-gatilho mostre o encode virando gargalo do pipeline em chunks.

Etapas via linha de comando, executadas **por chunk**:
1. **Separação**: uma única vez no início do episódio, `ffmpeg` extrai o áudio inteiro (`-vn -c:a copy`) — nunca por chunk, pra não precisar remuxar áudio fatiado depois. A extração de frames roda por chunk, forçando CFR (`-fps_mode cfr` no fps real obtido via `ffprobe`, nunca assumido) — fonte VFR quebra a contagem de frames por chunk e desincroniza áudio na montagem final.
2. **Upscaling (TensorRT FP16)**: engine TensorRT construída a partir do ONNX do `realesr-animevideov3`, **residente no processo do worker** (não um binário CLI por chunk), consumindo os frames do chunk atual. Calibrar o número de *streams* de inferência — a medição da seção 2.2 mostra ganho de até ~2x de 1 para 3 streams. **Tiling deixa de ser obrigatório**: com 16 GB de VRAM e ~1 GB de pico medido para este modelo a 1080p (2.2), o frame inteiro cabe com folga, e rodar sem tile elimina tanto a recomputação de bordas quanto o risco de costura visível. Timeout por chunk + retry **no nível do chunk** (com máximo de tentativas): o modo de falha específico de Polaris (`amdgpu: GPU reset` sob RADV) sai de cena, mas o genérico não — um Xid/TDR do driver NVIDIA, ou um OOM de VRAM com streams demais, ainda mata o processo sem estado de falha explícito, e retry no nível do job jogaria fora progresso já comitado. Capturar exit code e contexto em `erro_msg`. Rota de fallback, se a Fase 0(g) reprovar o TensorRT: `realesrgan-ncnn-vulkan` com o mesmo modelo, ~4x mais lento (2.2), sem nenhuma outra mudança no pipeline — é troca de uma etapa, não de arquitetura.
3. **Remontagem do chunk**: `ffmpeg` reconstrói um segmento de vídeo a partir dos frames upscalados do chunk, aplicando o downscale para **1920×1080** (`-vf scale=1920:1080:flags=lanczos` — o filtro importa: é ele que transforma o 4x em supersampling em vez de decimação) e codificando em H.264 com **parâmetros de encode idênticos em todos os chunks** (senão o demuxer `concat` do ffmpeg falha ou gera drift). O segmento é escrito em nome temporário e promovido com `os.replace()` para um diretório em ext4 (nunca tmpfs, mesmo que `SCRATCH_ROOT` esteja em tmpfs — ver ressalva acima) — atômico em ext4, não confiável sob `ntfs-3g` (mais um motivo pro `SCRATCH_ROOT` ficar fora do NTFS) — só ao concluir.
4. **Montagem final**: depois do último chunk, o `ffmpeg` concatena os segmentos via `concat` demuxer e mux com o áudio extraído no passo 1. Validação por `ffprobe` da contagem de frames de cada segmento antes do concat pega falha parcial de chunk cedo. Retomada = maior segmento comitado; no boot, o worker varre e apaga scratch de chunk em voo (não comitado) antes de retomar.

**A validar no PoC pós-gatilho (item previsto na seção 10)**: fps real de upscaling na RTX 5060 Ti com `realesr-animevideov3` via TensorRT FP16. A estimativa do Bloco B (2.2) é de **~15 fps (faixa 11–17)**, ou seja **~35–55 min por episódio de 24 min** — dezenas de minutos, não horas, **se confirmada**. Se confirmada, muda as expectativas de UX para esse modo: não seria mais "fila overnight e volte amanhã", seria "enfileirou, dá tempo de jantar". ETA visível continuaria necessário; barra travada por horas, não.

**O chunking permanece obrigatório — reexaminado, não herdado.** A velocidade nova poderia sugerir que dá pra processar o episódio inteiro de uma vez. Não dá, por três motivos independentes, e o primeiro sozinho já basta:

1. **Disco.** O pico de scratch de um episódio inteiro continua na ordem de ~1TB (ou ~250GB com um modelo 2x). Não existe esse disco nesta máquina. Isso não tem relação nenhuma com a velocidade da GPU.
2. **Retomada.** Perder 40 min de progresso ainda é pior que perder 40 s.
3. **O mais interessante:** é o chunking que faria os segmentos serem comitados **em ordem**, e é isso que habilitaria começar a assistir ~14 min depois de enfileirar, com o job ainda rodando (a conta de head-start no Bloco B, 2.2). Sem chunking, esse ganho — o mais relevante que a GPU nova traria — simplesmente não existiria. **Uma GPU mais rápida tornaria o chunking mais valioso, não menos.**

### D. Transcodificação para Web (HLS)

**Hoje**, o vídeo baixado só é validado e re-empacotado — `.ts` de 5–10s + manifesto `.m3u8` (`ffmpeg -hls_time 8 -hls_playlist_type vod`), com `-c copy` sempre que `ffprobe` (`validando_fonte`, 3B) confirmar H.264/AAC; senão, transcode x264 em CPU (1080p, ~5–12 min no 5700X, só neste caso). **Master manifest desde o dia 1, mesmo com uma variante só.** Custo hoje: uma linha a mais no comando `ffmpeg`. Benefício: quando o modo em lote entrar em produção (pós-gatilho, seção 12) e passar a produzir a rendition `1080p_ia`, ela é **adicionada ao master existente** — mesmo `hls_path`, mesma URL, mesmo player, sem migrar catálogo. É a decisão mais barata desta seção e a que mais economiza retrabalho depois.

**Sem ladder multi-bitrate hoje.** Uma variante só (`1080p`), servida por localhost/LAN, para um usuário — não há rede lenta a acomodar, e uma segunda qualidade custaria um encode inteiro que não existiria de outra forma. Fica registrado como não implementado agora, não como decisão fechada para sempre: pós-gatilho a conta muda, porque o encode extra deixa de ser um custo isolado.

**Ladder pós-gatilho: duas variantes, teto em 1080p.**

| Rendition | Origem | Papel |
|---|---|---|
| `1080p_ia` | saída do pipeline em lote (4x + downscale Lanczos, 3C) | **O produto do modo em lote.** Bitrate alto (~8–12 Mbps) |
| `720p` | downscale da `1080p_ia` | Fallback de rede fraca (~3 Mbps) |

Três decisões embutidas aí, cada uma com o porquê:

- **Por que passa a valer a pena ter ladder, mesmo sendo single-user em localhost/LAN.** Uma vez que o modo em lote já esteja encodando por chunk, acrescentar um encode a 720p sobre um frame já decodificado em memória é ruído perto do custo de GPU. Com Wi-Fi no meio, um stream de 10 Mbps ainda engasga; uma variante barata que evita rebuffer paga por si.
- **Por que parar em duas.** Múltiplas variantes de 1080p em bitrates diferentes seriam versões piores do mesmo produto para um único espectador que não muda de rede no meio do episódio. 720p já cobre o caso degradado — é onde a Escada de Minimalismo manda parar.
- **Por que a `720p` viria do `1080p_ia`, e não do original.** Derivar a 720p do arquivo original faria o fallback de rede **também** ser um fallback de qualidade de imagem — cair de rede trocaria o produto por outro. Um downscale para 720p já suprime bem o tipo de erro (alucinação) que preocuparia numa derivação direta.

**Nomenclatura de rendition, fixada para os dois modos coexistirem.** **`1080p`** é a fonte re-empacotada (`-c copy`, produzida pelo modo em tempo real, hoje); **`1080p_ia`** é a saída do Real-ESRGAN (produzida pelo modo em lote, pós-gatilho). Os dois nomes existem porque, com os dois modos entregando 1080p, "1080p" sozinho seria ambíguo. No modelo híbrido as duas coexistem no mesmo manifesto e o ABR do `hls.js` escolhe por bitrate, o que naturalmente favorece a `1080p_ia` quando ela existir. **O nome gravado em `renditions_disponiveis` (seção 4) é derivado da altura real sondada via `ffprobe`, não fixado por suposição** — na prática é quase sempre `1080p`, mas se uma fonte (tipicamente no modo arquivo local, Fase 1, roadmap 10) for `720p` ou outra altura, o catálogo reflete isso em vez de gravar um valor que não corresponde ao arquivo.

**Garbage Collection.** Frames temporários do modo em lote (3C) são apagados após a etapa correspondente concluir, não só no final. O arquivo original 1080p baixado é apagado depois que o ladder está empacotado, nos dois modos **que envolvem download real** (extrator, Fase 2 em diante). **"1080p original" (arquivo baixado, descartado) e as renditions do ladder HLS (mantidas) continuam sendo coisas diferentes**; ver 3G para a política de retenção, que atua sobre o ladder pronto, não sobre o original. **No modo arquivo local (Fase 1, roadmap 10) não há GC do original**: o arquivo não foi baixado pelo sistema, é do usuário, fora de `MEDIA_ROOT` — apagá-lo destruiria a fonte e inviabilizaria o propósito de debug/fallback do modo. Essa regra de GC só se aplica a partir do momento em que existe uma cópia transitória de fato baixada pelo sistema.

**Backend e armazenamento, resumo.** Banco relacional atualizado com status `pronto` e caminho do HLS ao fim de qualquer um dos dois fluxos. Arquivos físicos (`.ts`/`.m3u8`) servidos localmente no MVP; Object Storage (S3-compatível/MinIO) fica como evolução futura (seção 10, Fase 6) — não é bloqueante para a primeira versão funcional.

### E. Player WebGPU no Cliente — onde a qualidade de imagem mora hoje

**Por que o download é obrigatório, e não é escolha estética — pré-requisito dos dois modos.** Seria tentador simplificar: apontar o `<video>` direto pra URL do CDN da fonte, como o Slime Shell Web faz, e economizar o download e o disco inteiro. **Isso quebra a solução**, nos dois modos. Ler pixels de um `<video>` para WebGPU (`importExternalTexture`/`copyExternalImageToTexture`) exige que a mídia seja *same-origin* ou sirva CORS válido. Um CDN de site de anime **não** manda `Access-Control-Allow-Origin`. O canvas fica *tainted*, e a leitura é bloqueada pelo navegador. Sem o download e o re-serviço pela própria origem, não há upscaling client-side nenhum — o modelo "baixa e re-serve" (3A/3D) não é consequência do modo em lote: é pré-requisito do modo em tempo real também, e é por isso que os dois modos convergem no mesmo backend em vez de serem sistemas separados.

**Arquitetura do player:**
- `hls.js` alimenta um `<video>` que **não é o elemento visível**. O visível é um `<canvas>` WebGPU. O `<video>` continua sendo a fonte de áudio e o relógio de reprodução.
- **Loop de render**: `video.requestVideoFrameCallback()` — dispara uma vez por frame decodificado, não por frame de tela. Evita reprocessar frames repetidos em `requestAnimationFrame` (relevante: anime é frequentemente animado "em 2s/3s").
- **Controles**: o canvas cobre os controles nativos do `<video>`, então uma barra de controles própria (play/pause, seek, volume, fullscreen, seletor de preset) deixa de ser opcional — requisito não-negociável do CLAUDE.md (§4): navegação por teclado, foco visível e ARIA não são cortáveis pela Escada de Minimalismo. Se houver necessidade de legenda soft (`<track>`), a barra caseira deixa de ser o caminho mínimo e a escolha passa a ser Vidstack — gatilho explícito, não "quando parecer complicado" (S3, seção 9.1). A implementação de referência, incluindo o que ela resolveu além do mínimo (HUD, fullscreen, glow, áudio), está em 11.4.

**Preset: a escada medida substitui a recomendação da documentação oficial.** Uma versão anterior desta especificação fixava "Mode A é o alvo, A+A contraindicado por over-sharpening a 1:1" — previsão razoável, citando a documentação do Anime4K. O protótipo (seção 11) mediu o contrário: o A+A oficial (`aa-vl`) roda com folga e é a base do preset preferido. A recomendação vigente é a escada medida em 11.3 (`aa-vl-deblur → aa-vl → a-vl → b-vl/c-vl → a-m → original`), não a hierarquia teórica antiga — que fica registrada em 11.2 como previsão razoável que a medição contrariou, não apagada.

**Painel de preset + HUD de frame time.** A documentação do Anime4K não dá recomendação de *tamanho* (M/L/VL/UL) por GPU e manda medir com o profiler — a resposta certa a "não sabemos o orçamento desta GPU" não é chutar, é entregar o seletor e a medição, como o protótipo já faz (11.4). Preferência em `localStorage` — não precisa de backend (Escada de Minimalismo, passo 1).

**Degradação automática** (pós-MVP): `video.getVideoPlaybackQuality()` expõe `droppedVideoFrames`. Se a taxa de drop cruzar um limiar, cai um degrau na escada de 11.3 e avisa. O MPV original apenas dropava frames em silêncio — isto já é um avanço concreto sobre o baseline (seção 1).

**Alvo de render: resolução do display (1920×1080, seção 9.1/S2), com espaço para supersampling deliberado.** Renderizar acima da resolução do display sem motivo joga compute fora — mas há folga de GPU medida (seção 11) para, quando configurado para isso, renderizar o canvas de saída acima da resolução física do monitor antes do downscale final feito pela própria tela (supersampling client-side). A resolução física do display continua sendo 1920×1080 sem ambiguidade; o alvo de *render* pode mirar acima disso por escolha explícita de configuração, não por engano de medição (ver a nota completa em 9.1/S2).

**Reaproveitamento visual.** Painel admin e player reaproveitam os componentes visuais (`AnimeCard`, etc.) do Slime Shell Web — validar compatibilidade com o modelo de dados novo (seção 4) antes de portar direto.

### F. Metadados e Matching (AniList/Kitsu) — como o sistema sabe "isso é o episódio 5 de Slime"
Diferente do extrator (seção 3A), isso não precisa da camada de resiliência assíncrona — é uma chamada HTTP normal e rápida a uma API pública, feita de forma síncrona no próprio fluxo de cadastro (você já está no painel digitando; esperar 1s por uma resposta não é problema).

**Nível anime — busca-e-confirma uma vez, não fuzzy-match automático.** Ao cadastrar um anime novo, o sistema busca no AniList (GraphQL, `Media(search: ...)`) pelo nome digitado e mostra uma lista curta de candidatos (capa + título + ano) pra você confirmar qual é o certo. Kitsu entra como fallback só se o AniList não achar nada (cobertura de títulos obscuros/recentes varia entre os dois). Um match errado aqui contamina sinopse, capa e numeração de *todos* os episódios futuros daquele anime — por isso vale o clique extra de confirmar uma vez, em vez de confiar num score de similaridade automático. Depois de confirmado, o `anilist_id` fica salvo em `Anime` e os próximos episódios do mesmo anime reaproveitam sem perguntar de novo. Metadados são **cacheados** na tabela `Anime`, não buscados ao vivo a cada carregamento — se o AniList cair, você continua assistindo seu próprio acervo sem depender de API externa no caminho crítico (mesma lógica de "media server pessoal" da seção 8.3).

**O problema real: numeração absoluta vs. por temporada.** É o que mais quebra esse tipo de sistema na prática — inclusive Sonarr/Plex/Jellyfin têm exatamente essa dor com anime. O site de origem às vezes lista episódios numa sequência contínua (ex: "episódio 48"), enquanto o AniList trata cada temporada como uma obra separada (ex: Slime Temporada 2 = episódios 1 a 24). Resolver isso com conversão automática genérica é complexo e frágil — a solução mais simples, e que já se encaixa no fluxo manual deste projeto, é: **cada temporada é um `Anime` separado no banco** (mesma granularidade que o AniList já usa, sem inventar uma camada de "franquia" por cima), e o número do episódio **é confirmado por você ao enfileirar o job** — o sistema pré-preenche com o número que o site mostrou, como sugestão, não como verdade absoluta. Você já sabe que está enfileirando "Slime T2 Episódio 3"; o sistema não precisa adivinhar isso a partir de um número absoluto ambíguo.

**Sanity check, não bloqueio.** Se o número informado exceder a contagem oficial de episódios da temporada no AniList, o sistema avisa mas não impede o job — pode ser contagem desatualizada, filme/OVA numerado à parte, etc. Vira mais um item do padrão de notificação da seção 3A, não uma trava rígida.

**Especiais/OVAs/filmes**: campo `tipo` no episódio (`regular / ova / especial / filme`) em vez de forçar esse conteúdo na sequência numérica principal — evita que um "episódio 0" ou "25.5" bagunce a ordenação.

**Dublado vs. legendado**: se as duas versões do mesmo episódio forem processadas, um campo `versao` evita que uma sobrescreva o caminho HLS da outra sem querer.

**Capa por episódio**: AniList raramente tem thumbnail por episódio individual (só por anime/temporada). Em vez de depender de um metadado externo que provavelmente não existe, reaproveitar a técnica do Slime Shell Web: gerar a capa via `ffmpeg` a partir de um frame do próprio vídeo já processado (ex: captura em ~20% da duração).

### G. Gestão de Armazenamento de Longo Prazo (o catálogo, não os temporários)
Diferente do GC de arquivos temporários (seção 3D, já resolvido durante o processamento), isso é sobre o crescimento do catálogo HLS **já pronto** ao longo do tempo. Base comum aos dois modos:

- Campo `assistido_em` no `Episodio` (seção 4) — timestamp da última vez que você assistiu, base pra sugestão de retenção.
- Painel admin mostra uso de disco atual (seção 7) e, quando o espaço livre cruzar um limite configurável, dispara uma notificação (reaproveitando o padrão assíncrono da seção 3A/F) sugerindo candidatos a limpar, priorizando episódios assistidos há mais tempo.
- **Nunca deletar automaticamente sem confirmação** — é sua coleção pessoal; mesma filosofia de "avisa, não decide por você" já estabelecida pro extrator (seção 3A).

**Política hoje: deletar.** Sem a rendition `1080p_ia`, um episódio ocupa só a variante `1080p` — **~0,5–1,5 GB**. Com **316GB livres na partição NTFS** onde vive `media/` (711GB total, 56% usado — ver seção 6), isso dá pra algo como **~200–600 episódios** antes de precisar de política ativa. A ação de retenção é `DELETE` direto (endpoint em 5) — não há rendition pesada pra remover mantendo uma leve, então "reduzir" não se aplica neste modo.

**Política pós-gatilho: reduzir, com o `1080p_ia` entrando na conta.** Quando o modo em lote estiver em produção, o ladder ocupa **~2–3GB por episódio** de 24min (`1080p_ia` a ~8–12 Mbps ≈ 1,4–2,2GB + `720p` a ~3 Mbps ≈ 0,5GB) — o espaço prático cai para **~110–150 episódios** antes de precisar de política ativa. **Ação de retenção: remover a rendition `1080p_ia`, mantendo a `720p`** — apaga a variante pesada, libera ~75% do que o episódio ocupa e deixa uma cópia **ainda assistível**. Exige reescrever o master manifest, não é só apagar `.ts` — passo explícito do endpoint `POST /api/admin/episodios/{id}/reduzir` (seção 5, marcado pós-gatilho), não implícito.

**Por que não guardar o 1080p original em vez de reprocessar (pós-gatilho, quando o GC o apaga).** Guardá-lo custaria ~1–1,5GB por episódio *permanentemente*, para evitar um novo download que, na prática, é a parte barata do trabalho. Se a Fase 0 pós-gatilho confirmar reprocessar do zero em **~40 min** em vez de ~10–16h (Bloco B, 2.2), isso torna "apagar e refazer se precisar" uma opção real em vez de teórica. **O GC do original (3D) fica mantido nos dois modos.**

**A opção "reduzir" ainda faria sentido, sendo tão barato reprocessar?** Faria, mas por uma margem menor que se reprocessar continuasse caro, e vale registrar: reprocessar exige que a fonte **ainda esteja no ar** — sites de anime somem, trocam de domínio e removem catálogo antigo (mesmo risco que a seção 3A já trata para o extrator). Os ~0,5GB da `720p` comprariam uma cópia que não depende de a internet cooperar depois. Se em algum momento a fonte deixar de ser o gargalo, `reduzir` viraria redundante com `DELETE` e poderia ser aposentado.

---

## 4. Modelo de Dados

Banco relacional (SQLite via SQLAlchemy — arquivo único, zero-config, adequado para um nó local; migrar para Postgres só se houver necessidade real de acesso concorrente multiusuário mais adiante).

> `PRAGMA foreign_keys=ON` precisa ser setado por conexão — SQLite não aplica FK por padrão sem isso. Pragmas fixados: `journal_mode=WAL`, `busy_timeout=5000`, `synchronous=NORMAL`, `foreign_keys=ON`. Regra de acesso: nunca manter uma transação de escrita aberta atravessando uma chamada de `ffmpeg` ou um lote de inferência; sessões curtas por request na API. Cascade em nível de banco (`ON DELETE CASCADE`) apaga linhas, não arquivos em disco — o fluxo de deleção de anime/episódio precisa apagar os arquivos de mídia primeiro e as linhas depois, em nível de aplicação, senão sobra lixo órfão em `MEDIA_ROOT`.

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
| url_fonte | str | URL de origem do episódio — preenchida pela resolução automática (`FonteAnime` + listagem de episódios do site, 3A), não digitada; sem ela, retry/retomada de job é impossível |
| site_origem | str | qual scraper foi usado (movido de `Anime` — circuit breaker e falha são por site, e isso é por episódio: o caso comum, não a exceção) |
| status | enum | `pendente / pronto / falhou / somente_720p` — `somente_720p` após redução de retenção (seção 3G). Era `somente_1080p` quando o ladder tinha 4K; com o teto em 1080p, o nome antigo passaria a descrever o estado **normal** de um episódio pronto, não o reduzido — trocar não é cosmético, é evitar um enum que mente |
| hls_path | str | caminho do master `.m3u8`, **relativo a `MEDIA_ROOT`** (não absoluto) — um caminho absoluto gravado como string quebraria no dual-boot Windows/Zorin, mesmo risco já registrado na seção 6 pra `MEDIA_ROOT`/`SCRATCH_ROOT` |
| renditions_disponiveis | str/json | quais renditions do ladder ainda estão empacotadas: `["1080p"]` no modo em tempo real hoje, `["1080p_ia","720p"]` quando o modo em lote está pronto (pós-gatilho), `["720p"]` após redução (3G). Mantido como lista, e não substituído por um booleano `reduzido`, justamente porque a rendition `1080p` (modo em tempo real, sem IA no servidor) coexiste com a `1080p_ia` (modo em lote, pós-gatilho) no mesmo manifesto — o conjunto de renditions é aberto, não um par fixo (ver nomenclatura em 3D, inclusive a nota sobre nome derivado da altura real). Remover uma rendition reescreve o master manifest, é passo explícito |
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

**FonteAnime** (cache do mapeamento anime↔site — suporta a resolução automática de fonte da seção 3A, evita repetir busca por nome a cada episódio)
| campo | tipo | nota |
|---|---|---|
| anime_id | FK, parte da PK composta | `ON DELETE CASCADE` |
| site_dominio | str, parte da PK composta | mesma chave de `EstadoSite`, ex. `animefire.plus` |
| identificador_no_site | str | slug/URL do anime naquele site — o que a listagem de episódios do adapter (`get_episodes`, 3A) precisa pra não buscar por nome de novo |
| prioridade | int | ordem de tentativa entre sites pra este anime; herda a ordem global (AnimeFire = 0) no momento da resolução, mas fica por anime — se o padrão falhar e um fallback resolver, é o fallback que deve ser tentado primeiro no próximo episódio, não o padrão de novo |
| resolvido_em | datetime | quando esta entrada foi criada/confirmada |

---

## 5. API (rascunho de endpoints)

```
GET    /api/admin/animes/buscar?q=...           busca candidatos no AniList (fallback Kitsu) — busca-e-confirma da seção 3F
POST   /api/admin/animes                        confirma um candidato e cria o Anime (grava anilist_id/kitsu_id)
POST   /api/admin/jobs                        cria job — entrada normal é (anime_id, número, tipo, versão); resolve a fonte sozinho (`FonteAnime` + busca-e-fallback, 3A) e devolve o Job já em fila. Se a busca no site padrão for ambígua, devolve candidatos em vez de criar o job (ver /fontes/confirmar abaixo). `url` continua aceito como override manual — caminho de depuração da Fase 1 (roadmap 10), não o fluxo normal
POST   /api/admin/animes/{id}/fontes/confirmar  confirma qual candidato de site é o anime certo quando a resolução automática (3A) retornou mais de um resultado — grava em `FonteAnime` e completa a criação do job que ficou pendente dessa confirmação
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
POST   /api/admin/episodios/{id}/reduzir        [pós-gatilho] remove a rendition 1080p_ia do ladder, mantém a 720p (ação de retenção da 3G)

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

**Topologia: uma única máquina física, dual-boot.** `rogerio-win11` e `rogerio-zorin` não são hosts distintos — são o mesmo hardware, alternando entre Windows 11 e Zorin (Linux) via dual-boot. Isso muda a leitura do resto desta seção: não existe cenário de "ambiente remoto sem acesso à GPU" nem passthrough de GPU a configurar/validar — quando a máquina está booted num sistema, ela *é* aquele sistema, com acesso direto ao hardware.

**Regra vigente hoje: worker só roda sob Zorin — proibição técnica, não preferência.** Nunca iniciar o worker enquanto booted em Windows. O motivo é a GPU atual: Vulkan/AMDGPU sob Polaris tem ROCm inviável e o driver AMD do Windows fora do caminho testado — toda a validação do worker (bypass via DrissionPage/Chromium, pipeline) é feita sob Zorin, e nada foi revalidado sob Windows.

**O que cai, e o que sobra, quando a GPU for trocada (seção 12).** CUDA e TensorRT são igualmente maduros e suportados nos dois sistemas operacionais — quando a troca acontecer, o motivo técnico que hoje proíbe Windows deixa de existir, e o resto da stack (DrissionPage/Chromium, `ffmpeg`, Python) já roda nos dois. Mas sobra uma restrição que **não é sobre GPU** e por isso não cai com a troca:

- **Filesystem e caminhos.** Todo o desenho do modo em lote (3C) é Linux-shaped: `SCRATCH_ROOT` em ext4 ou tmpfs, atomicidade de `os.replace()`, locks POSIX para o WAL do SQLite. Nada disso é impossível no Windows, mas nada disso está validado lá — e tmpfs não existe no Windows.
- **O risco concreto de rodar nos dois: caminhos divergentes contra o mesmo banco.** `Episodio.hls_path`, `capa_path` e o `MEDIA_ROOT` são gravados como string. Rodar o worker ora sob Zorin (`/media/...`) ora sob Windows (`D:\...`) contra o **mesmo arquivo SQLite** produz um catálogo com metade dos caminhos inválidos em cada boot. Este é o motivo que sobreviveria à troca de GPU — e ele é de dados, não de hardware.

**Regra pós-gatilho:** o worker passaria a ser **suportado e validado sob Zorin**, com Windows tecnicamente possível mas exigindo `MEDIA_ROOT`/`SCRATCH_ROOT`/`DATABASE_URL` próprios daquele boot — nunca o mesmo banco dos dois lados. Como não há ganho em manter dois acervos, na prática continuaria-se em Zorin de qualquer forma; a diferença é que passaria a ser uma escolha, não uma proibição técnica. A rede de segurança do `heartbeat_em` (seção 4/9, I7) vale para crash e reboot nos dois regimes: no próximo boot, o worker reseta pra `na_fila` qualquer job preso com heartbeat velho.

**Hardware:**
| Componente | Especificação |
|---|---|
| GPU (**atual**) | **Radeon RX 580 2048SP** (Polaris 20 XL), 8 GB — hardware sobre o qual o modo em tempo real (3E) foi desenhado e medido (seção 11). Ver Bloco A, 2.2, para o orçamento de compute. |
| GPU (**planejada, pós-gatilho**) | **GeForce RTX 5060 Ti 16GB** (GB206-300-A1, Blackwell, TSMC 4N, 21,9 bi transistores) — 4608 CUDA cores, **144 tensor cores de 5ª geração**, 36 RT cores; base 2407 MHz / boost 2572 MHz → **23,7 TFLOPS FP32**, ~190 TFLOPS FP16 tensor denso; **16 GB GDDR7**, 128 bits @ 28 Gbps → **448 GB/s**; TDP 180 W. **Ainda não comprada nem instalada** (seção 12). Ver Bloco B, 2.2, para o que esses números significariam em fps. |
| CPU | Ryzen 7 5700X (AM4, Zen 3) — encode x264 a 1080p, ~100+ fps (3C/3D) |
| RAM | 16GB, **swap = 0** — um swapfile de 8–16GB é recomendado independente da GPU: o Chromium do bypass é o candidato real a OOM hoje |
| Disco (mídia, NTFS) | 316GB livres de 711GB total (56% usado) — mount via `ntfs-3g`. Hoje sustenta ~200–600 episódios (3G); pós-gatilho, com o ladder de duas variantes, cairia para ~110–150 |
| Disco (sistema, ext4 `/`) | 60GB livres — onde o banco SQLite (seção 4) e, pós-gatilho, o `SCRATCH_ROOT` (3C) devem ficar |

- **Monitoramento térmico, pós-gatilho:** `nvidia-smi` (uso, clock, temperatura, power draw, `Xid` no log do driver) substituiria `radeontop`/`hwmon`. Medir sob carga **sustentada** por 20+min, não só pico — item da Fase 0 pós-gatilho, não urgente hoje porque o modo em tempo real não sustenta carga de GPU por horas.
- **Fonte e gabinete:** a troca de GPU muda o conector de alimentação e o consumo de pico. Não é decisão de software e fica fora deste documento, mas é pré-requisito físico do gatilho (seção 12) — vale um item no checklist de compra, não aqui.

---

## 7. Observabilidade e Testes

- **Métrica de frame time no cliente, hoje.** HUD com preset, resolução do canvas, ms entre frames, `droppedVideoFrames`/`totalVideoFrames` e nome da GPU real via `GPUAdapter` — é o que torna o preset do player calibrável por medição em vez de chute (3E). Implementação de referência: seção 11.4.
- Logging estruturado por etapa do pipeline (download, extração, e pós-gatilho: upscaling, remux, HLS), incluindo tempo gasto por etapa — necessário para calibrar as estimativas de fps/tempo por episódio da seção 2.2.
- Progresso incremental exposto via WebSocket (`/ws/jobs/{id}`), não só polling — jobs longos (download hoje; upscaling pós-gatilho) precisam de feedback melhor que "processando...".
- Testes:
  - Unitário: interface `base.py` do Strategy Pattern dos extratores (contrato comum entre scrapers).
  - Integração, hoje: pipeline de download → `validando_fonte` → empacotamento HLS, com um episódio curto, de ponta a ponta antes de rodar em episódio real.
  - Integração, pós-gatilho: soma-se o ramo extração de frames → upscaling → remux (3C), com clipe de 5s (Fase 0 pós-gatilho, seção 10).
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

**Riscos já resolvidos pelo protótipo (seção 11) não aparecem mais aqui** — WebGPU disponível/estável sobre RADV/Polaris, controles nativos cobertos pelo canvas, e alvo de render travado no display via `AutoDownscalePre` estão fechados (11.5) e removidos do registro de risco; ficam só como itens medidos em 11.2/11.5.

### Riscos — hoje (extrator, dados, modo em tempo real)

| Risco | Mitigação |
|---|---|
| Overhead do navegador faz o preset escolhido não caber em 41ms/frame | Medido, não hipotético: o preset preferido (`aa-vl-deblur`) sustenta 0,0–0,6% de frames perdidos em execuções longas — folga larga (11.2). Ressalva que segue aberta: o baseline do MPV nunca foi medido para comparação direta (S1, 9.1), e o custo do `hls.js`/MSE ainda não foi medido — só `<video src=mp4>` local (S1/11.5) |
| Supersampling a 1:1 (upscale + downscale via Anime4K) não entrega ganho perceptível e só queima GPU | Não é mais hipótese central — o protótipo já entregou uma percepção de qualidade boa o bastante para virar preset padrão (11.2, item 5) — mas o teste formal lado a lado contra o 1080p original, com protocolo registrado, continua em aberto (11.5) |
| Fonte não é H.264/AAC (HEVC/VP9/AV1) → `-c copy` falha ou o navegador não toca | `ffprobe` na etapa `validando_fonte` decide entre `-c copy` e transcode x264 em CPU (3B/3D). HEVC continua proibido no entregável — via MSE não toca em Chrome/Firefox no Linux, que é onde o `hls.js` roda (seção 3C, B9) |
| Legenda *hardsub* deformada pelo CNN | Avaliar no PoC do modo em tempo real — presets com Restore mais leve tendem a sofrer menos. Se a legenda for *soft* em vez de hardsub, o desenho de controles muda de barra caseira para Vidstack (S3, 9.1) |
| Dependência `anime4k-webgpu` pré-1.0 / abandono | Pinar versão exata. O ativo real são os `.wgsl` com pesos embutidos — vendorizáveis, licença compatível. Risco de *lock-in* baixo |
| "Anime4K não é Real-ESRGAN" — expectativa de qualidade não atendida | Percepção inicial foi positiva no protótipo (11.2, item 5), mas sem protocolo formal de comparação lado a lado registrado ainda — mesmo critério do modo em lote quando ele existir: estabilidade temporal em movimento + "prefiro isso ao 1080p original na minha tela?" (11.5) |
| GPU a 100% (ou próximo) durante toda a reprodução de um episódio | Carga de tempo real é ordens de grandeza menor que upscaling em lote, mas vale a mesma instrumentação da seção 6 (`radeontop`, `hwmon/temp1_input`) numa sessão longa, se algum dia virar dúvida real |
| Os dois modos (tempo real e lote) divergem conforme o repo cresce | Master manifest desde o dia 1 (3D) + o modo em lote entra como **produtor de mais uma rendition**, nunca como sistema paralelo (12.2, item 4). Se essa invariante quebrar, o projeto virou dois projetos |
| Modo em tempo real é aposentado quando a GPU trocar | Não deveria ser: ele continua sendo a resposta a "quero assistir agora" mesmo pós-gatilho, e é o modelo híbrido de três degraus (§10), não a substituição de um modo pelo outro (12.2, item 4) |
| Worker cai no meio de um job | Estado do job + chunk persistido em DB, pipeline resumível (seção 4/5) |
| Job preso em execução após crash do worker (ou reboot pro Windows — seção 6) | `heartbeat_em` no `Job`, atualizado periodicamente; no boot, worker reseta pra `na_fila` todo job com heartbeat velho (seção 4, I7) |
| Duas instâncias do worker fazem claim do mesmo job | Claim atômico (`UPDATE ... WHERE status='na_fila'` conferindo `rowcount`, nunca SELECT-depois-UPDATE) + lock de instância única no boot (seção 3B, B6) |
| API não consegue matar o subprocesso do worker via tabela `Job` só | Cancelamento cooperativo: `cancelamento_solicitado` + status `cancelando`, 202 em `POST /jobs/{id}/cancelar`; polling da flag numa corrotina separada da do pipeline (seção 3B/5, B7) |
| Site-fonte muda DOM/anti-bot e quebra o scraper | Strategy Pattern isola por site; smoke test periódico por scraper (seção 7) |
| Sessão de bypass expirada não é detectada (Cloudflare pode responder challenge com HTTP 200) | Detector `is_challenge()` compartilhado (header `cf-mitigated`, `<title>Just a moment`, `cf_chl_opt`); sessão expirada invalida o cache sem contar pro circuit breaker — só falha após sessão nova conta pra `falhas_consecutivas`; `cf_clearance` é vinculado a IP+UA, egress trocado invalida o cache por definição (seção 3A, I5) |
| Download corrompido/incompleto só é descoberto tarde | Etapa `validando_fonte`: `ffprobe` confere decodabilidade e duração antes de empacotar (ou de enfileirar pra GPU, pós-gatilho); retomada por HTTP Range; reusa cookies/`Referer` da sessão de bypass (seção 3B, I6) |
| SQLite com escrita concorrente worker+API | Na prática são 2 writers (worker + API) + N readers, não 1+N; pragmas fixados (`journal_mode=WAL`, `busy_timeout=5000`, `synchronous=NORMAL`, `foreign_keys=ON` — seção 4); migrar para Postgres só se necessário (I4) |
| Exposição legal por armazenar/redistribuir conteúdo protegido | Ver 8.3 — decisão consciente de escopo, não acidente de arquitetura |
| Match errado de anime no AniList/Kitsu contamina sinopse/capa/numeração | Busca-e-confirma manual uma vez por anime, não fuzzy-match automático (seção 3F) |
| Numeração de episódio ambígua (absoluta vs. por temporada) | Cada temporada = `Anime` separado; número confirmado manualmente ao enfileirar, com sanity check contra a contagem do AniList (seção 3F) |
| Comparação entre modelos de upscaling sem critério nomeado (nitidez de frame parado engana — flicker temporal em áreas planas é o problema real) | Critério de comparação = estabilidade temporal em movimento, avaliado em qualquer PoC de upscaling, hoje ou pós-gatilho (seção 10, I10) |
| Disco (316GB NTFS + 60GB ext4) enche com o catálogo já pronto, não só temporários | Notificação de uso de disco + sugestão de retenção baseada em `assistido_em`, nunca deleção automática (3G) |

### Riscos — pós-gatilho (modo em lote, condicionados à troca de GPU)

| Risco | Mitigação |
|---|---|
| Estouro de disco por frames PNG de episódio inteiro | Pipeline em chunks + formato intermediário leve (seção 3C). **Não mitigado pela mudança de alvo de 4K para 1080p**: os intermediários seguiriam em 8K porque o modelo escala 4x — só um modelo 2x nativo reduziria isso (3C) |
| Estouro de VRAM durante upscaling | Deixaria de ser risco de primeira ordem: 16 GB planejados contra ~1 GB de pico *estimado* (não medido) para este modelo a 1080p (Bloco B, 2.2). Tiling viraria opcional. Reapareceria só se o número de streams de inferência fosse calibrado agressivamente demais — teto a medir na Fase 0(g) pós-gatilho |
| GPU trava/superaquece sob 100% sustentado | Monitorar temp/uso/power via `nvidia-smi` continuamente, não só em picos (seção 6). Risco reduzido frente ao que seria na GPU atual: a janela contínua cairia de ~10–16h para ~40 min estimados (Bloco B, 2.2). O estado `pausado` do `Job` fica **reservado mas provavelmente ocioso** — não implementar gatilho sem medição que o justifique |
| GPU reseta/mata o processo sem gerar falha explícita | Hoje o modo de falha específico de Polaris (`amdgpu: GPU reset` sob RADV) não se aplica porque o modo em lote não roda nesta GPU. Pós-gatilho, o genérico permaneceria (Xid/TDR do driver NVIDIA, OOM de VRAM). Mitigação: timeout + retry no nível do **chunk**, nunca do job inteiro; exit code/contexto em `erro_msg` (3C) |
| **Rota TensorRT adicionaria toolchain e um passo de build** (CUDA+TRT instalados, export ONNX, engine por GPU/driver/resolução) | Engine cacheada em disco com chave que inclui versão de driver/TRT e shape de entrada, reconstruída quando a chave mudar — falha silenciosa aqui daria resultado errado, não erro. Fallback pronto e sem custo de arquitetura: `realesrgan-ncnn-vulkan` com o mesmo modelo, ~4x mais lento (Bloco B, 2.2). A decidir empiricamente na Fase 0(g) pós-gatilho |
| **Estimativa de fps do Bloco B (2.2) é extrapolada de outras GPUs, não medida em nenhuma máquina deste projeto** | Âncoras são medições reais do mesmo modelo/resolução/runtime (3090, 4090), escaladas pelo fator limitante (banda). Conclusão estrutural aguentaria erro de 2x; o "~14 min de head start" não — é a primeira coisa a cair se a medição decepcionar, e cair nela não quebraria o pipeline, só a promessa de quase-ao-vivo |
| Upscaling 4x sem downscale gera 8K por acidente (espaço/banda desperdiçados numa tela de 1080p) | Downscale explícito pra **1920×1080** com Lanczos, por chunk, no passo de remontagem (seção 3C) |
| Supersampling de 16 amostras/pixel passa do ponto e vira suavização (over-smoothing) | Comparação direta contra o 2x nativo (`xsx2`, 4 amostras/pixel) na Fase 0 pós-gatilho — decisão central do PoC (3C) |
| Fonte-origem sai do ar e o episódio, já reduzido a `720p`, não pode mais ser reprocessado | É o que sustenta a ação `reduzir` continuar existindo em vez de virar `DELETE` puro, se reprocessar vier a custar só ~40 min como estimado (3G) |

---

## 9.1 Suposições a Validar (registradas, não resolvidas)

- **S1 — O baseline do Slime Shell Web de fato rodava liso.** Ainda não medido. O `player.py` *configura* Mode A com VL, mas a documentação do Anime4K posiciona `UL` como "só para Vega 64 / RTX 2080" e `M` como escolha para GPUs mais fracas — configurar não é rodar sem drop de frame. O protótipo (seção 11) mediu o preset novo com folga grande, mas não mediu o MPV lado a lado no mesmo clipe: a régua "o navegador precisa ser ≥, não quase igual" continua sem número (11.5, item a).
- **S2 — Resolução do display.** ✅ Confirmada pelo usuário: monitor físico é 1920×1080 nativo, sem escala configurada no SO. O canvas de saída medido na telemetria (2560×1440, nas amostras de `aa-vl-deblur`) é maior que isso de propósito — escolha deliberada de renderizar em supersampling acima da resolução nativa do display antes do downscale final, não uma inconsistência ou bug de medição. `targetDimensionsFor()` (`bench.js`) foi configurado/usado para produzir esse alvo maior; os números de 2.2 e o alvo de render de 3E continuam ancorados em 1920×1080 como resolução física do display, mas o pipeline de render pode mirar acima disso quando configurado para supersampling. O Hz do monitor não entra na conta em nenhum dos dois casos: o orçamento de 41ms/frame (Bloco A, 2.2) é regido pelo fps da fonte (~24fps do anime), não pelo refresh do monitor.
- **S3 — Legendas são *hardsub*.** O campo `versao` (`legendado/dublado`, seção 4) sugere que sim. Se houver legenda soft, o desenho de controles (3E) muda de barra caseira para Vidstack.
- **S4 — Os números de compute são aritmética/extrapolação, não medição — em graus diferentes por bloco.** Bloco A (RX 580, 2.2): a conclusão estrutural ("o meio-termo não existe nesta GPU") foi corroborada, não só suposta, pelo protótipo (seção 11) — sem depender do fps exato estimado. Bloco B (RTX, 2.2): segue extrapolação pura de outras GPUs (3090/4090), nunca medida em nenhuma máquina deste projeto — só substituível por medição depois do gatilho (Fase 0 pós-gatilho, 12.2). Ambos os blocos aguentam erro de 2–3x na conclusão estrutural; o número exato, em nenhum dos dois, não.

---

## 10. Roadmap

Uma trilha só. Fases 0–5 são o modo em tempo real. Fase 6 é o modo em lote inteiro — hoje **condicionada ao gatilho de hardware** (seção 12), detalhada abaixo como planejamento antecipado, não como trabalho liberado (regra em 12.4).

- **Fase 0 — PoC do modo em tempo real. ✅ CONCLUÍDA** (seção 11 registra o resultado completo). Critérios originais e o que a medição respondeu:
  - (a) `chrome://gpu` confirma WebGPU habilitado sobre Vulkan/RADV na RX 580 2048SP — **confirmado** (11.5);
  - (b) tabela de ms/frame por preset × tamanho (M/L/VL/UL), priorizando Mode A — **feita**, com o preset vencedor medido em detalhe (11.2/11.3);
  - (c) comparação direta contra o baseline MPV (`player.py`) — **não feita**, fica em aberto (S1, 9.1);
  - (d) confirmar que vídeo servido por `hls.js`/MSE entra no WebGPU sem readback dominante — **não feita**: só testado com `<video src=mp4>` local, o custo do MSE ainda não foi medido (11.5, item b);
  - (e) critério de qualidade = estabilidade temporal em movimento + "prefiro isso ao 1080p original" — avaliado informalmente (11.2, item 5), sem protocolo formal lado a lado registrado (11.5, item c);
  - (f) go/no-go: preset coube em 41ms/frame com margem folgada (0,0–0,6% de drop) — **go** confirmado; o projeto segue para as Fases 1–5.
- **Fase 1 — Backend mínimo.** Job com **caminho de arquivo local** como fonte → `ffprobe` (`validando_fonte`, 3B) → empacotamento HLS `-c copy` com master manifest de 1 variante (3D) → catálogo. Sem GPU, sem chunks, sem scratch. Esse modo "arquivo local" **permanece no sistema depois**, como caminho de debug/fallback pra quando um site estiver quebrado — não é só um atalho de bootstrap.
- **Fase 2 — Extrator.** Portar/adaptar os scrapers do Slime Shell Web (Strategy Pattern) para baixar o arquivo em vez de servir URL direta ao player, já com cache de sessão/cookies, retry+backoff e circuit breaker por site (3A) desde o início — mais fácil nascer com isso do que remendar depois. Adapters ganham busca por título e listagem de episódios (`search`/`get_episodes`, mesmo contrato do `AnimeProvider` do Slime Shell Web), não só extração dada uma URL — é o que a resolução automática de fonte (3A) precisa pra existir. Passa a alimentar a Fase 1 com fontes reais resolvidas automaticamente, complementando (não substituindo) o modo de arquivo local.
- **Fase 3 — API (REST + WS) e Autenticação.** Endpoints REST + `WS /ws/admin`/`WS /ws/jobs/{id}` de notificação/progresso sobre os jobs da Fase 1, e o gate de autenticação (token fixo, cookie — 5/8.1) desde os primeiros endpoints reais — a escolha do transporte de auth determina como HLS e WS são servidos, é decisão de arquitetura, não hardening tardio; o `.env.example` já tem o placeholder do token.
- **Fase 4 — Player WebGPU + Frontend.** Canvas + `requestVideoFrameCallback` + barra de controles acessível + seletor de preset + HUD de frame time (3E) — a implementação de referência já existe em `teste/` e informa esta fase diretamente (11.4). Galeria de capas → página do anime com posições prontas/não capturadas → clique dispara a resolução automática de fonte (entrada normal, 3A), sem formulário de URL separado; busca-e-confirma de anime no AniList/Kitsu (3F) e da fonte quando ambígua (3A) reaproveitam o mesmo padrão de UI (lista curta de candidatos), indicador persistente de "precisa de atenção", toast em tempo real — reaproveitando componentes visuais do Slime Shell Web.
- **Fase 5 — Hardening e refinamento.** Degradação automática por `droppedVideoFrames`; passe opcional de `RCAS`; investigar porte de ArtCNN para WGSL (opção I, 2.3); smoke tests dos scrapers; logging estruturado.
- **Fase 6 — Gatilho de hardware (pós-gatilho, condicionada à seção 12).** Liga o worker em lote como **produtor da rendition `1080p_ia`** do catálogo já existente. Nada do que foi construído nas Fases 1–5 é descartado. Internamente, repete a estrutura PoC → pipeline → refinamento que as Fases 0–5 já percorreram para o modo em tempo real:
  - **6.0 — PoC do modo em lote.** Validar upscaling com clipe de 5s na GPU planejada (RTX 5060 Ti ou superior); medir fps real, VRAM e tempo por frame com `realesr-animevideov3` e comparar com `realcugan` (2.3); comparar 4x+downscale vs. 2x nativo para 1920×1080 (3C); decidir formato intermediário (PNG vs WebP/JPG) com dados reais, não estimativa. Critério de go/no-go:
    - (a) fps e tempo total por episódio, contra a estimativa de **~35–55 min** (Bloco B, 2.2). Limiares: **>2h por episódio de 24min → investigar** (fora do previsto por mais de 3x — provavelmente a rota de inferência ou a banda); **>1h30 → a promessa de "assistir quase ao vivo" cai** e o lote vira modo overnight — não é fatal, mas muda o produto e precisa ser dito;
    - (b) custo de I/O do churn de frames medido nos alvos reais — `ntfs-3g` vs ext4 vs tmpfs decide onde fica `SCRATCH_ROOT` (3C);
    - (c) tamanho de chunk como saída medida, não palpite — também define a granularidade do head start de ~14 min (Bloco B, 2.2): chunk muito grande atrasa o primeiro segmento assistível;
    - (d) temperatura/clock/power **sustentados** por 20+min via `nvidia-smi`, não só pico (seção 6);
    - (e) teste de playback real do codec escolhido (H.264) no navegador alvo (3C);
    - (f) critério de qualidade = estabilidade temporal em movimento, não nitidez de frame parado — incluindo o teste honesto **"prefiro isso ao 1080p original na minha tela real"** (seção 1);
    - (g) rota de inferência decidida com medição: exportar o ONNX, construir a engine TensorRT FP16 e medir fps com 1/2/3 streams, com `realesrgan-ncnn-vulkan` como controle na mesma placa e no mesmo clipe. Confirma ou derruba o fator de ~4x do Bloco B (2.2), que sustenta tanto a escolha de runtime (2.1) quanto a viabilidade do head start. Medir também o tempo de build da engine e a invalidação do cache por versão de driver (seção 9).
  - **6.1 — Worker & Pipeline.** Pipeline em chunks (FFmpeg + Real-ESRGAN via TensorRT), GC automático por chunk, empacotamento HLS com a rendition `1080p_ia` somada ao master manifest já existente (3D) como etapa final do próprio pipeline.
  - **6.2 — "Assistir enquanto processa" (condicionada a 6.0(a) confirmar `r > 0,5`).** Só faz sentido se a GPU nova tornar isso possível — não é o plano padrão. Trocar `-hls_playlist_type vod` por uma playlist tipo `EVENT` atualizada a cada chunk comitado, liberando o episódio no player assim que o head start estimado for atingido. Trabalho pequeno — os segmentos já seriam produzidos em ordem e atômicos (3C); falta publicar a playlist incrementalmente e calcular quando é seguro começar. **Gatilho explícito, não "quando der"**: se 6.0 medir `r < 0,5`, esta subfase não acontece e o lote segue como modo overnight.
  - **6.3 — Futuro/opcional.** Object Storage/CDN, múltiplos workers se o hardware permitir, uso mobile dedicado (fora de escopo por ora — seção 1).

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
│   ├── models/                 # SQLAlchemy: Anime, Episodio, Job, SessaoBypass, EstadoSite, FonteAnime (seção 4 — 6 tabelas)
│   ├── db/                     # engine, sessão, migrations (Alembic) — arquivo .db fica fora daqui, em ext4 (DATABASE_URL, seção 6/2.1)
│   ├── core/config.py          # .env, paths de mídia, tile size etc.
│   ├── scripts/                # produtores/utilitários Python que precisam importar models/db (ex. enfileirar_local.py, Fase 1) — distinto do scripts/ da raiz, que é shell
│   └── pyproject.toml          # uv (2.1)
├── frontend/                   # React + Vite + Tailwind
│   └── src/{admin,player,components}/
├── media/                      # MEDIA_ROOT, runtime, fora do git, no mount NTFS — raw/, hls/{anime_slug}/{numero:03d}-{tipo}-{versao}/ (evita colisão entre dublado/legendado do mesmo número — sobrevive a reset/restore do banco, não obrigatório)
├── scripts/                    # start-dev.sh — equivalente ao `slimeWEB` original, sobe API+worker+Vite
└── .env.example                 # SCRATCH_ROOT (ext4/tmpfs) e DATABASE_URL (ext4) apontam pra fora deste diretório — ver seção 6
```

**Checklist — hoje (Fases 1–5, modo em tempo real):**
- [ ] Repositório criado.
- [ ] Confirmar que `animefire.py`/`animesdrive.py` (herdados do Slime Shell Web) ainda furam a proteção dos sites hoje — sites de anime mudam de domínio/proteção com frequência; não vale construir a resiliência da seção 3A em cima de um scraper que já pode estar quebrado.
- [ ] Alembic configurado pro schema inicial (as 6 tabelas da seção 4, incluindo `FonteAnime`).
- [ ] `.env.example` com os placeholders necessários hoje (token de acesso, `MEDIA_ROOT`, `DATABASE_URL`).
- [ ] Decisão de autenticação: em vez de usuário/senha + JWT completo (over-engineering pra 1 usuário), um **token fixo único** gerado uma vez, guardado no `.env`, comparado num cookie/header — tela de "desbloquear", não de login. Evolui depois se algum dia virar multiusuário.

**Checklist — pós-gatilho (bloqueante antes da Fase 6.0, não antes):**
- [ ] **GPU trocada e fisicamente instalada** (fonte/conector conferidos — seção 6), driver NVIDIA + CUDA + TensorRT instalados, `nvidia-smi` enxergando a placa.
- [ ] `ffmpeg` testado **manualmente** e a engine TensorRT construída **uma vez fora do projeto** a partir do ONNX do `realesr-animevideov3` — um upscale de um frame só, para confirmar que o export e o build funcionam antes de escrever código em volta disso. `realesrgan-ncnn-vulkan` instalado em paralelo como controle da Fase 6.0(g) e fallback (2.1).
- [ ] `.env.example` ganha os placeholders do modo em lote (`SCRATCH_ROOT`, tile size default).

---

## 11. Fase concluída — protótipo do player WebGPU (`teste/`)

Esta seção registra a única parte do projeto que **saiu do papel**. Tudo mais neste
documento é especificação; o que está aqui foi construído, medido e usado.

O sandbox `teste/` não é código de produção e não está sob os comandos de validação
do `CLAUDE.md` (§5 — só `backend/` e `frontend/` têm lint/teste configurados). Ele
existiu para responder à Fase 0 do modo em tempo real (§10) com medição em vez de
estimativa, e respondeu.

### 11.1 O que foi construído

| Arquivo | Papel |
|---|---|
| `teste/index.html` | Hub: um card por preset, com a descrição do que cada um testa |
| `teste/bench.html` | Player: `<video>` oculto → `<canvas>` WebGPU, HUD, barra de controles, ambient glow |
| `teste/bench.js` | Registro de 15 presets + loop de render + telemetria + áudio + glow |
| `teste/bench_server.py` | Coletor de telemetria (`POST /log`) → `bench_results.ndjson` |

Um preset por URL (`?preset=`), custo de GPU varrido por `?rate=` (playbackRate como
estresse controlado), e a métrica dura vinda de `getVideoPlaybackQuality()`
(`droppedVideoFrames` / `totalVideoFrames`) — não de impressão subjetiva.

### 11.2 O que foi medido, e o que a medição derrubou

Fonte: episódio real 1080p H.264 local, Chrome sobre RADV/Polaris.

1. **O preset vencedor roda com folga.** `aa-vl-deblur` sustentou **0,0–0,6% de frames
   perdidos** em execuções longas — a maior com **15.792 frames** e drop 0,0%. A
   cadência mediana de ~43,3 ms é o intervalo entre frames da *fonte* (~23,976 fps),
   não o custo da GPU.
2. **Sobra orçamento a 1x.** A base `aa-vl` sustenta `?rate=1.5` com drop ~2% (ruído),
   o que indica ~30%+ de folga na velocidade normal.
3. **O teto está no segundo restore, não no primeiro.** `aa-vl-vl` — que só sobe o
   `restore2` de `CNNM` para `CNNVL` — trava: **16,2% de drop a 1x** e 46,8% a 1,5x.
   Esse estágio roda depois do upscale, sobre 4x mais pixels; o custo dele não escala
   como o dos dois primeiros.
4. **O Tier UL/GAN não roda nesta GPU.** `aa-ul`, `aa-ul-vl`, `gan-a-ul`, `gan-x3-cnn`
   e `gan-x3` travam. **O ramo GAN inteiro está excluído por limitação de hardware** —
   não por decisão de qualidade. É a primeira coisa a reabrir quando a GPU mudar (§12).
5. **A documentação oficial errou para este caso, e a medição venceu.** A versão
   anterior desta especificação fixava "Mode A é o alvo, A+A contraindicado por
   over-sharpening a 1:1", citando a documentação do Anime4K. O teste mostrou o
   contrário: o A+A oficial (`aa-vl`) não só roda como é a base do preset preferido.
   A recomendação foi invertida e a escada de degradação ancorada em `A/UL → A/VL →
   …` foi substituída pela escada medida de 11.3. A previsão fica registrada porque
   ela era razoável; o que manda é o dado.

### 11.3 Ranking de qualidade e escada de degradação

**1º — `aa-vl-deblur` (confirmado).** `ClampHighlights → CNNVL → CNNx2VL → CNNM →
DoG(strength=7) → Downscale`. O deblur entra como último passe de conteúdo, antes do
downscale — afia o resultado já restaurado e upscalado, não a fonte crua. Valor de
`strength` vem do README oficial da lib, não de chute.

**2º/3º — não confirmados.** Os candidatos são `aa-vl` (a base, sem o deblur) e `a-ul`
(passe único no tier UL). Registrado como pendência aberta, não como decisão tomada.

**Também medidos e não escolhidos:** `aa-vl-denoise` (BilateralMean 0,2/2 antes do
restore) roda folgado (0,5% de drop) mas não superou o deblur na percepção; fica como
knob para fontes com grão. `aa-vl-vl`, `aa-ul`, `aa-ul-vl` e os três presets GAN estão
**fora por hardware** (11.2, item 3 e 4).

**Escada de degradação vigente**, se o frame time apertar (fonte mais pesada, tela
maior, ou o custo do `hls.js`/MSE que ainda não foi medido):
`aa-vl-deblur → aa-vl → a-vl → b-vl / c-vl (característica) → a-m → original`.

### 11.4 O player que saiu daqui (entra na especificação em 3E)

O harness deixou de ser só um medidor e virou o desenho de referência do player:

- **HUD de telemetria**: preset, resolução do canvas, ms entre frames, dropped/total,
  rate, e o nome da GPU real (capturado do `GPUAdapter`, que a lib não expõe).
- **Barra de controles própria** (play/seek/volume/mudo/fullscreen/HUD/áudio), com
  teclado e ARIA — o canvas cobre os controles nativos do `<video>`, então isso nunca
  foi opcional.
- **Fullscreen com moldura nos 4 lados**: `--fullscreen-margin: 6vmin` como `padding`
  do palco; a largura do `.frame` é **calculada explicitamente**
  (`width: min(100%, 1600px, calc((100dvh - var(--page-chrome)) * var(--frame-ar)))`)
  em vez de emergir de `max-height` + `aspect-ratio` — dentro de um container flex, o
  eixo principal é resolvido antes do cruzado e esse feedback não é garantido.
- **Ambient glow** (estilo YouTube Ambient Mode): canvas 2D borrado que amostra o
  `<video>` **fonte**, nunca o canvas WebGPU — decisão deliberada para ficar
  desacoplado de um pipeline que já roda no limite da GPU. Ancorado na caixa do
  próprio vídeo via `position: absolute` + `--ambient-bleed: 10%`; a versão anterior
  era `position: fixed` sobre o viewport inteiro e desalinhava de forma anisotrópica
  quando as proporções do vídeo e da janela divergiam. Amostragem em baixa resolução
  (canvas 32×18px, proporção 16:9 exata) com média móvel exponencial — cada frame novo
  entra com 30% de peso (`globalAlpha`) sobre o que já estava desenhado — pra suavizar
  corte de cena sem calcular "cor dominante" na mão.
- **Áudio "cinema"** (Web Audio): `highpass 30Hz → crossfeed estéreo (highshelf 700Hz
  -10dB + delay 300µs + mix 0,35) → bass shelf 90Hz +6dB → peaking 300Hz -2dB →
  DynamicsCompressor (threshold -20dB, knee 12, ratio 4, attack 10ms, release 250ms)
  → makeup gain 2x`. Bypass A/B por crossfade de 50 ms num grafo **fixo** (nunca
  reconectando nós em runtime), preferência em `localStorage`, atalho `C`, e o
  `AudioContext` criado só dentro de um gesto real do usuário — regra de autoplay
  policy, não estilo.
- **Vídeo sem corte**: `.frame` em 16:9 nativo + `object-fit: contain`. O crop 2.2:1
  ancorado que existia antes foi removido depois de `ffprobe`/`cropdetect` mostrarem
  que **nenhum** dos arquivos de teste tem barra preta gravada — o crop cortava imagem
  real o tempo todo. `--page-chrome` subiu de `5rem` para `7rem` para o vídeo não
  encostar na borda da viewport em modo janela.

### 11.5 O que isso fecha da Fase 0, e o que continua aberto

**Fechado:** WebGPU sobre RADV/Polaris funciona nesta máquina; existe tabela de custo
por preset baseada em medição; um preset de qualidade alta cabe no orçamento com
margem larga; o frame do `<video>` chega ao WebGPU sem readback dominante.

**Aberto:** (a) a comparação direta contra o baseline do MPV (9.1, S1) não foi feita —
a régua "o navegador precisa ser ≥, não quase igual" continua sem número; (b) todo o
teste usou `<video src=mp4>` local, **não** `hls.js`/MSE — o custo do MSE não está
medido e é a diferença entre o harness e o produto; (c) o critério de qualidade foi
percepção do usuário, sem protocolo lado a lado registrado.

**Conclusão prática da fase, que é o que autoriza o resto do documento:** o pipeline
Anime4K em WebGPU rodando ao vivo no navegador **funciona e é viável na RX 580**,
dentro dos limites de preset acima. O modo em tempo real deixou de ser hipótese.

---

## 12. Gatilho de troca de hardware (RX 580 → RTX 5060 Ti ou superior)

**Hardware atual: Radeon RX 580 2048SP (Polaris 20 XL), 8 GB.** Não é um detalhe de
ambiente: é a restrição que desenhou boa parte deste documento. Polaris não tem núcleo
tensor nem *rapid packed math*, entrega ~1,6–2,6 TFLOP/s efetivos em convolução (2.2),
e é sobre esse número que quase toda escolha abaixo foi feita.

### 12.1 Decisões que só existem por causa desta GPU

| Decisão vigente | Onde | O que se reabre com a GPU nova |
|---|---|---|
| Ramo GAN excluído do player (`gan-a-ul`, `gan-x3-cnn`, `gan-x3` travam) | 11.2, 11.3 | **Reabrir primeiro.** Não exige código novo — os presets já existem no harness, basta rodá-los |
| Teto de preset em `aa-vl-deblur`; Tier UL e passe duplo UL fora | 11.3 | Reabrir `aa-ul`, `aa-ul-vl`, `aa-vl-vl` e a escada inteira |
| Pipeline em lote descartado no presente (~10–16 h/episódio) | 2.2, 3C | Vira viável (~40 min estimados) e ativa as Fases 5b/6 do roadmap (§10) |
| Rota de inferência = `realesrgan-ncnn-vulkan` (Vulkan foge do ROCm em Polaris) | 2.1 | Troca para TensorRT FP16 sobre ONNX, com ncnn-Vulkan como fallback |
| Encode em CPU (x264) para não disputar a GPU com o upscaler | 3C | NVENC é bloco dedicado: deixa de haver disputa. A decisão pode ficar de pé por *qualidade por bit*, mas com fundamento novo |
| Tiling obrigatório e chunk pequeno por causa de 8 GB de VRAM | 3C | 16 GB tornam o tiling opcional — e desligá-lo elimina o risco de costura visível |
| "Worker só sob Zorin" (ROCm/AMDGPU sob Polaris) | 6 | Cai: CUDA/TensorRT rodam nos dois sistemas. **Sobra** a restrição de caminhos divergentes contra o mesmo SQLite, que não é sobre GPU |
| Alvo de render limitado à resolução do display via `AutoDownscalePre` | 3E | Abre margem para renderizar acima do display (supersampling no cliente) |

### 12.2 O gatilho, explicitamente

**Quando o usuário mencionar, em qualquer conversa e de qualquer forma casual — "troquei
pra uma 5060 Ti", "instalei a RTX", "chegou a placa nova", "agora tô na 5070" — que a
GPU foi trocada por uma RTX 5060 Ti ou qualquer outra da mesma geração ou superior
(5060 Ti / 5070 / 5080 / 5090 ou posterior), isso não é informação de ambiente. É o
gatilho de uma nova rodada de arquitetura.**

A resposta certa não é continuar a tarefa em curso como se nada tivesse mudado. É:

1. **Registrar** a troca na tabela de hardware (§6) com a data, e mover a RX 580 para
   linha de referência histórica.
2. **Abrir uma rodada de replanejamento** (`architect`), nesta ordem de custo/benefício:
   a. Re-testar o ramo GAN e os presets UL no harness (11.3) — é o ganho mais barato,
      mais rápido e mais visível, e não exige escrever código;
   b. Rodar a Fase 0 do pipeline em lote (§10) na placa nova, começando pelo item da
      rota de inferência — é o que sustenta todos os números de 2.2;
   c. Percorrer a tabela de 12.1 linha a linha, registrando qual decisão caiu, qual
      ficou de pé, e com que fundamento novo.
3. **Não tratar os números de 2.2 (bloco RTX) como medidos.** Eles são extrapolação a
   partir de âncoras medidas em *outras* GPUs (3090/4090), escalados por largura de
   banda. A conclusão estrutural ("dezenas de minutos, não horas") aguenta erro de 2x;
   o head start de ~14 min não aguenta.
4. **Não aposentar o modo em tempo real.** Ele continua sendo a resposta para "quero
   assistir agora", e continua sendo o modo que não depende de nada ser processado
   antes. O destino é o modelo híbrido dos três degraus (§10), não a substituição de um
   modo pelo outro.

### 12.3 O que não é gatilho

Trocar CPU, RAM, disco ou monitor **não** dispara replanejamento de arquitetura. Cada um
tem impacto local e conhecido, que se registra sem reabrir decisões: monitor afeta 9.1/S2
e o alvo de render (3E); disco afeta a política de retenção (3G); RAM afeta a pressão de
OOM do Chromium do bypass (6). Registrar, sim; replanejar, não.

### 12.4 Regra simétrica: enquanto a troca não acontecer

Nenhuma decisão de implementação deste documento deve ser tomada "já pensando na placa
nova". Código que só faz sentido com tensor core não entra no repositório antes de haver
tensor core — vira código morto que nunca foi executado e que envelhece sem ninguém
notar. O material sobre a RTX que já está escrito aqui (2.2, e as linhas marcadas como
pós-gatilho em 2.1/3C/3D/6/10) é **planejamento**, deliberadamente feito com
antecedência para que a rodada do 12.2 comece com o raciocínio pronto — não é permissão
para implementar antes.

---

## 13. Próximos Passos Imediatos

Com a Fase 0 do modo em tempo real concluída (seção 11), os próximos passos são os que destravam a Fase 1 em diante — nenhum depende do gatilho de hardware (seção 12):

1. **Estruturar o loop assíncrono do Worker em Python** com estado persistido em SQLite (não em memória) desde o início, aceitando um caminho de arquivo local como fonte do job (seção 10, Fase 1) — para já nascer resumível e validar o pipeline (download → `ffprobe` → empacotamento HLS) sem depender de scraper nenhum.
2. **Medir o baseline S1** (9.1) — rodar o MPV com o preset Mode A/VL do `player.py` no mesmo clipe usado no protótipo (seção 11), pra fechar a régua de comparação "o navegador precisa ser ≥, não quase igual" que a Fase 0 deixou em aberto (11.5, item a).
3. **Desenvolver a interface abstrata do extrator de links** (Strategy Pattern, Fase 2), portando o motor de bypass do Slime Shell Web para o modelo de download, já com cache de sessão e circuit breaker por site (seção 3A) — não como camada adicionada depois.

**O que não é próximo passo agora:** validar o PoC do upscaling em lote (Fase 6.0, seção 10) — está corretamente bloqueado até o gatilho de hardware (seção 12) acontecer, e entrar nele antes seria violar a regra de 12.4.

---

## 14. Referências

- [Anime4K-WebGPU (Anime4KWebBoost)](https://github.com/Anime4KWebBoost/Anime4K-WebGPU) — implementação escolhida, presets A/B/C/AA/BB/CA
- [anime4k-webgpu no npm](https://www.npmjs.com/package/anime4k-webgpu)
- [bloc97/Anime4K](https://github.com/bloc97/Anime4K) e [GLSL_Instructions_Advanced.md](https://github.com/bloc97/Anime4K/blob/master/md/GLSL_Instructions_Advanced.md) — orçamento de 41 ms/frame a 24fps, escalonamento S→M→L→VL→UL
- [Anime4K Wiki — Upscale Shaders](https://github.com/bloc97/Anime4K/wiki/Upscale-Shaders) — recomendação por classe de GPU
- [anime4k-wgpu (SegaraRai)](https://github.com/SegaraRai/anime4k-wgpu) — porte WGSL alternativo
- [WebSR (sb2702)](https://github.com/sb2702/websr) — opção H (2.3), pré-produção
- [AMD encerra suporte Vulkan a Polaris/Vega no Linux (AMDVLK)](https://videocardz.com/newz/amd-officially-drops-vulkan-driver-support-for-polaris-and-vega-architectures-on-linux) — RADV do Mesa segue mantido
- [Browser GPU Acceleration on Linux in 2026](https://sumguy.com/browser-gpu-acceleration-linux-2026/) — WebGPU padrão no Chrome; Firefox em rollout
- [vs-mlrt (AmusementClub)](https://github.com/AmusementClub/vs-mlrt/wiki) — âncoras de fps TensorRT FP16 usadas no Bloco B (2.2)
- Baseline local: `/media/rogerio/Projetos/Slime_Shell_Web/backend/player.py` (`_obter_argumentos_anime4k`)

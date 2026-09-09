// Import via namespace (não default): o pacote é publicado só como
// CommonJS (bundle webpack/UMD, ver node_modules/anime4k-webgpu/lib/index.js)
// e o módulo marca `__esModule: true` sem nunca definir uma chave `default`
// — só propriedades nomeadas (render, ClampHighlights, CNNM, ...). O
// interop CJS→ESM do Vite/esbuild respeita esse marcador e NÃO sintetiza um
// default a partir do objeto inteiro (diferente do esm.sh, que o protótipo
// em teste/bench.js usava e sintetiza um default sensato por conta própria)
// — `import Anime4K from 'anime4k-webgpu'` chega `undefined` em dev. Import
// de namespace pega as propriedades nomeadas de qualquer forma.
import * as Anime4K from 'anime4k-webgpu';

const {
  ClampHighlights,
  Original,
  CNNM,
  CNNVL,
  CNNSoftVL,
  DenoiseCNNx2VL,
  CNNx2M,
  CNNx2VL,
  DoG,
  BilateralMean,
} = Anime4K;

// --- Blocos ---------------------------------------------------------------
//
// Cada preset é uma lista ordenada de blocos (RECEITAS). Um bloco carrega:
//  - `criar(device, inputTexture)`: instancia o Anime4KPipeline da lib.
//  - `escala`: fator linear que o bloco aplica à resolução (1 = mantém, 2 = CNNx2).
//  - `custo`: proxy linear do custo de GPU, em "fetches de textura por pixel
//    de ENTRADA do bloco". Sai da contagem `nº de convs × texturas lidas por
//    conv` no bundle da lib (cada Conv2d roda um dispatch de ⌈W/8⌉×⌈H/8⌉
//    workgroups sobre um output do tamanho da entrada → custo linear no nº de
//    texels). A constante absoluta não importa — só a razão entre degraus, e
//    essa é recalibrada ao vivo (fatia de afinação). Reproduz o que já foi
//    medido na mão: `aa-vl` ~6% abaixo do topo, `b-vl` == `a-vl`
//    (CNNSoftVL tem topologia idêntica a CNNVL), `a-vl` sem o x2 ~metade.
//
// Não há mais bloco de Downscale final: o blit da lib pro canvas usa
// exatamente o mesmo shader (textureSampleBaseClampToEdge + sampler linear)
// e já reduz a saída do último bloco pro tamanho do canvas. Um Downscale
// explícito antes dele era um render pass e uma textura redundantes por frame.
//
// Presets UL (a-ul, aa-ul, ...) e GAN (gan-*) do protótipo (teste/bench.js)
// ficam de fora: travam na RX 580 atual (ESPECIFICACAO §11.2/11.3).
// Reintroduzir fica condicionado ao gatilho de troca de GPU (§12).
//
// `passes` = nº de compute/render passes que o bloco enfileira por frame
// (contagem de convs + overlay/d2s no bundle). Só instrumentação: o HUD
// mostra o total pra dar como diagnosticar se o modelo de custo (linear em
// megafetches) precisa de um termo fixo por passe (overhead de driver).
const BLOCOS = {
  original: { escala: 1, custo: 1, passes: 0, criar: (_device, tex) => new Original({ inputTexture: tex }) },
  clamp: { escala: 1, custo: 20, passes: 3, criar: (device, tex) => new ClampHighlights({ device, inputTexture: tex }) },
  restoreVL: { escala: 1, custo: 286, passes: 18, criar: (device, tex) => new CNNVL({ device, inputTexture: tex }) },
  restoreSoftVL: { escala: 1, custo: 286, passes: 18, criar: (device, tex) => new CNNSoftVL({ device, inputTexture: tex }) },
  restoreM: { escala: 1, custo: 72, passes: 9, criar: (device, tex) => new CNNM({ device, inputTexture: tex }) },
  x2VL: { escala: 2, custo: 296, passes: 19, criar: (device, tex) => new CNNx2VL({ device, inputTexture: tex }) },
  x2M: { escala: 2, custo: 90, passes: 10, criar: (device, tex) => new CNNx2M({ device, inputTexture: tex }) },
  denoiseX2VL: { escala: 2, custo: 296, passes: 19, criar: (device, tex) => new DenoiseCNNx2VL({ device, inputTexture: tex }) },
  // `strength` é o expoente da curva de sharpening (WGSL do DoG). 7 = valor
  // do README oficial da lib — mantido só onde o restore por trás já é
  // pesado o bastante pra não sobrar halo (só aa-vl-deblur agora).
  deblur: {
    escala: 1,
    custo: 20,
    passes: 4,
    criar: (device, tex) => {
      const p = new DoG({ device, inputTexture: tex });
      p.updateParam('strength', 7);
      return p;
    },
  },
  // strength=4: confirmado ao vivo em cima de restore mais fraco (a-vl/
  // a-vl-1x com CNNVL sem o restoreM extra que aa-vl-deblur tem; a-m com
  // CNNM, ainda mais fraca) — strength=7 nesses sobrava em halo/ringing e
  // lia como MENOS nítido que essa versão mais fraca, não mais.
  deblurLeve: {
    escala: 1,
    custo: 20,
    passes: 4,
    criar: (device, tex) => {
      const p = new DoG({ device, inputTexture: tex });
      p.updateParam('strength', 4);
      return p;
    },
  },
  // `strength`/`strength2` nascem zerados na lib — sem updateParam() explícito
  // o shader do BilateralMean divide por zero (intensitySigma=0 no denominador
  // do gaussianVec). 0.2/2 = valores do README oficial (`strength`=intensitySigma,
  // `strength2`=spatialSigma, conferido na WGSL). Testado ao vivo como passe
  // extra antes do restore em a-m/a-vl/a-vl-1x (comparação temporária,
  // removida) — rejeitado, não valeu a qualidade. Continua valendo só em
  // aa-vl-denoise, o knob dedicado pra fonte com grão de verdade.
  denoise: {
    escala: 1,
    custo: 20,
    passes: 1,
    criar: (device, tex) => {
      const p = new BilateralMean({ device, inputTexture: tex });
      p.updateParam('strength', 0.2);
      p.updateParam('strength2', 2);
      return p;
    },
  },
};

// Receita de cada preset: blocos em ordem de execução. A saída do último
// bloco vai direto pro blit do canvas.
// Deblur (DoG) como último passe de conteúdo em todo degrau que não seja
// `original`: custo baixo (20, ante 72-296 dos blocos de restore/upscale) e
// sem ele a imagem sai opaca/sem nitidez assim que sai do topo (só
// `aa-vl-deblur` tinha o passe antes desta linha).
const RECEITAS = {
  original: ['original'],
  // deblurLeve ANTES do x2M (diferente de a-vl/a-vl-1x, onde vem depois):
  // confirmado ao vivo que o x2M não suaviza o sharpen de volta, então
  // sharpenar no low-res evita rodar o passe a 4x os megapixels da fonte
  // (~80 de custo) por ~20 — de graça, sem perda visível.
  'a-m': ['clamp', 'restoreM', 'deblurLeve', 'x2M'],
  'a-vl': ['clamp', 'restoreVL', 'x2VL', 'deblurLeve'],
  // Sem o CNNx2VL: com fonte ~1080p e alvo mirando a tela, o x2 gera 2160p que
  // o blit joga fora de volta. Tirar o x2 mantém a fonte inteira na CNN de
  // restauração (o que limpa o anime) e corta ~metade do custo.
  'a-vl-1x': ['clamp', 'restoreVL', 'deblurLeve'],
  'aa-vl': ['clamp', 'restoreVL', 'x2VL', 'restoreM'],
  'b-vl': ['clamp', 'restoreSoftVL', 'x2VL'],
  'c-vl': ['clamp', 'denoiseX2VL'],
  // Denoise logo após o clamp, antes do restore — limpa a fonte antes da CNN
  // "restaurar" detalhe em cima de ruído.
  'aa-vl-denoise': ['clamp', 'denoise', 'restoreVL', 'x2VL', 'restoreM'],
  'aa-vl-deblur': ['clamp', 'restoreVL', 'x2VL', 'restoreM', 'deblur'],
};

const LABELS = {
  original: 'Original',
  'a-m': 'Anime4K A · M',
  'a-vl': 'Anime4K A · VL',
  'a-vl-1x': 'Anime4K A · VL (sem upscale)',
  'aa-vl': 'Anime4K A+A · VL',
  'b-vl': 'Anime4K B · VL',
  'c-vl': 'Anime4K C · VL + Denoise',
  'aa-vl-denoise': 'Anime4K A+A · VL + Denoise',
  'aa-vl-deblur': 'Anime4K A+A · VL + Deblur',
};

// Encadeia os blocos: a saída de textura de um é a entrada do próximo.
// Devolve o array de Anime4KPipeline que render() espera.
function montarPipeline(blocos, device, inputTexture) {
  const pipelines = [];
  let tex = inputTexture;
  for (const nome of blocos) {
    const pipeline = BLOCOS[nome].criar(device, tex);
    pipelines.push(pipeline);
    tex = pipeline.getOutputTexture();
  }
  return pipelines;
}

// Fator linear total que o pipeline aplica à resolução (produto das escalas
// dos blocos). 1 nos presets sem x2, 2 nos com CNNx2.
function escalaDeSaida(blocos) {
  return blocos.reduce((acc, nome) => acc * (BLOCOS[nome]?.escala ?? 1), 1);
}

// Total de passes por frame (blocos + 1 do blit final). Só pro HUD.
export function contarPasses(blocos) {
  return blocos.reduce((acc, nome) => acc + (BLOCOS[nome]?.passes ?? 0), 1);
}

// Custo relativo de GPU do pipeline em "megafetches por frame", dada a
// resolução de entrada. Percorre os blocos acumulando `custo × megapixels na
// entrada do bloco` e escalando os megapixels pelo `escala²` de cada bloco.
// Consumido pela política preditiva (fatias seguintes); hoje só alimenta o HUD.
export function custoEmMegafetches(blocos, larguraEntrada, alturaEntrada) {
  let megapixels = (larguraEntrada * alturaEntrada) / 1e6;
  let total = 0;
  for (const nome of blocos) {
    const bloco = BLOCOS[nome];
    if (!bloco) continue;
    total += bloco.custo * megapixels;
    megapixels *= bloco.escala ** 2;
  }
  return total;
}

// Cada preset: label (pt-br), a lista de blocos, e `build()` — devolve a
// função (device, inputTexture) => Anime4KPipeline[] esperada por render().
// `build` não recebe mais `dims`: sem Downscale final, a resolução de saída é
// só `canvas.width/height` (setado pelo motor) e o blit se ajusta sozinho.
export const PRESETS = Object.fromEntries(
  Object.entries(RECEITAS).map(([id, blocos]) => [
    id,
    {
      label: LABELS[id],
      blocos,
      build: () => (device, inputTexture) => montarPipeline(blocos, device, inputTexture),
    },
  ])
);

// Ordem por custo de GPU decrescente — o degrau mais pesado (melhor
// qualidade) primeiro. Consumido por SeletorDePreset.jsx só para ordenar o
// <select> manual.
export const ESCADA_DE_DEGRADACAO = ['aa-vl-deblur', 'aa-vl', 'a-vl', 'b-vl', 'c-vl', 'a-vl-1x', 'a-m', 'original'];

// Degraus da degradação automática (modo "Automático" do seletor, percorrido
// por useControleAdaptativo.js) — subconjunto da escada manual, só os saltos
// cujo corte de custo de GPU paga a reconstrução do GPUDevice na troca. Fora
// daqui de propósito: 'aa-vl' (só ~6% mais leve que o topo), 'b-vl' (mesmo
// custo de 'a-vl'), 'c-vl'/'aa-vl-denoise' (mudam o look — trocar look no meio
// do episódio é pior que perder um pouco de detalhe).
export const DEGRAUS_ADAPTATIVOS = ['aa-vl-deblur', 'a-vl', 'a-vl-1x', 'a-m', 'original'];

export const PRESET_PADRAO = 'aa-vl-deblur';

// Resolução do canvas de saída.
//
// Mira sempre o tamanho equivalente a TELA CHEIA (o maior que o .frame algum
// dia vai ocupar nesta sessão), não o tamanho atual — de propósito, mesmo em
// modo janela. Motivo: o bundle real da lib mostra que render() cria um
// GPUDevice novo e reconfigura o canvas a cada chamada, sem devolver handle
// pra parar o requestVideoFrameCallback recursivo da chamada anterior —
// reconstruir o pipeline ao entrar/sair de tela cheia vazaria o device antigo
// e deixaria dois loops rodando. Miramos o maior caso de uma vez; o blit
// baixar de uma resolução maior pro tamanho do canvas é seguro (não borra).
//
// Dois tetos sobre esse alvo:
//  - Resolução CSS da tela, SEM multiplicar por devicePixelRatio. Num painel
//    1080p o DPR > 1 vem de zoom do navegador / escalonamento do SO, não de
//    pixels físicos a mais — supersamplear por cima disso numa GPU fraca
//    custa caro sem ganho visível. (Um painel HiDPI real vai querer o fator
//    de volta; revisitar quando aparecer.)
//  - `escalaDeSaida` do preset: quanto a CNN de upscale multiplica a fonte.
//    Passar disso faria o blit *magnificar* com bilinear — borra e gasta.
//
// Largura CSS alvo (mesmos dois tetos do comentário acima) pra um aspect
// ratio dado — extraído pra ser compartilhado com resolverDegrauPorResolucao
// abaixo, que precisa do mesmo alvo pra decidir se um preset sem upscale é
// seguro pra uma fonte.
function alvoCssDoAspecto(aspect) {
  const screenCssWidth = window.screen?.width || window.innerWidth;
  const screenCssHeight = window.screen?.height || window.innerHeight;
  return Math.min(screenCssWidth, screenCssHeight * aspect);
}

// "original" fica de fora: é a referência "fonte pura sem shader".
export function calcularDimensoesDeSaida(presetId, video) {
  if (presetId === 'original') {
    return { width: video.videoWidth, height: video.videoHeight };
  }
  const videoAspect = video.videoWidth / video.videoHeight;
  const alvoCss = alvoCssDoAspecto(videoAspect);
  const escalaMax = escalaDeSaida(PRESETS[presetId]?.blocos ?? []);
  const width = Math.round(Math.min(alvoCss, video.videoWidth * escalaMax));
  const height = Math.round(width / videoAspect);
  return { width, height };
}

// Presets sem bloco de escala (x2VL/x2M) só são seguros quando a fonte já
// cobre o alvo da tela — abaixo disso, pular o upscale por CNN deixa a
// lacuna pro CSS (#output-canvas usa object-fit:fill) esticar sem rede
// nenhuma, revertendo a economia de custo em perda de nitidez real (medido
// ao vivo: 'a-vl-1x' ruim em fonte 720p/tela 1080p, bom quando fonte já é
// 1080p). Mapeia cada preset "sem upscale" pro equivalente COM upscale, pra
// usar no lugar quando a fonte não cobre.
const SUBSTITUTOS_SEM_UPSCALE = { 'a-vl-1x': 'a-vl' };

// Troca `presetId` pelo substituto com upscale se ele estiver em
// SUBSTITUTOS_SEM_UPSCALE e `dimensoesDaFonte` ({width,height}, de
// useFonteDeVideo.js) não cobrir o alvo da tela. Só usado no modo
// automático (PlayerAtivo.jsx) — presets escolhidos na mão continuam
// literais, é escolha explícita do usuário. `dimensoesDaFonte` null (antes
// do loadedmetadata) devolve presetId como veio: sem dado pra decidir.
export function resolverDegrauPorResolucao(presetId, dimensoesDaFonte) {
  const substituto = SUBSTITUTOS_SEM_UPSCALE[presetId];
  if (!substituto || !dimensoesDaFonte) return presetId;
  const aspect = dimensoesDaFonte.width / dimensoesDaFonte.height;
  const alvoCss = alvoCssDoAspecto(aspect);
  return dimensoesDaFonte.width < alvoCss ? substituto : presetId;
}

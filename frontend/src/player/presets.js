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
  Downscale,
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

// Estrutura comum a boa parte dos presets: clamp → restore → upscale(x2) → downscale.
// Passe duplo (`aa-vl`) e sem-restore (`c-vl`) ficam de fora por terem
// topologia diferente.
function buildStandardPipeline({ device, inputTexture, dims, Restore, Upscale }) {
  const clamp = new ClampHighlights({ device, inputTexture });
  const restore = new Restore({ device, inputTexture: clamp.getOutputTexture() });
  const upscale = new Upscale({ device, inputTexture: restore.getOutputTexture() });
  const down = new Downscale({ device, inputTexture: upscale.getOutputTexture(), targetDimensions: dims });
  return [clamp, restore, upscale, down];
}

// Cada preset carrega label (pt-br) + fábrica do pipelineBuilder.
// `build(dims)` recebe as dimensões nativas do vídeo (só conhecidas após
// loadedmetadata) e devolve a função (device, inputTexture) => Anime4KPipeline[]
// esperada por render().
//
// Presets UL (a-ul, aa-ul, aa-ul-vl, aa-vl-vl) e GAN (gan-*) do protótipo
// (teste/bench.js) foram excluídos: travam na RX 580 atual (ESPECIFICACAO
// §11.2/11.3). Reintroduzir fica condicionado ao gatilho de troca de GPU
// (ESPECIFICACAO §12).
export const PRESETS = {
  original: {
    label: 'Original',
    build() {
      return (_device, inputTexture) => [new Original({ inputTexture })];
    },
  },
  'a-m': {
    label: 'Anime4K A · M',
    build(dims) {
      return (device, inputTexture) =>
        buildStandardPipeline({ device, inputTexture, dims, Restore: CNNM, Upscale: CNNx2M });
    },
  },
  'a-vl': {
    label: 'Anime4K A · VL',
    build(dims) {
      return (device, inputTexture) =>
        buildStandardPipeline({ device, inputTexture, dims, Restore: CNNVL, Upscale: CNNx2VL });
    },
  },
  // Igual ao 'a-vl' sem o passe CNNx2VL: com a fonte já em ~1080p e o alvo
  // mirando a tela, o x2 gera 2160p que o Downscale final joga fora de volta
  // — supersampling caro, não resolução. Tirar o x2 mantém a fonte inteira
  // entrando na CNN de restauração (o que limpa o anime) e corta ~metade do
  // custo. Degrau "mais fluidez sem trocar de algoritmo" da escada automática.
  'a-vl-1x': {
    label: 'Anime4K A · VL (sem upscale)',
    escalaMax: 1, // sem CNNx2: a CNN devolve na resolução da fonte, nunca mais
    build(dims) {
      return (device, inputTexture) => {
        const clamp = new ClampHighlights({ device, inputTexture });
        const restore = new CNNVL({ device, inputTexture: clamp.getOutputTexture() });
        const down = new Downscale({ device, inputTexture: restore.getOutputTexture(), targetDimensions: dims });
        return [clamp, restore, down];
      };
    },
  },
  'aa-vl': {
    label: 'Anime4K A+A · VL',
    build(dims) {
      return (device, inputTexture) => {
        const clamp = new ClampHighlights({ device, inputTexture });
        const restore1 = new CNNVL({ device, inputTexture: clamp.getOutputTexture() });
        const upscale1 = new CNNx2VL({ device, inputTexture: restore1.getOutputTexture() });
        const restore2 = new CNNM({ device, inputTexture: upscale1.getOutputTexture() });
        const down = new Downscale({ device, inputTexture: restore2.getOutputTexture(), targetDimensions: dims });
        return [clamp, restore1, upscale1, restore2, down];
      };
    },
  },
  'b-vl': {
    label: 'Anime4K B · VL',
    build(dims) {
      return (device, inputTexture) =>
        buildStandardPipeline({ device, inputTexture, dims, Restore: CNNSoftVL, Upscale: CNNx2VL });
    },
  },
  'c-vl': {
    label: 'Anime4K C · VL + Denoise',
    build(dims) {
      return (device, inputTexture) => {
        const clamp = new ClampHighlights({ device, inputTexture });
        const upscale = new DenoiseCNNx2VL({ device, inputTexture: clamp.getOutputTexture() });
        const down = new Downscale({ device, inputTexture: upscale.getOutputTexture(), targetDimensions: dims });
        return [clamp, upscale, down];
      };
    },
  },
  // `strength`/`strength2` nascem zerados na lib — sem updateParam() explícito
  // o shader do BilateralMean divide por zero (intensitySigma=0 no
  // denominador do gaussianVec). Valores abaixo não são chute: vêm do README
  // oficial da lib (Anime4KWebBoost/Anime4K-WebGPU) — denoise calibrado em
  // intensitySigma=0.2/spatialSigma=2, deblur em strength=7. Conferido também
  // na WGSL (`strength`=intensitySigma, `strength2`=spatialSigma, no shader
  // do BilateralMean).
  'aa-vl-denoise': {
    label: 'Anime4K A+A · VL + Denoise',
    build(dims) {
      return (device, inputTexture) => {
        const clamp = new ClampHighlights({ device, inputTexture });
        // Denoise logo após o clamp, antes do restore — limpa a fonte antes
        // da CNN "restaurar" detalhe em cima de ruído (mesmo lugar que o
        // `c-vl` já usa pro denoise combinado).
        const denoise = new BilateralMean({ device, inputTexture: clamp.getOutputTexture() });
        denoise.updateParam('strength', 0.2);
        denoise.updateParam('strength2', 2);
        const restore1 = new CNNVL({ device, inputTexture: denoise.getOutputTexture() });
        const upscale1 = new CNNx2VL({ device, inputTexture: restore1.getOutputTexture() });
        const restore2 = new CNNM({ device, inputTexture: upscale1.getOutputTexture() });
        const down = new Downscale({ device, inputTexture: restore2.getOutputTexture(), targetDimensions: dims });
        return [clamp, denoise, restore1, upscale1, restore2, down];
      };
    },
  },
  'aa-vl-deblur': {
    label: 'Anime4K A+A · VL + Deblur',
    build(dims) {
      return (device, inputTexture) => {
        const clamp = new ClampHighlights({ device, inputTexture });
        const restore1 = new CNNVL({ device, inputTexture: clamp.getOutputTexture() });
        const upscale1 = new CNNx2VL({ device, inputTexture: restore1.getOutputTexture() });
        const restore2 = new CNNM({ device, inputTexture: upscale1.getOutputTexture() });
        // Deblur como último passe de conteúdo, antes do Downscale — afia o
        // resultado já restaurado/upscalado, não a fonte crua.
        const deblur = new DoG({ device, inputTexture: restore2.getOutputTexture() });
        deblur.updateParam('strength', 7);
        const down = new Downscale({ device, inputTexture: deblur.getOutputTexture(), targetDimensions: dims });
        return [clamp, restore1, upscale1, restore2, deblur, down];
      };
    },
  },
};

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

// Resolução-alvo do Downscale final de cada preset.
//
// Mira sempre o tamanho equivalente a TELA CHEIA (o maior que o .frame algum
// dia vai ocupar nesta sessão), não o tamanho atual — de propósito, mesmo em
// modo janela. Motivo: o bundle real da lib (checado via curl, não
// documentação) mostra que render() cria um GPUDevice novo e reconfigura o
// canvas a cada chamada, sem devolver handle pra parar o
// requestVideoFrameCallback recursivo da chamada anterior — reconstruir o
// pipeline ao entrar/sair de tela cheia vazaria o device antigo e deixaria
// dois loops rodando. Miramos o maior caso de uma vez; baixar de uma
// resolução maior pro tamanho da janela é seguro (downscale não borra).
//
// Dois tetos sobre esse alvo:
//  - Resolução CSS da tela, SEM multiplicar por devicePixelRatio. Num painel
//    1080p o DPR > 1 vem de zoom do navegador / escalonamento do SO, não de
//    pixels físicos a mais — supersamplear por cima disso numa GPU fraca
//    custa caro sem ganho visível. (Um painel HiDPI real vai querer o fator
//    de volta; revisitar quando aparecer.)
//  - `escalaMax` do preset: quanto a CNN de upscale multiplica a fonte (2 nos
//    presets com CNNx2, 1 no 'a-vl-1x'). Passar disso é o Downscale final
//    *magnificando* com bilinear — borra e gasta à toa.
//
// "original" fica de fora: é a referência "fonte pura sem shader".
export function calcularDimensoesDeSaida(presetId, video) {
  if (presetId === 'original') {
    return { width: video.videoWidth, height: video.videoHeight };
  }
  const videoAspect = video.videoWidth / video.videoHeight;
  const screenCssWidth = window.screen?.width || window.innerWidth;
  const screenCssHeight = window.screen?.height || window.innerHeight;
  // Em tela cheia o canvas é "contained": o limite é o menor entre a largura
  // da tela e a largura que a altura da tela comporta nessa proporção.
  const alvoCss = Math.min(screenCssWidth, screenCssHeight * videoAspect);
  const escalaMax = PRESETS[presetId]?.escalaMax ?? 2;
  const width = Math.round(Math.min(alvoCss, video.videoWidth * escalaMax));
  const height = Math.round(width / videoAspect);
  return { width, height };
}

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

// Ordem de fallback por custo de GPU decrescente — o degrau mais pesado
// (melhor qualidade) primeiro. Consumido hoje por SeletorDePreset.jsx; o
// TODO de degradação automática (useTelemetriaDeVideo.js) também vai
// percorrer esta lista quando for implementado.
export const ESCADA_DE_DEGRADACAO = ['aa-vl-deblur', 'aa-vl', 'a-vl', 'b-vl', 'c-vl', 'a-m', 'original'];

export const PRESET_PADRAO = 'aa-vl-deblur';

// Resolução-alvo do Downscale de cada preset. Por padrão mira a resolução
// nativa do vídeo (comportamento antigo) — mas isso faz o navegador aplicar
// um SEGUNDO resize (compositor, bilinear genérico) por cima do que o shader
// Anime4K já produziu, pra encaixar no tamanho CSS do .frame; em telas com
// devicePixelRatio > 1 esse segundo resize pode até estar ampliando os
// pixels nativos além do que existem, borrando o resultado.
//
// Mira sempre o tamanho físico equivalente a TELA CHEIA (o maior que o
// .frame algum dia vai ocupar nesta sessão), não o tamanho atual — de
// propósito, mesmo em modo janela. Motivo: o bundle real da lib
// (checado via curl, não documentação) mostra que render() cria um
// GPUDevice novo e reconfigura o canvas a cada chamada, sem devolver
// nenhum handle pra parar o requestVideoFrameCallback recursivo da chamada
// anterior — reconstruir o pipeline ao entrar/sair de tela cheia vazaria o
// device antigo e deixaria dois loops rodando ao mesmo tempo. Miramos o
// maior caso de uma vez em troca: baixar de uma resolução maior pro
// tamanho da janela é seguro (downscale não borra — é o mesmo princípio de
// supersampling); só subir resolução borraria, e isso nunca acontece nessa
// abordagem. "original" fica de fora: é a referência "1080p puro sem
// shader", mudar a resolução dele quebraria o propósito de controle.
export function calcularDimensoesDeSaida(presetId, video) {
  if (presetId === 'original') {
    return { width: video.videoWidth, height: video.videoHeight };
  }
  const videoAspect = video.videoWidth / video.videoHeight;
  const screenCssWidth = window.screen?.width || window.innerWidth;
  const screenCssHeight = window.screen?.height || window.innerHeight;
  // Maior largura CSS que o canvas pode chegar a ocupar: em tela cheia ele é
  // "contained", então o limite é o menor entre a largura da tela e a largura
  // que a altura da tela comporta nessa proporção.
  const fullscreenCssWidth = Math.min(screenCssWidth, screenCssHeight * videoAspect);
  const width = Math.round(fullscreenCssWidth * (window.devicePixelRatio || 1));
  const height = Math.round(width / videoAspect);
  return { width, height };
}

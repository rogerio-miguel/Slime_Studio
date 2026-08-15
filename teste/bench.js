// Import via default + desestruturação (não named imports): o pacote é
// publicado só como CommonJS (bundle webpack) e o módulo que o esm.sh gera
// não tem NENHUM named export próprio — só `export { ... as default }`, com
// o objeto inteiro do CJS (render, ClampHighlights, CNNM, ...) pendurado
// nesse default. Named imports estáticos (`import { CNNM } from ...`) ou
// `import * as X` falham do mesmo jeito; só o default funciona.
import Anime4K from 'https://esm.sh/anime4k-webgpu@1.0.0';

const {
  render,
  ClampHighlights,
  Downscale,
  Original,
  CNNM,
  CNNVL,
  CNNUL,
  CNNSoftVL,
  DenoiseCNNx2VL,
  CNNx2M,
  CNNx2VL,
  CNNx2UL,
  GANUUL,
  GANx3L,
  DoG,
  BilateralMean,
} = Anime4K;

const VIDEO_FILENAME =
  '[AnimeFire.io] Tensei shitara Slime Datta Ken 4th Season - Episódio 6 (HD).mp4';

// Estrutura comum a boa parte dos presets: clamp → restore → upscale(x2) → downscale.
// Passe duplo (`aa-vl`, `aa-ul`, `aa-ul-vl`) e sem-restore (`c-vl`) ficam de fora por
// terem topologia diferente.
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
const PRESETS = {
  original: {
    label: 'Original (controle)',
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
  'a-ul': {
    label: 'Anime4K A · UL',
    build(dims) {
      return (device, inputTexture) =>
        buildStandardPipeline({ device, inputTexture, dims, Restore: CNNUL, Upscale: CNNx2UL });
    },
  },
  'aa-vl': {
    label: 'Anime4K A+A · VL (oficial)',
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
    label: 'Anime4K C · VL (denoise)',
    build(dims) {
      return (device, inputTexture) => {
        const clamp = new ClampHighlights({ device, inputTexture });
        const upscale = new DenoiseCNNx2VL({ device, inputTexture: clamp.getOutputTexture() });
        const down = new Downscale({ device, inputTexture: upscale.getOutputTexture(), targetDimensions: dims });
        return [clamp, upscale, down];
      };
    },
  },
  // --- Tier 1 (2026-08-14): variantes UL e GAN, avaliadas depois que aa-vl
  // (ModeAA oficial) se mostrou candidato de verdade, não só controle.
  'aa-ul': {
    label: 'Anime4K A+A · UL',
    build(dims) {
      return (device, inputTexture) => {
        const clamp = new ClampHighlights({ device, inputTexture });
        const restore1 = new CNNUL({ device, inputTexture: clamp.getOutputTexture() });
        const upscale1 = new CNNx2UL({ device, inputTexture: restore1.getOutputTexture() });
        const restore2 = new CNNM({ device, inputTexture: upscale1.getOutputTexture() });
        const down = new Downscale({ device, inputTexture: restore2.getOutputTexture(), targetDimensions: dims });
        return [clamp, restore1, upscale1, restore2, down];
      };
    },
  },
  'gan-a-ul': {
    label: 'Anime4K GAN A · UL',
    build(dims) {
      return (device, inputTexture) =>
        buildStandardPipeline({ device, inputTexture, dims, Restore: GANUUL, Upscale: CNNx2UL });
    },
  },
  'gan-x3-cnn': {
    label: 'Anime4K GAN x3 · CNN',
    build(dims) {
      // GANx3L faz upscale 3x (não 2x como os CNNx2*), mas buildStandardPipeline
      // não assume fator fixo em lugar nenhum: o Downscale final já mira `dims`
      // (dimensões absolutas), então o fator de upscale do estágio anterior é
      // irrelevante pra interface.
      return (device, inputTexture) =>
        buildStandardPipeline({ device, inputTexture, dims, Restore: CNNUL, Upscale: GANx3L });
    },
  },
  'gan-x3': {
    label: 'Anime4K GAN x3 · GAN',
    build(dims) {
      return (device, inputTexture) =>
        buildStandardPipeline({ device, inputTexture, dims, Restore: GANUUL, Upscale: GANx3L });
    },
  },
  'aa-ul-vl': {
    label: 'Anime4K A+A · UL→VL',
    build(dims) {
      return (device, inputTexture) => {
        const clamp = new ClampHighlights({ device, inputTexture });
        const restore1 = new CNNUL({ device, inputTexture: clamp.getOutputTexture() });
        const upscale1 = new CNNx2UL({ device, inputTexture: restore1.getOutputTexture() });
        const restore2 = new CNNVL({ device, inputTexture: upscale1.getOutputTexture() });
        const down = new Downscale({ device, inputTexture: restore2.getOutputTexture(), targetDimensions: dims });
        return [clamp, restore1, upscale1, restore2, down];
      };
    },
  },
  // --- Pós-Tier 1 (2026-08-14): `aa-vl` (vencedor confirmado, ver hub) sustenta
  // `?rate=1.5` com drop ~ruído (2,2%) e só desmorona entre 1,5x-2x — ou seja,
  // sobra ~30%+ de orçamento de GPU não usado a 1x. Os 5 do Tier 1 pularam
  // restore1/upscale1 de VL pra UL (salto grande, travou em todos). Este
  // candidato é um incremento bem menor: só o restore2 sobe de CNNM (padrão
  // do `aa-vl` oficial) pra CNNVL, sem tocar nos dois primeiros estágios.
  'aa-vl-vl': {
    label: 'Anime4K A+A · VL→VL',
    build(dims) {
      return (device, inputTexture) => {
        const clamp = new ClampHighlights({ device, inputTexture });
        const restore1 = new CNNVL({ device, inputTexture: clamp.getOutputTexture() });
        const upscale1 = new CNNx2VL({ device, inputTexture: restore1.getOutputTexture() });
        const restore2 = new CNNVL({ device, inputTexture: upscale1.getOutputTexture() });
        const down = new Downscale({ device, inputTexture: restore2.getOutputTexture(), targetDimensions: dims });
        return [clamp, restore1, upscale1, restore2, down];
      };
    },
  },
  // --- Tier 3 (2026-08-14): filtros de passe único (não redes), avaliados
  // em cima do vencedor `aa-vl` depois que a família de passe duplo CNN se
  // esgotou (aa-ul/aa-ul-vl/aa-vl-vl travam). `strength`/`strength2` nascem
  // zerados na lib — sem updateParam() explícito o shader do BilateralMean
  // divide por zero (intensitySigma=0 no denominador do gaussianVec). Valores
  // abaixo não são chute: vêm do README oficial da lib (Anime4KWebBoost/
  // Anime4K-WebGPU) — denoise calibrado em intensitySigma=0.2/spatialSigma=2,
  // deblur em strength=7. Conferido também na WGSL (`strength`=intensitySigma,
  // `strength2`=spatialSigma, no shader do BilateralMean).
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

const params = new URLSearchParams(location.search);
const presetId = params.get('preset');
const preset = PRESETS[presetId];

// `?rate=` varre o playbackRate pra medir custo real de GPU (ver comentário
// junto de `video.playbackRate` em initBench para o racional completo).
const rateParam = params.get('rate');
const rateRaw = rateParam === null ? NaN : Number(rateParam);
const rate = Number.isFinite(rateRaw) ? Math.min(4, Math.max(0.25, rateRaw)) : 1;

const video = document.getElementById('source-video');
const canvas = document.getElementById('output-canvas');
const frame = document.getElementById('frame');
const fullscreenStage = document.getElementById('fullscreen-stage');
const controls = document.getElementById('controls');
const fatalError = document.getElementById('fatal-error');
const pageTitle = document.getElementById('page-title');

function showFatalError(message) {
  fatalError.textContent = message;
  fatalError.hidden = false;
  frame.hidden = true;
  controls.hidden = true;
}

// --- Áudio cinema (bass boost + compressor + crossfeed pra fone) ---------
//
// Subsistema de áudio independente do pipeline de imagem acima: não lê nem
// escreve nada dos presets/WebGPU, só se pendura no <video> via Web Audio.
//
// Precisa ficar ANTES do gatilho `if (!navigator.gpu) {...} else { initBench() }`
// logo abaixo, não depois: esse gatilho chama initBench() de forma síncrona,
// que por sua vez chama wireControls() -> syncCinemaButton() também de forma
// síncrona, tudo ainda dentro da execução linear de topo do módulo. Se este
// bloco ficasse fisicamente depois do gatilho (como numa versão anterior),
// `cinemaEnabled`/`cinemaAudio` (let) estariam na temporal dead zone nesse
// instante — ReferenceError, que aborta o módulo inteiro e derruba em
// cascata até coisas sem relação nenhuma com áudio (ex. constantes/funções
// declaradas mais abaixo, que nunca chegariam a ser inicializadas).

const CINEMA_AUDIO_STORAGE_KEY = 'slime.cinemaAudio';
// Ganho do ramo processado quando "cinema" está ligado — >1 porque a cadeia
// (highshelf -10dB no crossfeed, lowshelf/peaking, compressor com threshold
// -20dB) perde energia percebida ao longo do caminho; 2.0 é o "makeup gain"
// que compensa isso. Nomeado em vez de deixar o número solto nos dois
// pontos (criação do grafo e toggle) onde ele é usado.
const CINEMA_WET_LEVEL = 2.0;
const CINEMA_CROSSFADE_S = 0.05;

let cinemaAudio = null; // refs do grafo (context, wetGain, dryGain) — null até o primeiro gesto
let cinemaAudioFailed = false; // não tentar de novo depois de um erro de construção
let cinemaEnabled = readCinemaPreference();

function readCinemaPreference() {
  try {
    return localStorage.getItem(CINEMA_AUDIO_STORAGE_KEY) === '1';
  } catch {
    return false; // localStorage bloqueado (ex. modo anônimo) — default desligado, não é erro fatal
  }
}

function writeCinemaPreference(enabled) {
  try {
    localStorage.setItem(CINEMA_AUDIO_STORAGE_KEY, enabled ? '1' : '0');
  } catch {
    // best-effort, mesmo espírito de sendTelemetry — falha de storage não pode quebrar o toggle
  }
}

// Crossfade sempre por rampa de ganho num grafo fixo, nunca por
// desconectar/reconectar nós em runtime: reconectar no meio da reprodução
// cortaria o áudio por alguns ms (o novo nó ainda não processou nada) e sob
// Chrome pode disparar glitches audíveis de click/pop. Os dois ramos (dry
// direto e wet processado) ficam sempre conectados no destination; só o
// gain de cada um sobe/desce.
function rampTo(param, value, ctx) {
  const now = ctx.currentTime;
  param.cancelScheduledValues(now);
  param.setValueAtTime(param.value, now);
  param.linearRampToValueAtTime(value, now + CINEMA_CROSSFADE_S);
}

function buildCinemaAudioGraph(videoEl, startEnabled) {
  const ctx = new (window.AudioContext || window.webkitAudioContext)();
  const source = ctx.createMediaElementSource(videoEl);

  const dryGain = ctx.createGain();
  const subsonic = ctx.createBiquadFilter();
  subsonic.type = 'highpass';
  subsonic.frequency.value = 30;
  subsonic.Q.value = 0.707;

  const splitter = ctx.createChannelSplitter(2);
  const merger = ctx.createChannelMerger(2);

  // Crossfeed via highshelf (corta agudo), não lowpass: um lowpass também
  // atenuaria o grave que vai pro canal oposto, e é justo o grave que
  // precisa vazar pra simular a cabeça absorvendo o agudo cruzado — um
  // fone não tem "acústica de sala" nenhuma entre os dois canais, então
  // sem esse vazamento o estéreo extremo (comum em anime/BGM) soa
  // artificialmente separado. highshelf deixa o grave cruzado passar e só
  // suaviza o agudo, que é o que realmente soaria "de dentro da cabeça".
  const shelfL = ctx.createBiquadFilter();
  shelfL.type = 'highshelf';
  shelfL.frequency.value = 700;
  shelfL.gain.value = -10;
  const shelfR = ctx.createBiquadFilter();
  shelfR.type = 'highshelf';
  shelfR.frequency.value = 700;
  shelfR.gain.value = -10;

  // Delay de ~0.3ms simula o pequeno atraso interaural (ITD) que o canal
  // cruzado teria ao chegar no ouvido oposto numa escuta em caixas reais.
  const delayL = new DelayNode(ctx, { maxDelayTime: 0.02 });
  delayL.delayTime.value = 0.0003;
  const delayR = new DelayNode(ctx, { maxDelayTime: 0.02 });
  delayR.delayTime.value = 0.0003;

  const crossL = ctx.createGain();
  crossL.gain.value = 0.35;
  const crossR = ctx.createGain();
  crossR.gain.value = 0.35;

  const bassShelf = ctx.createBiquadFilter();
  bassShelf.type = 'lowshelf';
  bassShelf.frequency.value = 90;
  bassShelf.gain.value = 6;

  const mudCut = ctx.createBiquadFilter();
  mudCut.type = 'peaking';
  mudCut.frequency.value = 300;
  mudCut.Q.value = 1.0;
  mudCut.gain.value = -2;

  // Compressor por ÚLTIMO, depois do EQ: o bass boost (+6dB em 90Hz) é
  // justo o tipo de mudança que reduz headroom e pode gerar clipping — o
  // compressor precisa ver o sinal já com esse boost aplicado pra nivelar
  // de verdade os picos resultantes. Compressor antes do EQ deixaria o
  // boost de graves furar o teto sem controle.
  const compressor = ctx.createDynamicsCompressor();
  compressor.threshold.value = -20;
  compressor.knee.value = 12;
  compressor.ratio.value = 4;
  compressor.attack.value = 0.01;
  compressor.release.value = 0.25;

  const wetGain = ctx.createGain();

  // fiação — ver diagrama de nós no plano; splitter→merger tem 3 caminhos
  // em paralelo por canal (direto + crossfeed do canal oposto).
  source.connect(dryGain);
  dryGain.connect(ctx.destination);

  source.connect(subsonic);
  subsonic.connect(splitter);

  splitter.connect(merger, 0, 0);
  splitter.connect(merger, 1, 1);

  splitter.connect(shelfL, 0);
  shelfL.connect(delayL);
  delayL.connect(crossL);
  crossL.connect(merger, 0, 1); // L cruza pro lado direito do merger

  splitter.connect(shelfR, 1);
  shelfR.connect(delayR);
  delayR.connect(crossR);
  crossR.connect(merger, 0, 0); // R cruza pro lado esquerdo do merger

  merger.connect(bassShelf);
  bassShelf.connect(mudCut);
  mudCut.connect(compressor);
  compressor.connect(wetGain);
  wetGain.connect(ctx.destination);

  // Só na criação do grafo os ganhos são setados direto (sem rampa): nenhum
  // áudio passou pelos nós ainda, não há o que suavizar. Rampas (rampTo)
  // entram só no toggle em runtime, ver setCinemaAudio().
  wetGain.gain.value = startEnabled ? CINEMA_WET_LEVEL : 0;
  dryGain.gain.value = startEnabled ? 0 : 1;

  return { context: ctx, wetGain, dryGain };
}

// Inicialização lazy, disparada só dentro de gesto real do usuário (clique
// no botão ou tecla): AudioContext/createMediaElementSource exigem gesto
// pela autoplay policy, e criar isso fora de um handler de gesto (ex. no
// loadedmetadata) deixaria a página MUDA — createMediaElementSource desvia
// o áudio nativo do <video> pro grafo assim que é chamado, mesmo que o
// contexto resultante nasça suspenso.
function ensureCinemaAudio() {
  if (cinemaAudio || cinemaAudioFailed) {
    cinemaAudio?.context.resume().catch(() => {});
    return cinemaAudio;
  }
  try {
    cinemaAudio = buildCinemaAudioGraph(video, cinemaEnabled);
  } catch (err) {
    cinemaAudioFailed = true;
    console.error('[Áudio] Falha ao montar a cadeia cinema, seguindo com áudio nativo:', err);
    document.getElementById('btn-cinema').disabled = true;
    return null;
  }
  cinemaAudio.context.resume().catch(() => {});
  return cinemaAudio;
}

function setCinemaAudio(enabled) {
  cinemaEnabled = enabled;
  writeCinemaPreference(enabled);
  syncCinemaButton();
  if (!cinemaAudio) return; // grafo ainda não existe (nenhum gesto aconteceu) — só a preferência foi salva
  const { context, wetGain, dryGain } = cinemaAudio;
  rampTo(wetGain.gain, enabled ? CINEMA_WET_LEVEL : 0, context);
  rampTo(dryGain.gain, enabled ? 0 : 1, context);
}

function syncCinemaButton() {
  const btnCinema = document.getElementById('btn-cinema');
  btnCinema.setAttribute('aria-pressed', String(cinemaEnabled));
}

if (!navigator.gpu) {
  showFatalError(
    'WebGPU não está disponível neste navegador. Use Chrome/Edge com WebGPU habilitado (verifique chrome://gpu).'
  );
} else if (!preset) {
  const validIds = Object.keys(PRESETS).join(', ');
  showFatalError(
    `Preset desconhecido: "${presetId ?? ''}". Presets válidos: ${validIds}. Volte ao hub e escolha um card.`
  );
} else {
  initBench();
}

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

function targetDimensionsFor(presetId, video) {
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

// render() da anime4k-webgpu cria o GPUAdapter/GPUDevice internamente e nunca
// os expõe — captura via patch de instância (não de GPUAdapter.prototype: o
// blast radius fica restrito ao adapter realmente devolvido por essa chamada,
// mais fácil de revisar do que alterar o protótipo global) pra recuperar os
// handles reais usados pelo pipeline. Ver motivo completo no comentário
// dentro de initBench(), junto da chamada.
let capturedAdapter = null;
let capturedDevice = null;

function captureGpuHandles() {
  const originalRequestAdapter = navigator.gpu.requestAdapter.bind(navigator.gpu);
  navigator.gpu.requestAdapter = async (...args) => {
    const adapter = await originalRequestAdapter(...args);
    if (adapter) {
      capturedAdapter = adapter;
      const originalRequestDevice = adapter.requestDevice.bind(adapter);
      adapter.requestDevice = async (...deviceArgs) => {
        const device = await originalRequestDevice(...deviceArgs);
        capturedDevice = device;
        return device;
      };
    }
    return adapter;
  };
}

// Destrói o device explicitamente ao sair da página, em vez de depender do
// Chrome reciclar sozinho: recarregar rápido (ex. preset travando) empilha
// GPUDevices vivos porque render() nunca chama destroy() — telemetria real
// (bench_results.ndjson) mostra dropped-frames subindo de ~0% na 1ª carga
// pra 50-68% na 4ª/5ª carga em sequência rápida. `event.persisted` indica
// que a página está indo pro bfcache (não sendo destruída de fato) — nesse
// caso destruir o device quebraria a página se o usuário voltar com o botão
// "voltar", então pulamos.
window.addEventListener('pagehide', (event) => {
  if (event.persisted) return;
  capturedDevice?.destroy();
  cinemaAudio?.context.close().catch(() => {});
});

function initBench() {
  document.title = `Slime Studio — ${preset.label}`;
  pageTitle.textContent = preset.label;

  video.src = encodeURIComponent(VIDEO_FILENAME);

  video.addEventListener('error', () => {
    const detail = video.error ? video.error.message : 'desconhecido';
    showFatalError(`Erro ao carregar o vídeo: ${detail}`);
  });

  video.addEventListener(
    'loadedmetadata',
    async () => {
      const dims = targetDimensionsFor(presetId, video);
      canvas.width = dims.width;
      canvas.height = dims.height;
      const pipelineBuilder = preset.build(dims);

      // A GPU só desenha 1x por frame de vídeo (render() usa
      // requestVideoFrameCallback internamente), então a 24fps o orçamento
      // efetivo é sempre ~41ms/frame, não importa quão caro seja o shader —
      // por isso presets diferentes tendem a aparecer com cadência parecida
      // no HUD. Acelerar playbackRate encolhe esse orçamento pra ~41/rate ms
      // e expõe o preset que não aguenta o custo real.
      video.playbackRate = rate;
      if (rate > 1) {
        video.muted = true;
        syncMuteButton(true);
      }

      // render() da anime4k-webgpu@1.0.0 (bundle CJS sem API pública
      // documentada) não devolve o GPUDevice nem qualquer handle pra ele —
      // cria e encapsula tudo internamente via navigator.gpu.requestAdapter()
      // / adapter.requestDevice(). captureGpuHandles() troca essas duas
      // funções por wrappers, só na instância retornada (nunca em
      // GPUAdapter.prototype), que guardam o adapter/device reais assim que
      // são criados. Chamada de forma síncrona aqui, antes do await, pra
      // garantir que o patch já esteja instalado quando render() pedir o
      // adapter internamente. Resolve de uma vez o vazamento de GPUDevice
      // entre recargas (destroy() explícito no pagehide, acima) e libera o
      // device real pras Tarefas 3/4 abaixo — um device paralelo aberto via
      // navigator.gpu.requestDevice() direto não serviria, pois seria
      // diferente do que o pipeline do render() efetivamente usa.
      captureGpuHandles();

      try {
        await render({ video, canvas, pipelineBuilder });
      } catch (err) {
        capturedDevice?.destroy();
        showFatalError(`Falha ao inicializar WebGPU: ${err.message}`);
        return;
      }

      if (!capturedDevice) {
        console.error('[Anime4K] Falha ao capturar GPUDevice — vazamento de GPU NÃO resolvido nesta sessão.');
      }

      capturedDevice?.lost.then((info) => {
        if (info.reason === 'destroyed') return; // esperado: foi o nosso próprio destroy() no pagehide
        showFatalError(`GPU perdeu o device (${info.reason}): ${info.message}`);
      });
      capturedDevice?.addEventListener('uncapturederror', (event) => {
        console.error('[Anime4K] WebGPU uncaptured error:', event.error);
      });

      startHudLoop();
      startAmbientGlow();
    },
    { once: true }
  );

  const controlRefs = wireControls();
  wireKeyboardShortcuts(controlRefs);
}

function formatTime(seconds) {
  if (!Number.isFinite(seconds)) return '0:00';
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60)
    .toString()
    .padStart(2, '0');
  return `${m}:${s}`;
}

// Reusado tanto pelo clique manual quanto pelo mute automático de `?rate=`
// (ver comentário junto de `video.playbackRate` em initBench), pra nunca
// deixar o ícone/aria-label do botão dessincronizado do estado real.
function syncMuteButton(muted) {
  const btnMute = document.getElementById('btn-mute');
  btnMute.textContent = muted ? '🔇' : '🔊';
  btnMute.setAttribute('aria-label', muted ? 'Ativar som' : 'Mudo');
}

function wireControls() {
  const btnPlay = document.getElementById('btn-play');
  const seek = document.getElementById('seek');
  const timeDisplay = document.getElementById('time-display');
  const btnMute = document.getElementById('btn-mute');
  const volume = document.getElementById('volume');
  const btnFullscreen = document.getElementById('btn-fullscreen');
  const btnHud = document.getElementById('btn-hud');
  const btnCinema = document.getElementById('btn-cinema');
  const hud = document.getElementById('hud');

  let seeking = false;

  function togglePlay() {
    // Gesto do usuário (clique/tecla chega até aqui) — ponto de entrada
    // pro áudio cinema quando o play é o primeiro gesto da sessão.
    ensureCinemaAudio();
    if (video.paused) video.play();
    else video.pause();
  }

  function toggleHud() {
    hud.hidden = !hud.hidden;
  }

  btnPlay.addEventListener('click', togglePlay);
  video.addEventListener('play', () => {
    btnPlay.textContent = '⏸';
    btnPlay.setAttribute('aria-label', 'Pausar');
  });
  // Rede de segurança, não criação: se o navegador suspender o AudioContext
  // sozinho (ex. depois de uma pausa longa), retoma ao voltar a tocar. Não
  // cria o grafo aqui — só ensureCinemaAudio() (chamado a partir de gesto
  // real) faz isso.
  video.addEventListener('play', () => {
    cinemaAudio?.context.resume().catch(() => {});
  });
  video.addEventListener('pause', () => {
    btnPlay.textContent = '▶';
    btnPlay.setAttribute('aria-label', 'Reproduzir');
  });

  video.addEventListener('timeupdate', () => {
    if (!seeking && video.duration) {
      seek.value = String((video.currentTime / video.duration) * 100);
    }
    timeDisplay.textContent = `${formatTime(video.currentTime)} / ${formatTime(video.duration)}`;
  });

  seek.addEventListener('input', () => {
    seeking = true;
    if (video.duration) video.currentTime = (Number(seek.value) / 100) * video.duration;
  });
  seek.addEventListener('change', () => {
    seeking = false;
  });

  btnMute.addEventListener('click', () => {
    video.muted = !video.muted;
    syncMuteButton(video.muted);
  });

  volume.addEventListener('input', () => {
    video.volume = Number(volume.value);
    video.muted = video.volume === 0;
  });

  btnFullscreen.addEventListener('click', () => {
    if (!document.fullscreenElement) {
      fullscreenStage.requestFullscreen?.();
    } else {
      document.exitFullscreen?.();
    }
  });

  btnHud.addEventListener('click', toggleHud);

  syncCinemaButton(); // aplica o estado restaurado do localStorage ao carregar a página
  btnCinema.addEventListener('click', () => {
    ensureCinemaAudio();
    setCinemaAudio(!cinemaEnabled);
  });

  return { togglePlay, toggleHud, btnMute, btnFullscreen, btnCinema, volume };
}

function wireKeyboardShortcuts({ togglePlay, toggleHud, btnMute, btnFullscreen, btnCinema, volume }) {
  document.addEventListener('keydown', (event) => {
    if (event.target instanceof HTMLInputElement || event.target instanceof HTMLButtonElement) return;

    switch (event.key.toLowerCase()) {
      case ' ':
        event.preventDefault();
        togglePlay();
        break;
      case 'arrowleft':
        video.currentTime = Math.max(0, video.currentTime - 5);
        break;
      case 'arrowright':
        video.currentTime = Math.min(video.duration || Infinity, video.currentTime + 5);
        break;
      case 'arrowup':
        event.preventDefault();
        video.volume = Math.min(1, video.volume + 0.05);
        video.muted = false;
        volume.value = String(video.volume);
        break;
      case 'arrowdown':
        event.preventDefault();
        video.volume = Math.max(0, video.volume - 0.05);
        volume.value = String(video.volume);
        break;
      case 'f':
        btnFullscreen.click();
        break;
      case 'm':
        btnMute.click();
        break;
      case 'h':
        toggleHud();
        break;
      case 'c':
        btnCinema.click();
        break;
      default:
        break;
    }
  });
}

// Um id por carregamento de página, só para conseguir agrupar as amostras de
// uma mesma sessão de teste no ndjson (o usuário navega entre cards = páginas).
const RUN_ID = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;

// Best-effort: se não houver bench_server.py rodando (ex. file://, ou um
// http.server comum sem o endpoint /log), a amostra é descartada em silêncio —
// isso nunca pode quebrar a reprodução.
function sendTelemetry(sample) {
  fetch('/log', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(sample),
    keepalive: true,
  }).catch(() => {});
}

// render() já roda seu próprio loop interno de rVFC — este é um segundo loop
// independente, só para instrumentação (múltiplos rVFC concorrentes são
// suportados nativamente pelo navegador).
function startHudLoop() {
  const hudPreset = document.getElementById('hud-preset');
  const hudResolution = document.getElementById('hud-resolution');
  const hudMsFrame = document.getElementById('hud-msframe');
  const hudDropped = document.getElementById('hud-dropped');
  const hudRate = document.getElementById('hud-rate');
  const hudGpu = document.getElementById('hud-gpu');

  hudPreset.textContent = preset.label;
  hudResolution.textContent = `${canvas.width}×${canvas.height}`;
  hudRate.textContent = `${rate}x`;
  // GPUAdapter.info é atributo síncrono (GPUAdapterInfo) — não precisa await.
  const info = capturedAdapter?.info;
  hudGpu.textContent = info
    ? [info.vendor, info.architecture || info.device].filter(Boolean).join(' · ') ||
      info.description ||
      'sem detalhes'
    : 'indisponível';

  let lastTimestamp = null;
  let lastLogAt = 0;
  const LOG_INTERVAL_MS = 1000;

  function onFrame(_now, _metadata) {
    const nowMs = performance.now();
    let deltaMs = null;
    if (lastTimestamp !== null) {
      deltaMs = nowMs - lastTimestamp;
      hudMsFrame.textContent = `${deltaMs.toFixed(1)} ms (cadência, não custo de GPU)`;
    }
    lastTimestamp = nowMs;

    let dropped = null;
    let total = null;
    if (typeof video.getVideoPlaybackQuality === 'function') {
      const quality = video.getVideoPlaybackQuality();
      dropped = quality.droppedVideoFrames;
      total = quality.totalVideoFrames;
      hudDropped.textContent = `${dropped} / ${total}`;
    }

    if (deltaMs !== null && nowMs - lastLogAt >= LOG_INTERVAL_MS) {
      lastLogAt = nowMs;
      sendTelemetry({
        runId: RUN_ID,
        preset: presetId,
        rate,
        canvasWidth: canvas.width,
        canvasHeight: canvas.height,
        videoCurrentTime: video.currentTime,
        videoPaused: video.paused,
        frameDeltaMs: Number(deltaMs.toFixed(1)),
        droppedVideoFrames: dropped,
        totalVideoFrames: total,
      });
    }

    video.requestVideoFrameCallback(onFrame);
  }

  video.requestVideoFrameCallback(onFrame);
}

// Ambient glow — amostra do <video> FONTE (estilo YouTube Ambient Mode), não
// do #output-canvas WebGPU: decisão deliberada pra ficar 100% desacoplado do
// pipeline anime4k-webgpu, que já roda no limite da GPU (RX 580, ver
// CONTEXT_NEXT.md). Canvas2D é barato e não disputa device/VRAM com o
// WebGPU. Segundo rVFC independente, mesmo padrão de startHudLoop() acima
// (múltiplos rVFC concorrentes já são suportados nativamente).
function startAmbientGlow() {
  const ambientCanvas = document.getElementById('ambient-glow');
  const ctx = ambientCanvas?.getContext('2d', { alpha: false });
  if (!ctx) return;

  // Poucos pixels de propósito: drawImage encolhendo já faz a "média de cor"
  // da cena sem calcular nada na mão, e menos pixels = amostragem mais barata.
  const AMBIENT_CANVAS_WIDTH = 32;
  // Sem throttle de tempo: desenha a cada rVFC (cadência natural do vídeo,
  // ~41ms/24fps aqui). Uma versão anterior throttlava pra ~5x/s por cautela
  // com GPU, mas ficou visivelmente "travada" — 5x/s contra 24fps de vídeo
  // dá saltos grandes demais pro olho. drawImage num canvas de poucos pixels
  // via Canvas2D é barato; o cuidado original era só com o pipeline WebGPU
  // (device separado, nunca tocado aqui), não com isso.

  // Fração do vídeo-fonte considerada "borda" pra amostragem — só essa faixa
  // (não a cena inteira) alimenta o halo de cada lado. É o que dá a sensação
  // de continuação: céu claro no topo do quadro vira halo claro só em cima,
  // chão escuro embaixo vira halo escuro só embaixo, em vez de uma média
  // única do frame borrando os 4 lados pra cor igual.
  const AMBIENT_EDGE_FRACTION = 0.01;

  // Centro do canvas = o frame inteiro (mesma amostragem de antes, a tela
  // também não recorta nada — #output-canvas usa object-fit: contain, então
  // glow e cena ficam sincronizados sem matemática de crop). Margem = onde as
  // faixas de borda são esticadas pra fora; sai da mesma % que o CSS usa pra
  // esticar esse canvas pra fora do .frame (--ambient-bleed), lida daqui em
  // vez de duplicada como constante — sem isso as duas proporções (canvas
  // interno vs. caixa CSS) descasam e o "centro" do bitmap para de bater com
  // a área real do vídeo na tela.
  const bleedRaw = getComputedStyle(frame).getPropertyValue('--ambient-bleed');
  const bleedPct = parseFloat(bleedRaw);
  const bleedFraction = Number.isFinite(bleedPct) ? bleedPct / 100 : 0.1; // 0.1 = fallback do CSS

  const centerW = AMBIENT_CANVAS_WIDTH;
  const centerH = Math.round(centerW * (video.videoHeight / video.videoWidth)) || 18;
  const marginW = Math.max(1, Math.round(centerW * bleedFraction));
  const marginH = Math.max(1, Math.round(centerH * bleedFraction));
  ambientCanvas.width = centerW + 2 * marginW;
  ambientCanvas.height = centerH + 2 * marginH;

  // Cada draw funde só 30% do frame novo sobre o que já estava no canvas
  // (globalAlpha < 1, sem limpar antes) — sem isso, mesmo a 24fps, corte de
  // cena/movimento rápido faz a cor "pular" em vez de fluir. Média móvel
  // exponencial: converge pra cor real em poucos frames, mas suaviza a
  // transição — mais "extensão do vídeo" do que fotos soltas trocando. Cada
  // uma das 9 regiões abaixo (centro, 4 bordas, 4 cantos) é disjunta das
  // outras no canvas, então essa suavização por região continua correta —
  // nenhum draw pisa na área que outro acabou de atualizar.
  const AMBIENT_SMOOTHING = 0.3;

  function onFrame() {
    // Aba em segundo plano: sem efeito visível pra justificar o custo de
    // amostrar o vídeo. Fullscreen NÃO é mais motivo de skip aqui: o canvas
    // agora vive dentro de #fullscreen-stage no HTML, então o navegador
    // pinta ele normalmente quando esse elemento é o elemento fullscreen.
    if (!document.hidden) {
      const vw = video.videoWidth;
      const vh = video.videoHeight;
      const edgeW = Math.max(1, Math.round(vw * AMBIENT_EDGE_FRACTION));
      const edgeH = Math.max(1, Math.round(vh * AMBIENT_EDGE_FRACTION));

      ctx.globalAlpha = AMBIENT_SMOOTHING;

      // Centro: frame inteiro, igual à versão anterior.
      ctx.drawImage(video, marginW, marginH, centerW, centerH);

      // Bordas: só a faixa mais próxima de cada lado do vídeo, esticada pra
      // fora — a peça central do efeito "continuação" (ver AMBIENT_EDGE_FRACTION).
      ctx.drawImage(video, 0, 0, vw, edgeH, marginW, 0, centerW, marginH); // topo
      ctx.drawImage(video, 0, vh - edgeH, vw, edgeH, marginW, marginH + centerH, centerW, marginH); // baixo
      ctx.drawImage(video, 0, 0, edgeW, vh, 0, marginH, marginW, centerH); // esquerda
      ctx.drawImage(video, vw - edgeW, 0, edgeW, vh, marginW + centerW, marginH, marginW, centerH); // direita

      // Cantos: amostra do canto do vídeo, esticada no quadrado do canto —
      // sem isso os 4 retângulos de borda acima deixam os cantos do halo sem
      // desenho nenhum (cor de fundo do canvas, nunca atualizada).
      ctx.drawImage(video, 0, 0, edgeW, edgeH, 0, 0, marginW, marginH); // topo-esquerda
      ctx.drawImage(video, vw - edgeW, 0, edgeW, edgeH, marginW + centerW, 0, marginW, marginH); // topo-direita
      ctx.drawImage(video, 0, vh - edgeH, edgeW, edgeH, 0, marginH + centerH, marginW, marginH); // baixo-esquerda
      ctx.drawImage(video, vw - edgeW, vh - edgeH, edgeW, edgeH, marginW + centerW, marginH + centerH, marginW, marginH); // baixo-direita
    }
    video.requestVideoFrameCallback(onFrame);
  }

  video.requestVideoFrameCallback(onFrame);
}

// Áudio cinema (bass boost + compressor + crossfeed pra fone) ---------------
//
// Subsistema de áudio independente do pipeline de imagem: não lê nem escreve
// nada dos presets/WebGPU, só se pendura no <video> via Web Audio. Sem
// document.getElementById nenhum — este módulo só toca o <video> recebido;
// estado (preferência, erro) vive no hook useAudioCinema.js.

// Ganho do ramo processado quando "cinema" está ligado — >1 porque a cadeia
// (highshelf -10dB no crossfeed, lowshelf/peaking, compressor com threshold
// -22dB) perde energia percebida ao longo do caminho; é o "makeup gain" que
// compensa isso. Medido offline: o compressor do Chrome já aplica makeup
// próprio (+8 a +17 dB no total conforme o nível de entrada), então acima de
// ~1.4 o limitador final passa a trabalhar >2 dB em material de volume normal
// — é aí que a distorção começa. Reduzir aqui e subir o grave rende o mesmo
// grave com ~2 dB a menos de limitação.
export const CINEMA_WET_LEVEL = 1.3;
const CINEMA_CROSSFADE_S = 0.05;

// Ajustes de timbre — mexa aqui primeiro.
const GRAVE_FREQ_HZ = 110;
const GRAVE_GANHO_DB = 11;
// Harmônicos do grave (psicoacústico): fone raramente entrega <80 Hz, mas o
// ouvido "reconstrói" a fundamental a partir dos harmônicos. 0 desliga.
const HARMONICOS_GANHO = 0.4;
const HARMONICOS_CORTE_HZ = 100;
const PRESENCA_GANHO_DB = 2.5; // clareza de voz (3 kHz)

// Crossfade sempre por rampa de ganho num grafo fixo, nunca por
// desconectar/reconectar nós em runtime: reconectar no meio da reprodução
// cortaria o áudio por alguns ms (o novo nó ainda não processou nada) e sob
// Chrome pode disparar glitches audíveis de click/pop. Os dois ramos (dry
// direto e wet processado) ficam sempre conectados no destination; só o
// gain de cada um sobe/desce.
export function aplicarRampa(param, valor, ctx) {
  const now = ctx.currentTime;
  param.cancelScheduledValues(now);
  param.setValueAtTime(param.value, now);
  param.linearRampToValueAtTime(valor, now + CINEMA_CROSSFADE_S);
}

function curvaDeSaturacao() {
  const pontos = 2048;
  const curva = new Float32Array(pontos);
  for (let i = 0; i < pontos; i++) {
    curva[i] = Math.tanh((i / (pontos - 1)) * 2 * 3 - 3);
  }
  return curva;
}

export function montarGrafoCinema(videoEl, habilitadoNoInicio) {
  const ctx = new (window.AudioContext || window.webkitAudioContext)();
  const source = ctx.createMediaElementSource(videoEl);

  const dryGain = ctx.createGain();
  const subsonic = ctx.createBiquadFilter();
  subsonic.type = 'highpass';
  subsonic.frequency.value = 30;
  subsonic.Q.value = 0.707;

  // Mono vira L+R e 5.1 vira downmix estéreo (com o centro/diálogo); sem isso
  // o splitter(2) pegaria só os canais 0 e 1 crus.
  const estereo = ctx.createGain();
  estereo.channelCount = 2;
  estereo.channelCountMode = 'explicit';
  estereo.channelInterpretation = 'speakers';

  const splitter = ctx.createChannelSplitter(2);
  const merger = ctx.createChannelMerger(2);

  // Crossfeed via highshelf (corta agudo), não lowpass: um lowpass também
  // atenuaria o grave que vai pro canal oposto, e é justo o grave que
  // precisa vazar pra simular a cabeça absorvendo o agudo cruzado — um fone
  // não tem "acústica de sala" nenhuma entre os dois canais, então sem esse
  // vazamento o estéreo extremo (comum em anime/BGM) soa artificialmente
  // separado. highshelf deixa o grave cruzado passar e só suaviza o agudo,
  // que é o que realmente soaria "de dentro da cabeça".
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

  // Compressor ANTES do realce: comprimindo depois, o grave amplificado
  // dispara a compressão e abaixa o resto junto (efeito de "bombeamento" que
  // abafa o som). Mais suave (ratio 3, ataque lento) preserva o ataque dos
  // transientes.
  const compressor = ctx.createDynamicsCompressor();
  compressor.threshold.value = -22;
  compressor.knee.value = 18;
  compressor.ratio.value = 3;
  compressor.attack.value = 0.025;
  compressor.release.value = 0.3;

  const bassShelf = ctx.createBiquadFilter();
  bassShelf.type = 'lowshelf';
  bassShelf.frequency.value = GRAVE_FREQ_HZ;
  bassShelf.gain.value = GRAVE_GANHO_DB;

  const mudCut = ctx.createBiquadFilter();
  mudCut.type = 'peaking';
  mudCut.frequency.value = 300;
  mudCut.Q.value = 1.0;
  mudCut.gain.value = -2;

  const presenca = ctx.createBiquadFilter();
  presenca.type = 'peaking';
  presenca.frequency.value = 3000;
  presenca.Q.value = 0.8;
  presenca.gain.value = PRESENCA_GANHO_DB;

  // Harmônicos do grave: isola < corte, satura (tanh gera harmônicos
  // ímpares), tira a fundamental (o shelf já a reforça) e mistura em paralelo.
  const harmGrave = ctx.createBiquadFilter();
  harmGrave.type = 'lowpass';
  harmGrave.frequency.value = HARMONICOS_CORTE_HZ;
  const harmDrive = ctx.createGain();
  harmDrive.gain.value = 2; // a curva já tem ganho 3 interno
  const harmSaturador = ctx.createWaveShaper();
  harmSaturador.curve = curvaDeSaturacao();
  harmSaturador.oversample = '4x';
  const harmSemFundamental = ctx.createBiquadFilter();
  harmSemFundamental.type = 'highpass';
  harmSemFundamental.frequency.value = HARMONICOS_CORTE_HZ * 1.3;
  const harmSemChiado = ctx.createBiquadFilter();
  harmSemChiado.type = 'lowpass';
  harmSemChiado.frequency.value = 400;
  const harmGain = ctx.createGain();
  harmGain.gain.value = HARMONICOS_GANHO;

  const mix = ctx.createGain();
  const wetGain = ctx.createGain();

  // Rede de segurança: bass boost + makeup gain podem passar de 0 dBFS, e
  // clipar degrada a qualidade mais que qualquer ganho de grave compensa.
  const limitador = ctx.createDynamicsCompressor();
  limitador.threshold.value = -2;
  limitador.knee.value = 0;
  limitador.ratio.value = 20;
  limitador.attack.value = 0.003;
  limitador.release.value = 0.1;

  // fiação — splitter→merger tem 3 caminhos em paralelo por canal (direto +
  // crossfeed do canal oposto).
  source.connect(dryGain);
  dryGain.connect(ctx.destination);

  source.connect(subsonic);
  subsonic.connect(estereo);
  estereo.connect(splitter);

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

  merger.connect(compressor);
  compressor.connect(bassShelf);
  bassShelf.connect(mudCut);
  mudCut.connect(presenca);
  presenca.connect(mix);

  compressor.connect(harmGrave);
  harmGrave.connect(harmDrive);
  harmDrive.connect(harmSaturador);
  harmSaturador.connect(harmSemFundamental);
  harmSemFundamental.connect(harmSemChiado);
  harmSemChiado.connect(harmGain);
  harmGain.connect(mix);

  mix.connect(wetGain);
  wetGain.connect(limitador);
  limitador.connect(ctx.destination);

  // Só na criação do grafo os ganhos são setados direto (sem rampa): nenhum
  // áudio passou pelos nós ainda, não há o que suavizar. Rampas
  // (aplicarRampa) entram só no ajuste em runtime, ver ajustarCinema().
  wetGain.gain.value = habilitadoNoInicio ? CINEMA_WET_LEVEL : 0;
  dryGain.gain.value = habilitadoNoInicio ? 0 : 1;

  return { context: ctx, wetGain, dryGain };
}

export function ajustarCinema(grafo, habilitado) {
  const { context, wetGain, dryGain } = grafo;
  aplicarRampa(wetGain.gain, habilitado ? CINEMA_WET_LEVEL : 0, context);
  aplicarRampa(dryGain.gain, habilitado ? 0 : 1, context);
}

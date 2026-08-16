// Áudio cinema (bass boost + compressor + crossfeed pra fone) ---------------
//
// Subsistema de áudio independente do pipeline de imagem: não lê nem escreve
// nada dos presets/WebGPU, só se pendura no <video> via Web Audio. Sem
// document.getElementById nenhum — este módulo só toca o <video> recebido;
// estado (preferência, erro) vive no hook useAudioCinema.js.

// Ganho do ramo processado quando "cinema" está ligado — >1 porque a cadeia
// (highshelf -10dB no crossfeed, lowshelf/peaking, compressor com threshold
// -20dB) perde energia percebida ao longo do caminho; 2.0 é o "makeup gain"
// que compensa isso. Nomeado em vez de deixar o número solto nos dois pontos
// (criação do grafo e ajuste) onde ele é usado.
export const CINEMA_WET_LEVEL = 2.0;
const CINEMA_CROSSFADE_S = 0.05;

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

export function montarGrafoCinema(videoEl, habilitadoNoInicio) {
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

  const bassShelf = ctx.createBiquadFilter();
  bassShelf.type = 'lowshelf';
  bassShelf.frequency.value = 90;
  bassShelf.gain.value = 6;

  const mudCut = ctx.createBiquadFilter();
  mudCut.type = 'peaking';
  mudCut.frequency.value = 300;
  mudCut.Q.value = 1.0;
  mudCut.gain.value = -2;

  // Compressor por ÚLTIMO, depois do EQ: o bass boost (+6dB em 90Hz) é justo
  // o tipo de mudança que reduz headroom e pode gerar clipping — o
  // compressor precisa ver o sinal já com esse boost aplicado pra nivelar de
  // verdade os picos resultantes. Compressor antes do EQ deixaria o boost de
  // graves furar o teto sem controle.
  const compressor = ctx.createDynamicsCompressor();
  compressor.threshold.value = -20;
  compressor.knee.value = 12;
  compressor.ratio.value = 4;
  compressor.attack.value = 0.01;
  compressor.release.value = 0.25;

  const wetGain = ctx.createGain();

  // fiação — splitter→merger tem 3 caminhos em paralelo por canal (direto +
  // crossfeed do canal oposto).
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

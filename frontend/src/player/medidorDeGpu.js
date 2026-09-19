// Mede quantos frames por segundo o pipeline Anime4K consegue *apresentar*,
// interceptando device.queue.submit. render() enfileira um submit por frame
// no seu requestVideoFrameCallback, então a taxa de submits = a taxa em que
// o canvas WebGPU está de fato atualizando.
//
// Isto substituiu uma tentativa de cronometrar o custo de GPU via
// onSubmittedWorkDone(): medido ao vivo na RX 580, aquele número quantiza no
// intervalo de frame (a promise resolve numa macrotask no ritmo do rVFC) e
// não distingue os presets — o mais pesado chegava a medir MENOS que os
// médios. A taxa de apresentação, comparada à taxa de decode do <video>
// (getVideoPlaybackQuality, que não sofre com o shader lento), é o sinal
// confiável de "a GPU não está dando conta".
//
// motorAnime4k.js cria um GPUDevice exclusivo por sessão (agora por vídeo,
// não mais por preset — trocar de preset reaproveita o mesmo device) — a
// fila é só nossa.

const MEMORIA_MS = 5000; // buffer de instantes de submit retido

// Instala o medidor sobre `device`. Devolve { disponivel, ler, encerrar }.
// `encerrar()` DEVE rodar antes de device.destroy().
export function instalarMedidorDeGpu(device) {
  const fila = device.queue;
  const submitOriginal = fila.submit.bind(fila);

  let ativo = true;
  let patchOk = true;
  const submits = []; // performance.now() de cada submit

  try {
    fila.submit = (buffers) => {
      submitOriginal(buffers);
      if (ativo) submits.push(performance.now());
    };
  } catch (err) {
    patchOk = false;
    console.warn('[medidorDeGpu] não foi possível interceptar queue.submit:', err?.message);
  }

  return {
    disponivel: patchOk,

    // fps de apresentação médio na janela. null se o patch não pegou (o
    // chamador cai no sinal reativo de frames dropados).
    ler(janelaMs = 3000) {
      if (!patchOk || !ativo) return null;
      const agora = performance.now();
      while (submits.length && agora - submits[0] > MEMORIA_MS) submits.shift();
      const naJanela = submits.filter((t) => agora - t <= janelaMs).length;
      return { fpsApresentacao: naJanela / (janelaMs / 1000), amostras: naJanela };
    },

    encerrar() {
      ativo = false;
      if (!patchOk) return;
      try {
        delete fila.submit; // volta ao método do protótipo — nunca reatribuir (deixaria own property viva)
      } catch {
        /* non-configurable: nada a fazer, o guard `ativo` já neutralizou */
      }
    },
  };
}

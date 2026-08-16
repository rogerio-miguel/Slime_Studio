// Fonte real de vídeo (URL .m3u8 via hls.js, ou qualquer formato que o
// <video> toque nativamente) — gap real, sem equivalente no protótipo
// (teste/bench.js apontava direto pra um .mp4 local via `video.src`, sem
// stack de streaming nenhuma). HLS é a entrega de produção (CLAUDE.md §3).
import Hls from 'hls.js';

function ehM3u8(url) {
  return /\.m3u8($|\?)/i.test(url);
}

function limparVideo(video) {
  video.removeAttribute('src');
  video.load();
}

// Conecta `url` ao `video`. Devolve `desconectar()`.
//
// `aoFalhar` (recebe um Error) é chamado só em erro fatal do hls.js — sem
// equivalente no protótipo porque o <video> local não tinha stack de
// streaming nenhuma; assinatura com esse terceiro parâmetro é uma escolha
// documentada aqui por não estar explícita no plano ("nunca em silêncio"
// exige algum jeito de propagar o erro pra fora do módulo).
export function conectarFonte(video, url, aoFalhar = () => {}) {
  // Setado antes de qualquer branch (HLS nativo Safari, hls.js/MSE ou
  // genérico) — não só no genérico: WebGPU importa o <video> como external
  // texture, e sem crossOrigin isso pode lançar SecurityError no Safari
  // especificamente se a origem do HLS divergir da do frontend.
  video.crossOrigin = 'anonymous';

  if (ehM3u8(url)) {
    if (video.canPlayType('application/vnd.apple.mpegurl')) {
      // Safari: HLS nativo, sem hls.js.
      video.src = url;
      return () => limparVideo(video);
    }

    if (!Hls.isSupported()) {
      aoFalhar(new Error('HLS não é suportado neste navegador.'));
      return () => {};
    }

    const hls = new Hls();
    hls.on(Hls.Events.ERROR, (_event, data) => {
      if (!data.fatal) return;
      switch (data.type) {
        case Hls.ErrorTypes.NETWORK_ERROR:
          hls.startLoad();
          break;
        case Hls.ErrorTypes.MEDIA_ERROR:
          hls.recoverMediaError();
          break;
        default:
          hls.destroy();
          aoFalhar(new Error(`Falha fatal no HLS: ${data.details}`));
          break;
      }
    });
    hls.attachMedia(video);
    hls.loadSource(url);

    return () => {
      hls.destroy();
      limparVideo(video);
    };
  }

  video.src = url;
  return () => limparVideo(video);
}

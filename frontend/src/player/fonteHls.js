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

// Erro nativo do <video> — só usado no ramo sem hls.js (Safari, único
// browser em que `Hls.isSupported()` dá false pra HLS via MSE). No ramo
// hls.js não se registra: o próprio MSE dispara `error` no <video> pra
// glitches de segmento que o hls.js já sabe recuperar (`recoverMediaError`,
// abaixo); ouvir os dois em paralelo derrubava o player como fatal no meio
// da recuperação.
function ouvirErroNativo(video, aoFalhar) {
  const aoDarErro = () => {
    const detalhe = video.error ? video.error.message : 'desconhecido';
    aoFalhar(new Error(`Erro ao carregar o vídeo: ${detalhe}`));
  };
  video.addEventListener('error', aoDarErro);
  return () => video.removeEventListener('error', aoDarErro);
}

// Conecta `url` ao `video`. Devolve `desconectar()`.
//
// `aoFalhar` (recebe um Error) é chamado só em erro fatal — sem equivalente
// no protótipo porque o <video> local não tinha stack de streaming nenhuma;
// assinatura com esse terceiro parâmetro é uma escolha documentada aqui por
// não estar explícita no plano ("nunca em silêncio" exige algum jeito de
// propagar o erro pra fora do módulo).
export function conectarFonte(video, url, aoFalhar = () => {}) {
  // Setado antes de qualquer branch (hls.js/MSE, HLS nativo Safari ou
  // genérico) — não só no genérico: WebGPU importa o <video> como external
  // texture, e sem crossOrigin isso pode lançar SecurityError no Safari
  // especificamente se a origem do HLS divergir da do frontend.
  video.crossOrigin = 'anonymous';

  if (ehM3u8(url)) {
    // `Hls.isSupported()` primeiro, não `video.canPlayType(...)` — ordem que
    // parece invertida mas é a recomendada pelo próprio hls.js: Chrome vem
    // devolvendo "maybe" nesse canPlayType (suporte nativo/experimental a
    // HLS, não só Safari mais), o que fazia o Chrome cair no ramo nativo e
    // nunca passar pelo hls.js — reproduzido manualmente via
    // canPlayType => "maybe" nesse Chrome, com o player inteiro rodando no
    // demuxer nativo, mais frágil (sem `recoverMediaError`, sem retry) e é
    // ele quem estourava DEMUXER_ERROR_COULD_NOT_PARSE num segmento que o
    // hls.js/MSE tolera. `Hls.isSupported()` já exclui Safari por conta
    // própria (Safari não suporta MSE pra HLS), então preferi-lo primeiro dá
    // hls.js em todo mundo que aguenta MSE e só sobra nativo pra quem não.
    if (Hls.isSupported()) {
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

    if (video.canPlayType('application/vnd.apple.mpegurl')) {
      // Safari: HLS nativo, sem hls.js — o <video> é a única fonte de erro.
      const pararDeOuvir = ouvirErroNativo(video, aoFalhar);
      video.src = url;
      return () => {
        pararDeOuvir();
        limparVideo(video);
      };
    }

    aoFalhar(new Error('HLS não é suportado neste navegador.'));
    return () => {};
  }

  const pararDeOuvir = ouvirErroNativo(video, aoFalhar);
  video.src = url;
  return () => {
    pararDeOuvir();
    limparVideo(video);
  };
}

import { useEffect, useRef } from 'react';

const _LIMIAR_CONCLUSAO = 0.9;
// Piso baixo de propósito: com 30s quem assistia só o começo e saía não virava
// "continuar assistindo" (nada era salvo antes disso). 5s filtra só o play
// acidental.
const _POSICAO_MINIMA_S = 5;
// Margem do fim (créditos): retomar a menos disso do final não vale a pena.
const _MARGEM_FINAL_S = 30;
const _THROTTLE_MS = 10000;

// Feature "continuar assistindo": restaura a posição salva ao carregar o
// vídeo (`loadedmetadata`) e salva a posição atual periodicamente
// (`timeupdate`, throttle de ~10s) e imediatamente ao pausar. Irmão de
// usePontoDeAssistido.js, mesma fronteira Clean Architecture: este hook não
// importa nada de `src/api/` — `aoSalvar` é um callback plano que quem monta
// o player decide o que fazer (PaginaDoPlayer.jsx chama a API).
//
// `retomarDe` chega via fetch assíncrono (obterEpisodio em PaginaDoPlayer.jsx)
// que corre em paralelo com o carregamento do HLS (useFonteDeVideo.js conecta
// a fonte no mount, sem esperar esse fetch). Quando o fetch demora mais que
// `loadedmetadata` disparar, o listener abaixo é registrado tarde demais —
// evento nativo, dispara uma vez só — e a retomada nunca aconteceria; por
// isso o check síncrono de `readyState` logo após registrar o listener.
//
// Fora da janela [5s, 90% da duração) a posição não é salva (início/fim do
// episódio não vale a pena retomar — o fim já é coberto pela Feature "liberar
// arquivo ao terminar"/usePontoDeAssistido.js). Fire-and-forget: erro dentro
// de `aoSalvar()` nunca deve interromper playback (CLAUDE.md §4, nunca em
// silêncio — quem implementa `aoSalvar` decide como reportar).
export function usePosicaoDeReproducao(videoRef, aoSalvar, retomarDe) {
  const jaRetomouRef = useRef(false);
  const ultimoSalvoEmRef = useRef(0);

  useEffect(() => {
    jaRetomouRef.current = false;
    ultimoSalvoEmRef.current = 0;
    const video = videoRef.current;
    if (!video || !aoSalvar) return;

    function tentarRetomar() {
      if (jaRetomouRef.current) return;
      if (!video.duration || Number.isNaN(video.duration)) return;
      if (
        retomarDe != null &&
        retomarDe > _POSICAO_MINIMA_S &&
        retomarDe < video.duration - _MARGEM_FINAL_S
      ) {
        jaRetomouRef.current = true;
        video.currentTime = retomarDe;
      }
    }

    function posicaoElegivel() {
      if (!video.duration || Number.isNaN(video.duration)) return false;
      if (video.currentTime < _POSICAO_MINIMA_S) return false;
      if (video.currentTime > _LIMIAR_CONCLUSAO * video.duration) return false;
      return true;
    }

    function aoAtualizarTempo() {
      if (Date.now() - ultimoSalvoEmRef.current < _THROTTLE_MS) return;
      if (!posicaoElegivel()) return;
      ultimoSalvoEmRef.current = Date.now();
      aoSalvar(Math.floor(video.currentTime));
    }

    function aoPausar() {
      if (!posicaoElegivel()) return;
      ultimoSalvoEmRef.current = Date.now();
      aoSalvar(Math.floor(video.currentTime));
    }

    video.addEventListener('loadedmetadata', tentarRetomar);
    video.addEventListener('timeupdate', aoAtualizarTempo);
    video.addEventListener('pause', aoPausar);
    // `loadedmetadata` já pode ter disparado antes deste efeito rodar (o
    // fetch de `retomarDe` demorou mais que o HLS carregar) — evento nativo
    // não dispara de novo pra um listener tardio, então cobre esse caso
    // chamando a mesma lógica direto se os metadados já estão disponíveis.
    if (video.readyState >= HTMLMediaElement.HAVE_METADATA) tentarRetomar();
    return () => {
      video.removeEventListener('loadedmetadata', tentarRetomar);
      video.removeEventListener('timeupdate', aoAtualizarTempo);
      video.removeEventListener('pause', aoPausar);
    };
  }, [videoRef, aoSalvar, retomarDe]);
}

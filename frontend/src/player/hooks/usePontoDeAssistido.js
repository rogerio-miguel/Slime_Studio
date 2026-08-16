import { useEffect, useRef } from 'react';

const _LIMIAR = 0.9;

// Observa `timeupdate` do <video> e chama `aoAtingir()` uma vez quando
// currentTime/duration cruza 90% — guard de ref pra nunca repetir na mesma
// montagem (troca de fonte remonta o componente pai, PlayerAtivo, então o
// guard reresta sozinho). Fronteira Clean Architecture: este hook não
// importa nada de `src/api/` — `aoAtingir` é um callback plano que quem
// monta o player decide o que fazer (PaginaDoPlayer.jsx chama a API).
//
// Fire-and-forget: erro de rede/API dentro de `aoAtingir()` nunca deve
// interromper playback — só vai pro console (nunca em silêncio, mas também
// nunca fatal aqui, CLAUDE.md §4).
export function usePontoDeAssistido(videoRef, aoAtingir) {
  const jaAtingiuRef = useRef(false);

  useEffect(() => {
    jaAtingiuRef.current = false;
    const video = videoRef.current;
    if (!video || !aoAtingir) return;

    function aoAtualizarTempo() {
      if (jaAtingiuRef.current) return;
      if (!video.duration || Number.isNaN(video.duration)) return;
      if (video.currentTime / video.duration < _LIMIAR) return;

      jaAtingiuRef.current = true;
      Promise.resolve()
        .then(() => aoAtingir())
        .catch((erro) => console.error('falha ao registrar assistido', erro));
    }

    video.addEventListener('timeupdate', aoAtualizarTempo);
    return () => video.removeEventListener('timeupdate', aoAtualizarTempo);
  }, [videoRef, aoAtingir]);
}

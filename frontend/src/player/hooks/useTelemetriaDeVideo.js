import { useEffect, useRef, useState } from 'react';

// setState no máximo a cada 250ms: o laço em si roda por frame (cadência
// real de vídeo, ~41ms/24fps), mas re-renderizar o HUD nessa taxa não traz
// informação nova pro olho humano e custa reconciliação de React à toa.
const INTERVALO_MIN_SETSTATE_MS = 250;

// Segundo loop de rVFC, independente do laço de frame da sessão Anime4K
// (motorAnime4k.js) — só para instrumentação; múltiplos rVFC concorrentes
// sobre o mesmo <video> são suportados nativamente pelo navegador, e este
// loop não precisa de nenhuma indireção pra sobreviver a trocas de preset:
// motorAnime4k.js não intercepta `requestVideoFrameCallback` mais.
//
// A degradação automática de preset por telemetria vive em
// useControleAdaptativo.js (janela própria, não este loop por frame).
export function useTelemetriaDeVideo({ videoRef, adaptador }) {
  const [estado, setEstado] = useState({ cadenciaMs: null, dropped: null, total: null, gpu: 'indisponível' });
  const ultimoSetStateEmRef = useRef(0);
  const ultimoTimestampRef = useRef(null);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;

    const rvfc = video.requestVideoFrameCallback.bind(video);
    // GPUAdapter.info é atributo síncrono (GPUAdapterInfo) — não precisa await.
    const info = adaptador?.info;
    const gpu = info
      ? [info.vendor, info.architecture || info.device].filter(Boolean).join(' · ') ||
        info.description ||
        'sem detalhes'
      : 'indisponível';

    let handle = null;
    ultimoTimestampRef.current = null;

    function onFrame() {
      const nowMs = performance.now();
      let cadenciaMs = null;
      if (ultimoTimestampRef.current !== null) {
        cadenciaMs = nowMs - ultimoTimestampRef.current;
      }
      ultimoTimestampRef.current = nowMs;

      let dropped = null;
      let total = null;
      if (typeof video.getVideoPlaybackQuality === 'function') {
        const quality = video.getVideoPlaybackQuality();
        dropped = quality.droppedVideoFrames;
        total = quality.totalVideoFrames;
      }

      if (cadenciaMs !== null && nowMs - ultimoSetStateEmRef.current >= INTERVALO_MIN_SETSTATE_MS) {
        ultimoSetStateEmRef.current = nowMs;
        setEstado({ cadenciaMs, dropped, total, gpu });
      }

      handle = rvfc(onFrame);
    }

    handle = rvfc(onFrame);

    return () => {
      if (handle !== null) video.cancelVideoFrameCallback(handle);
    };
  }, [videoRef, adaptador]);

  return estado;
}

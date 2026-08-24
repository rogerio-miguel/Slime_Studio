import { useEffect, useState } from 'react';
import { conectarFonte } from '../fonteHls.js';

// Conecta `fonte` (URL/blob URL) ao <video> via fonteHls.js. Reconecta
// sempre que `fonte` muda; desconecta no unmount. Devolve as dimensões
// nativas do vídeo, gravadas em `loadedmetadata` (null até lá) — usadas por
// Player.jsx como gate/dependência pra iniciar a sessão WebGPU
// (useMotorAnime4k) só depois que o vídeo tem dimensões reais.
export function useFonteDeVideo(videoRef, fonte, aoFalhar) {
  const [dimensoesDaFonte, setDimensoesDaFonte] = useState(null);

  useEffect(() => {
    setDimensoesDaFonte(null);
    const video = videoRef.current;
    if (!video || !fonte) return;

    // Erro é responsabilidade de `conectarFonte` (cada ramo — hls.js,
    // Safari nativo, genérico — sabe qual fonte de erro é a certa pra ele;
    // ver comentário de `ouvirErroNativo` em fonteHls.js).
    const desconectar = conectarFonte(video, fonte, aoFalhar);

    const aoCarregarMetadados = () => {
      setDimensoesDaFonte({ width: video.videoWidth, height: video.videoHeight });
    };

    video.addEventListener('loadedmetadata', aoCarregarMetadados, { once: true });

    return () => {
      video.removeEventListener('loadedmetadata', aoCarregarMetadados);
      desconectar();
    };
  }, [videoRef, fonte, aoFalhar]);

  return dimensoesDaFonte;
}

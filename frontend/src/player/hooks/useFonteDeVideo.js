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

    const desconectar = conectarFonte(video, fonte, aoFalhar);

    const aoCarregarMetadados = () => {
      setDimensoesDaFonte({ width: video.videoWidth, height: video.videoHeight });
    };
    const aoDarErro = () => {
      const detalhe = video.error ? video.error.message : 'desconhecido';
      aoFalhar(new Error(`Erro ao carregar o vídeo: ${detalhe}`));
    };

    video.addEventListener('loadedmetadata', aoCarregarMetadados, { once: true });
    video.addEventListener('error', aoDarErro);

    return () => {
      video.removeEventListener('loadedmetadata', aoCarregarMetadados);
      video.removeEventListener('error', aoDarErro);
      desconectar();
    };
  }, [videoRef, fonte, aoFalhar]);

  return dimensoesDaFonte;
}

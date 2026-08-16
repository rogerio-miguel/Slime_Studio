import { useEffect, useRef } from 'react';
import { iniciarGlowAmbiente } from './glowAmbiente.js';
import { obterRvfcOriginal } from './motorAnime4k.js';

// Wrapper React fino sobre glowAmbiente.js — o <canvas id="ambient-glow">
// precisa continuar dentro de #fullscreen-stage (via `elementoDeMedidaRef`,
// o nó do .frame passado por Player.jsx), senão o glow some em tela cheia
// (ver player.css). Renderizado por Player.jsx só depois que
// dimensoesDaFonte existe (video.videoWidth/videoHeight já populados).
export default function GlowAmbiente({ videoRef, elementoDeMedidaRef }) {
  const canvasRef = useRef(null);

  useEffect(() => {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    const elementoDeMedida = elementoDeMedidaRef.current;
    if (!video || !canvas || !elementoDeMedida) return;

    const rvfc = obterRvfcOriginal(video);
    return iniciarGlowAmbiente({ video, canvas, elementoDeMedida, rvfc });
  }, [videoRef, elementoDeMedidaRef]);

  return <canvas ref={canvasRef} id="ambient-glow" aria-hidden="true" />;
}

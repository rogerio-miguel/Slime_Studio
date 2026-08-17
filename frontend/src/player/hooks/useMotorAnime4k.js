import { useEffect, useState } from 'react';
import { iniciarSessaoDeRender } from '../motorAnime4k.js';
import { PRESETS, calcularDimensoesDeSaida } from '../presets.js';

// Inicia (e reinicia, a cada troca de preset/dimensões) uma sessão do
// pipeline Anime4K. Guard de cancelamento assíncrono: se a limpeza deste
// efeito rodar antes de iniciarSessaoDeRender() resolver (StrictMode do dev
// monta/desmonta cada componente duas vezes — main.jsx mantém isso de
// propósito), o device precisa ser destruído assim que existir. Sem isso o
// StrictMode vaza um GPUDevice por mount.
export function useMotorAnime4k({ videoRef, canvasRef, presetId, dimensoesDaFonte, aoFalhar }) {
  const [adaptador, setAdaptador] = useState(null);

  useEffect(() => {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    const preset = PRESETS[presetId];
    if (!video || !canvas || !preset || !dimensoesDaFonte) return;

    let cancelado = false;
    let sessao = null;
    const dimensoes = calcularDimensoesDeSaida(presetId, video);

    iniciarSessaoDeRender({ video, canvas, preset, dimensoes, aoFalhar }).then((resultado) => {
      if (cancelado) {
        resultado.encerrar();
        return;
      }
      sessao = resultado;
      setAdaptador(resultado.adaptador);
    });

    return () => {
      cancelado = true;
      sessao?.encerrar();
      setAdaptador(null);
    };
    // videoRef/canvasRef são refs estáveis (useRef) — não entram nas deps.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [presetId, dimensoesDaFonte, aoFalhar]);

  return { adaptador };
}

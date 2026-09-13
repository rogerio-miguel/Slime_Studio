import { useEffect, useState } from 'react';

// Espelhado em worker/pipeline/storyboard.py — 1 frame a cada INTERVALO_S,
// num grid único de COLUNAS colunas. Mudar um lado sem o outro desalinha o
// recorte (a prévia mostraria pedaço de um frame vizinho).
const INTERVALO_S = 10;
const COLUNAS = 10;
const LARGURA_THUMB = 320;
const ALTURA_THUMB = 180;

// Prévia de cena ao passar o mouse na barra de progresso (BarraDeControles.jsx),
// recorte via CSS puro de um sprite único (sem canvas, sem segundo <video> —
// ver decisão registrada na conversa: um segundo elemento de vídeo só pra
// isso dobraria decodificação/rede por episódio). `url` pode apontar pra um
// episódio sem storyboard (capturado antes desta feature, ou o passo
// best-effort do worker falhou) — o probe de carregamento abaixo é o que
// decide, silenciosamente, se há algo pra mostrar.
export default function PreviaDeCena({ url, tempo, esquerda }) {
  const [disponivel, setDisponivel] = useState(false);

  useEffect(() => {
    setDisponivel(false);
    if (!url) return;
    let cancelado = false;
    const imagem = new Image();
    imagem.onload = () => {
      if (!cancelado) setDisponivel(true);
    };
    imagem.src = url;
    return () => {
      cancelado = true;
    };
  }, [url]);

  if (!disponivel) return null;

  const indice = Math.floor(tempo / INTERVALO_S);
  const coluna = indice % COLUNAS;
  const linha = Math.floor(indice / COLUNAS);

  return (
    <div
      aria-hidden="true"
      className="pointer-events-none absolute bottom-full mb-3 -translate-x-1/2 overflow-hidden rounded-md shadow-lg shadow-black/50 ring-1 ring-white/10"
      style={{
        left: esquerda,
        width: LARGURA_THUMB,
        height: ALTURA_THUMB,
        backgroundImage: `url(${url})`,
        backgroundPosition: `-${coluna * LARGURA_THUMB}px -${linha * ALTURA_THUMB}px`,
      }}
    />
  );
}

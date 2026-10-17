import { useEffect, useState } from 'react';
import { formatarTempo } from './formatarTempo.js';

// Espelhado em worker/pipeline/storyboard.py — 1 frame a cada INTERVALO_S,
// num grid único de COLUNAS colunas. Mudar um lado sem o outro desalinha o
// recorte (a prévia mostraria pedaço de um frame vizinho).
const INTERVALO_S = 10;
const COLUNAS = 10;
// Exportado: BarraDeControles.jsx usa o mesmo valor pra clampar o centro do
// grupo contra a borda real do player antes de chegar aqui (ver
// aoPassarMouseNoProgresso) — meia-largura é o quanto a miniatura pode
// avançar além do ponto do cursor sem estourar a borda.
export const LARGURA_THUMB = 320;
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

  // `esquerda` já chega clampado (BarraDeControles.jsx::aoPassarMouseNoProgresso,
  // contra a borda real do player — `.controls` — não a estreita faixa do
  // próprio input) — aqui só converte o CENTRO pra borda esquerda do grupo.
  // Sem `-translate-x-1/2`: o clamp upstream já opera em px, translate por
  // cima reintroduziria a mesma matemática de duas formas.
  const metade = LARGURA_THUMB / 2;

  return (
    <div
      aria-hidden="true"
      className="pointer-events-none absolute bottom-full mb-3 flex flex-col items-center gap-1"
      style={{ left: esquerda - metade, width: LARGURA_THUMB }}
    >
      <div
        className="overflow-hidden rounded-md shadow-lg shadow-black/50 ring-1 ring-white/10"
        style={{
          width: LARGURA_THUMB,
          height: ALTURA_THUMB,
          backgroundImage: `url(${url})`,
          backgroundPosition: `-${coluna * LARGURA_THUMB}px -${linha * ALTURA_THUMB}px`,
        }}
      />
      <span className="text-sm font-semibold text-white drop-shadow-[0_1px_2px_rgba(0,0,0,0.9)] [font-variant-numeric:tabular-nums]">
        {formatarTempo(tempo)}
      </span>
    </div>
  );
}

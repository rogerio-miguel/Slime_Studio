import { useEffect, useRef } from 'react';

// Atributo que marca as áreas que pausam a rotação com o mouse em cima — o
// hook abaixo procura por ele sob o cursor. Quem usa o hook como o palco do
// Top 10 escreve o literal `data-pausa-por-mouse` direto no JSX.
export const ATRIBUTO_PAUSA_POR_MOUSE = 'data-pausa-por-mouse';

// Reavalia o "mouse em cima" quando uma sinopse acaba de fechar. Enquanto ela
// está aberta, o painel/overlay fica por cima da área e o navegador dispara
// `mouseleave` nela; ao fechar, com o cursor parado no mesmo lugar, nenhum
// `mouseenter` volta a disparar (só com o próximo movimento), e a rotação
// seguia andando com o mouse em cima, tendo que tirar e recolocar o cursor.
// Aqui guardamos a última posição do mouse e, no fechamento, vemos se há uma
// área marcada com `ATRIBUTO_PAUSA_POR_MOUSE` sob ela. Só mouse: em toque não
// existe "em cima" e travaria a pausa.
export function useHoverAposFechar(aberta, definirMouseEmCima) {
  const ponteiroRef = useRef(null);
  const estavaAbertaRef = useRef(aberta);

  useEffect(() => {
    const guardar = (evento) => {
      if (evento.pointerType === 'mouse') {
        ponteiroRef.current = { x: evento.clientX, y: evento.clientY };
      }
    };
    window.addEventListener('pointermove', guardar, { passive: true });
    return () => window.removeEventListener('pointermove', guardar);
  }, []);

  useEffect(() => {
    const acabouDeFechar = estavaAbertaRef.current && !aberta;
    estavaAbertaRef.current = aberta;
    if (!acabouDeFechar || !ponteiroRef.current) return undefined;
    // Um quadro depois: o painel já saiu do DOM e o layout assentou.
    const quadro = requestAnimationFrame(() => {
      const { x, y } = ponteiroRef.current;
      const sobAreaDePausa = document
        .elementFromPoint(x, y)
        ?.closest(`[${ATRIBUTO_PAUSA_POR_MOUSE}]`);
      definirMouseEmCima(Boolean(sobAreaDePausa));
    });
    return () => cancelAnimationFrame(quadro);
  }, [aberta, definirMouseEmCima]);
}

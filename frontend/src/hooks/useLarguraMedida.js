import { useCallback, useRef, useState } from 'react';

// Largura natural de um nó, medida por ResizeObserver. Ref por CALLBACK (não
// `useRef` + efeito): a cápsula da ilha desmonta e remonta quando Início e
// Catálogo trocam de posição, e um efeito amarrado ao primeiro nó ficaria
// observando um elemento morto, congelando a largura num valor velho.
export function useLarguraMedida() {
  const [largura, setLargura] = useState(0);
  const observadorRef = useRef(null);
  const refDoNo = useCallback((no) => {
    observadorRef.current?.disconnect();
    observadorRef.current = null;
    if (!no) return;
    const medir = () => setLargura(Math.ceil(no.getBoundingClientRect().width));
    medir();
    const observador = new ResizeObserver(medir);
    observador.observe(no);
    observadorRef.current = observador;
  }, []);
  return [largura, refDoNo];
}

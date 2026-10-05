import { useEffect } from 'react';

const TECLAS_DE_ROLAGEM = new Set([' ', 'PageUp', 'PageDown', 'Home', 'End', 'ArrowUp', 'ArrowDown']);

// Trava a rolagem da página enquanto a sinopse está aberta SEM mexer no
// layout, e por isso só em JS (roda, toque e teclas), sem CSS no <html>:
// - `overflow: hidden` tira a barra de rolagem e a largura útil sobe (medido:
//   1905 -> 1920px), refluindo os textos da página — títulos do carrossel
//   quebravam em outra linha, só em alguns cards; `scrollbar-gutter: stable` não
//   segura esse espaço no <html>.
// - `overflow-y: scroll` mantém a barra, mas muda as unidades `vw` (passam a
//   descontar a barra: o `max-w` do título do carrossel, em `vw`, encolhia 7px).
// A rolagem só é permitida dentro da `regiaoRef` quando ela tem texto pra rolar
// (`overscroll-behavior: contain` evita encadear pra página).
export function useTravaDeRolagem(ativa, regiaoRef) {
  useEffect(() => {
    if (!ativa) return undefined;
    const rolagemPermitida = (evento) => {
      const regiao = regiaoRef.current;
      return Boolean(
        regiao && regiao.contains(evento.target) && regiao.scrollHeight > regiao.clientHeight,
      );
    };
    const bloquear = (evento) => {
      if (!rolagemPermitida(evento)) evento.preventDefault();
    };
    const bloquearTecla = (evento) => {
      if (TECLAS_DE_ROLAGEM.has(evento.key) && !rolagemPermitida(evento)) evento.preventDefault();
    };

    // Não passivos: `preventDefault` em roda/toque só vale assim.
    window.addEventListener('wheel', bloquear, { passive: false });
    window.addEventListener('touchmove', bloquear, { passive: false });
    window.addEventListener('keydown', bloquearTecla);
    return () => {
      window.removeEventListener('wheel', bloquear);
      window.removeEventListener('touchmove', bloquear);
      window.removeEventListener('keydown', bloquearTecla);
    };
  }, [ativa, regiaoRef]);
}

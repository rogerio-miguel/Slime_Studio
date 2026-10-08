import { useEffect, useRef, useState } from 'react';

// Fundo da navbar: 420px de scroll até ficar opaco. Curto demais (140px) lia
// como brusco perto do hero da Início; o smoothstep desacelera os dois extremos,
// onde o olho nota mais a mudança de contraste (alpha linear parecia abrupto
// nos dois sentidos).
const LIMIAR_FUNDO_PX = 420;
// Logo e ilha são binários (um limiar + transição CSS), não acompanham o pixel.
const LIMIAR_LOGO_PX = 24;
// ~ distância de `pt-24` do <main> da Galeria até o topo: a fileira original já
// sumiu, a ilha pode abrir.
const LIMIAR_ILHA_PX = 96;

const suavizar = (t) => t * t * (3 - 2 * t);

export const ESTILO_FUNDO_INICIAL_TRANSPARENTE = { backgroundColor: 'rgba(0, 0, 0, 0)' };

// Estado de scroll da navbar. O fundo é gravado direto no DOM via `navRef`, fora
// do ciclo de render: um `useState` por frame de scroll re-renderizava a navbar
// a ~60fps enquanto a transição CSS da cápsula (layout, não compositor) rodava,
// e a abertura por scroll saía mais truncada do que a aberta por mensagem.
// `logoColapsada`/`ilhaAtiva` são booleanos que só mudam ao cruzar o limiar, então
// ficam em `useState` sem custo. `rAF` agrupa os eventos de scroll em lote.
export function useScrollDaNavbar(transparente) {
  const navRef = useRef(null);
  const [logoColapsada, setLogoColapsada] = useState(false);
  const [ilhaAtiva, setIlhaAtiva] = useState(false);

  useEffect(() => {
    if (!transparente) return undefined;
    let quadroPendente = false;
    const atualizar = () => {
      const t = Math.min(window.scrollY / LIMIAR_FUNDO_PX, 1);
      if (navRef.current) {
        navRef.current.style.backgroundColor = `rgba(0, 0, 0, ${suavizar(t)})`;
      }
      setLogoColapsada(window.scrollY > LIMIAR_LOGO_PX);
      setIlhaAtiva(window.scrollY > LIMIAR_ILHA_PX);
      quadroPendente = false;
    };
    const aoRolar = () => {
      if (quadroPendente) return;
      quadroPendente = true;
      requestAnimationFrame(atualizar);
    };
    atualizar();
    window.addEventListener('scroll', aoRolar, { passive: true });
    return () => window.removeEventListener('scroll', aoRolar);
  }, [transparente]);

  return { navRef, logoColapsada, ilhaAtiva };
}

import { useCallback, useEffect, useRef, useState } from 'react';

const TAMANHO_MINIMO_PX = 40;

// Barra de rolagem da página sobreposta ao conteúdo: a nativa ocupa uma coluna
// própria (faixa preta ao lado da arte do hero), e CSS não consegue tirá-la do
// fluxo. Aqui a nativa some (index.css) e só o polegar flutua, sem trilho.
// `scrollbar-width: none` fixo também deixa `vw` estável (ver useTravaDeRolagem).
export default function BarraDeRolagem() {
  const [polegar, setPolegar] = useState(null);
  const [arrastando, setArrastando] = useState(false);
  const arrasteRef = useRef(null);

  const medir = useCallback(() => {
    const raiz = document.documentElement;
    const { scrollHeight, clientHeight, scrollTop } = raiz;
    if (scrollHeight <= clientHeight + 1) {
      setPolegar(null);
      return;
    }
    const tamanho = Math.max(TAMANHO_MINIMO_PX, (clientHeight / scrollHeight) * clientHeight);
    const curso = clientHeight - tamanho;
    const topo = (scrollTop / (scrollHeight - clientHeight)) * curso;
    setPolegar({ tamanho, topo, curso });
  }, []);

  useEffect(() => {
    medir();
    window.addEventListener('scroll', medir, { passive: true });
    window.addEventListener('resize', medir);
    // O conteúdo cresce/encolhe sem scroll nem resize (imagens, listas, rota nova).
    const observador = new ResizeObserver(medir);
    observador.observe(document.documentElement);
    observador.observe(document.body);
    return () => {
      window.removeEventListener('scroll', medir);
      window.removeEventListener('resize', medir);
      observador.disconnect();
    };
  }, [medir]);

  if (!polegar) return null;

  const iniciarArrasto = (evento) => {
    evento.currentTarget.setPointerCapture(evento.pointerId);
    arrasteRef.current = { y: evento.clientY, scrollTop: document.documentElement.scrollTop };
    setArrastando(true);
  };
  const arrastar = (evento) => {
    const arrasto = arrasteRef.current;
    if (!arrasto || polegar.curso <= 0) return;
    const raiz = document.documentElement;
    const rolavel = raiz.scrollHeight - raiz.clientHeight;
    raiz.scrollTop = arrasto.scrollTop + ((evento.clientY - arrasto.y) / polegar.curso) * rolavel;
  };
  const soltar = () => {
    arrasteRef.current = null;
    setArrastando(false);
  };

  return (
    <div
      aria-hidden="true"
      className="pointer-events-none fixed top-0 right-0 z-[1000] h-screen w-3"
    >
      <div
        onPointerDown={iniciarArrasto}
        onPointerMove={arrastar}
        onPointerUp={soltar}
        onPointerCancel={soltar}
        style={{ height: polegar.tamanho, transform: `translateY(${polegar.topo}px)` }}
        className={`pointer-events-auto absolute right-0 w-3 touch-none rounded-full border-[3px] border-transparent bg-clip-padding transition-colors ${
          arrastando ? 'bg-neon' : 'bg-[#2a2d35] hover:bg-neon'
        }`}
      />
    </div>
  );
}

import { useCallback, useEffect, useRef, useState } from 'react';

const TAMANHO_MINIMO_PX = 48;
const INATIVIDADE_MS = 1500;

const ROLAGEM_POR_TIMELINE = typeof CSS !== 'undefined' && CSS.supports('animation-timeline', 'scroll()');

// Barra de rolagem da página sobreposta ao conteúdo: a nativa ocupa uma coluna
// própria (faixa preta ao lado da arte do hero), e CSS não consegue tirá-la do
// fluxo. Aqui a nativa some (index.css) e só o polegar flutua, sem trilho.
// `scrollbar-width: none` fixo também deixa `vw` estável (ver useTravaDeRolagem).
// Some com fade após INATIVIDADE_MS sem rolar (como no Gemini; mexer o mouse não a acorda);
// fica visível enquanto o mouse está sobre o polegar ou durante o arrasto.
//
// Posição do polegar: a rolagem roda no compositor, então mover o polegar por
// JS/React a cada `scroll` fazia ele atrasar e "travar" quando a thread principal
// estava ocupada (WebGPU, blur do hero). Onde há scroll-timeline, a posição é uma
// animação CSS atrelada à rolagem (`.polegar-da-pagina`, também no compositor);
// o JS só mede tamanho/curso quando o layout muda. Sem suporte, cai num rAF.
export default function BarraDeRolagem() {
  const [polegar, setPolegar] = useState(null);
  const [arrastando, setArrastando] = useState(false);
  const [sobre, setSobre] = useState(false);
  const [ativa, setAtiva] = useState(true);
  const arrasteRef = useRef(null);
  const polegarRef = useRef(null);

  const medir = useCallback(() => {
    const { scrollHeight, clientHeight } = document.documentElement;
    if (scrollHeight <= clientHeight + 1) {
      setPolegar(null);
      return;
    }
    const tamanho = Math.max(TAMANHO_MINIMO_PX, (clientHeight / scrollHeight) * clientHeight);
    const curso = clientHeight - tamanho;
    setPolegar((atual) =>
      atual && atual.tamanho === tamanho && atual.curso === curso ? atual : { tamanho, curso },
    );
  }, []);

  useEffect(() => {
    medir();
    window.addEventListener('resize', medir);
    // O conteúdo cresce/encolhe sem resize (imagens, listas, rota nova).
    const observador = new ResizeObserver(medir);
    observador.observe(document.documentElement);
    observador.observe(document.body);
    return () => {
      window.removeEventListener('resize', medir);
      observador.disconnect();
    };
  }, [medir]);

  useEffect(() => {
    if (ROLAGEM_POR_TIMELINE) return undefined;
    let quadro = 0;
    const posicionar = () => {
      quadro = 0;
      const { scrollHeight, clientHeight, scrollTop } = document.documentElement;
      const rolavel = scrollHeight - clientHeight;
      const elemento = polegarRef.current;
      if (!elemento || rolavel <= 0) return;
      const curso = clientHeight - elemento.offsetHeight;
      elemento.style.transform = `translateY(${(scrollTop / rolavel) * curso}px)`;
    };
    const agendar = () => {
      if (!quadro) quadro = requestAnimationFrame(posicionar);
    };
    agendar();
    window.addEventListener('scroll', agendar, { passive: true });
    return () => {
      cancelAnimationFrame(quadro);
      window.removeEventListener('scroll', agendar);
    };
  }, [polegar]);

  useEffect(() => {
    let timer;
    const acordar = () => {
      setAtiva(true);
      clearTimeout(timer);
      timer = setTimeout(() => setAtiva(false), INATIVIDADE_MS);
    };
    acordar();
    window.addEventListener('scroll', acordar, { passive: true });
    return () => {
      clearTimeout(timer);
      window.removeEventListener('scroll', acordar);
    };
  }, []);

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
        onPointerEnter={() => setSobre(true)}
        onPointerLeave={() => setSobre(false)}
        ref={polegarRef}
        style={{ height: polegar.tamanho, '--curso': `${polegar.curso}px` }}
        className={`${ROLAGEM_POR_TIMELINE ? 'polegar-da-pagina ' : ''}pointer-events-auto absolute right-0 w-3 touch-none rounded-full border-2 border-transparent bg-clip-content transition-[background-color,opacity] duration-300 ${
          arrastando ? 'bg-neon' : 'bg-[#2a2d35] hover:bg-neon'
        } ${ativa || arrastando || sobre ? 'opacity-100' : 'opacity-0'}`}
      />
    </div>
  );
}

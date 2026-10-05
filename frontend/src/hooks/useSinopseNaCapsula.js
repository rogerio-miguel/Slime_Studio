import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react';

import { useTravaDeRolagem } from './useTravaDeRolagem.js';

// Duração da transformação cápsula <-> painel (BarraDeNavegacao.jsx aplica nos
// estilos devolvidos). Também é o tempo que o fechamento espera antes de
// devolver a cápsula ao fluxo normal.
export const PAINEL_MS = 450;
// Folga depois da transição de altura, até o painel assentar de vez.
const FOLGA_ASSENTAR_MS = 120;
const LARGURA_MAXIMA_PX = 704;
const MARGEM_PX = 12;
const RAIO_PAINEL_PX = 28;
const EASE = 'cubic-bezier(0.4, 0, 0.2, 1)';

// `sm` do Tailwind: abaixo dele o `<ul>` central da navbar (onde mora a
// cápsula) some, então a sinopse cai no <dialog> de SinopseNaIlha.jsx.
const CONSULTA_SM = '(min-width: 40rem)';
function assinarSm(aoMudar) {
  const consulta = window.matchMedia(CONSULTA_SM);
  consulta.addEventListener('change', aoMudar);
  return () => consulta.removeEventListener('change', aoMudar);
}
export function useCapsulaVisivel() {
  return useSyncExternalStore(
    assinarSm,
    () => window.matchMedia(CONSULTA_SM).matches,
    () => true,
  );
}

// Sinopse completa DENTRO da cápsula da ilha: a própria pílula vira o painel
// (pedido do usuário — um <dialog> por cima parecia um painel separado). Fases:
//   fechado    — cápsula normal, em fluxo.
//   ancorado   — a cápsula já abriu (mostrando "Sinopse") e sai do fluxo,
//                `absolute` no MESMO retângulo (o <li> ganha o tamanho dela pra
//                os vizinhos não andarem): nenhuma mudança visível.
//   aberto     — largura/posição/fundo/raio animam pro painel, a altura cresce
//                pelo truque `grid-template-rows: 0fr -> 1fr` (altura `auto`
//                não transiciona) e o cabeçalho (link + rótulo) colapsa.
//   recolhendo — volta ao retângulo da pílula; ao fim `aoFechar` roda e a
//                cápsula retorna ao fluxo, que fecha por conta própria quando
//                a página zera `sinopse`.
// `ancorado -> aberto` espera dois quadros: sem um estilo "ancorado" já
// pintado o navegador não tem de onde transicionar.
//
// Sem <dialog> nativo, o que ele dava de graça é refeito aqui: foco levado ao
// painel e devolvido ao botão de origem, Esc fecha, Tab não escapa (o painel não
// tem nada focável dentro — sem botão X, pedido do usuário) e a rolagem da
// página trava (useTravaDeRolagem.js, sem mexer no layout).
export function useSinopseNaCapsula({ ativa, atrasoAbrirMs, capsulaRef, aoFechar, movimentoReduzido }) {
  const [fase, setFase] = useState('fechado');
  const [geometria, setGeometria] = useState(null);
  // O texto precisa rolar: só decidido DEPOIS do painel assentar. Liberar
  // `overflow-y: auto` no fim da transição (ou antes) fazia uma barra de rolagem
  // aparecer e sumir: nos últimos quadros a altura ainda está 1-2px abaixo do
  // texto. Aqui só vira true se, já assentado, o texto de fato não cabe.
  const [rolavel, setRolavel] = useState(false);
  const regiaoRef = useRef(null);
  const abridorRef = useRef(null);
  const aoFecharRef = useRef(aoFechar);
  useEffect(() => {
    aoFecharRef.current = aoFechar;
  });

  const fechar = useCallback(() => {
    setFase((atual) => (atual === 'fechado' || atual === 'recolhendo' ? atual : 'recolhendo'));
  }, []);

  // fechado -> ancorado: espera a cápsula terminar de abrir, mede e ancora.
  useEffect(() => {
    if (!ativa || fase !== 'fechado') return undefined;
    const temporizador = setTimeout(
      () => {
        const caixa = capsulaRef.current?.getBoundingClientRect();
        if (!caixa || caixa.width === 0) return;
        const largura = document.documentElement.clientWidth;
        const larguraFinal = Math.min(LARGURA_MAXIMA_PX, largura - 2 * MARGEM_PX);
        abridorRef.current = document.activeElement;
        setGeometria({
          largura: caixa.width,
          altura: caixa.height,
          larguraFinal,
          // Offsets relativos ao <li> (o `absolute` ancora nele), que está
          // exatamente onde a cápsula estava.
          esquerdaFinal: Math.max(MARGEM_PX, (largura - larguraFinal) / 2) - caixa.left,
          topoFinal: MARGEM_PX - caixa.top,
        });
        setFase('ancorado');
      },
      movimentoReduzido ? 0 : atrasoAbrirMs,
    );
    return () => clearTimeout(temporizador);
  }, [ativa, fase, atrasoAbrirMs, capsulaRef, movimentoReduzido]);

  useEffect(() => {
    if (fase !== 'ancorado') return undefined;
    let segundoQuadro;
    const primeiroQuadro = requestAnimationFrame(() => {
      segundoQuadro = requestAnimationFrame(() => setFase('aberto'));
    });
    return () => {
      cancelAnimationFrame(primeiroQuadro);
      cancelAnimationFrame(segundoQuadro);
    };
  }, [fase]);

  useEffect(() => {
    if (fase !== 'aberto') return undefined;
    const temporizadorRolavel = setTimeout(
      () => {
        const regiao = regiaoRef.current;
        setRolavel(Boolean(regiao && regiao.scrollHeight > regiao.clientHeight + 1));
      },
      movimentoReduzido ? 0 : PAINEL_MS + FOLGA_ASSENTAR_MS,
    );
    regiaoRef.current?.focus({ preventScroll: true });
    const aoTeclar = (evento) => {
      if (evento.key === 'Escape') {
        evento.preventDefault();
        fechar();
      } else if (evento.key === 'Tab') {
        evento.preventDefault();
        regiaoRef.current?.focus({ preventScroll: true });
      }
    };
    document.addEventListener('keydown', aoTeclar);
    return () => {
      clearTimeout(temporizadorRolavel);
      setRolavel(false);
      document.removeEventListener('keydown', aoTeclar);
    };
  }, [fase, fechar, movimentoReduzido]);

  useEffect(() => {
    if (fase !== 'recolhendo') return undefined;
    const temporizador = setTimeout(
      () => {
        setFase('fechado');
        const abridor = abridorRef.current;
        if (abridor?.isConnected) abridor.focus({ preventScroll: true });
        aoFecharRef.current?.();
      },
      movimentoReduzido ? 0 : PAINEL_MS,
    );
    return () => clearTimeout(temporizador);
  }, [fase, movimentoReduzido]);

  // Pai zerou `sinopse` (ou a tela encolheu pra < sm) no meio do caminho.
  useEffect(() => {
    if (!ativa && fase !== 'fechado' && fase !== 'recolhendo') setFase('fechado');
  }, [ativa, fase]);

  useTravaDeRolagem(fase !== 'fechado', regiaoRef);

  const ancorada = fase !== 'fechado';
  const expandida = fase === 'aberto';
  const duracao = movimentoReduzido ? '0s' : `${PAINEL_MS}ms`;

  return {
    ancorada,
    expandida,
    rolavel,
    // Largura do texto = painel menos o padding horizontal da cápsula (`px-3`):
    // fixa, pra o texto NÃO reflowar enquanto a cápsula cresce (o excesso fica
    // cortado pelo `overflow-hidden` e vai sendo revelado).
    larguraConteudo: geometria ? geometria.larguraFinal - 24 : undefined,
    fechar,
    regiaoRef,
    // <li>: reserva o lugar da cápsula e serve de âncora do `absolute`.
    estiloItem: ancorada
      ? { position: 'relative', opacity: 1, width: geometria.largura, height: geometria.altura }
      : undefined,
    // Cápsula: mesmo retângulo ancorado; expandida, vira o painel.
    estiloCapsula: ancorada
      ? {
          position: 'absolute',
          zIndex: 10,
          top: expandida ? geometria.topoFinal : 0,
          left: expandida ? geometria.esquerdaFinal : 0,
          width: expandida ? geometria.larguraFinal : geometria.largura,
          // Raio em px (não `rounded-full`, 9999px) e fora da transição enquanto
          // só ancorado: senão o raio "sai" de 9999px e a pílula vira um
          // estádio durante quase todo o crescimento.
          borderRadius: expandida || fase === 'recolhendo' ? RAIO_PAINEL_PX : geometria.altura / 2,
          backgroundColor: expandida ? 'rgb(10 12 16 / 0.94)' : 'rgb(255 255 255 / 0.05)',
          boxShadow: expandida
            ? '0 0 0 1px rgb(255 255 255 / 0.08), 0 24px 60px rgb(0 0 0 / 0.55)'
            : '0 0 0 1px rgb(255 255 255 / 0), 0 24px 60px rgb(0 0 0 / 0)',
          overflow: 'hidden',
          transitionProperty: `top, left, width, background-color, box-shadow${
            fase === 'ancorado' ? '' : ', border-radius'
          }`,
          // O fundo escurece mais rápido que a forma: no meio do caminho o painel
          // não pode deixar a arte da página aparecer por baixo.
          transitionDuration: movimentoReduzido
            ? '0s'
            : `${PAINEL_MS}ms, ${PAINEL_MS}ms, ${PAINEL_MS}ms, 220ms, ${PAINEL_MS}ms, ${PAINEL_MS}ms`,
          transitionTimingFunction: EASE,
        }
      : undefined,
    estiloGrade: {
      transition: `grid-template-rows ${duracao} ${EASE}`,
    },
  };
}

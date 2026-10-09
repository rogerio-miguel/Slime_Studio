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
// `px-3` dos dois lados da cápsula (BarraDeNavegacao.jsx).
const PADDING_X_CAPSULA_PX = 24;
// Sólido (branco 5% sobre o preto da navbar opaca): no scroll 0 a navbar é
// transparente e um fundo translúcido deixaria a arte do hero vazar pela cápsula.
const FUNDO_DA_ILHA = 'rgb(13 13 13)';
const FUNDO_PAINEL_PADRAO = 'rgb(10 12 16 / 0.94)';

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
//
// Também hospeda o painel de filtros da Galeria (mesma transformação). Com
// `interativo` o painel TEM controles: Tab circula entre eles em vez de ficar
// preso na região. `fundoExpandido` troca o fundo do painel aberto (o dos filtros
// é sólido; o da sinopse deixa uns 6% de transparência), `larguraMaximaPx` a
// largura do painel e `larguraAoFechar` a largura natural que a cápsula terá
// depois de fechada (só quando o conteúdo do cabeçalho muda com o painel aberto,
// como o resumo do filtro): sem ela, a volta ao fluxo daria um salto de largura.
// `travarRolagem` (padrão `true`): a sinopse é leitura e prende a página; o painel
// de filtros passa `false` — dá pra rolar a grade com o painel aberto e ver o
// resultado de cada escolha (sem isso o painel parecia modal sem ser).
// `topoFinalPx`: onde fica o topo do painel aberto na tela (padrão: a margem). A
// navbar passa o topo da ilha, pra o painel nascer alinhado com o logo e a busca
// e crescer só pra baixo.
// `manterPosicao`: o painel abre centrado na tela, só pra baixo e pros lados, e o
// cabeçalho (link + gatilho) vai do lugar de repouso ao centro do painel em linha
// reta, sem balançar (`crescimentoDoCabecalhoPx` = quanto ele alarga/encolhe com o
// painel aberto: "Ordem e filtros" difere do resumo). Centralizar o cabeçalho
// numa cápsula que cresce assimétrica o fazia balançar ~10px no meio da animação;
// prendê-lo no lugar de repouso deslocava o painel quando o resumo é longo.
export function useSinopseNaCapsula({
  ativa,
  atrasoAbrirMs,
  capsulaRef,
  aoFechar,
  movimentoReduzido,
  interativo = false,
  fundoExpandido = FUNDO_PAINEL_PADRAO,
  larguraMaximaPx = LARGURA_MAXIMA_PX,
  larguraAoFechar,
  manterPosicao = false,
  crescimentoDoCabecalhoPx = 0,
  travarRolagem = true,
  topoFinalPx = MARGEM_PX,
}) {
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
        const larguraFinal = Math.min(larguraMaximaPx, largura - 2 * MARGEM_PX);
        // Offsets relativos ao <li> (o `absolute` ancora nele), que está
        // exatamente onde a cápsula estava.
        const cabecalhoAberto = caixa.width - PADDING_X_CAPSULA_PX + crescimentoDoCabecalhoPx;
        // Aberta a partir da pílula fechada (sem `px-3`), a cápsula ganha o padding
        // ao virar painel e o devolve na volta (`voltaAPilula`).
        const paddingAtual = parseFloat(getComputedStyle(capsulaRef.current).paddingLeft) || 0;
        abridorRef.current = document.activeElement;
        setGeometria({
          largura: caixa.width,
          acrescimoDePadding: paddingAtual === 0 ? PADDING_X_CAPSULA_PX : 0,
          altura: caixa.height,
          larguraFinal,
          esquerdaFinal: Math.max(MARGEM_PX, (largura - larguraFinal) / 2) - caixa.left,
          // Sobra de cada lado do cabeçalho no painel, fora o `px-3` da cápsula.
          deslocamentoDoCabecalho: Math.max(
            0,
            (larguraFinal - cabecalhoAberto) / 2 - PADDING_X_CAPSULA_PX / 2,
          ),
          topoFinal: topoFinalPx - caixa.top,
        });
        setFase('ancorado');
      },
      movimentoReduzido ? 0 : atrasoAbrirMs,
    );
    return () => clearTimeout(temporizador);
  }, [
    ativa,
    fase,
    atrasoAbrirMs,
    capsulaRef,
    movimentoReduzido,
    larguraMaximaPx,
    topoFinalPx,
    crescimentoDoCabecalhoPx,
  ]);

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
        const regiao = regiaoRef.current;
        const focaveis = interativo
          ? [...(regiao?.querySelectorAll('button:not([disabled])') ?? [])]
          : [];
        if (focaveis.length === 0) {
          regiao?.focus({ preventScroll: true });
          return;
        }
        const atual = focaveis.indexOf(document.activeElement);
        const proximo =
          atual === -1
            ? evento.shiftKey ? focaveis.length - 1 : 0
            : (atual + (evento.shiftKey ? -1 : 1) + focaveis.length) % focaveis.length;
        focaveis[proximo].focus({ preventScroll: true });
      }
    };
    document.addEventListener('keydown', aoTeclar);
    return () => {
      clearTimeout(temporizadorRolavel);
      setRolavel(false);
      document.removeEventListener('keydown', aoTeclar);
    };
  }, [fase, fechar, movimentoReduzido, interativo]);

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

  useTravaDeRolagem(travarRolagem && fase !== 'fechado', regiaoRef);

  const ancorada = fase !== 'fechado';
  const expandida = fase === 'aberto';
  const recolhendo = fase === 'recolhendo';
  const larguraDeRepouso =
    recolhendo && larguraAoFechar ? larguraAoFechar : geometria?.largura;
  // Aberta a partir da pílula fechada, a volta devolve também o padding e o fundo
  // da pílula junto com o encolhimento; deixar pra depois dava um salto no fim.
  const voltaAPilula = recolhendo && geometria?.acrescimoDePadding > 0;
  const duracao = movimentoReduzido ? '0s' : `${PAINEL_MS}ms`;

  return {
    ancorada,
    expandida,
    recolhendo,
    rolavel,
    // Largura do texto = painel menos o padding horizontal da cápsula (`px-3`):
    // fixa, pra o texto NÃO reflowar enquanto a cápsula cresce (o excesso fica
    // cortado pelo `overflow-hidden` e vai sendo revelado).
    larguraConteudo: geometria ? geometria.larguraFinal - 24 : undefined,
    fechar,
    regiaoRef,
    // Margem esquerda do cabeçalho: leva o link ao centro do painel na mesma
    // transição da cápsula (soma linear, então ele anda em linha reta). Zero com
    // o painel fechado.
    estiloCabecalho: manterPosicao
      ? {
          marginLeft: expandida ? geometria.deslocamentoDoCabecalho : 0,
          transition: `margin-left ${duracao} ${EASE}`,
        }
      : undefined,
    // <li>: reserva o lugar da cápsula e serve de âncora do `absolute`.
    estiloItem: ancorada
      ? {
          position: 'relative',
          opacity: 1,
          width: larguraDeRepouso,
          height: geometria.altura,
          // Acompanha a cápsula na volta, senão o <ul> (centralizado) pularia.
          transition: `width ${duracao} ${EASE}`,
        }
      : undefined,
    // Cápsula: mesmo retângulo ancorado; expandida, vira o painel.
    estiloCapsula: ancorada
      ? {
          position: 'absolute',
          zIndex: 10,
          top: expandida ? geometria.topoFinal : 0,
          left: expandida ? geometria.esquerdaFinal : 0,
          width: expandida ? geometria.larguraFinal : larguraDeRepouso,
          ...(voltaAPilula ? { padding: 0 } : null),
          // Raio em px (não `rounded-full`, 9999px) e fora da transição enquanto
          // só ancorado: senão o raio "sai" de 9999px e a pílula vira um
          // estádio durante quase todo o crescimento.
          borderRadius: expandida || fase === 'recolhendo' ? RAIO_PAINEL_PX : geometria.altura / 2,
          backgroundColor: expandida
            ? fundoExpandido
            : voltaAPilula
              ? 'rgb(255 255 255 / 0)'
              : FUNDO_DA_ILHA,
          boxShadow: expandida
            ? '0 0 0 1px rgb(255 255 255 / 0.08), 0 24px 60px rgb(0 0 0 / 0.55)'
            : '0 0 0 1px rgb(255 255 255 / 0), 0 24px 60px rgb(0 0 0 / 0)',
          overflow: 'hidden',
          // `padding`: aberta da pílula fechada, o `px-3` entra junto da forma.
          transitionProperty: `top, left, width, background-color, box-shadow, padding${
            fase === 'ancorado' ? '' : ', border-radius'
          }`,
          // O fundo escurece mais rápido que a forma: no meio do caminho o painel
          // não pode deixar a arte da página aparecer por baixo.
          transitionDuration: movimentoReduzido
            ? '0s'
            : `${PAINEL_MS}ms, ${PAINEL_MS}ms, ${PAINEL_MS}ms, 220ms, ${PAINEL_MS}ms, ${PAINEL_MS}ms, ${PAINEL_MS}ms`,
          transitionTimingFunction: EASE,
        }
      : undefined,
    estiloGrade: {
      transition: `grid-template-rows ${duracao} ${EASE}`,
    },
  };
}

import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import FiltrosDePixelizacao from './ilha/FiltrosDePixelizacao';
import { duracaoTotalDaTroca, pixelarTroca } from './ilha/pixelarTroca';
import { usePrefersReducedMotion } from '../inicio/usePrefersReducedMotion';

// Mascote slime em pixel art (pedido do usuário, 2026-10-14; substituiu a
// claquete do lucide). Escada de Minimalismo, CLAUDE.md §4 passo 6: nenhuma lib
// de ícones tem esse mascote, então o desenho mora aqui. Segue a arte do
// projeto (`assets/icone-Slime_Studio2.png`): cúpula larga e baixa, brilho no
// canto, olhos semicerrados em traço e fones de ouvido.
//
// Grade 16×16 num ícone de `TAMANHO_DO_ICONE_PX` (40px = células de 2,5px; 32px
// e 48px são os tamanhos de células inteiras, 2 e 3px). Com `crispEdges` as
// bordas não borram, mas em tela 1× as células alternam 2 e 3px.
//
// Cada letra do desenho é uma cor: `b` corpo (`currentColor`, o neon da navbar),
// `h` fones (branco, igual ao SLIME ao lado) e `l` brilho; `.` é vazio (olhos e
// boca são o fundo aparecendo). Cada quadro vira um `<path>` por cor, gerado
// das linhas abaixo — o desenho fica legível aqui em vez de virar um monte de
// `d` escrito à mão. Tentativas descartadas: slime com ponta no topo (lia como
// gota), brilho de 1 célula (lia como terceiro olho) e olhos em L (liam como
// zangados).
//
// Os quadros alternam em degraus (sem interpolar, igual à pixelização da troca
// nome ↔ ícone). Entrada: o slime cai esticado, amassa ao bater, dá um pulinho e
// assenta. Depois, de tempos em tempos, ele pisca (`usePiscar`: o quadro do
// repouso sem os olhos). Os quadros da entrada têm a base alinhada na linha 13;
// só o esticado sai do lugar (ver `slime-esticado` em `index.css`).
const CORES_DO_SLIME = [
  { letra: 'b', classe: '' },
  { letra: 'h', classe: 'fill-white' },
  { letra: 'l', classe: 'fill-blue-300' },
];

function caminhoDaCor(linhaInicial, linhas, letra) {
  const corridas = new RegExp(`${letra}+`, 'g');
  return linhas
    .flatMap((linha, i) =>
      [...linha.matchAll(corridas)].map(
        ({ 0: trecho, index }) =>
          `M${index} ${linhaInicial + i}h${trecho.length}v1h-${trecho.length}z`,
      ),
    )
    .join('');
}

function montarQuadro(linhaInicial, linhas) {
  return CORES_DO_SLIME.map(({ letra, classe }) => ({
    letra,
    classe,
    d: caminhoDaCor(linhaInicial, linhas, letra),
  }));
}

const LINHAS_DO_REPOUSO = [
  '.....hhhhhh.....',
  '...hh......hh...',
  '..h...bbbb...h..',
  '.h..bllbbbbb..h.',
  'hh.blllbbbbbb.hh',
  'hhbbbbbbbbbbbbhh',
  'hhbbbbbbbbbbbbhh',
  'hhbb..bbbb..bbhh',
  '.hbbbbbbbbbbbbh.',
  '..bbbbbbbbbbbb..',
  '...bbbbbbbbbb...',
];
const TOPO_DO_REPOUSO = 3;
const QUADRO_REPOUSO = montarQuadro(TOPO_DO_REPOUSO, LINHAS_DO_REPOUSO);

// Piscar: o repouso com os olhos (linha 7, buracos de 2 células nas colunas 4-5
// e 10-11) preenchidos pelo corpo. Já houve outros gestos (olhar de lado, cima e
// baixo, arregalar ao passar o mouse num card) e foram tirados a pedido.
const LINHA_DOS_OLHOS = 7;
const QUADRO_PISCANDO = montarQuadro(
  TOPO_DO_REPOUSO,
  LINHAS_DO_REPOUSO.map((linha, i) => (i === LINHA_DOS_OLHOS ? 'hhbbbbbbbbbbbbhh' : linha)),
);

const DURACAO_DA_PISCADA_MS = 120;
const ESPERA_ENTRE_PISCADAS_MS = [3000, 8000];
const ESPERA_ATE_A_PRIMEIRA_PISCADA_MS = [2500, 5000];

const sortearEntre = ([minimo, maximo]) => minimo + Math.random() * (maximo - minimo);

// `true` enquanto o slime está de olhos fechados. Fica parado enquanto `ativo`
// for falso (ícone escondido, movimento reduzido) e só começa depois de
// `atrasoInicialMs`, pra não brigar com a entrada pelo mesmo quadro de repouso.
// O intervalo é sorteado em `setTimeout`, e não em CSS, pra nunca ser o mesmo.
function usePiscar(ativo, atrasoInicialMs) {
  const [piscando, setPiscando] = useState(false);
  useEffect(() => {
    if (!ativo) return undefined;
    let temporizador;
    const agendarProxima = (espera) => {
      temporizador = setTimeout(() => {
        setPiscando(true);
        temporizador = setTimeout(() => {
          setPiscando(false);
          agendarProxima(sortearEntre(ESPERA_ENTRE_PISCADAS_MS));
        }, DURACAO_DA_PISCADA_MS);
      }, espera);
    };
    agendarProxima(atrasoInicialMs + sortearEntre(ESPERA_ATE_A_PRIMEIRA_PISCADA_MS));
    return () => clearTimeout(temporizador);
  }, [ativo, atrasoInicialMs]);
  return ativo && piscando;
}
const QUADRO_AGACHADO = montarQuadro(5, [
  '.....hhhhhh.....',
  '...hh......hh...',
  '..h..bbbbbb..h..',
  '.h.bllbbbbbbb.h.',
  'hhbbbbbbbbbbbbhh',
  'hhbb..bbbb..bbhh',
  '.hbbbbbbbbbbbbh.',
  '..bbbbbbbbbbbb..',
  '...bbbbbbbbbb...',
]);
const QUADRO_ESTICADO = montarQuadro(1, [
  '.....hhhhhh.....',
  '...hh......hh...',
  '..h...bbbb...h..',
  '..h.bllbbbbb.h..',
  '.hhbllbbbbbbbhh.',
  '.hhbbbbbbbbbbhh.',
  '.hhbbbbbbbbbbhh.',
  '.hhbb.bbbb.bbhh.',
  '.hhbb.bbbb.bbhh.',
  '..hbbbbbbbbbbh..',
  '...bbbbbbbbbb...',
  '...bbbbbbbbbb...',
  '....bbbbbbbb....',
]);

// Entrada (800ms, ver `index.css`): queda, impacto e pulinho. `backwards`:
// durante o atraso de entrada já vale o 0% (esticado lá em cima), senão o
// repouso apareceria um instante antes da queda. Mudou a duração aqui, mude
// `DURACAO_DA_ENTRADA_MS` abaixo (literal por causa do Tailwind).
const CLASSE_REPOUSO =
  'animate-[slime-repouso_800ms_step-end_backwards] motion-reduce:animate-none';
const CLASSE_AGACHADO =
  'animate-[slime-agachado_800ms_step-end_backwards] motion-reduce:animate-none';
const CLASSE_ESTICADO =
  'animate-[slime-esticado_800ms_step-end_backwards] motion-reduce:animate-none';

// Troca nome ↔ ícone (pedido do usuário, 2026-10-08): a mesma "upscale
// pixelado" do texto da ilha (`ilha/pixelarTroca.js`). Substituiu o voo das
// letras de STUDIO até virarem as peças do ícone (morph via flubber, ver
// `git log` deste arquivo). O ícone fica parado e pixeliza no local; o STUDIO
// pixeliza e recolhe.
//
// Duração-base da troca. Fica abaixo de 450ms (colapso do STUDIO) pra a
// dissolução do texto terminar junto com o recolhimento.
const DURACAO_PIXEL_MS = 300;
// O ícone entra depois que o texto já começou a pixelar; a queda espera esse
// atraso pra não rodar com o ícone ainda invisível.
const ATRASO_ENTRADA_ICONE_MS = duracaoTotalDaTroca(DURACAO_PIXEL_MS) - DURACAO_PIXEL_MS;
const DURACAO_DA_ENTRADA_MS = 800;
// Os olhos só começam a se mexer depois que a entrada termina, senão brigariam
// com ela pelo mesmo quadro de repouso.
const ATRASO_DO_OLHAR_MS = ATRASO_ENTRADA_ICONE_MS + DURACAO_DA_ENTRADA_MS;
// Lado do ícone na tela. O recolhimento do STUDIO (`LARGURA_STUDIO_RECOLHIDO`)
// e o recuo `left-1.5` do ícone acompanham: ao mudar aqui, mude lá (valores
// literais por causa do Tailwind).
const TAMANHO_DO_ICONE_PX = 40;
// Margem do filtro (% da caixa): a queda começa até ~15px acima da caixa e a
// dilatação da pixelização passa dela; menos que isso corta o slime no ar.
const MARGEM_FILTRO_PIXEL = 50;
// O STUDIO recolhe até a largura do ícone (não até 0) e o ícone fica ancorado
// nesse espaço, parado, em vez de ser empurrado pelo recolhimento. 44px = 6px
// de recuo do ícone (`left-1.5` na âncora, o respiro entre SLIME e o slime) + 40
// de largura − 2 do gap antes do STUDIO.
const LARGURA_STUDIO_RECOLHIDO = 'max-w-[44px]';

// `alvo` com atraso: vira `true` após `esperaAoLigar` e `false` após
// `esperaAoDesligar`. Serve pra manter ícone/texto montados até a dissolução
// terminar (o `pixelarTroca` devolve `opacity` ao padrão ao acabar, então
// quem esconde de vez é este estado).
function useAtrasado(alvo, esperaAoLigar, esperaAoDesligar) {
  const [valor, setValor] = useState(alvo);
  useLayoutEffect(() => {
    const id = setTimeout(() => setValor(alvo), alvo ? esperaAoLigar : esperaAoDesligar);
    return () => clearTimeout(id);
  }, [alvo, esperaAoLigar, esperaAoDesligar]);
  return valor;
}

// `montado` mostra/esconde o ícone inteiro (`visibility`, não `opacity`: esta
// fica com o `pixelarTroca`) e só ele liga as animações, pra a entrada rodar de
// novo a cada volta do ícone. Os quadros agachado e esticado nascem invisíveis
// (`opacity-0`): sem animação (movimento reduzido), sobra só o repouso. `overflow: visible`: o SVG recorta no próprio viewBox, e a queda vem
// de fora.
function QuadroDoSlime({ partes, className, atraso }) {
  return (
    <g className={className} style={atraso}>
      {partes.map(({ letra, classe, d }) => (
        <path key={letra} d={d} className={classe} />
      ))}
    </g>
  );
}

function IconeSlime({ montado, animar, atrasoMs, ...props }) {
  const atraso = { animationDelay: `${atrasoMs}ms` };
  const piscando = usePiscar(montado && animar, ATRASO_DO_OLHAR_MS);
  return (
    <svg
      viewBox="0 0 16 16"
      fill="currentColor"
      shapeRendering="crispEdges"
      aria-hidden="true"
      focusable="false"
      style={{ overflow: 'visible', visibility: montado ? 'visible' : 'hidden' }}
      {...props}
    >
      {/* O repouso some enquanto o quadro de olhos fechados ocupa o lugar dele:
          os dois têm o mesmo corpo, e sobrepostos os olhos do repouso
          continuariam à mostra. O `opacity` daqui não mexe na animação de
          entrada (outro nó). */}
      <g style={{ opacity: piscando ? 0 : 1 }}>
        <QuadroDoSlime
          partes={QUADRO_REPOUSO}
          className={montado ? CLASSE_REPOUSO : ''}
          atraso={atraso}
        />
      </g>
      <QuadroDoSlime
        partes={QUADRO_AGACHADO}
        className={`opacity-0 ${montado ? CLASSE_AGACHADO : ''}`}
        atraso={atraso}
      />
      <QuadroDoSlime
        partes={QUADRO_ESTICADO}
        className={`opacity-0 ${montado ? CLASSE_ESTICADO : ''}`}
        atraso={atraso}
      />
      {piscando && <QuadroDoSlime partes={QUADRO_PISCANDO} />}
    </svg>
  );
}

// Wordmark "SLIME STUDIO". `aria-hidden` no texto + um `.sr-only` com a
// palavra por baixo, como antes. `overflow-hidden` no STUDIO recorta o texto
// que não cabe mais enquanto a largura recolhe.
export default function LogoSlimeStudio({ className = '', colapsada = false }) {
  const movimentoReduzido = usePrefersReducedMotion();
  const duracaoTotalMs = movimentoReduzido ? 0 : duracaoTotalDaTroca(DURACAO_PIXEL_MS) + 20;
  // Ícone fica montado até a dissolução da volta terminar; o texto, ao
  // contrário, só some de vez quando a da ida termina (recolhido, ele ainda
  // cabe parcialmente na janela do ícone) e volta na hora ao expandir.
  const iconeMontado = useAtrasado(colapsada, 0, duracaoTotalMs);
  const textoEscondido = useAtrasado(colapsada, duracaoTotalMs, 0);
  const textoStudioRef = useRef(null);
  const iconeRef = useRef(null);
  const filtrosRef = useRef(null);
  const sufixoDoFiltro = useId().replace(/:/g, '');
  const colapsadaAnteriorRef = useRef(colapsada);

  // Só reage a MUDANÇA de `colapsada` (comparando com a ref, que o efeito
  // atualiza no corpo): o StrictMode roda o efeito duas vezes no mount e
  // não pode disparar a troca no carregamento.
  useLayoutEffect(() => {
    if (colapsadaAnteriorRef.current === colapsada) return undefined;
    colapsadaAnteriorRef.current = colapsada;
    if (movimentoReduzido) return undefined;
    const studio = textoStudioRef.current;
    const icone = iconeRef.current;
    return pixelarTroca({
      entra: colapsada ? icone : studio,
      sai: colapsada ? studio : icone,
      svg: filtrosRef.current,
      sufixo: sufixoDoFiltro,
      ms: DURACAO_PIXEL_MS,
    });
  }, [colapsada, movimentoReduzido, sufixoDoFiltro]);

  return (
    <div className={`flex items-center gap-0.5 uppercase leading-none ${className}`}>
      <span className="font-extrabold tracking-tight text-white text-3xl">SLIME</span>
      {/* Âncora de largura zero ANTES do STUDIO: o ícone fica parado onde o
          STUDIO começa e o recolhimento do texto não o empurra. `-ml-0.5`
          cancela o gap da âncora (o STUDIO continua a 2px do SLIME). */}
      <span className="relative -ml-0.5 w-0 self-stretch text-neon">
        <span
          className="absolute left-2 top-1/2"
          style={{ transform: 'translateY(calc(-50% - 2px))' }}
        >
          <IconeSlime
            ref={iconeRef}
            montado={iconeMontado}
            animar={!movimentoReduzido}
            atrasoMs={ATRASO_ENTRADA_ICONE_MS}
            width={TAMANHO_DO_ICONE_PX}
            height={TAMANHO_DO_ICONE_PX}
          />
        </span>
      </span>
      <span
        className={`overflow-hidden whitespace-nowrap font-bold tracking-wide text-neon text-3xl transition-[max-width] duration-[450ms] ease-[cubic-bezier(0.4,0,0.2,1)] motion-reduce:transition-none ${
          colapsada ? LARGURA_STUDIO_RECOLHIDO : 'max-w-[8em]'
        }`}
      >
        <span
          ref={textoStudioRef}
          aria-hidden="true"
          className={`inline-block ${textoEscondido ? 'invisible' : ''}`}
        >
          STUDIO
        </span>
        <span className="sr-only">STUDIO</span>
      </span>
      <FiltrosDePixelizacao
        svgRef={filtrosRef}
        sufixo={sufixoDoFiltro}
        margem={MARGEM_FILTRO_PIXEL}
      />
    </div>
  );
}

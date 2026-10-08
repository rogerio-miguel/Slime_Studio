import { useId, useLayoutEffect, useRef, useState } from 'react';
import FiltrosDePixelizacao from './ilha/FiltrosDePixelizacao';
import { duracaoTotalDaTroca, pixelarTroca } from './ilha/pixelarTroca';
import { usePrefersReducedMotion } from '../inicio/usePrefersReducedMotion';

// Ícone de claquete (Escada de Minimalismo, CLAUDE.md §4 passo 6: nada
// pronto resolve — mesma exceção já documentada em IconeVolume/IconeSkip10,
// player/Icones.jsx, pra quando a lib não permite animar só UMA parte de
// um ícone). Os 4 `<path>` vêm copiados à mão do `Clapperboard` do
// lucide-react (node_modules/lucide-react/dist/esm/icons/clapperboard.mjs)
// — mesmos `d`, só reagrupados: os 3 que formam a LÂMINA de cima (a barra
// listrada + as 2 listras diagonais) entram num `<g>` que gira sozinho pra
// simular o "clap"; a caixa da base fica parada, fora do grupo.
//
// `strokeWidth={2}` = padrão do lucide, sem alteração: usuário pediu pra
// manter o valor padrão (2026-09-25) depois de testar engrossar o traço.
//
// `transformOrigin: '3px 11px'` no `<g>` da lâmina: em elemento SVG, um
// comprimento absoluto (não `%`) em `transform-origin` resolve no sistema
// de coordenadas LOCAL do próprio SVG (as unidades do viewBox), não em px
// de tela — dá pra girar exatamente no ponto onde a lâmina encontra a base
// no path original do lucide (a lâmina termina em `3 11`, a base começa em
// `M3 11h18v8...`), sem precisar de `transform-box` nem recalcular a
// geometria.
const PATH_ICONE_BASE = 'M3 11h18v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z';
const PATH_ICONE_LAMINA =
  'M20.2 6 3 11l-.9-2.4c-.3-1.1.3-2.2 1.3-2.5l13.5-4c1.1-.3 2.2.3 2.5 1.3z';
const CLASSE_CLAP = 'animate-[claquete-clap_900ms_ease-in-out] motion-reduce:animate-none';

// Troca nome ↔ ícone (pedido do usuário, 2026-10-08): a mesma "upscale
// pixelado" do texto da ilha (`ilha/pixelarTroca.js`). Substituiu o voo das
// letras de STUDIO até virarem as peças do ícone (morph via flubber, ver
// `git log` deste arquivo). O ícone fica parado e pixeliza no local; o STUDIO
// pixeliza e recolhe.
//
// Duração-base da troca. Fica abaixo de 450ms (colapso do STUDIO) pra a
// dissolução do texto terminar junto com o recolhimento.
const DURACAO_PIXEL_MS = 300;
// O ícone entra depois que o texto já começou a pixelar; o clap espera esse
// atraso pra não rodar com o ícone ainda invisível.
const ATRASO_ENTRADA_ICONE_MS = duracaoTotalDaTroca(DURACAO_PIXEL_MS) - DURACAO_PIXEL_MS;
// Margem do filtro (% da caixa): a lâmina aberta da claquete passa da caixa.
const MARGEM_FILTRO_PIXEL = 25;
// O STUDIO recolhe até a largura do ícone (não até 0) e o ícone fica ancorado
// nesse espaço, parado, em vez de ser empurrado pelo recolhimento. 34px = 4px
// de recuo do ícone (2 de gap + 2 da âncora) + 32 de largura − 2 do gap antes
// do STUDIO.
const LARGURA_STUDIO_RECOLHIDO = 'max-w-[34px]';

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
// fica com o `pixelarTroca`). Sem `overflow-hidden` em nenhum ancestral: a
// LÂMINA gira pra fora da caixa 32×32 (até ~6px acima, ~2px à esquerda,
// medido em cada frame do keyframe `claquete-clap`) e um corte justo cortava
// a ponta da lâmina aberta. O `<svg>` em si também recorta no limite do
// próprio `viewBox`, por isso `overflow: 'visible'`.
function IconeClaquete({ montado, atrasoClapMs, ...props }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      style={{ overflow: 'visible', visibility: montado ? 'visible' : 'hidden' }}
      {...props}
    >
      <path d={PATH_ICONE_BASE} />
      <g
        className={montado ? CLASSE_CLAP : ''}
        style={{ transformOrigin: '3px 11px', animationDelay: `${atrasoClapMs}ms` }}
      >
        <path d="m12.296 3.464 3.02 3.956" />
        <path d={PATH_ICONE_LAMINA} />
        <path d="m6.18 5.276 3.1 3.899" />
      </g>
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
          className="absolute left-1 top-1/2"
          style={{ transform: 'translateY(calc(-50% - 2px))' }}
        >
          <IconeClaquete
            ref={iconeRef}
            montado={iconeMontado}
            atrasoClapMs={ATRASO_ENTRADA_ICONE_MS}
            width={32}
            height={32}
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

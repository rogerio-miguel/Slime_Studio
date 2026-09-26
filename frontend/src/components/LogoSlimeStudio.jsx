import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import LetraViajante from './LetraViajante';
import { DURACAO_TRAVESSIA_MS } from './useTransicaoParaIcone';
import { USA_ENCONTRO, VOLTA_ANIMADA } from './variantesMorphLogo';
import {
  PATH_LETRA_S,
  PATH_LETRA_T,
  PATH_LETRA_U,
  PATH_LETRA_D,
  PATH_LETRA_I,
  PATH_LETRA_O,
  PATH_ICONE_BASE,
  PATH_ICONE_LAMINA,
  BBOX_LETRA_S,
  BBOX_LETRA_T,
  BBOX_LETRA_U,
  BBOX_LETRA_D,
  BBOX_LETRA_I,
  BBOX_LETRA_O,
} from './logoMorphPaths';

// Ícone de claquete (Escada de Minimalismo, CLAUDE.md §4 passo 6: nada
// pronto resolve — mesma exceção já documentada em IconeVolume/IconeSkip10,
// player/Icones.jsx, pra quando a lib não permite animar só UMA parte de
// um ícone). Os 4 `<path>` vêm copiados à mão do `Clapperboard` do
// lucide-react (node_modules/lucide-react/dist/esm/icons/clapperboard.mjs)
// — mesmos `d`, só reagrupados: os 3 que formam a LÂMINA de cima (a barra
// listrada + as 2 listras diagonais) entram num `<g>` que gira sozinho pra
// simular o "clap"; a caixa da base fica parada, fora do grupo.
//
// `strokeWidth={2}` = padrão do lucide, sem alteração: usuário notou o
// ícone "mais pixelado" (2026-09-25) — comparei com/sem o `<g>` acima,
// pixel a pixel idênticos, não é regressão de código; é só o ícone de
// CONTORNO sendo naturalmente mais "ruidoso" em diagonal do que o slime
// preenchido que existiu antes, numa tela sem DPI alto. Testamos engrossar
// o traço (2.5) pra amaciar isso; usuário pediu pra manter o valor padrão.
//
// `transformOrigin: '3px 11px'` no `<g>` da lâmina: em elemento SVG, um
// comprimento absoluto (não `%`) em `transform-origin` resolve no sistema
// de coordenadas LOCAL do próprio SVG (as unidades do viewBox), não em px
// de tela — dá pra girar exatamente no ponto onde a lâmina encontra a base
// no path original do lucide (a lâmina termina em `3 11`, a base começa em
// `M3 11h18v8...`), sem precisar de `transform-box` nem recalcular a
// geometria.
//
// Base(0) e lâmina(1) "chegam" via as 6 letras de STUDIO viajando
// (`LetraViajante`, `LogoSlimeStudio` abaixo) — os 4 pedaços do ícone só se
// montam aqui DEPOIS que essa viagem termina, senão a peça estática
// duplicaria visualmente a letra ainda em trânsito.
//
// Pedido do usuário (2026-09-26, revisado no mesmo dia): a IDA (nome →
// ícone) continua com essa coreografia — letras viajando e se misturando
// nos pedaços do ícone, já aprovada. A VOLTA (ícone → nome) foi
// SIMPLIFICADA pra um crossfade puro, inspirado no wordmark da Anthropic
// (o `\` do logo deles nunca viaja nem morfa — só o resto das letras
// aparece/some ao redor dele): nenhum pedaço se "desmonta" em letra. O
// ícone inteiro só encolhe/some (sem stagger, sem clap de fechamento) e,
// na sequência, "SLIME STUDIO" aparece por fade no lugar — ver
// `estiloRevelacaoTexto` e `visivel`/`ativo` de `LetraViajante` mais
// abaixo. Motivo: o desmonte anterior (pedaços do ícone virando letra via
// flubber, ver histórico em `useTransicaoParaIcone.js`) incomodava pelo
// CONCEITO, não só pela execução.
const atrasoPedaco = (indice) => `${indice * 40}ms`;
const classePedaco =
  'origin-center transition-[opacity,transform] duration-200 ease-[cubic-bezier(0.4,0,0.2,1)] motion-reduce:transition-none';
// `classePedaco` (`duration-200`) + `atrasoPedaco` (`* 40`, 3 pedaços de
// atraso depois do primeiro) somam 320ms do primeiro ao último pedaço
// terminar de APARECER — só a IDA monta em estágio assim; a VOLTA (ver
// `DURACAO_ICONE_SOME_MS`) some com os 4 pedaços juntos, sem stagger. Se um
// dos dois mudar, o outro precisa mudar junto — nada mais no código lê esse
// total, é só documentação da relação entre os dois números.
const CLASSE_CLAP = 'animate-[claquete-clap_900ms_ease-in-out] motion-reduce:animate-none';
// Quanto tempo o ícone leva pra sumir por inteiro na VOLTA (sem stagger por
// pedaço, ver `estiloPedaco` em `IconeClaquete`) antes do handoff pro
// wordmark — mesma duração de `classePedaco` (`duration-200`), já que os 4
// pedaços somem juntos agora.
const DURACAO_ICONE_SOME_MS = 200;

// Detecta a transição `colapsada: true -> false` (a "volta") no exato
// render em que ela acontece — `usePrevious` clássico: o efeito só
// atualiza a ref DEPOIS do render/commit, então durante o render atual
// `anteriorRef.current` ainda é o valor do render passado. `VOLTA_ANIMADA`
// (`variantesMorphLogo.js`) é quem decide se isso vira `instantaneo` de
// verdade (pula direto pro estado final, sem crossfade) ou anima.
function useVoltandoInstantaneo(colapsada) {
  const anteriorRef = useRef(colapsada);
  const instantaneo = !VOLTA_ANIMADA && anteriorRef.current && !colapsada;
  useEffect(() => {
    anteriorRef.current = colapsada;
  });
  return instantaneo;
}

// `useLayoutEffect` (não `useEffect`): quando `instantaneo`, o `setState`
// precisa acontecer ANTES do browser pintar o frame — senão pinta rapidinho
// o estado "ainda animando" e só no frame seguinte o estado final, um flash
// perceptível em vez de salto instantâneo.
function useMostrarBaseLamina(animar, instantaneo) {
  const [mostrar, setMostrar] = useState(animar);
  useLayoutEffect(() => {
    if (instantaneo) {
      setMostrar(animar);
      return undefined;
    }
    const espera = animar ? DURACAO_TRAVESSIA_MS : DURACAO_ICONE_SOME_MS;
    const id = setTimeout(() => setMostrar(animar), espera);
    return () => clearTimeout(id);
  }, [animar, instantaneo]);
  return mostrar;
}

// Ícone inteiro (sem desmontar em letra) — ver comentário grande acima.
// `mostrarBaseLamina` controla visibilidade dos 4 pedaços; `colapsada`
// distingue as duas direções: só a IDA (`colapsada` true, ícone montando)
// usa o stagger por pedaço (`atrasoPedaco`) e o clap de abertura contínuo
// desde o mount — a VOLTA (`colapsada` false, ícone sumindo) faz os 4
// pedaços sumirem juntos, sem atraso.
function IconeClaquete({ mostrarBaseLamina, colapsada, instantaneo, ...props }) {
  const estiloPedaco = (indice) => ({
    transitionDelay: instantaneo || !colapsada ? '0ms' : atrasoPedaco(indice),
    transitionDuration: instantaneo ? '0ms' : undefined,
    opacity: mostrarBaseLamina ? 1 : 0,
    transform: mostrarBaseLamina ? 'scale(1)' : 'scale(0.4)',
  });
  const classeClap = mostrarBaseLamina ? CLASSE_CLAP : '';
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
      style={{ overflow: 'visible' }}
      {...props}
    >
      <path d={PATH_ICONE_BASE} className={classePedaco} style={estiloPedaco(0)} />
      <g className={classeClap} style={{ transformOrigin: '3px 11px' }}>
        <path
          d="m12.296 3.464 3.02 3.956"
          className={classePedaco}
          style={estiloPedaco(2)}
        />
        <path d={PATH_ICONE_LAMINA} className={classePedaco} style={estiloPedaco(1)} />
        <path
          d="m6.18 5.276 3.1 3.899"
          className={classePedaco}
          style={estiloPedaco(3)}
        />
      </g>
    </svg>
  );
}

// Letras de "STUDIO" desaparecendo/reaparecendo — SEMPRE esquerda pra
// direita (S primeiro, O por último), nos dois sentidos, não espelhado
// (pedido do usuário, 2026-09-25: faz sentido narrativo o ícone sumir
// primeiro e a palavra se recompor na ordem de leitura normal).
// `aria-hidden` em cada pedaço de letra + um `.sr-only` com a palavra
// completa por baixo: leitor de tela não precisa navegar letra por letra.
//
// `USA_ENCONTRO` zera o atraso de VIAGEM (`LetraViajante`, ida) — as 6
// letras precisam chegar ao MESMO TEMPO na gota central pra ler como um
// "encontro" formando um círculo só, não uma fila. `atrasoRevelacaoMs`
// abaixo é outra cascata, independente: a da VOLTA (texto normal
// reaparecendo por fade), que continua em cascata mesmo com 'encontro'
// ativo — não é viagem, então a técnica não se aplica a ela.
const LETRAS_STUDIO = ['S', 'T', 'U', 'D', 'I', 'O'];
function atrasoLetraMs(indice) {
  return USA_ENCONTRO ? 0 : indice * 30;
}
const ATRASO_REVELACAO_LETRA_MS = 30;
function atrasoRevelacaoMs(indice) {
  return indice * ATRASO_REVELACAO_LETRA_MS;
}
const classeLetra =
  'inline-block transition-[opacity,transform] duration-200 ease-[cubic-bezier(0.4,0,0.2,1)] motion-reduce:transition-none';

// Estilo do placeholder de cada letra (`<span>` real, com o texto de
// verdade) — na IDA fica sempre invisível (quem representa a letra
// visualmente é o `LetraViajante`, viajando por cima). Na VOLTA é ele quem
// reaparece por fade simples, sem o `LetraViajante` (que fica parado/
// invisível o tempo todo nessa direção, ver `visivel` no render abaixo) —
// sem transição no sumiço (início da ida, corte instantâneo: o overlay já
// assume no mesmo instante) e com cascata esquerda→direita só no aparecer.
function estiloRevelacaoTexto(indice, mostrarTexto, instantaneo) {
  if (instantaneo || !mostrarTexto) {
    return { opacity: mostrarTexto ? 1 : 0, transitionDuration: '0ms', transitionDelay: '0ms' };
  }
  return { opacity: 1, transitionDelay: `${atrasoRevelacaoMs(indice)}ms` };
}

// TODAS as 6 letras viajam/mudam de forma até um dos 2 destinos do ícone,
// só na IDA (pedido do usuário, 2026-09-26: "fazer todas se misturar pra
// formar o ícone" em vez de só T/O viajarem). T e O são as "principais"
// (cada uma com geometria mais parecida com o próprio destino: T ~ barra
// da lâmina, O ~ caixa arredondada da base); S/U só se MISTURAM na lâmina
// junto com o T, D/I só se misturam na base junto com o O. Ver
// `logoMorphPaths.js` pro detalhe de cada path.
const LETRAS_VIAJANTES = {
  S: { dLetra: PATH_LETRA_S, dIcone: PATH_ICONE_LAMINA, bboxLetra: BBOX_LETRA_S },
  T: { dLetra: PATH_LETRA_T, dIcone: PATH_ICONE_LAMINA, bboxLetra: BBOX_LETRA_T },
  U: { dLetra: PATH_LETRA_U, dIcone: PATH_ICONE_LAMINA, bboxLetra: BBOX_LETRA_U },
  D: { dLetra: PATH_LETRA_D, dIcone: PATH_ICONE_BASE, bboxLetra: BBOX_LETRA_D },
  I: { dLetra: PATH_LETRA_I, dIcone: PATH_ICONE_BASE, bboxLetra: BBOX_LETRA_I },
  O: { dLetra: PATH_LETRA_O, dIcone: PATH_ICONE_BASE, bboxLetra: BBOX_LETRA_O },
};

// Wordmark "SLIME STUDIO" construído do zero. SLIME fica sempre por
// extenso; STUDIO desaparece letra a letra enquanto o ícone de claquete
// aparece pedaço a pedaço. `max-width`/`overflow-hidden`: cada lado
// declara seu próprio max-width generoso o bastante pro conteúdo real,
// senão sobra vão vazio. Duração do container (450ms) fica de propósito
// MAIOR que o total da cascata de letras da ida (6 × 30ms + 200ms própria =
// 350ms), pra não cortar a última letra no meio do fade.
//
// Bug real medido no navegador (2026-09-26, `getBoundingClientRect` do
// ícone por frame): atrasar só o `max-width` do PRÓPRIO span do ícone (fix
// anterior) não bastava — o span do STUDIO vem ANTES dele na linha flex, e
// como ele começava a crescer (`max-w-0` → `max-w-[8em]`) na mesma hora em
// que `colapsada` virava `false`, o ícone era EMPURRADO pra direita por um
// vizinho crescendo, mesmo sem mudar de tamanho ele mesmo. Por isso os
// DOIS spans (STUDIO e ícone) usam `estiloColapso` — mesma regra de atraso
// nos dois, senão o de trás sempre empurra o da frente. O atraso na VOLTA
// casa com `DURACAO_ICONE_SOME_MS` (o ícone precisa terminar de sumir
// antes do espaço do STUDIO voltar a crescer).
function estiloColapso(instantaneo, colapsada) {
  if (instantaneo) return { transitionDuration: '0ms' };
  if (!colapsada) return { transitionDelay: `${DURACAO_ICONE_SOME_MS}ms` };
  return undefined;
}
export default function LogoSlimeStudio({ className = '', colapsada = false }) {
  const slimeRef = useRef(null);
  const origemSRef = useRef(null);
  const origemTRef = useRef(null);
  const origemURef = useRef(null);
  const origemDRef = useRef(null);
  const origemIRef = useRef(null);
  const origemORef = useRef(null);
  const instantaneo = useVoltandoInstantaneo(colapsada);
  const mostrarBaseLamina = useMostrarBaseLamina(colapsada, instantaneo);
  // `LetraViajante` só viaja/aparece na IDA (`colapsada` true, ícone ainda
  // não montado) — nos outros 3 estados (repouso expandido, repouso
  // recolhido, volta inteira) fica invisível e o `<span>` de texto real
  // (`estiloRevelacaoTexto`) é quem representa a letra. Ver comentário
  // grande em `IconeClaquete` acima pro porquê da volta não viajar mais.
  const letraViajanteVisivel = colapsada && !mostrarBaseLamina;
  const mostrarTextoNormal = !colapsada && !mostrarBaseLamina;
  const ORIGEM_REFS = {
    S: origemSRef,
    T: origemTRef,
    U: origemURef,
    D: origemDRef,
    I: origemIRef,
    O: origemORef,
  };

  return (
    <div className={`flex items-center gap-0.5 uppercase leading-none ${className}`}>
      <span ref={slimeRef} className="font-extrabold tracking-tight text-white text-3xl">
        SLIME
      </span>
      <span
        className={`overflow-hidden whitespace-nowrap font-bold tracking-wide text-neon text-3xl transition-[max-width] duration-[450ms] ease-[cubic-bezier(0.4,0,0.2,1)] motion-reduce:transition-none ${
          colapsada ? 'max-w-0' : 'max-w-[8em]'
        }`}
        style={estiloColapso(instantaneo, colapsada)}
      >
        <span aria-hidden="true">
          {LETRAS_STUDIO.map((letra, indice) => (
            // Placeholder com o texto de VERDADE: reserva a largura/posição
            // da letra no fluxo (pra medir e pra nenhuma pular de lugar) e,
            // na volta, é o próprio conteúdo visível (fade simples, sem
            // `LetraViajante` por cima — ver `mostrarTextoNormal`).
            <span
              key={indice}
              ref={ORIGEM_REFS[letra]}
              className={classeLetra}
              style={estiloRevelacaoTexto(indice, mostrarTextoNormal, instantaneo)}
            >
              {letra}
            </span>
          ))}
        </span>
        <span className="sr-only">STUDIO</span>
      </span>
      {/* Este `<span>` do ícone NÃO tem `overflow-hidden` (diferença
          proposital em relação ao span do STUDIO acima, que precisa) —
          bug visto e medido no navegador (2026-09-24, "tem uma parte do
          ícone que corta na hora da animação"): a LÂMINA do
          `IconeClaquete` gira pra fora da caixa 32×32 do ícone parado (até
          ~6px acima, ~2px à esquerda, medido via `getBoundingClientRect`
          em cada frame do keyframe `claquete-clap`), e um
          `overflow-hidden` ajustado bem justo a esse tamanho cortava a
          ponta da lâmina aberta. `overflow-hidden` no STUDIO existe porque
          TEXTO não teria como ficar "escondido" de outro jeito durante a
          transição; o ícone já esconde via `opacity` de cada pedaço
          (acima), que funciona independente de clipping. Segunda fresta do
          mesmo bug: o `<svg>` em si também recorta no limite do próprio
          `viewBox`, independente do pai — `style={{ overflow: 'visible' }}`
          dentro de `IconeClaquete` cobre essa parte. */}
      <span
        className={`flex items-center -translate-y-0.5 text-neon transition-[max-width] duration-[400ms] ease-[cubic-bezier(0.4,0,0.2,1)] motion-reduce:transition-none ${
          colapsada ? 'max-w-[40px]' : 'max-w-0'
        }`}
        style={estiloColapso(instantaneo, colapsada)}
      >
        <IconeClaquete
          mostrarBaseLamina={mostrarBaseLamina}
          colapsada={colapsada}
          instantaneo={instantaneo}
          width={32}
          height={32}
        />
      </span>
      {LETRAS_STUDIO.map((letra, indice) => {
        const { dLetra, dIcone, bboxLetra } = LETRAS_VIAJANTES[letra];
        return (
          <LetraViajante
            key={letra}
            origemRef={ORIGEM_REFS[letra]}
            slimeRef={slimeRef}
            letra={letra}
            dLetra={dLetra}
            dIcone={dIcone}
            bboxLetra={bboxLetra}
            ativo={colapsada}
            visivel={letraViajanteVisivel}
            atrasoMs={atrasoLetraMs(indice)}
            instantaneo={instantaneo}
          />
        );
      })}
    </div>
  );
}

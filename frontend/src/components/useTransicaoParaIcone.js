import { useEffect, useLayoutEffect, useMemo, useRef } from 'react';
import { interpolate } from 'flubber';
import {
  USA_ESTICAR_FUSAO,
  USA_RASTRO_GOSMA,
  USA_BLOB,
  USA_SPRING,
} from './variantesMorphLogo';
import { PATH_BLOB_TRANSICIONAL } from './logoMorphPaths';

// Loop de `requestAnimationFrame` COMPARTILHADO entre as 6 letras de STUDIO
// (`LogoSlimeStudio.jsx` monta um `useTransicaoParaIcone` por letra, e com
// `USA_ENCONTRO` as 6 viajam ao mesmo tempo — ver `variantesMorphLogo.js`).
// Bug real medido (trace do Performance panel do usuário, 2026-09-27):
// antes, CADA letra chamava `requestAnimationFrame` recursivamente por
// conta própria dentro do seu próprio `passo` — 6 chamadas/agendamentos
// SEPARADOS por frame em vez de 1, medido a ~270 chamadas/segundo no trace
// (o esperado pra uma única animação é ~60/s). Não é o custo de CADA
// chamada que pesa (a soma do tempo de função do hook inteiro no trace era
// só ~57ms), é o VOLUME de agendamentos/despachos de task separados
// competindo pela main thread bem no mesmo instante em que o usuário rola a
// página (a animação do wordmark dispara já a 24px de scroll). Um `Set` de
// callbacks + um ÚNICO `requestAnimationFrame` ativo por vez: cada letra
// registra seu próprio `passo` (mesma assinatura de sempre, recebe `agora`)
// e se remove sozinha quando termina (`bruto >= 1`); o laço só re-agenda o
// próprio `requestAnimationFrame` enquanto o `Set` não estiver vazio.
const passosAtivos = new Set();
let idQuadroCompartilhado = null;
function quadroCompartilhado(agora) {
  idQuadroCompartilhado = null;
  // Cópia antes de iterar: um `passo` pode se remover do `Set` (via
  // `pararPasso`) na própria chamada — mutar o `Set` durante a iteração
  // dele quebraria o `for...of`.
  for (const passo of [...passosAtivos]) passo(agora);
  if (passosAtivos.size > 0) {
    idQuadroCompartilhado = requestAnimationFrame(quadroCompartilhado);
  }
}
function registrarPasso(passo) {
  passosAtivos.add(passo);
  if (idQuadroCompartilhado == null) {
    idQuadroCompartilhado = requestAnimationFrame(quadroCompartilhado);
  }
  return () => passosAtivos.delete(passo);
}

// Reescrita completa (pedido do usuário, 2026-09-26: o resultado anterior
// tinha duas animações concorrentes — a cascata de fade+scale "falsa" e o
// morph de forma real do I/O — e ainda duplicava base/lâmina, porque a
// letra morphava NO LUGAR onde já estava, não até a posição real do ícone.
// Esta versão faz a letra VIAJAR de verdade (posição + forma) até virar a
// peça do ícone.
export const DURACAO_TRAVESSIA_MS = 380;
const GAP_PX = 2; // gap-0.5 do Tailwind (0.125rem), mesmo valor da linha flex do logo
const TAMANHO_ICONE_PX = 32; // width/height fixos passados pro IconeClaquete
const DESLOC_Y_ICONE_PX = -2; // -translate-y-0.5 do slot do ícone em LogoSlimeStudio.jsx
const VIEWBOX = 24; // viewBox 0 0 24 24, mesmo dos paths do IconeClaquete
// A tinta extraída da fonte (`logoMorphPaths.js`) começa exatamente em
// x=0, sem a folga (side bearing) que uma letra de verdade tem antes do
// traço — por isso I/O nasciam grudados na letra anterior (D). Pequeno
// empurrão fixo pra direita, só cosmético (pedido do usuário, 2026-09-26).
const ESPACAMENTO_EXTRA_PX = 2;
// Quanto a letra "estica" no pico do trajeto (squash-and-stretch, pedido do
// usuário 2026-09-26: efeito de gosma esticando/comprimindo em vez de
// viajar rígida) — 18% de alongamento no eixo do movimento, comprimindo o
// eixo perpendicular a 60% desse valor (não 100%, senão parece "achatar"
// demais e perder a leitura da letra no meio do trajeto).
const AMPLITUDE_ESTICAR = 0.18;
// Curva do trajeto (posição/tamanho do FLIP, `overlay.style.transition`
// abaixo) — técnica 'spring' (`variantesMorphLogo.js`) troca a curva padrão
// por uma com overshoot: a peça passa um pouco do destino e assenta de
// volta, em vez de desacelerar reto até parar. `cubic-bezier(0.34,1.56,
// 0.64,1)` é a aproximação padrão de "easeOutBack" (o 2º valor >1 é o que
// produz o overshoot). Só a CURVA muda — a forma (path `d`) continua na
// mesma técnica de base (morph direto letra↔ícone, `suavizar` abaixo), sem
// overshoot nela: passar `t` fora de 0..1 pro `flubber` extrapolaria a
// forma de um jeito imprevisível.
const EASING_TRAVESSIA =
  USA_SPRING ? 'cubic-bezier(0.34,1.56,0.64,1)' : 'cubic-bezier(0.4,0,0.2,1)';

function suavizar(t) {
  return t * t * (3 - 2 * t);
}

// Perfil de "velocidade" do trajeto pra modular o esticar: 0 no início/fim
// (letra parada = forma normal), pico em t=0.5 (meio do trajeto = esticada
// ao máximo) — mesmo formato de uma parábola invertida normalizada pra
// topo=1, não a derivada exata de `suavizar` (overkill pra um efeito
// cosmético; a forma visual é a mesma).
function perfilDeEsticar(t) {
  return 4 * t * (1 - t);
}

let canvasMedicao;
// `getBoundingClientRect`/`Range` de um `<span>` medem a caixa de
// LINE-HEIGHT inteira (inclui espaço de ascendente/descendente), não o
// traço visível da letra — em ambos os casos `D` saía com ~35-36px de
// altura mesmo com fonte de ~30px. Só `CanvasRenderingContext2D.measureText`
// devolve a tinta de verdade (`actualBoundingBox*`), na MESMA fonte
// computada do elemento — é o que faz a escala do morph bater com o
// tamanho real das letras vizinhas.
function medirTintaLetra(elementoDeReferencia, letra) {
  const cs = getComputedStyle(elementoDeReferencia);
  const ctx = (canvasMedicao ||= document.createElement('canvas').getContext('2d'));
  ctx.font = `${cs.fontStyle} ${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;
  const m = ctx.measureText(letra);
  return {
    width: m.actualBoundingBoxLeft + m.actualBoundingBoxRight,
    height: m.actualBoundingBoxAscent + m.actualBoundingBoxDescent,
    // `ascentTinta` = do topo da TINTA até a baseline; `ascentFonte` = da
    // caixa cheia do `<span>` (que é ancorada na métrica da FONTE, não no
    // traço específico da letra) até a baseline. A diferença entre os dois
    // é quanto a tinta desta letra "sobra" abaixo do topo da caixa cheia —
    // sem isso, alinhar pelo topo da caixa deixa I/O flutuando mais alto
    // ou mais baixo que a baseline de verdade das outras letras.
    ascentTinta: m.actualBoundingBoxAscent,
    ascentFonte: m.fontBoundingBoxAscent,
  };
}

// `position: fixed` no overlay (não `absolute`) de propósito: assim as
// contas usam direto as coordenadas de VIEWPORT que `getBoundingClientRect`
// já devolve, sem precisar subtrair o retângulo de nenhum container
// intermediário. Versão anterior dependia de um `containerRef` (o `<div>`
// mais externo do logo) só pra converter coordenada — e esse ref se
// mostrou instável na prática (`container.current` virava `null` em
// alguns carregamentos, causa raiz não confirmada — suspeita é StrictMode/
// timing de commit — mas sem precisar dele o bug some de qualquer jeito).
//
// Por que o destino é CALCULADO (a partir do retângulo do "SLIME", que
// nunca se move) em vez de MEDIDO no ícone de verdade: o slot do ícone
// encolhe a largura ao MESMO TEMPO que essa viagem acontece — medir a
// posição dele em pleno voo seria mirar um alvo móvel com outro alvo
// móvel.
//
// A ORIGEM (posição da letra) não precisa desse cuidado: o placeholder
// (`origemRef`) mora num `<span>` `whitespace-nowrap` — o texto NUNCA
// quebra/reflui pra caber num container menor, só transborda e é cortado
// no PAINT pelo `overflow-hidden` do avô. A geometria do próprio `<span>`
// da letra continua a mesma de sempre, mesmo com o container STUDIO
// visualmente colapsado — por isso dá pra medir direto aqui.
export default function useTransicaoParaIcone({
  origemRef,
  slimeRef,
  overlayRef,
  esticoRef,
  pathRef,
  letra,
  dLetra,
  dIcone,
  bboxLetra,
  ativo,
  visivel,
  atrasoMs = 0,
  instantaneo = false,
}) {
  const primeiraExecucaoRef = useRef(true);

  // Toda técnica que NÃO é 'blob' usa o morph direto letra↔ícone; 'blob'
  // usa os dois interpoladores de estágio abaixo. `USA_BLOB` é derivado de
  // constante de módulo (não muda em runtime), então este `if` dentro do
  // `useMemo` não quebra a regra dos hooks — só evita montar um
  // interpolador do `flubber` que a técnica ativa nunca vai chamar.
  const interpolador = useMemo(
    () => (USA_BLOB ? null : interpolate(dLetra, dIcone, { maxSegmentLength: 2 })),
    [dLetra, dIcone]
  );
  const interpoladorParaBlob = useMemo(
    () => (USA_BLOB ? interpolate(dLetra, PATH_BLOB_TRANSICIONAL, { maxSegmentLength: 2 }) : null),
    [dLetra]
  );
  const interpoladorDoBlob = useMemo(
    () => (USA_BLOB ? interpolate(PATH_BLOB_TRANSICIONAL, dIcone, { maxSegmentLength: 2 }) : null),
    [dIcone]
  );

  useLayoutEffect(() => {
    const overlay = overlayRef.current;
    const estico = esticoRef.current;
    const path = pathRef.current;
    const slime = slimeRef.current;
    const origemEl = origemRef.current;
    if (!overlay || !estico || !path || !slime || !origemEl) return undefined;

    const s = slime.getBoundingClientRect();
    const r = origemEl.getBoundingClientRect();
    const tinta = medirTintaLetra(origemEl, letra);
    const destinoLeft = s.right + GAP_PX;
    const destinoTop = s.top + s.height / 2 - TAMANHO_ICONE_PX / 2 + DESLOC_Y_ICONE_PX;

    overlay.style.left = `${destinoLeft}px`;
    overlay.style.top = `${destinoTop}px`;

    // Horizontal usa o `<span>` inteiro (left da caixa cheia já bate com os
    // vizinhos). Vertical usa a BASELINE calculada (`inkTop` acima) — a
    // caixa cheia do `<span>` não é o traço da letra, então alinhar pelo
    // topo dela deixava I/O flutuando fora da baseline das outras.
    // Tamanho usa `tinta` (ver `medirTintaLetra`) pelo mesmo motivo.
    const dx = r.left - destinoLeft + ESPACAMENTO_EXTRA_PX;
    const inkTop = r.top + tinta.ascentFonte - tinta.ascentTinta;
    const dy = inkTop - destinoTop;
    // `dLetra` só ocupa `bboxLetra` dentro do viewBox 0 0 24 24 (o resto é
    // margem vazia) — escalar por `TAMANHO_ICONE_PX` direto (como se a
    // letra ocupasse o viewBox inteiro) rendia ela bem menor que o texto
    // vizinho. Escalar pela FRAÇÃO real da tinta corrige isso.
    const sx = (tinta.width * VIEWBOX) / (TAMANHO_ICONE_PX * bboxLetra.width);
    const sy = (tinta.height * VIEWBOX) / (TAMANHO_ICONE_PX * bboxLetra.height);
    const transformLetra = `translate(${dx}px, ${dy}px) scale(${sx}, ${sy})`;
    const transformIcone = 'translate(0px, 0px) scale(1, 1)';
    // Ângulo do trajeto reto entre os dois pontos (origem letra ↔ destino
    // ícone), no MESMO sistema de coordenadas do `dx,dy` acima — eixo pro
    // squash-and-stretch esticar. Não importa o sentido da viagem (ida ou
    // volta): a reta é a mesma, só percorrida ao contrário.
    const angulo = Math.atan2(dy, dx);
    // Direção do MOVIMENTO real (não só a reta): sinal muda com o sentido
    // da viagem — `ativo` true percorre letra→ícone (de dx,dy até 0,0,
    // vetor -dx,-dy), `ativo` false percorre ícone→letra (vetor dx,dy). O
    // rastro (`rastro-gosma`) aponta pro lado OPOSTO ao movimento — por
    // isso o sinal já sai invertido aqui.
    const sinalMovimento = ativo ? 1 : -1;
    const magnitude = Math.hypot(dx, dy) || 1;
    const rastroX = (sinalMovimento * dx) / magnitude;
    const rastroY = (sinalMovimento * dy) / magnitude;
    // Cor base lida do computed style (herdada de `.text-neon`) em vez de
    // hardcoded — `drop-shadow` precisa de alpha explícito (`currentColor`
    // não aceita modificador de opacidade), então convertemos o
    // `rgb(r, g, b)` computado pro `rgba(...)` que o perfil de rastro usa
    // por frame.
    const corBase = getComputedStyle(overlay).color;
    const corComAlpha = (alpha) => corBase.replace('rgb(', 'rgba(').replace(')', `, ${alpha.toFixed(2)})`);

    // `!visivel` (pedido do usuário, 2026-09-26: trocar o "desmonte" da
    // volta por um crossfade simples) entra na mesma saída sem transição:
    // esta peça só fica visível durante a IDA (viagem de verdade, ver
    // `letraViajanteVisivel` em `LogoSlimeStudio.jsx`) — na volta ela
    // continua invisível o tempo todo, então animar o trajeto seria
    // trabalho de GPU/CPU sem efeito visual nenhum. `instantaneo` cobre o
    // caso de reentrada rápida (`VOLTA_ANIMADA=false` ou toggle no meio de
    // uma transição em curso): pula pro estado final sem transição.
    if (primeiraExecucaoRef.current || instantaneo || !visivel) {
      primeiraExecucaoRef.current = false;
      overlay.style.transition = 'none';
      overlay.style.transform = ativo ? transformIcone : transformLetra;
      overlay.style.filter = 'none';
      estico.style.transition = 'none';
      estico.style.transform = 'none';
      path.setAttribute('d', ativo ? dIcone : dLetra);
      return undefined;
    }

    const de = ativo ? transformLetra : transformIcone;
    const para = ativo ? transformIcone : transformLetra;

    overlay.style.transition = 'none';
    overlay.style.transform = de;
    overlay.style.filter = 'none';
    // Reseta pra identidade aqui (fora do rAF) — só a técnica
    // 'esticar-fusao' escreve em `estico.style.transform` por frame; nas
    // outras técnicas ele precisa ficar parado neste valor o tempo todo.
    estico.style.transition = 'none';
    estico.style.transform = 'none';

    // Duplo `requestAnimationFrame` no lugar de forçar reflow
    // (`getBoundingClientRect()` logo após o `transition:none` — técnica
    // antiga daqui, trocada 2026-09-26): com só 2 letras viajando (I/O) um
    // reflow forçado por letra passava batido, mas agora são 6 de uma vez
    // — 6 recálculos de layout síncronos em sequência, no mesmo commit,
    // travando a thread principal bem no instante em que a animação
    // deveria começar (pedido do usuário: "a fluidez não está boa").
    // 2 rAFs garante que o browser PINTOU o estado "sem transição" antes
    // de religar a transição (mesma garantia do reflow forçado), sem
    // bloquear a thread — o 1º rAF só garante que já passamos deste frame
    // de commit, o 2º já está depois do paint. O `setTimeout` do morph de
    // forma entra AQUI DENTRO (não fora) pra continuar sincronizado com o
    // instante real em que a transição de posição começa.
    let pararPasso;
    let idAtraso;
    let idRaf2;
    const de01 = ativo ? 0 : 1;
    const para01 = ativo ? 1 : 0;
    const idRaf1 = requestAnimationFrame(() => {
      idRaf2 = requestAnimationFrame(() => {
        overlay.style.transition = `transform ${DURACAO_TRAVESSIA_MS}ms ${EASING_TRAVESSIA} ${atrasoMs}ms`;
        overlay.style.transform = para;

        idAtraso = setTimeout(() => {
          const inicio = performance.now();
          function passo(agora) {
            const bruto = Math.min((agora - inicio) / DURACAO_TRAVESSIA_MS, 1);
            const t = de01 + (para01 - de01) * suavizar(bruto);
            // 'blob': 1ª metade do trajeto (t 0→0.5) morfa letra→gota, 2ª
            // metade (t 0.5→1) morfa gota→ícone — remapeia cada metade pra
            // 0..1 antes de passar pro interpolador correspondente.
            // Direção reversa (ícone→letra) funciona igual: `t` já vem
            // direction-agnostic de `de01`/`para01` acima.
            const d = USA_BLOB
              ? t <= 0.5
                ? interpoladorParaBlob(t / 0.5)
                : interpoladorDoBlob((t - 0.5) / 0.5)
              : interpolador(t);
            path.setAttribute('d', d);
            // Squash-and-stretch escreve em `estico.style.transform` — roda
            // no MESMO rAF do morph de forma acima (não um loop à parte)
            // pra ficar sincronizado sem custo extra — só `transform`, que
            // não dispara layout.
            const transformsEstico = [];
            if (USA_ESTICAR_FUSAO) {
              const esticar = perfilDeEsticar(bruto) * AMPLITUDE_ESTICAR;
              transformsEstico.push(
                `rotate(${angulo}rad) scale(${1 + esticar}, ${1 - esticar * 0.6}) rotate(${-angulo}rad)`
              );
            }
            if (transformsEstico.length > 0) {
              estico.style.transform = transformsEstico.join(' ');
            }
            // Rastro de gosma: reaproveita o MESMO perfil de "velocidade"
            // do squash-and-stretch (pico no meio do trajeto, zero parado)
            // pra modular blur geral + 3 "fantasmas" (`drop-shadow`
            // empilhados) na direção oposta ao movimento, cada um mais
            // longe/apagado que o anterior. Combina limpo com
            // 'esticar-fusao' (pedido do usuário, 2026-09-26: "junta esse
            // mais o esticar-fusao") — os dois só escrevem em propriedades
            // CSS diferentes (`transform` do `estico` vs `filter` do
            // `overlay`), sem conflito.
            if (USA_RASTRO_GOSMA) {
              const velocidade = perfilDeEsticar(bruto);
              overlay.style.filter = velocidade <= 0 ? 'none' : [
                `blur(${(velocidade * 0.6).toFixed(2)}px)`,
                `drop-shadow(${(rastroX * 3).toFixed(1)}px ${(rastroY * 3).toFixed(1)}px 2px ${corComAlpha(velocidade * 0.5)})`,
                `drop-shadow(${(rastroX * 7).toFixed(1)}px ${(rastroY * 7).toFixed(1)}px 3px ${corComAlpha(velocidade * 0.3)})`,
                `drop-shadow(${(rastroX * 12).toFixed(1)}px ${(rastroY * 12).toFixed(1)}px 4px ${corComAlpha(velocidade * 0.15)})`,
              ].join(' ');
            }
            if (bruto >= 1) pararPasso?.();
          }
          pararPasso = registrarPasso(passo);
        }, atrasoMs);
      });
    });

    return () => {
      cancelAnimationFrame(idRaf1);
      cancelAnimationFrame(idRaf2);
      clearTimeout(idAtraso);
      pararPasso?.();
    };
  }, [
    ativo,
    visivel,
    interpolador,
    interpoladorParaBlob,
    interpoladorDoBlob,
    atrasoMs,
    instantaneo,
    dLetra,
    dIcone,
    bboxLetra,
    letra,
    origemRef,
    overlayRef,
    esticoRef,
    pathRef,
    slimeRef,
  ]);

  // Corte instantâneo (sem transition) — na IDA, o handoff pra peça
  // estática do IconeClaquete só fica invisível quando as formas já
  // COINCIDEM (mesma posição/forma), então o corte não é percebido. Na
  // VOLTA, `visivel` já começa e termina `false` (ver efeito acima), então
  // este set é sempre um no-op redundante nessa direção.
  useEffect(() => {
    if (overlayRef.current) overlayRef.current.style.opacity = visivel ? '1' : '0';
  }, [visivel, overlayRef]);
}

// Troca de texto "Upscale pixelado" (escolhida pelo usuário, 2026-10-08): o texto
// antigo vira pixel grosso e some; o novo chega em baixa resolução e ganha
// nitidez, como o upscale do player. Os elementos recebem um filtro SVG de
// pixelização (`<filter id="pixA-…">`/`pixB-…`, renderizados por
// components/SeletorEmMenu.jsx) cujo tamanho de célula este módulo anima por
// quadro — filtro SVG não anima por CSS.

const TAMANHO_MAX_PX = 10;
const SAI_FRACAO = 0.9;
const ENTRA_ATRASO_FRACAO = 0.35;
const ENTRA_FRACAO = 1;
const ENTRA_OPACIDADE_FRACAO = 0.5;

// Duração total da troca para uma duração-base `ms`.
export const duracaoTotalDaTroca = (ms) => ms * (ENTRA_ATRASO_FRACAO + ENTRA_FRACAO);

const limitar = (p) => Math.max(0, Math.min(p, 1));
const interpolar = (de, ate, p) => de + (ate - de) * p;

function partesDoFiltro(svg, letra, sufixo) {
  const filtro = svg.querySelector(`#pix${letra}-${sufixo}`);
  return {
    referencia: `url(#pix${letra}-${sufixo})`,
    flood: filtro.querySelector('[data-p="flood"]'),
    comp: filtro.querySelector('[data-p="comp"]'),
    morph: filtro.querySelector('[data-p="morph"]'),
  };
}

// Células pares: o raio da dilatação (metade da célula) fica inteiro.
function pixelar(no, partes, tamanho) {
  const celula = 2 * Math.round(tamanho / 2);
  if (celula <= 1) {
    no.style.filter = '';
    return;
  }
  partes.flood.setAttribute('x', String(celula / 2 - 1));
  partes.flood.setAttribute('y', String(celula / 2 - 1));
  partes.comp.setAttribute('width', String(celula));
  partes.comp.setAttribute('height', String(celula));
  partes.morph.setAttribute('radius', String(celula / 2));
  no.style.filter = partes.referencia;
}

// Roda a troca em `entra`/`sai` e devolve a função que a cancela. Chamar dentro de
// um `useLayoutEffect`: o primeiro quadro é aplicado na hora, antes da pintura, senão
// o texto novo apareceria inteiro por um instante.
// Sem `sai`, só a entrada roda (texto que aparece sem trocar outro, ex.: a ilha
// abrindo); `atrasoMs` empurra o começo de tudo (esperar o fade da cápsula).
export function pixelarTroca({ entra, sai, svg, sufixo, ms, atrasoMs = 0 }) {
  if (!entra || !svg) return undefined;
  const filtroSai = sai ? partesDoFiltro(svg, 'A', sufixo) : null;
  const filtroEntra = partesDoFiltro(svg, 'B', sufixo);
  const inicio = performance.now();
  let quadro = 0;

  const limpar = () => {
    for (const no of [entra, sai].filter(Boolean)) {
      no.style.filter = '';
      no.style.opacity = '';
    }
  };

  const desenhar = (agora) => {
    const t = agora - inicio - atrasoMs;
    if (sai) {
      const pSai = limitar(t / (ms * SAI_FRACAO));
      sai.style.opacity = String(1 - pSai);
      pixelar(sai, filtroSai, interpolar(1, TAMANHO_MAX_PX, pSai * pSai));
    }

    const pEntra = limitar((t - ms * ENTRA_ATRASO_FRACAO) / (ms * ENTRA_FRACAO));
    const pOpacidade = limitar((t - ms * ENTRA_ATRASO_FRACAO) / (ms * ENTRA_OPACIDADE_FRACAO));
    entra.style.opacity = String(pOpacidade);
    pixelar(entra, filtroEntra, interpolar(TAMANHO_MAX_PX, 1, 1 - (1 - pEntra) ** 2));

    if (t < duracaoTotalDaTroca(ms)) quadro = requestAnimationFrame(desenhar);
    else limpar();
  };

  desenhar(inicio);
  return () => {
    cancelAnimationFrame(quadro);
    limpar();
  };
}

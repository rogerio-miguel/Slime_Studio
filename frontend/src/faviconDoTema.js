import { QUADRO_REPOUSO } from './components/mascote/quadros.js';

// Favicon = o mascote de repouso na cor do tema. O SVG nasce dos mesmos `d` do
// quadro que a UI usa, então os dois não divergem. Navegador sem suporte a
// favicon SVG fica sem ícone: não há PNG de reserva.
//
// Fones mais claros que o `#262626` da UI: na aba escura do navegador aquele
// cinza some em 16px.
const COR_DOS_FONES = '#404040';
const FRACAO_DE_BRANCO_NO_BRILHO = 0.4; // mesma proporção de `--color-neon-claro` (index.css)

// O mascote tem 11 linhas (3 a 13); o viewBox quadrado de 16 evita que o
// navegador estique o desenho.
const VIEWBOX = '0 1 16 16';

function misturarComBranco(hex, fracao) {
  const canais = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
  const [r, g, b] = canais.map((c) => Math.round(c * (1 - fracao) + 255 * fracao));
  return `#${[r, g, b].map((c) => c.toString(16).padStart(2, '0')).join('')}`;
}

function montarSvg(corNeon) {
  const cores = {
    b: corNeon,
    h: COR_DOS_FONES,
    l: misturarComBranco(corNeon, FRACAO_DE_BRANCO_NO_BRILHO),
  };
  const caminhos = QUADRO_REPOUSO.map(
    ({ letra, d }) => `<path fill="${cores[letra]}" d="${d}"/>`,
  ).join('');
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${VIEWBOX}" shape-rendering="crispEdges">${caminhos}</svg>`;
}

function obterLink() {
  let link = document.getElementById('favicon-do-tema');
  if (!link) {
    link = document.createElement('link');
    link.id = 'favicon-do-tema';
    link.rel = 'icon';
    link.type = 'image/svg+xml';
    link.setAttribute('sizes', 'any');
    document.head.appendChild(link);
  }
  return link;
}

export function aplicarFavicon(corNeon) {
  obterLink().href = `data:image/svg+xml,${encodeURIComponent(montarSvg(corNeon))}`;
}

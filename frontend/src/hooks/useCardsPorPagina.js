import { useSyncExternalStore } from 'react';

// Quantos pôsteres de `tamanho="pequeno"` cabem numa linha — espelha
// `CLASSES_POR_PAGINA.pequeno` (inicio/tamanhoDeCard.js): 2 / sm 3 / md 4 / lg 5 /
// xl 6. Existe em JS porque quem monta a lista precisa saber QUANTOS itens
// entram na linha de pôsteres (o resto vira outra apresentação); o CSS sozinho
// só esconderia os excedentes, que sumiriam da tela.
const FAIXAS = [
  ['(min-width: 1280px)', 6],
  ['(min-width: 1024px)', 5],
  ['(min-width: 768px)', 4],
  ['(min-width: 640px)', 3],
];
const MINIMO = 2;

function lerQuantidade() {
  return FAIXAS.find(([consulta]) => window.matchMedia(consulta).matches)?.[1] ?? MINIMO;
}

function assinar(aoMudar) {
  const consultas = FAIXAS.map(([consulta]) => window.matchMedia(consulta));
  consultas.forEach((c) => c.addEventListener('change', aoMudar));
  return () => consultas.forEach((c) => c.removeEventListener('change', aoMudar));
}

export default function useCardsPorPagina() {
  return useSyncExternalStore(assinar, lerQuantidade, () => MINIMO);
}

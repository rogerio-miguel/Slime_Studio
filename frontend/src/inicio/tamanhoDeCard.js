// Vocabulário de tamanho de card — fonte única compartilhada pelas seções da
// home que rolam (FileiraDeCards.jsx) e pela grade de catálogo que quebra
// linha (GradeDeCatalogo.jsx). As duas montam o slot do card com EXATAMENTE
// estas constantes, então saem com o mesmo tamanho por construção, não por
// coincidência aritmética.
//
// Geometria medida ao vivo no Disney+ (viewport 1920): pôster 2:3, dois
// tamanhos — `tamanho="grande"` ~336×502 / `"pequeno"` ~277×414 (ver
// `CLASSES_POR_PAGINA`). O respiro entre cards vem do `p-[10px]` de cada slot
// (a trilha/grade NÃO tem `gap`); gutter de 3.7% de cada lado (onde a fileira
// ancora as setas). O título alinha com a borda do CARD interno: gutter 3.7%
// + os 10px do `p-[10px]` do slot.
//
// `--por-pagina` mora nas CLASSES (um valor por breakpoint), nunca numa prop
// numérica: prop viraria classe interpolada e o Tailwind não extrai valor
// dinâmico. A prop `tamanho` seleciona entre DUAS strings de classe LITERAIS
// (as duas presentes aqui no fonte pro Tailwind extrair). Valores com `/` ou
// `calc()` (`FLEX_BASIS_SLOT`, `PADDING_TITULO`) vão no `style` inline: a `/`
// colide com o modificador de opacidade do Tailwind v4 (mesma armadilha do
// `--slide-gap` em CarrosselDestaques.jsx).
//
//   - `grande`  (default): pôster ~336px, 5 por página no desktop — fileiras de
//                catálogo (Próximas estreias, Top 10, gênero) e grade da Galeria.
//   - `pequeno`: pôster ~277px, 6 por página — "Continuar assistindo".
export const CLASSES_POR_PAGINA = {
  grande: '[--por-pagina:2] sm:[--por-pagina:3] md:[--por-pagina:3] lg:[--por-pagina:4] xl:[--por-pagina:5]',
  pequeno: '[--por-pagina:2] sm:[--por-pagina:3] md:[--por-pagina:4] lg:[--por-pagina:5] xl:[--por-pagina:6]',
};

// flex-basis de cada slot: uma fração igual da trilha/grade conforme
// `--por-pagina`. Vai no `style` inline — a `/` colide com o modificador de
// opacidade do Tailwind v4.
export const FLEX_BASIS_SLOT = 'calc(100% / var(--por-pagina))';

// Gutter de 3.7% de cada lado da trilha/grade (onde a fileira ancora as setas).
export const CLASSE_GUTTER = 'px-[3.7%]';

// padding-inline do título: alinha o texto com a borda do CARD (não do slot) —
// gutter 3.7% + os 10px do `p-[10px]` do slot. Vai no `style` inline pelo
// mesmo motivo de `FLEX_BASIS_SLOT` (calc arbitrário com `%`).
export const PADDING_TITULO = 'calc(3.7% + 10px)';

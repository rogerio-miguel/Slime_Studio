// Vocabulário de tamanho de card — fonte única compartilhada pelas seções da
// home que rolam (FileiraDeCards.jsx) e pela grade de catálogo que quebra
// linha (GradeDeCatalogo.jsx). As duas montam o slot do card com EXATAMENTE
// estas constantes, então saem com o mesmo tamanho por construção, não por
// coincidência aritmética.
//
// Geometria medida ao vivo no Disney+ (viewport 1920): pôster 2:3, dois
// tamanhos — `tamanho="grande"` ~336×502 / `"pequeno"` ~277×414 (ver
// `CLASSES_POR_PAGINA`). Slot do `<li>` SEM padding e trilha/grade SEM `gap`
// (pedido explícito do usuário, 2026-09-15 — removido o `p-[10px]` que cada
// slot tinha antes): cards colam borda a borda, maximizando o pôster; gutter
// de 3.7% de cada lado (onde a fileira ancora as setas). O título alinha
// direto com o gutter — a borda do CARD e a borda do SLOT são a mesma coisa
// agora, sem inset a mais pra somar.
//
// `--por-pagina` mora nas CLASSES (um valor por breakpoint), nunca numa prop
// numérica: prop viraria classe interpolada e o Tailwind não extrai valor
// dinâmico. A prop `tamanho` seleciona entre DUAS strings de classe LITERAIS
// (as duas presentes aqui no fonte pro Tailwind extrair). `FLEX_BASIS_SLOT`
// (tem `/`, colide com o modificador de opacidade do Tailwind v4) vai no
// `style` inline por necessidade; `PADDING_TITULO`/`PADDING_TITULO_GRADE`
// (hoje só `'3.7%'`, sem `calc()`) seguem no `style` inline também, só por
// consistência com o mesmo padrão de import nos call sites.
//
//   - `grande`  (default do componente, mas nenhum chamador pede hoje):
//                pôster ~336px, 5 por página no desktop.
//   - `pequeno`: pôster ~277px, 6 por página — tamanho PADRÃO de fato,
//                pedido explícito do usuário (2026-09-15) pra Home e Galeria
//                saírem com o mesmo card: fileiras de pôster da Home
//                (Próximas estreias, Top 10), grade da Galeria e a grade de
//                resultado de busca da própria Home. "Continuar assistindo"
//                não entra aqui — usa `episodio` (thumb, não pôster).
//   - `episodio`: cards 16:9 (thumb de episódio, não pôster) — bem mais largo
//                por item que `grande`/`pequeno` porque 16:9 já é mais largo
//                que 2:3 pra mesma "presença" visual. Menos por página (1–4)
//                pra reproduzir a largura do card real de
//                LinhaDeEpisodio.jsx/PaginaDoAnime.jsx (~444px, medido ao
//                vivo em viewport 1920 — 4 por página nesse breakpoint, não
//                3: a essa largura 3 por página dava ~568px, passando do
//                alvo em ~28%). Usado só por "Continuar assistindo".
export const CLASSES_POR_PAGINA = {
  grande: '[--por-pagina:2] sm:[--por-pagina:3] md:[--por-pagina:3] lg:[--por-pagina:4] xl:[--por-pagina:5]',
  pequeno: '[--por-pagina:2] sm:[--por-pagina:3] md:[--por-pagina:4] lg:[--por-pagina:5] xl:[--por-pagina:6]',
  episodio: '[--por-pagina:1] sm:[--por-pagina:2] md:[--por-pagina:3] lg:[--por-pagina:3] xl:[--por-pagina:4]',
};

// flex-basis de cada slot: uma fração igual da trilha/grade conforme
// `--por-pagina`. Vai no `style` inline — a `/` colide com o modificador de
// opacidade do Tailwind v4.
export const FLEX_BASIS_SLOT = 'calc(100% / var(--por-pagina))';

// Gutter de 3.7% de cada lado da trilha/grade (onde a fileira ancora as setas).
export const CLASSE_GUTTER = 'px-[3.7%]';

// padding-inline do título ACIMA de uma GRADE (GradeDeCatalogo.jsx): o slot
// não tem padding (pedido do usuário, zerado pra maximizar o pôster — ver
// comentário no topo de GradeDeCatalogo.jsx), então o título alinha só com o
// gutter.
export const PADDING_TITULO_GRADE = '3.7%';

// padding-inline do título ACIMA de uma FILEIRA (FileiraDeCards.jsx) —
// exportado à parte pro nome no call site dizer qual contexto é, mas
// literalmente o mesmo valor: desde que o `p-[10px]` do slot da fileira foi
// removido (pedido explícito do usuário, 2026-09-15), a borda do card
// coincide com a borda do slot nos dois casos (fileira e grade), então os
// dois títulos alinham só com o gutter. Antes disso `PADDING_TITULO` somava
// +10px pra compensar o inset que só a fileira tinha.
export const PADDING_TITULO = PADDING_TITULO_GRADE;

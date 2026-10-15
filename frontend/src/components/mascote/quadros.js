// Mascote slime em pixel art (pedido do usuário, 2026-10-14; substituiu a
// claquete do lucide). Escada de Minimalismo, CLAUDE.md §4 passo 6: nenhuma lib
// de ícones tem esse mascote, então o desenho mora aqui. Segue a arte do
// projeto (`assets/icone-Slime_Studio2.png`): cúpula larga e baixa, brilho no
// canto, olhos semicerrados em traço e fones de ouvido.
//
// Grade 16×16. Cada letra do desenho é uma cor: `b` corpo (`currentColor`, o
// neon), `h` fones (cinza neutro `#262626`: a navbar rolada é preto puro e o
// `#0d0d0d` da busca some em traço de 1 célula) e `l` brilho; `.` é vazio (olhos
// e boca são o fundo aparecendo). Cada quadro vira um `<path>` por cor, gerado
// das linhas abaixo — o desenho fica legível aqui em vez de virar um monte de
// `d` escrito à mão. Tentativas descartadas: slime com ponta no topo (lia como
// gota), brilho de 1 célula (lia como terceiro olho) e olhos em L (liam como
// zangados).
//
// Os quadros da entrada (agachado, esticado) têm a base alinhada na linha 13,
// igual ao repouso; só o esticado sai do lugar (ver `slime-esticado` em
// `index.css`). Todo quadro novo mantém a base na linha 13, senão a troca de
// pose faz o slime "afundar" ou flutuar.
export const CORES_DO_SLIME = [
  { letra: 'b', classe: '' },
  { letra: 'h', classe: 'fill-[#262626]' },
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

export function montarQuadro(linhaInicial, linhas) {
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
export const QUADRO_REPOUSO = montarQuadro(TOPO_DO_REPOUSO, LINHAS_DO_REPOUSO);

// Olhos fechados: o repouso com os olhos (linha 7, buracos de 2 células nas
// colunas 4-5 e 10-11) preenchidos pelo corpo. Serve ao piscar e ao dormindo.
// Já houve outros gestos (olhar de lado, cima e baixo, arregalar ao passar o
// mouse num card) e foram tirados a pedido.
const LINHA_DOS_OLHOS = 7;
export const QUADRO_OLHOS_FECHADOS = montarQuadro(
  TOPO_DO_REPOUSO,
  LINHAS_DO_REPOUSO.map((linha, i) => (i === LINHA_DOS_OLHOS ? 'hhbbbbbbbbbbbbhh' : linha)),
);

export const QUADRO_AGACHADO = montarQuadro(5, [
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

export const QUADRO_ESTICADO = montarQuadro(1, [
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

// Murcho (erro): mais baixo e espalhado que o agachado, olhos inclinados com a
// ponta de fora mais baixa — o "/ \" de sobrancelha preocupada. Olhos de 2
// células nas colunas 5-6 e 9-10 (linha de cima) e 3-4 e 11-12 (linha de baixo).
export const QUADRO_MURCHO = montarQuadro(6, [
  '.....hhhhhh.....',
  '..hhh......hhh..',
  'hhbbbbbbbbbbbbhh',
  'hhblllbbbbbbbbhh',
  'hhbbb..bb..bbbhh',
  'hhb..bbbbbb..bhh',
  '.hbbbbbbbbbbbbh.',
  '..bbbbbbbbbbbb..',
]);

// O "Z" do sono, 3×3 no canto de cima à direita (colunas 12-14), acima dos
// fones. Só a cor do corpo (`b`), então segue o neon.
export const QUADRO_ZZZ = montarQuadro(0, ['............bbb.', '..............b.', '............bbb.']);

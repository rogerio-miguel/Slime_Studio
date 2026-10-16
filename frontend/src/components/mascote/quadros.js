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
  { letra: 'l', classe: 'fill-neon-claro' },
];

function caminhoDaCor(linhaInicial, colunaInicial, linhas, letra) {
  const corridas = new RegExp(`${letra}+`, 'g');
  return linhas
    .flatMap((linha, i) =>
      [...linha.matchAll(corridas)].map(
        ({ 0: trecho, index }) =>
          `M${colunaInicial + index} ${linhaInicial + i}h${trecho.length}v1h-${trecho.length}z`,
      ),
    )
    .join('');
}

// `colunaInicial` negativa deixa o desenho passar da grade pela esquerda (a poça
// espalhada do estado vazio); o SVG tem `overflow: visible`.
export function montarQuadro(linhaInicial, linhas, colunaInicial = 0) {
  return CORES_DO_SLIME.map(({ letra, classe }) => ({
    letra,
    classe,
    d: caminhoDaCor(linhaInicial, colunaInicial, linhas, letra),
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
// colunas 4-5 e 10-11) preenchidos pelo corpo. Serve ao piscar.
// Já houve outros gestos (olhar de lado, cima e baixo, arregalar ao passar o
// mouse num card) e foram tirados a pedido.
const LINHA_DOS_OLHOS = 7;
export const QUADRO_OLHOS_FECHADOS = montarQuadro(
  TOPO_DO_REPOUSO,
  LINHAS_DO_REPOUSO.map((linha, i) => (i === LINHA_DOS_OLHOS ? 'hhbbbbbbbbbbbbhh' : linha)),
);
// Um quadro de meio-fechado (1 célula por olho) foi tentado e tirado a pedido:
// o olho virava um pixel e ficava feio.
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

// Corpo murcho: a cúpula do agachado (arredondada, com brilho) derretendo numa
// poça mais larga que os fones, base na linha 13. Uma versão anterior com o topo
// reto lia como um retângulo. As linhas dos olhos (5 e 6) variam por pose, então
// ficam fora daqui.
const CABECA_DO_MURCHO = [
  '.....hhhhhh.....',
  '...hh......hh...',
  '..h..bbbbbb..h..',
  '.h.bllbbbbbbb.h.',
  'hhbbbbbbbbbbbbhh',
];
const POCA_DO_MURCHO = '.bbbbbbbbbbbbbb.';
const TOPO_DO_MURCHO = 6;

// Murcho (erro): olhos inclinados com a ponta de fora mais baixa — o "/ \\" de
// sobrancelha preocupada. Olhos de 2 células nas colunas 5-6 e 9-10 (linha de
// cima) e 3-4 e 11-12 (linha de baixo).
export const QUADRO_MURCHO = montarQuadro(TOPO_DO_MURCHO, [
  ...CABECA_DO_MURCHO,
  'hhbbb..bb..bbbhh',
  '.hb..bbbbbb..bh.',
  POCA_DO_MURCHO,
]);

// Vazio (estado vazio): o corpo sem os fones, espalhado numa poça mais larga que
// a grade (colunas -4 a 19, por isso as linhas têm 24 caracteres). Escolhido pelo
// usuário no artefato de variações (2026-10-15, "4a"): sem fone nenhum e com os
// olhos na linha de baixo, logo acima da poça, pra dar o ar de cabisbaixo. Já
// houve uma queda animada (repouso, murcho, engolindo o fone, repuxo) e uma versão
// que deixava o arco da cabeça de fora; as duas foram tiradas a pedido. Olhos
// fechados fixos sumiam no corpo e deixavam o slime sem rosto.
const COLUNA_DA_POCA = -4;
const LARGURA_DA_POCA = 24;
const alargar = (linha) => `....${linha}....`;
function faixaDaPoca(de, ate) {
  let linha = '';
  for (let i = 0; i < LARGURA_DA_POCA; i += 1) {
    const coluna = COLUNA_DA_POCA + i;
    linha += coluna >= de && coluna <= ate ? 'b' : '.';
  }
  return linha;
}
const CORPO_ESPALHADO = [
  '.....bbbbbb.....',
  '...bbllbbbbbb...',
  '.bbbllbbbbbbbbb.',
  'bbbbbbbbbbbbbbbb',
];
const TOPO_DO_ESPALHADO = 7;
const montarEspalhado = (linhaDosOlhos) =>
  montarQuadro(
    TOPO_DO_ESPALHADO,
    [...CORPO_ESPALHADO, linhaDosOlhos]
      .map(alargar)
      .concat(faixaDaPoca(-2, 17), faixaDaPoca(-3, 18)),
    COLUNA_DA_POCA,
  );
export const QUADRO_ESPALHADO = montarEspalhado('bbbb..bbbb..bbbb');
// Piscada: os olhos preenchidos pelo corpo, só por um instante.
export const QUADRO_ESPALHADO_DE_OLHOS_FECHADOS = montarEspalhado('bbbbbbbbbbbbbbbb');

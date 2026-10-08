// Tempos e curvas da cápsula da ilha dinâmica.
//
// Uma curva só (Material, sem overshoot) para forma e conteúdo. Uma mola na
// forma (`y1 > 1`) foi tentada e removida: na abertura a borda passava do
// tamanho final e corrigia no último instante; no fechamento o progresso
// ultrapassava a outra ponta, o navegador clampava `max-width`/`padding` em 0
// antes da hora e a cápsula ficava parada o resto da transição. Também não dá
// pra mover o overshoot para um `scale()`: encolhia o texto do link em repouso.
//
// Durações (450/400ms) copiadas do wordmark (LogoSlimeStudio.jsx). O conteúdo
// aparece com atraso (a forma abre antes, o texto entra quando já há espaço) e
// some rápido no fechamento.
export const EASE_ILHA = 'cubic-bezier(0.4, 0, 0.2, 1)';
export const DURACAO_ABRE_MS = 450;
export const DURACAO_FECHA_MS = 400;
const DURACAO_CONTEUDO_ABRE_MS = 280;
const DURACAO_CONTEUDO_FECHA_MS = 200;
const ATRASO_CONTEUDO_ABRE_MS = 170;
// Tempo que a cápsula leva para abrir depois da troca dos links, quando um gatilho
// que não é scroll (sinopse, captura...) pede a ilha no topo: dois quadros
// (hooks/useTrocaAntesDaIlha.js) mais folga. Só serve de base ao atraso do painel
// da sinopse; a abertura em si espera a troca ser pintada, não um tempo fixo.
export const ATRASO_APOS_TROCA_MS = 40;

export function estilosDaIlha(aberta) {
  const forma = aberta ? DURACAO_ABRE_MS : DURACAO_FECHA_MS;
  return {
    // `contain` isola o reflow do padding/background desta subárvore; o tamanho
    // da PRÓPRIA cápsula ainda conta para o layout do <ul> por fora.
    forma: {
      transitionDuration: `${forma}ms`,
      transitionTimingFunction: EASE_ILHA,
      contain: 'layout style',
    },
    // Duas propriedades: largura e opacidade.
    conteudo: {
      transitionDuration: `${forma}ms, ${aberta ? DURACAO_CONTEUDO_ABRE_MS : DURACAO_CONTEUDO_FECHA_MS}ms`,
      transitionTimingFunction: `${EASE_ILHA}, ${EASE_ILHA}`,
      transitionDelay: `0ms, ${aberta ? ATRASO_CONTEUDO_ABRE_MS : 0}ms`,
    },
  };
}

import { useEffect, useRef } from 'react';

// Move o foco pro heading da página a cada montagem — troca de rota do
// react-router-dom é navegação client-side, o navegador não reseta o foco
// sozinho como faria numa troca de página real. Sem isto, quem navega por
// teclado/leitor de tela ficaria "preso" no elemento clicado a cada troca de
// rota (acessibilidade nunca é opcional, CLAUDE.md §4). Uso: `<h1 ref={foco}
// tabIndex={-1}>`.
//
// `dep` opcional: refaz o foco quando muda, mesmo sem remontar o componente
// — necessário pra rotas que trocam só o parâmetro (ex. "/assistir/:id1" ->
// "/assistir/:id2" sem passar por outra rota), onde o React Router não
// remonta e o foco ficaria preso no elemento antigo.
export function useFocoAoMontar(dep) {
  const ref = useRef(null);
  useEffect(() => {
    ref.current?.focus();
  }, [dep]);
  return ref;
}

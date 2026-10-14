import { useEffect } from 'react';

// Com o menu/painel aberto, o clique fora dele só o fecha: é interceptado na
// captura, antes de chegar ao card, link ou botão que estava embaixo (senão o
// mesmo clique que fecha também abriria o episódio ou criaria o anime). Fechar
// no `pointerdown` não serviria: o ouvinte sai com o fechamento e o `click`
// seguinte passaria direto. `bloqueado` (ex.: confirmação em voo) ignora o
// clique fora sem fechar nem engolir.
//
// Não depende de posição nem de empilhamento (a "cortina" invisível da ilha
// exige `fixed` sem ancestral com `transform`/`overflow`, que não vale na
// fileira de cards), por isso serve a qualquer menu da aplicação.
export function useFecharAoClicarFora(aberto, containerRef, aoFechar, { bloqueado = false } = {}) {
  useEffect(() => {
    if (!aberto || bloqueado) return undefined;
    const aoClicarFora = (evento) => {
      if (containerRef.current?.contains(evento.target)) return;
      evento.preventDefault();
      evento.stopPropagation();
      aoFechar();
    };
    document.addEventListener('click', aoClicarFora, true);
    return () => document.removeEventListener('click', aoClicarFora, true);
  }, [aberto, bloqueado, containerRef, aoFechar]);
}

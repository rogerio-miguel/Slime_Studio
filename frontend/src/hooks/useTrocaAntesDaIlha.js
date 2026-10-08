import { useEffect, useState } from 'react';

// Na volta, os links voltam ao lugar pouco depois de a cápsula começar a fechar
// (como rolando pra cima, onde a ilha fecha aos 96px e a troca desfaz aos 24px),
// não depois de ela terminar de fechar: esperar os ~400ms do fechamento fazia o
// nome sumir, a ilha fechar e SÓ ENTÃO os links trocarem. A troca remonta a
// cápsula, então o fim do fechamento é cortado — igual ao scroll real.
const ATRASO_VOLTA_DOS_LINKS_MS = 120;

// Na Início a ilha só abre DEPOIS da troca de posição dos links, a mesma ordem
// do scroll (troca aos 24px, cápsula aos 96px). Quando um gatilho que não é
// scroll (sinopse, captura, notificação) pede a ilha no topo, `simulandoScroll`
// faz a troca primeiro e `liberada` abre a cápsula assim que a troca foi pintada
// (dois quadros, como dois eventos de scroll seguidos);
// ao fechar, os links voltam `ATRASO_VOLTA_DOS_LINKS_MS` depois de a cápsula começar
// a fechar. Abrir tudo junto remontava a cápsula (o slot do link muda) já aberta,
// sem animação.
// `exigeTroca` falso (já rolado, ou fora da Início): nada a simular.
export function useTrocaAntesDaIlha(exigeTroca, ilhaPedida) {
  const [simulandoScroll, setSimulandoScroll] = useState(false);
  const [liberada, setLiberada] = useState(false);
  useEffect(() => {
    if (!exigeTroca) return undefined;
    if (ilhaPedida) {
      setSimulandoScroll(true);
      return undefined;
    }
    setLiberada(false);
    const temporizador = setTimeout(() => setSimulandoScroll(false), ATRASO_VOLTA_DOS_LINKS_MS);
    return () => clearTimeout(temporizador);
  }, [exigeTroca, ilhaPedida]);
  // Só depois de a troca estar no DOM e pintada fechada: abrir antes remontava a
  // cápsula já aberta (o slot do link muda), sem animação. Dois `rAF` = o próximo
  // quadro depois da pintura, o mais perto possível do scroll real.
  useEffect(() => {
    if (!exigeTroca || !ilhaPedida || !simulandoScroll) return undefined;
    let segundo;
    const primeiro = requestAnimationFrame(() => {
      segundo = requestAnimationFrame(() => setLiberada(true));
    });
    return () => {
      cancelAnimationFrame(primeiro);
      cancelAnimationFrame(segundo);
    };
  }, [exigeTroca, ilhaPedida, simulandoScroll]);
  return { simulandoScroll, liberada };
}

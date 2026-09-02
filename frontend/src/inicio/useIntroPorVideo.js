import { useCallback, useEffect, useState } from 'react';
import { usePrefersReducedMotion } from './usePrefersReducedMotion.js';

// Introdução da home tocada por vídeo (CenarioDeEntrada.jsx via
// paginas/Inicio.jsx): o vídeo da logo toca uma vez sobre fundo preto fixo;
// ao terminar (`onEnded` em CenarioDeEntrada.jsx), `revelar()` vira a fase
// pra `revelado` e o fade de opacidade (CSS, já em CenarioDeEntrada.jsx e
// paginas/Inicio.jsx) descobre a interface por trás. Sem scroll, sem spacer,
// sem loop de frame — só o estado discreto `fase` (entrada/revelado).
//
// `prefers-reduced-motion`: fase já nasce `revelado` (inicializador do
// `useState`) — CenarioDeEntrada nem monta o `<video>`. Ouve mudança de
// preferência em runtime (usuário pode alternar com a página aberta).
export function useIntroPorVideo() {
  const movimentoReduzido = usePrefersReducedMotion();
  const [fase, setFase] = useState(() => (movimentoReduzido ? 'revelado' : 'entrada'));

  const revelar = useCallback(() => setFase('revelado'), []);

  useEffect(() => {
    if (movimentoReduzido) revelar();
  }, [movimentoReduzido, revelar]);

  return { fase, movimentoReduzido, revelar };
}

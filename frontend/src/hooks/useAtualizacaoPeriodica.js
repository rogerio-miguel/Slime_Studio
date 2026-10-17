import { useEffect } from 'react';

// Rebusca um recurso enquanto a página está aberta: a cada `intervaloMs` e ao
// voltar à aba. Só roda com a aba visível — aba em segundo plano não deve
// gerar tráfego, e a volta ao foco já recarrega.
export function useAtualizacaoPeriodica(recarregar, intervaloMs) {
  useEffect(() => {
    const recarregarSeVisivel = () => {
      if (document.visibilityState === 'visible') recarregar();
    };
    const intervalo = setInterval(recarregarSeVisivel, intervaloMs);
    document.addEventListener('visibilitychange', recarregarSeVisivel);
    return () => {
      clearInterval(intervalo);
      document.removeEventListener('visibilitychange', recarregarSeVisivel);
    };
  }, [recarregar, intervaloMs]);
}

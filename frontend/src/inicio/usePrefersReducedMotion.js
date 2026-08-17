import { useEffect, useState } from 'react';

const _CONSULTA = '(prefers-reduced-motion: reduce)';

// Detecta `prefers-reduced-motion: reduce` e acompanha mudança em runtime
// (usuário pode alternar a preferência do SO com a página aberta). Extraído
// de useScrubDeVideo.js na Fase 4 (pivot da home) pra ser reaproveitado por
// GradeRotativa.jsx sem duplicar a mesma lógica de matchMedia duas vezes.
export function usePrefersReducedMotion() {
  const [reduzido, setReduzido] = useState(() => window.matchMedia(_CONSULTA).matches);

  useEffect(() => {
    const consulta = window.matchMedia(_CONSULTA);
    const aoMudar = (evento) => setReduzido(evento.matches);
    consulta.addEventListener('change', aoMudar);
    return () => consulta.removeEventListener('change', aoMudar);
  }, []);

  return reduzido;
}

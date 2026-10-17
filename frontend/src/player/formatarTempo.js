// Extraído de BarraDeControles.jsx pra ser reaproveitado por PreviaDeCena.jsx
// (rótulo de tempo sob a miniatura) sem duplicar a formatação.
export function formatarTempo(segundos) {
  if (!Number.isFinite(segundos)) return '0:00';
  const m = Math.floor(segundos / 60);
  const s = Math.floor(segundos % 60)
    .toString()
    .padStart(2, '0');
  return `${m}:${s}`;
}

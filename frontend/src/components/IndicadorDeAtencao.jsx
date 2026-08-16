// Indicador persistente (ESPECIFICACAO.md §4/§10) de jobs em
// `aguardando_intervencao`, vindo do WS (`useEventosDeJobs.js` via
// App.jsx::Shell). Só leitura nesta fase — ação de retry/cancelar pela UI é
// o painel admin completo (Fase 4D, fora de escopo aqui). `role="status"` +
// `aria-live` pra leitor de tela anunciar sem precisar de foco explícito.
export default function IndicadorDeAtencao({ jobs }) {
  if (jobs.length === 0) return null;

  return (
    <div
      role="status"
      aria-live="polite"
      className="fixed right-4 top-4 z-50 rounded-full border border-amber-500/40 bg-amber-500/10 px-3 py-1 text-xs font-semibold text-amber-300 shadow-lg"
    >
      {jobs.length} {jobs.length === 1 ? 'job precisa' : 'jobs precisam'} de atenção
    </div>
  );
}

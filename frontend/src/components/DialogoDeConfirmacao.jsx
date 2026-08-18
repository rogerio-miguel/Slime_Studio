import { useEffect, useRef } from 'react';

// `<dialog>` nativo, mesmo idioma de DialogoDeFonteAmbigua.jsx (foco preso,
// backdrop e Esc de graça, sem lib de modal — Escada de Minimalismo,
// CLAUDE.md §4). Genérico o bastante pra qualquer ação destrutiva com
// confirmação (hoje: remover anime do catálogo, nos dois lugares que usam).
//
// `erro` (opcional): renderizado DENTRO do dialog, não fora — enquanto
// `showModal()` está ativo o resto do documento fica `inert`, então um erro
// exibido fora do <dialog> fica coberto pelo backdrop e inacessível a
// teclado/leitor de tela. Em caso de erro, quem chama mantém `aberto` true
// (permite retry) e só limpa `erro` junto do resto do estado ao fechar.
//
// Fechar via Esc (evento nativo `cancel`, cancelável) é ignorado enquanto
// `confirmando` for true — evita abandonar o dialog com a ação ainda em voo
// no servidor. Clique no backdrop não fecha este dialog de qualquer forma
// (sem `closedby="any"`); "Cancelar" já fica `disabled` nesse estado, então
// o guard aqui existe sobretudo pro Esc.
export default function DialogoDeConfirmacao({
  aberto,
  titulo,
  mensagem,
  erro,
  aoConfirmar,
  aoFechar,
  confirmando = false,
  rotuloConfirmar = 'Remover',
}) {
  const dialogRef = useRef(null);

  useEffect(() => {
    const dialogo = dialogRef.current;
    if (!dialogo) return;
    if (aberto && !dialogo.open) dialogo.showModal();
    if (!aberto && dialogo.open) dialogo.close();
  }, [aberto]);

  const fechar = (evento) => {
    if (confirmando) {
      evento?.preventDefault();
      return;
    }
    aoFechar();
  };

  return (
    <dialog
      ref={dialogRef}
      onClose={fechar}
      onCancel={fechar}
      aria-labelledby="titulo-dialogo-confirmacao"
      className="m-auto rounded-xl border border-neon-soft bg-surface p-6 text-white backdrop:bg-black/70"
    >
      <h2 id="titulo-dialogo-confirmacao" className="mb-2 text-base font-semibold">
        {titulo}
      </h2>
      <p className="mb-4 text-sm text-ink-muted">{mensagem}</p>
      {erro && (
        <p role="alert" className="mb-4 text-sm text-red-400">
          {erro}
        </p>
      )}
      <div className="flex items-center gap-4">
        <button
          type="button"
          onClick={aoConfirmar}
          disabled={confirmando}
          className="rounded-lg border border-red-500/60 px-4 py-2 text-sm text-red-400 outline-none transition-colors hover:border-red-400 hover:bg-red-950/40 focus-visible:ring-2 focus-visible:ring-neon disabled:cursor-not-allowed disabled:opacity-50"
        >
          {confirmando ? 'Removendo…' : rotuloConfirmar}
        </button>
        <button
          type="button"
          onClick={fechar}
          disabled={confirmando}
          className="text-xs text-ink-muted underline outline-none focus-visible:ring-2 focus-visible:ring-neon disabled:cursor-not-allowed disabled:opacity-50 disabled:no-underline"
        >
          Cancelar
        </button>
      </div>
    </dialog>
  );
}

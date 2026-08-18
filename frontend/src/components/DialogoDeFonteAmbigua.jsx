import { useEffect, useRef } from 'react';

// `<dialog>` nativo: foco preso, backdrop e fechar com Esc de graça, sem lib
// de modal — a única dependência de UI do projeto continua sendo Tailwind
// (Escada de Minimalismo, CLAUDE.md §4). Aberto/fechado via
// `.showModal()`/`.close()` no ref (não pelo atributo `open` direto — é
// `showModal()` que dá o comportamento modal real).
export default function DialogoDeFonteAmbigua({ aberto, dominio, candidatos, aoEscolher, aoFechar }) {
  const dialogRef = useRef(null);

  useEffect(() => {
    const dialogo = dialogRef.current;
    if (!dialogo) return;
    if (aberto && !dialogo.open) dialogo.showModal();
    if (!aberto && dialogo.open) dialogo.close();
  }, [aberto]);

  return (
    <dialog
      ref={dialogRef}
      onClose={aoFechar}
      onCancel={aoFechar}
      aria-labelledby="titulo-fonte-ambigua"
      className="m-auto rounded-xl border border-neon-soft bg-surface p-6 text-white backdrop:bg-black/70"
    >
      <h2 id="titulo-fonte-ambigua" className="mb-2 text-base font-semibold">
        Mais de um resultado em {dominio}
      </h2>
      <p className="mb-4 text-sm text-ink-muted">
        Não foi possível decidir sozinho — escolha o título correto:
      </p>
      <ul className="flex flex-col gap-2">
        {candidatos?.map((candidato) => (
          <li key={candidato.identificador}>
            <button
              type="button"
              onClick={() => aoEscolher(candidato)}
              className="flex w-full items-center justify-between gap-3 rounded-lg border border-border-chrome px-4 py-2 text-left text-sm outline-none transition-colors hover:border-neon focus-visible:ring-2 focus-visible:ring-neon"
            >
              <span className="truncate">{candidato.titulo_exibicao}</span>
              {candidato.versao != null && (
                <span className="flex-none rounded-md border border-border-chrome px-2 py-0.5 text-xs text-ink-muted">
                  {candidato.versao === 'dublado' ? 'Dublado' : 'Legendado'}
                </span>
              )}
            </button>
          </li>
        ))}
      </ul>
      <button
        type="button"
        onClick={aoFechar}
        className="mt-4 text-xs text-ink-muted underline outline-none focus-visible:ring-2 focus-visible:ring-neon"
      >
        Cancelar
      </button>
    </dialog>
  );
}

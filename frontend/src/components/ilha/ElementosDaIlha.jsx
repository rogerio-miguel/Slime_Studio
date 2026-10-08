// Peças tipográficas da cápsula: botão sem fundo (18px semibold, `ink-muted` →
// branco no hover, mesmo padrão do gatilho do `SeletorEmMenu`) e o divisor
// entre vizinhos. Quem monta conteúdo de ilha (Gerenciar, "Trocar banner")
// usa estas duas.
export function DivisorDaIlha() {
  return <span aria-hidden="true" className="h-4 w-px shrink-0 bg-white/15" />;
}

export function BotaoDaIlha({ children, perigo = false, ...props }) {
  return (
    <button
      type="button"
      className={`inline-flex h-8 shrink-0 cursor-pointer items-center whitespace-nowrap text-[18px] font-semibold outline-none transition-colors disabled:cursor-not-allowed disabled:opacity-40 motion-reduce:transition-none ${
        perigo
          ? 'text-red-400 hover:text-red-300 focus-visible:text-red-300'
          : 'text-ink-muted hover:text-white focus-visible:text-white'
      }`}
      {...props}
    >
      {children}
    </button>
  );
}

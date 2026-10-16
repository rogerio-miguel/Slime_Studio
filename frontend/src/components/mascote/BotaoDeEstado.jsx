// Botão de ação do `EstadoComMascote` (pílula neon, igual ao "Limpar filtros" da
// Galeria).
export default function BotaoDeEstado({ onClick, children }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="h-8 cursor-pointer rounded-full border border-neon bg-neon-soft px-4 text-sm font-semibold text-white outline-none transition-colors hover:bg-neon/30 focus-visible:border-white"
    >
      {children}
    </button>
  );
}

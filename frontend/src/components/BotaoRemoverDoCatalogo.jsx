// Botão de remover do catálogo — compartilhado por components/AnimeCard.jsx e
// inicio/CartaoDeEstreia.jsx. Renderiza posicionado absoluto sobre a capa, como
// IRMÃO do Link/button do card quando houver (button dentro de <a>/<button> é
// inválido). `preventDefault` + `stopPropagation` evitam ativar o Link/button
// por baixo. A opacidade some por padrão e só aparece no hover do card
// (`group-hover/card:` — exige um ancestral com `group/card`, que ambos os
// cards têm no wrapper) ou no foco do próprio botão (`focus-visible:`) — nunca
// via `hidden`/DOM removido, senão ficaria inalcançável por Tab.
export default function BotaoRemoverDoCatalogo({ titulo, aoRemover }) {
  return (
    <button
      type="button"
      onClick={(evento) => {
        evento.preventDefault();
        evento.stopPropagation();
        aoRemover();
      }}
      aria-label={`Remover ${titulo} do catálogo`}
      className="absolute right-2 top-2 z-10 rounded-full bg-black/70 p-1.5 text-white opacity-0 outline-none transition-all duration-200 hover:bg-red-950/80 hover:text-red-400 focus-visible:opacity-100 focus-visible:ring-2 focus-visible:ring-neon group-hover/card:opacity-100"
    >
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-4 w-4">
        <path strokeLinecap="round" strokeLinejoin="round" d="M6 18 18 6M6 6l12 12" />
      </svg>
    </button>
  );
}

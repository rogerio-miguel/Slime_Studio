// Ícone de "salvar" (fita de marcador) — cópia exata do glifo do botão
// "Salvar" do Instagram (mesmo `viewBox`/`points`, confirmado direto no SVG
// renderizado do próprio site, não só no HTML colado). Checado contra
// `lucide-react` (já instalado, ver `player/Icones.jsx`) antes de desenhar à
// mão — nenhum ícone de lá bate: o `Bookmark` de lá tem cantos arredondados
// no topo e um entalhe curvo embaixo (glifo "livro"), não o retângulo de
// cantos retos + V reto do Instagram. Sem equivalente pronto, mão na massa é
// o passo certo da Escada de Minimalismo (CLAUDE.md §4, passo 6).
// Extraído de `inicio/CartaoDeEstreia.jsx` (usava só lá) pra reuso em
// `AnimeCard.jsx` (pill "Já no catálogo", pedido explícito do usuário,
// 2026-09-21) — `className` vira prop pra cada chamador ajustar o tamanho ao
// próprio contexto (32px flutuando sobre a capa lá, 16px dentro da pill aqui).
// `preenchido` alterna entre contorno (ainda não salvo) e sólido (já
// salvo/catalogado), igual ao toggle do Instagram; `strokeWidth="2.5"` (mais
// grosso que o "2" de lá, pedido explícito do usuário) porque aqui é sempre
// um selo pequeno, precisa de mais peso visual pra não sumir.
export default function IconeSalvar({ preenchido = false, className = 'h-8 w-8' }) {
  return (
    <svg viewBox="0 0 24 24" className={className} role="img" aria-hidden="true">
      <polygon
        points="20 21 12 13.44 4 21 4 3 20 3 20 21"
        fill={preenchido ? 'currentColor' : 'none'}
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

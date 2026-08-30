// Pill de contagem de "episódios novos" sobre o card do anime (canto
// superior ESQUERDO — o superior direito é do botão de remover em
// AnimeCard.jsx). A origem do número e o status de lançamento já foram
// resolvidos no backend (`GET /api/animes` → `episodios_novos`, detector via
// AniList `nextAiringEpisode`, sem scraping/scheduler); aqui a única regra é
// "tem número positivo → mostra". `quantidade` ausente (card alimentado pelo
// feed "em alta", que não carrega esse campo), zero, `null` ou negativa não
// renderiza nada.
//
// `className` sobrescreve só o posicionamento (default: absoluto no canto,
// pro AnimeCard) — `PaginaDoAnime.jsx` passa "" e posiciona o badge inline,
// ao lado do <h1>. Acessibilidade: o número visível é `aria-hidden` e o
// texto real ("3 episódios novos") vai num <span class="sr-only"> —
// `aria-label` em <span> sem `role` não é anunciado de forma confiável.
export default function BadgeDeEpisodiosNovos({
  quantidade,
  className = 'absolute left-2 top-2 z-10',
}) {
  if (!quantidade || quantidade < 1) return null;

  const plural = quantidade > 1 ? 's' : '';

  return (
    <span
      className={`${className} inline-flex items-center rounded-full bg-neon px-2 py-0.5 text-xs font-semibold text-black`}
    >
      <span aria-hidden="true">{quantidade}</span>
      <span className="sr-only">
        {quantidade} episódio{plural} novo{plural}
      </span>
    </span>
  );
}

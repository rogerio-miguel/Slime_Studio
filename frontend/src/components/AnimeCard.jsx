import { Link } from 'react-router-dom';

// Linguagem visual portada de Slime_Shell_Web/AnimeCard.jsx (superfície
// escura, borda neon, hover translate leve, tag pill, line-clamp-2 no
// título) — não o componente em si: lá é Tailwind v3 com tokens que não
// existem aqui (bg-surface/text-cyanNeon do OUTRO projeto), usa
// `<div onClick>` sem role/tabIndex/teclado (viola acessibilidade
// obrigatória, CLAUDE.md §4), busca capa de endpoint que não existe nesta
// API, e o modelo de dados diverge (lá titulo_exibicao/dublado no título;
// aqui titulo/ano/slug, versao mora no Episodio). MVP tipográfico: sem
// imagem de capa (decisão do usuário) — `<Link>` real dá foco/navegação por
// teclado de graça, sem reimplementar nada.
export default function AnimeCard({ anime }) {
  return (
    <Link
      to={`/anime/${anime.id}`}
      className="group flex h-40 flex-col justify-between rounded-xl border border-neon-soft bg-surface p-4 outline-none transition-all duration-200 hover:-translate-y-1 hover:border-neon hover:bg-surface-hover focus-visible:-translate-y-1 focus-visible:border-neon focus-visible:ring-2 focus-visible:ring-neon"
    >
      <span className="w-fit rounded border border-neon-soft bg-neon/5 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-widest text-neon">
        {anime.ano ?? 'sem ano'}
      </span>
      <h2 className="line-clamp-2 text-sm font-semibold leading-snug text-white transition-colors group-hover:text-neon">
        {anime.titulo}
      </h2>
    </Link>
  );
}

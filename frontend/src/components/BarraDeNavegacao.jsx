import { useId } from 'react';
import { Link } from 'react-router-dom';

// Navbar fixa (z-20, sempre acima do vídeo hero e do conteúdo revelado) —
// opacidade e `inert` controlados pela fase do scrub (paginas/Inicio.jsx via
// inicio/useScrubDeVideo.js): invisível e inalcançável por teclado até
// `revelado`, mesma fase que dispara o fade-in do `main` (paginas/Inicio.jsx)
// — navbar e conteúdo aparecem juntos, ao final da animação.
//
// Gêneros/Favoritos: decisão do usuário sobre dados faltantes — não existe
// gêneros/favoritos no modelo hoje, então ficam visíveis mas desabilitados
// (`disabled` + `aria-disabled` + `title`), nunca escondidos.
//
// Busca: `termoBusca`/`aoMudarBusca` controlados pelo pai (`paginas/Inicio.jsx`
// — único lugar que hoje renderiza esta navbar). Filtro ao vivo, sem submit:
// digitar já dispara `aoMudarBusca` via `onChange`; Enter só evita reload de
// página (`preventDefault`), não navega mais pra `/animes`.
export default function BarraDeNavegacao({ fase, termoBusca, aoMudarBusca }) {
  const idBusca = useId();
  const visivel = fase === 'revelado';

  return (
    <nav
      aria-label="Principal"
      inert={fase !== 'revelado'}
      className={`fixed inset-x-0 top-0 z-20 flex items-center justify-between gap-6 bg-surface/70 px-6 py-4 backdrop-blur-sm transition-opacity duration-700 ease-out md:px-10 ${
        visivel ? 'opacity-100' : 'opacity-0'
      }`}
    >
      <div className="flex items-center gap-10">
        <Link
          to="/"
          className="text-2xl font-semibold tracking-wide text-white outline-none focus-visible:ring-2 focus-visible:ring-neon"
        >
          Slime Studio
        </Link>
        <ul className="hidden items-center gap-8 text-lg text-ink-muted sm:flex sm:text-lg">
          <li>
            <Link
              to="/"
              className="outline-none transition-colors hover:text-white focus-visible:text-white focus-visible:ring-2 focus-visible:ring-neon"
            >
              Início
            </Link>
          </li>
          <li>
            <Link
              to="/animes"
              className="outline-none transition-colors hover:text-white focus-visible:text-white focus-visible:ring-2 focus-visible:ring-neon"
            >
              Animes
            </Link>
          </li>
          <li>
            <button
              type="button"
              disabled
              aria-disabled="true"
              title="Em breve"
              className="cursor-not-allowed opacity-50"
            >
              Gêneros
            </button>
          </li>
          <li>
            <button
              type="button"
              disabled
              aria-disabled="true"
              title="Em breve"
              className="cursor-not-allowed opacity-50"
            >
              Favoritos
            </button>
          </li>
        </ul>
      </div>
      <form onSubmit={(event) => event.preventDefault()} role="search" className="flex items-center gap-2">
        <label htmlFor={idBusca} className="sr-only">
          Buscar animes
        </label>
        <input
          id={idBusca}
          type="search"
          value={termoBusca}
          onChange={(event) => aoMudarBusca(event.target.value)}
          placeholder="Buscar…"
          className="w-32 rounded-md border border-border-chrome bg-surface/80 px-3 py-1.5 text-sm text-white outline-none transition-all focus-visible:border-neon focus-visible:ring-2 focus-visible:ring-neon sm:w-40"
        />
      </form>
    </nav>
  );
}

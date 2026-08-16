import { useId, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';

// Navbar fixa (z-20, sempre acima do vídeo hero e do conteúdo revelado) —
// opacidade e `inert` controlados pela fase do scrub (paginas/Inicio.jsx via
// inicio/useScrubDeVideo.js): invisível e inalcançável por teclado durante
// `entrada`, aparece a partir de `chegando`.
//
// Gêneros/Favoritos: decisão do usuário sobre dados faltantes — não existe
// gêneros/favoritos no modelo hoje, então ficam visíveis mas desabilitados
// (`disabled` + `aria-disabled` + `title`), nunca escondidos.
export default function BarraDeNavegacao({ fase }) {
  const navigate = useNavigate();
  const [termoBusca, setTermoBusca] = useState('');
  const idBusca = useId();
  const visivel = fase !== 'entrada';

  function aoSubmeterBusca(event) {
    event.preventDefault();
    const termo = termoBusca.trim();
    navigate(termo ? `/animes?q=${encodeURIComponent(termo)}` : '/animes');
  }

  return (
    <nav
      aria-label="Principal"
      inert={fase === 'entrada'}
      className={`fixed inset-x-0 top-0 z-20 flex items-center justify-between gap-6 px-6 py-4 transition-opacity duration-700 ease-out md:px-10 ${
        visivel ? 'opacity-100' : 'opacity-0'
      }`}
    >
      <div className="flex items-center gap-8">
        <Link
          to="/"
          className="text-lg font-semibold tracking-wide text-white outline-none focus-visible:ring-2 focus-visible:ring-neon"
        >
          Slime Studio
        </Link>
        <ul className="hidden items-center gap-6 text-sm text-ink-muted sm:flex">
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
      <form onSubmit={aoSubmeterBusca} role="search" className="flex items-center gap-2">
        <label htmlFor={idBusca} className="sr-only">
          Buscar animes
        </label>
        <input
          id={idBusca}
          type="search"
          value={termoBusca}
          onChange={(event) => setTermoBusca(event.target.value)}
          placeholder="Buscar…"
          className="w-32 rounded-md border border-border-chrome bg-surface/80 px-3 py-1.5 text-sm text-white outline-none transition-all focus-visible:border-neon focus-visible:ring-2 focus-visible:ring-neon sm:w-40"
        />
      </form>
    </nav>
  );
}

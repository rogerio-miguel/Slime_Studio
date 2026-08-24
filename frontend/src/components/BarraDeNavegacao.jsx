import { useId } from 'react';
import { Link, useLocation } from 'react-router-dom';
import logo from '../assets/logo2.png';

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
// e `paginas/Galeria.jsx`, cada um filtrando sua própria lista). Filtro local
// ao vivo, sem submit: digitar já dispara `aoMudarBusca` via `onChange`.
// Enter (`onSubmit`, `preventDefault` evita reload de página) dispara
// `aoSubmeterBusca`, opcional — hoje aciona a busca em fontes externas.
// `aoMudarBusca` inteiro é opcional: `paginas/PaginaDoAnime.jsx` não tem uma
// lista pra filtrar, então o formulário de busca nem renderiza ali — melhor
// omitir a caixa do que exibir um campo que não faz nada ao digitar.
export default function BarraDeNavegacao({ fase, termoBusca, aoMudarBusca, aoSubmeterBusca }) {
  const idBusca = useId();
  const visivel = fase === 'revelado';
  const { pathname } = useLocation();
  const emAnimes = pathname.startsWith('/animes');

  return (
    <nav
      aria-label="Principal"
      inert={fase !== 'revelado'}
      className={`fixed inset-x-0 top-0 z-20 flex h-20 items-center justify-between gap-6 bg-surface/70 px-6 backdrop-blur-sm transition-opacity duration-700 ease-out md:px-10 ${
        visivel ? 'opacity-100' : 'opacity-0'
      }`}
    >
      <div className="flex items-center gap-10">
        <Link
          to="/"
          // `state.revelado`: sinaliza pra Inicio.jsx (via `location.state`)
          // que a navegação veio do clique na logo — pula a intro de scroll
          // direto pro estado final em vez de reiniciá-la do zero.
          state={{ revelado: true }}
          className="outline-none focus-visible:ring-2 focus-visible:ring-neon"
        >
          {/* Altura da nav é fixa (h-20 acima) e não depende do tamanho da
              logo. Para redimensionar a logo, ajuste só a classe h-* abaixo
              (até o teto de max-h-full = altura da nav). */}
          <img src={logo} alt="Slime Studio" className="h-20 max-h-full w-auto object-contain" />
        </Link>
        <ul className="hidden items-center gap-8 text-lg text-ink-muted sm:flex sm:text-lg">
          <li>
            <Link
              to="/animes"
              aria-current={emAnimes ? 'page' : undefined}
              className={`outline-none transition-colors font-bold hover:text-neon focus-visible:ring-2 focus-visible:ring-neon ${
                emAnimes ? 'text-neon' : 'focus-visible:text-white'
              }`}
            >
              Meu Catálogo
            </Link>
          </li>
          <li>
            <button
              type="button"
              disabled
              aria-disabled="true"
              title="Em breve"
              className="cursor-not-allowed opacity-50 font-bold"
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
              className="cursor-not-allowed opacity-50 font-bold"
            >
              Favoritos
            </button>
          </li>
        </ul>
      </div>
      {aoMudarBusca && (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            aoSubmeterBusca?.();
          }}
          role="search"
          className="flex items-center gap-2"
        >
          <label htmlFor={idBusca} className="sr-only">
            Buscar animes
          </label>
          <input
            id={idBusca}
            type="search"
            value={termoBusca}
            onChange={(event) => aoMudarBusca(event.target.value)}
            placeholder="Buscar…"
            className="w-60 rounded-md border border-border-chrome bg-surface/80 px-3 py-1.5 text-sm text-white outline-none transition-all focus-visible:border-neon focus-visible:ring-2 focus-visible:ring-neon"
          />
        </form>
      )}
    </nav>
  );
}

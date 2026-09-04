import { useEffect, useId, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import logo from '../assets/logo2.png';

// Navbar fixa (z-20, sempre acima do vídeo de intro e do conteúdo revelado) —
// opacidade e `inert` controlados pela fase da intro (paginas/Inicio.jsx via
// inicio/useIntroPorVideo.js): invisível e inalcançável por teclado até
// `revelado`, mesma fase que dispara o fade-in do `main` (paginas/Inicio.jsx)
// — navbar e conteúdo aparecem juntos, ao final do vídeo.
//
// Gêneros: decisão do usuário sobre dado faltante — não existe gênero no
// modelo hoje, então fica visível mas desabilitado (`disabled` +
// `aria-disabled` + `title`), nunca escondido. Favoritos saiu da navbar:
// agora é filtro dentro de paginas/Galeria.jsx.
//
// Logo: puramente decorativa (sem `<Link>`/navegação) — "Início" na lista
// de links é quem leva pra `/`.
//
// Busca: `termoBusca`/`aoMudarBusca` controlados pelo pai (`paginas/Inicio.jsx`
// e `paginas/Galeria.jsx`, cada um filtrando sua própria lista). Filtro local
// ao vivo, sem submit: digitar já dispara `aoMudarBusca` via `onChange`.
// Enter (`onSubmit`, `preventDefault` evita reload de página) dispara
// `aoSubmeterBusca`, opcional — hoje aciona a busca em fontes externas.
// `aoMudarBusca` inteiro é opcional: `paginas/PaginaDoAnime.jsx` não tem uma
// lista pra filtrar, então o formulário de busca nem renderiza ali — melhor
// omitir a caixa do que exibir um campo que não faz nada ao digitar.
//
// `transparente`: usado por Início, Galeria e Página do Anime. Sem fundo
// enquanto a página está no topo (o conteúdo full-bleed do topo — faixa
// panorâmica, carrossel — aparece atrás da navbar); ao rolar, ganha um fundo
// mais escuro que o `<main>` (#17171b) pra manter contraste com o conteúdo
// que passa por baixo.
export default function BarraDeNavegacao({
  fase,
  transparente = false,
  termoBusca,
  aoMudarBusca,
  aoSubmeterBusca,
}) {
  const idBusca = useId();
  const visivel = fase === 'revelado';
  const { pathname } = useLocation();
  const emInicio = pathname === '/';
  const emAnimes = pathname.startsWith('/animes');
  const [rolou, setRolou] = useState(false);

  useEffect(() => {
    if (!transparente) return undefined;
    const aoRolar = () => setRolou(window.scrollY > 8);
    aoRolar();
    window.addEventListener('scroll', aoRolar, { passive: true });
    return () => window.removeEventListener('scroll', aoRolar);
  }, [transparente]);

  const fundo =
    transparente && !rolou
      ? 'bg-transparent'
      : transparente
        ? 'bg-[#0d0d10]/95 backdrop-blur-sm'
        : 'bg-surface/40 backdrop-blur-sm';

  return (
    <nav
      aria-label="Principal"
      inert={fase !== 'revelado'}
      className={`fixed inset-x-0 top-0 z-20 flex h-20 items-center justify-between gap-6 px-6 transition-[opacity,background-color] duration-700 ease-out md:px-10 ${fundo} ${
        visivel ? 'opacity-100' : 'opacity-0'
      }`}
    >
      <div className="flex items-center gap-10">
        {/* Decorativa: não navega. Altura da nav é fixa (h-20 acima) e não
            depende do tamanho da logo. Para redimensionar a logo, ajuste só
            a classe h-* abaixo (até o teto de max-h-full = altura da nav). */}
        <img src={logo} alt="Slime Studio" className="h-20 max-h-full w-auto object-contain" />
        <ul className="hidden items-center gap-8 text-lg text-ink-muted sm:flex sm:text-lg">
          <li>
            <Link
              to="/"
              // `state.revelado`: sinaliza pra Inicio.jsx (via `location.state`)
              // que a navegação veio deste link — pula a intro de vídeo
              // direto pro estado final em vez de reiniciá-la do zero.
              state={{ revelado: true }}
              aria-current={emInicio ? 'page' : undefined}
              className={`outline-none transition-colors font-bold hover:text-neon focus-visible:ring-2 focus-visible:ring-neon ${
                emInicio ? 'text-neon' : 'focus-visible:text-white'
              }`}
            >
              Início
            </Link>
          </li>
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

import { useEffect, useId, useRef, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { Search, X } from 'lucide-react';
import logo from '../assets/logo2.png';

// Navbar fixa (z-20, sempre acima do conteúdo).
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
//
// Busca colapsável: nasce como botão-ícone circular (`w-10`, só a lupa) e
// expande pra um campo pill largo (`w-96`, borda neon + halo) no foco ou
// assim que há texto — opção escolhida pelo usuário entre um canvas de 5
// variantes (2026-09-21). `buscaExpandida = focada || Boolean(termoBusca)`:
// colapsar exige as DUAS condições falsas, então nunca esconde texto
// digitado (só recolhe com o campo genuinamente vazio e sem foco). É sempre
// o MESMO `<input>` nos dois estados (nunca um `<button>` decorativo por
// cima) — clicar no círculo já foca e edita o campo real, sem elemento
// duplicado pra sincronizar. O ícone de lupa é um `<span>` irmão, absoluto:
// centralizado (`inset-x-0 justify-center`) quando colapsado, ancorado à
// esquerda (`left-3.5`) quando expandido — index. `pointer-events-none` nele
// pra não bloquear o clique that chega no input por baixo. Botão de limpar
// (`X`) só quando expandido E com texto; `onMouseDown` com `preventDefault`
// evita que o clique nele dispare `blur` do input antes do `onClick` (senão
// o campo colapsaria antes de limpar). Cancelador nativo do
// `type="search"` (Chrome/Edge) escondido via `[&::-webkit-search-cancel-
// button]:hidden` — duplicaria o nosso `X`.
export default function BarraDeNavegacao({
  transparente = false,
  termoBusca,
  aoMudarBusca,
  aoSubmeterBusca,
}) {
  const idBusca = useId();
  const inputBuscaRef = useRef(null);
  const [buscaFocada, setBuscaFocada] = useState(false);
  const buscaExpandida = buscaFocada || Boolean(termoBusca);
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
      className={`fixed inset-x-0 top-0 z-20 flex h-20 items-center justify-between gap-6 px-6 transition-[background-color] duration-700 ease-out md:px-10 ${fundo}`}
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
              aria-current={emInicio ? 'page' : undefined}
              className={`outline-none transition-colors font-bold hover:text-neon ${
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
              className={`outline-none transition-colors font-bold hover:text-neon ${
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
          className="flex items-center mr-8"
        >
          <label htmlFor={idBusca} className="sr-only">
            Buscar animes
          </label>
          <div className="relative flex items-center">
            <span
              aria-hidden="true"
              className={`pointer-events-none absolute inset-y-0 flex items-center text-ink-muted transition-all duration-300 ease-out motion-reduce:transition-none ${
                buscaExpandida ? 'left-3.5' : 'inset-x-0 justify-center'
              }`}
            >
              <Search strokeWidth={4} className="h-4 w-4" />
            </span>
            <input
              ref={inputBuscaRef}
              id={idBusca}
              type="search"
              value={termoBusca}
              onChange={(event) => aoMudarBusca(event.target.value)}
              onFocus={() => setBuscaFocada(true)}
              onBlur={() => setBuscaFocada(false)}
              placeholder={buscaExpandida ? 'Buscar animes' : ''}
              className={`h-10 rounded-full bg-surface/80 text-sm font-bold text-white outline-none transition-all duration-300 ease-out motion-reduce:transition-none [&::-webkit-search-cancel-button]:hidden ${
                buscaExpandida
                  ? 'w-96 border-2 border-neon pl-10 pr-9 '
                  : 'w-10 cursor-pointer border-2 border-border-chrome px-0'
              }`}
            />
            {buscaExpandida && termoBusca && (
              <button
                type="button"
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => {
                  aoMudarBusca('');
                  inputBuscaRef.current?.focus();
                }}
                aria-label="Limpar busca"
                className="absolute right-2 flex h-6 w-6 items-center justify-center rounded-full text-ink-muted outline-none transition-colors hover:text-white cursor-pointer"
              >
                <X strokeWidth={4} className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
        </form>
      )}
    </nav>
  );
}

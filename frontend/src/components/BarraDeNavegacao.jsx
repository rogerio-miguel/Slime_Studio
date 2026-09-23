import { useEffect, useId, useRef, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { Home, LibraryBig, Search, Tags, X } from 'lucide-react';
import LogoSlimeStudio from './LogoSlimeStudio';

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
// Busca: campo pill sempre aberto (`w-96`, borda neon), sem animação de
// expandir/colapsar — a versão colapsável (botão-ícone circular que virava
// pill no foco/texto, escolhida num canvas de 5 variantes em 2026-09-21)
// foi removida a pedido do usuário (2026-09-23). Borda: `border-neon` em
// repouso, `hover:border-white/80` (mesmo tom usado no hover dos links da
// navbar) e `focus-visible:border-white` — precisa das DUAS variantes
// porque a borda neon fica fixa agora, então sem elas nem hover nem foco
// dariam feedback visual (nunca cortar isso, mesmo campo sempre aberto).
// Botão de limpar (`X`) só com texto; `onMouseDown` com
// `preventDefault` evita que o clique nele dispare `blur` do input antes do
// `onClick`. Cancelador nativo do `type="search"` (Chrome/Edge) escondido
// via `[&::-webkit-search-cancel-button]:hidden` — duplicaria o nosso `X`.
export default function BarraDeNavegacao({
  transparente = false,
  termoBusca,
  aoMudarBusca,
  aoSubmeterBusca,
}) {
  const idBusca = useId();
  const inputBuscaRef = useRef(null);
  const { pathname } = useLocation();
  const emInicio = pathname === '/';
  const emAnimes = pathname.startsWith('/animes');
  // Fundo ligado direto ao pixel rolado (0 a 1), não a um booleano com
  // `transition` no CSS correndo atrás dele — alternar classe + CSS
  // transition deixava a troca com uma sensação de atraso/brusca, porque a
  // curva do `transition` não acompanha 1:1 a velocidade real do scroll do
  // usuário. Com opacidade calculada a cada evento de scroll, a "animação"
  // é o próprio scroll (2026-09-23, referência: animefire.one, que na
  // real nem anima — troca instantânea; aqui preferimos o fade contínuo).
  //
  // 140px (primeira tentativa) ainda parecia brusco: era curto demais perto
  // da altura do hero da Início (`min-h-screen`, ~85-100vh) — um scroll
  // normal cobria a distância toda de uma vez, então o fade acontecia
  // "dentro" do mesmo gesto e não dava tempo do olho perceber gradiente.
  // 700px (tentativa seguinte) resolveu a ida, mas a volta (fundo
  // reaparecendo transparente) continuou parecendo brusca mesmo mais devagar
  // — sintoma de que o problema não era só distância: alpha LINEAR não
  // corresponde a percepção linear de contraste (olho humano é mais
  // sensível a mudança perto dos extremos 0/1 do que no meio), então a
  // borda de "quase transparente" e "quase opaco" sempre vai parecer mais
  // repentina que o miolo do fade, em qualquer direção. `suavizar()`
  // (smoothstep) desacelera a curva perto dos dois extremos em vez de
  // andar num ritmo constante — resolve a assimetria sem precisar
  // distinguir subindo/descendo. Com isso, 420px (valor pedido de volta
  // pelo usuário, 2026-09-23) já fica suave o bastante de novo.
  // `requestAnimationFrame` no listener evita também que o evento nativo
  // `scroll` (que alguns navegadores/trackpads disparam em lotes, não a
  // cada pixel) deixe a atualização com passos visíveis em vez de contínua.
  const LIMIAR_FUNDO_PX = 420;
  const suavizar = (t) => t * t * (3 - 2 * t);
  const [progressoScroll, setProgressoScroll] = useState(0);
  // Logo: booleano simples (rolou/não rolou um pouco), não um progresso
  // contínuo — referência anthropic.com (pedido do usuário, 2026-09-23):
  // lá o wordmark do header troca de uma vez com uma `transition` CSS
  // curta ao passar de um limiar pequeno, sem acompanhar o pixel do
  // scroll como o fundo acima. LogoSlimeStudio.jsx aplica a
  // `transition-all` nas classes; aqui só decide QUANDO virou.
  const LIMIAR_LOGO_PX = 24;
  const [logoColapsada, setLogoColapsada] = useState(false);

  useEffect(() => {
    if (!transparente) return undefined;
    let quadroPendente = false;
    const atualizar = () => {
      const t = Math.min(window.scrollY / LIMIAR_FUNDO_PX, 1);
      setProgressoScroll(suavizar(t));
      setLogoColapsada(window.scrollY > LIMIAR_LOGO_PX);
      quadroPendente = false;
    };
    const aoRolar = () => {
      if (quadroPendente) return;
      quadroPendente = true;
      requestAnimationFrame(atualizar);
    };
    atualizar();
    window.addEventListener('scroll', aoRolar, { passive: true });
    return () => window.removeEventListener('scroll', aoRolar);
  }, [transparente]);

  const fundoClasse = transparente ? '' : 'bg-surface/40 backdrop-blur-sm';
  const estiloFundo = transparente ? { backgroundColor: `rgba(0, 0, 0, ${progressoScroll})` } : undefined;

  return (
    <nav
      aria-label="Principal"
      style={estiloFundo}
      className={`fixed inset-x-0 top-0 z-20 flex h-20 items-center justify-between gap-6 px-6 md:px-10 ${fundoClasse}`}
    >
      {/* Decorativa: não navega. Wordmark em texto (não SVG/imagem) —
          tamanho vem das classes text-* dentro de LogoSlimeStudio.jsx, não
          de uma altura fixa aqui. `colapsada` troca STUDIO pelo ícone de
          play assim que `scrollY` passa de `LIMIAR_LOGO_PX` — binário,
          independente do fade contínuo do fundo (`progressoScroll`
          acima). */}
      <LogoSlimeStudio colapsada={logoColapsada} />
      {/* `absolute left-1/2 -translate-x-1/2`: centraliza em relação à
          navbar inteira (que já é `fixed`, então já é containing block pra
          isso), não em relação ao espaço sobrando entre logo e busca — se
          centralizasse via flex normal, a posição dependeria de quanto a
          logo e a busca pesam de cada lado (varia por página: PaginaDoAnime
          não tem busca, então o `justify-between` sozinho puxaria os links
          pro centro errado ali). */}
      <ul className="absolute left-1/2 hidden -translate-x-1/2 items-center gap-8 text-lg text-ink-muted sm:flex sm:text-lg">
        <li>
          <Link
            to="/"
            aria-current={emInicio ? 'page' : undefined}
            className={`flex items-center gap-2 outline-none transition-colors font-bold ${
              emInicio ? 'text-neon' : 'hover:text-white/80 focus-visible:text-white'
            }`}
          >
            <Home aria-hidden="true" strokeWidth={2.5} className="h-5 w-5" />
            Início
          </Link>
        </li>
        <li>
          <Link
            to="/animes"
            aria-current={emAnimes ? 'page' : undefined}
            className={`flex items-center gap-2 outline-none transition-colors font-bold ${
              emAnimes ? 'text-neon' : 'hover:text-white/80 focus-visible:text-white'
            }`}
          >
            <LibraryBig aria-hidden="true" strokeWidth={2.5} className="h-5 w-5" />
            Meu Catálogo
          </Link>
        </li>
        <li>
          <button
            type="button"
            disabled
            aria-disabled="true"
            title="Em breve"
            className="flex items-center gap-2 cursor-not-allowed opacity-50 font-bold"
          >
            <Tags aria-hidden="true" strokeWidth={2.5} className="h-5 w-5" />
            Gêneros
          </button>
        </li>
      </ul>
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
              className="pointer-events-none absolute inset-y-0 left-3.5 flex items-center text-ink-muted"
            >
              <Search strokeWidth={4} className="h-4 w-4" />
            </span>
            <input
              ref={inputBuscaRef}
              id={idBusca}
              type="search"
              value={termoBusca}
              onChange={(event) => aoMudarBusca(event.target.value)}
              placeholder="Buscar animes"
              className="h-10 w-86 rounded-full bg-surface/80 pl-10 pr-9 text-sm font-bold text-white outline-none transition-colors [&::-webkit-search-cancel-button]:hidden"
            />
            {termoBusca && (
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

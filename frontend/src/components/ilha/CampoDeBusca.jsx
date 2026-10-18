import { Search, X } from 'lucide-react';
import { useId, useRef } from 'react';
import { useFocarAoDigitar } from '../../hooks/useFocarAoDigitar.js';
import { FUNDO_DA_ILHA } from '../painelFlutuante.js';

// Busca da navbar: pílula sempre aberta, borda neon. Filtro local ao vivo
// (cada tecla chama `aoMudar`); Enter chama `aoSubmeter`, opcional, que hoje
// dispara a busca em fontes externas. O pai só renderiza este campo quando tem
// uma lista para filtrar (PaginaDoAnime não tem).
//
// A borda precisa das DUAS variantes (`hover` e `focus-visible`): como a neon
// fica fixa, sem elas nem hover nem foco dariam feedback. O `X` de limpar usa
// `onMouseDown` + `preventDefault` para o clique não disparar `blur` do input
// antes do `onClick`; o cancelador nativo do `type="search"` é escondido porque
// duplicaria o nosso.
//
// Reaproveitado pelo seletor de fonte (`components/SeletorDeFonte.jsx`): lá
// `rotulo` troca o texto do campo, `larguraTotal` ocupa a coluna do painel em
// vez dos 21.5rem da navbar e `focarAoMontar` põe o foco ao abrir o painel.
// `focarAoDigitar` (só a navbar liga) foca o campo ao digitar em qualquer ponto
// da página; desligado por padrão para não capturar teclas em usos novos.
export default function CampoDeBusca({
  termo,
  aoMudar,
  aoSubmeter,
  rotulo = 'Buscar animes',
  larguraTotal = false,
  focarAoMontar = false,
  focarAoDigitar = false,
}) {
  const id = useId();
  const inputRef = useRef(null);
  useFocarAoDigitar(focarAoDigitar, inputRef);
  return (
    <form
      onSubmit={(evento) => {
        evento.preventDefault();
        aoSubmeter?.();
      }}
      role="search"
      className={`flex items-center ${larguraTotal ? 'w-full' : ''}`}
    >
      <label htmlFor={id} className="sr-only">
        {rotulo}
      </label>
      <div className={`relative flex items-center ${larguraTotal ? 'w-full' : ''}`}>
        <span
          aria-hidden="true"
          className="pointer-events-none absolute inset-y-0 left-3.5 flex items-center text-ink-muted"
        >
          <Search strokeWidth={4} className="h-4 w-4" />
        </span>
        <input
          ref={inputRef}
          id={id}
          type="search"
          value={termo}
          onChange={(evento) => aoMudar(evento.target.value)}
          placeholder={rotulo}
          autoFocus={focarAoMontar}
          className={`h-10 ${larguraTotal ? 'w-full' : 'w-86'} rounded-full ${FUNDO_DA_ILHA} pl-10 pr-9 text-sm font-bold text-white outline-none transition-colors [&::-webkit-search-cancel-button]:hidden`}
        />
        {termo && (
          <button
            type="button"
            onMouseDown={(evento) => evento.preventDefault()}
            onClick={() => {
              aoMudar('');
              inputRef.current?.focus();
            }}
            aria-label="Limpar busca"
            className="absolute right-2 flex h-6 w-6 items-center justify-center rounded-full text-ink-muted outline-none transition-colors hover:text-white cursor-pointer"
          >
            <X strokeWidth={4} className="h-3.5 w-3.5" />
          </button>
        )}
      </div>
    </form>
  );
}

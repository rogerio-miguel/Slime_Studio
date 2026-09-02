// Card da fileira "Próximas estreias" (paginas/Inicio.jsx). Ao contrário de
// AnimeCard, NÃO navega: o anime da próxima temporada ainda não existe em
// nenhuma fonte extratora, então abrir `/anime/:id` levaria a uma página sem
// episódios e com resolução de fonte fadada a falhar. O card é inerte; a única
// ação é o botão "Salvar", que materializa o anime no catálogo local
// (`POST /api/admin/animes`, get-or-create por slug) como bookmark/watchlist —
// quando o anime estrear de verdade e aparecer num site, a página dele passa a
// resolver fonte normalmente.
//
// Mesma mecânica visual de hover/foco do AnimeCard/CartaoContinuarAssistindo
// (Disney+): escala no wrapper + borda neon de 4px via overlay, grupo NOMEADO
// `group/card` (a fileira horizontal tem `group/fileira` próprio pras setas).
// A borda acende no `focus-within` porque o único foco possível aqui é o do
// botão "Salvar".

// Instâncias únicas de módulo — recriar `Intl.*` por render é caro.
const fmtDia = new Intl.DateTimeFormat('pt-BR', { day: 'numeric', month: 'long' });
const fmtDiaAno = new Intl.DateTimeFormat('pt-BR', {
  day: 'numeric',
  month: 'long',
  year: 'numeric',
});

// Linha de estreia derivada do item do feed `GET /api/animes/proxima-temporada`
// (`AnimeEmAltaSaida`). Ordem importa — para no primeiro match.
//   1. `proximo_ep_em` no futuro: para NOT_YET_RELEASED é o ar do episódio 1 =
//      data de estreia exata (com ano só quando difere do atual).
//   2. já em lançamento com próximo ep datado: "Novo episódio ..." (raro nesta
//      fileira, mas o feed pode trazer título que estreou adiantado).
//   3. só `ano_estreia` (Kitsu degradado, ou AniList sem grade ainda): o ano.
//   4. nada aproveitável: rótulo genérico.
function textoDeEstreia(item) {
  const epEm = item.proximo_ep_em;
  const data = epEm ? new Date(epEm) : null;
  const futuro = data && data > new Date();

  if (futuro && item.status_lancamento !== 'em_lancamento') {
    const mesmoAno = data.getFullYear() === new Date().getFullYear();
    return `Estreia ${(mesmoAno ? fmtDia : fmtDiaAno).format(data)}`;
  }
  if (futuro) {
    const mesmoAno = data.getFullYear() === new Date().getFullYear();
    return `Novo episódio ${(mesmoAno ? fmtDia : fmtDiaAno).format(data)}`;
  }
  if (item.ano_estreia) return `Estreia em ${item.ano_estreia}`;
  return 'Estreia em breve';
}

export default function CartaoDeEstreia({ item, salvo, salvando, aoSalvar }) {
  const titulo = item.titulo_romaji || item.titulo_ingles || 'Sem título';

  return (
    <div className="group/card relative transition-transform duration-300 ease-out motion-reduce:transition-none hover:z-10 hover:scale-105 focus-within:z-10 focus-within:scale-105">
      <div className="relative flex aspect-[2/3] w-full flex-col justify-end overflow-hidden rounded-xl bg-surface">
        {item.capa_url && (
          <img
            src={item.capa_url}
            alt=""
            loading="lazy"
            className="absolute inset-0 h-full w-full object-cover"
          />
        )}
        <div className="absolute inset-0 bg-gradient-to-t from-black/95 via-black/45 to-transparent" />
        <div className="relative flex flex-col items-start gap-2 p-4">
          <p className="text-xs font-semibold uppercase tracking-wide text-neon">
            {textoDeEstreia(item)}
          </p>
          <h3 className="line-clamp-2 text-sm font-semibold leading-snug text-white lg:text-base">
            {titulo}
          </h3>
          {salvo ? (
            <span className="inline-flex items-center gap-1 rounded-md border border-neon-soft px-3 py-1.5 text-xs font-semibold text-ink-muted">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" className="h-3.5 w-3.5">
                <path strokeLinecap="round" strokeLinejoin="round" d="m5 13 4 4L19 7" />
              </svg>
              No catálogo
            </span>
          ) : (
            <button
              type="button"
              onClick={aoSalvar}
              disabled={salvando}
              aria-label={`Salvar ${titulo} no catálogo`}
              className="inline-flex items-center gap-1 rounded-md border border-neon-soft bg-black/40 px-3 py-1.5 text-xs font-semibold text-neon outline-none transition-colors hover:border-neon hover:bg-surface-hover focus-visible:ring-2 focus-visible:ring-neon disabled:cursor-not-allowed disabled:opacity-50"
            >
              {salvando ? 'Salvando…' : '+ Salvar'}
            </button>
          )}
        </div>
        {/* Borda neon: overlay por cima da capa/degradê (mesma técnica do
            AnimeCard e do CarrosselDestaques). */}
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 rounded-xl border-4 border-transparent transition-colors duration-300 ease-out group-hover/card:border-neon group-focus-within/card:border-neon motion-reduce:transition-none"
        />
      </div>
    </div>
  );
}

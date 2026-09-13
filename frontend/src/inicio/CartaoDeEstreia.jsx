import BotaoRemoverDoCatalogo from '../components/BotaoRemoverDoCatalogo.jsx';

// Card de anime que ainda NÃO estreou. Dois usos:
//   1. Fileira "Próximas estreias" da Home (paginas/Inicio.jsx) — item do feed
//      `GET /api/animes/proxima-temporada`, com `aoSalvar` pra materializar o
//      anime no catálogo local (`POST /api/admin/animes`, get-or-create por
//      slug) como bookmark/watchlist.
//   2. Cards de anime não-estreado no catálogo (paginas/Galeria.jsx) — já
//      materializado; a Galeria passa `aoRemover` e nunca `aoSalvar`.
// A Galeria reusa ESTE card em vez de AnimeCard justamente porque o anime ainda
// não estreou: AnimeCard navega pra `/anime/:id`, que aqui levaria a uma página
// sem episódios e com resolução de fonte fadada a falhar. Este card é inerte de
// propósito — sem `<Link>`/`onClick`/`tabIndex`/`role` (card focável sem ação é
// armadilha de teclado). Quando o anime estrear de verdade e aparecer num site,
// a página dele passa a resolver fonte normalmente.
//
// Área de ação (pill "No catálogo" / botão "Salvar") só renderiza com
// `aoSalvar`; o botão de remover só com `aoRemover`. A ausência do handler é o
// sinal — sem prop booleana.
//
// Risco conhecido (não corrigir agora): um bookmark recém-salvo pode nascer sem
// nenhum sinal de data (`estreia_em`/`proximo_ep_em`/`ano` todos ausentes — o
// enriquecimento é best-effort/assíncrono) e cair no rótulo genérico "Estreia
// em breve" até o próximo carregamento. Assim que o warm de lançamento roda,
// `estreia_em` (data completa da AniList) ou pelo menos `ano` passam a existir.
//
// Mesma mecânica visual de hover/foco do AnimeCard — sem escala (removida a
// pedido do usuário): os DOIS gatilhos são independentes e cobrem o card
// INTEIRO (pôster + legenda), não só a imagem — mesmo padrão descrito no
// bloco de comentário equivalente em components/AnimeCard.jsx:
//  - Hover de mouse → `hover:bg-surface-hover` sobre `p-3 -m-3` (o padding
//    some o conteúdo do lugar, a margem negativa cancela; só revela a caixa
//    de fundo quando o hover pinta ela).
//  - Foco de teclado → borda neon via overlay `aria-hidden`, só com
//    `group-focus-within/card` (o foco pode cair no botão "Salvar" ou no
//    botão de remover).
// Grupo NOMEADO `group/card` (a fileira horizontal tem `group/fileira`
// próprio pras setas).
//
// Título ABAIXO do pôster, em fluxo normal — não mais sobre um degradê por
// cima da imagem (rationale completo do porquê em components/AnimeCard.jsx,
// mesma correção: o degradê deixava uma lasca sem escurecer no canto
// arredondado em alguns motores gráficos). `BotaoRemoverDoCatalogo` (posição
// `absolute right-2 top-2`) mora como irmão do pôster e da legenda dentro do
// MESMO wrapper `relative` — como os dois têm `w-full`, o topo/direita do
// wrapper coincide com o topo/direita do pôster mesmo com a legenda abaixo
// mudando a altura total do card.

// Instâncias únicas de módulo — recriar `Intl.*` por render é caro.
const fmtDia = new Intl.DateTimeFormat('pt-BR', { day: 'numeric', month: 'long' });
const fmtDiaAno = new Intl.DateTimeFormat('pt-BR', {
  day: 'numeric',
  month: 'long',
  year: 'numeric',
});

// Linha de estreia derivada do item — feed `GET /api/animes/proxima-temporada`
// (`AnimeEmAltaSaida`) na Home, ou `GET /api/animes` (`AnimeSaida`) na Galeria.
// Ordem importa — para no primeiro match.
//   1. `proximo_ep_em` no futuro: para NOT_YET_RELEASED é o ar do episódio 1 =
//      data de estreia exata (com ano só quando difere do atual).
//   2. já em lançamento com próximo ep datado: "Novo episódio ..." (raro nesta
//      fileira, mas o feed pode trazer título que estreou adiantado).
//   3. `estreia_em` no futuro (`AnimeSaida`, catálogo): data completa da AniList
//      (`startDate`), disponível ~semanas antes de `proximo_ep_em` ser agendado.
//   4. só `ano_estreia`/`ano` (Kitsu degradado, ou AniList sem grade ainda): o ano.
//   5. nada aproveitável: rótulo genérico.
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
  // `estreia_em`: string ISO `YYYY-MM-DD` de `GET /api/animes`. Parse com sufixo
  // `T00:00:00` pra cair na meia-noite LOCAL, não UTC (`new Date('2026-01-15')`
  // é UTC e em UTC-3 mostraria 14/01).
  if (item.estreia_em) {
    const estreia = new Date(`${item.estreia_em}T00:00:00`);
    if (!Number.isNaN(estreia.getTime()) && estreia > new Date()) {
      const mesmoAno = estreia.getFullYear() === new Date().getFullYear();
      return `Estreia ${(mesmoAno ? fmtDia : fmtDiaAno).format(estreia)}`;
    }
  }
  const ano = item.ano_estreia ?? item.ano;
  if (ano) return `Estreia em ${ano}`;
  return 'Estreia em breve';
}

export default function CartaoDeEstreia({ item, salvo, salvando, aoSalvar, aoRemover }) {
  const titulo =
    item.titulo || item.titulo_romaji || item.titulo_ingles || 'Sem título';
  const capa = item.capa_url ?? item.capa_path ?? null;

  return (
    <div className="group/card relative">
      <div className="relative flex w-full flex-col gap-2 rounded-xl p-3 -m-3 transition-colors duration-300 ease-out hover:bg-surface-hover motion-reduce:transition-none">
        <div className="relative aspect-[2/3] w-full overflow-hidden rounded-lg bg-surface">
          {capa && (
            <img
              src={capa}
              alt=""
              loading="lazy"
              className="absolute inset-0 h-full w-full object-cover"
            />
          )}
        </div>
        <div className="relative flex flex-col items-start gap-2">
          <div className="flex flex-col gap-1">
            <h3 className="line-clamp-2 text-sm font-semibold leading-snug text-white transition-colors lg:text-base">
              {titulo}
            </h3>
            <p className="text-xs font-semibold uppercase tracking-wide text-ink-muted">
              {textoDeEstreia(item)}
            </p>
          </div>
          {aoSalvar &&
            (salvo ? (
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
            ))}
        </div>
        {/* Anel de foco: overlay cobrindo o card INTEIRO (pôster + legenda), só
            `group-focus-within/card` — mesma peça de components/AnimeCard.jsx. */}
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 rounded-xl border-4 border-transparent transition-colors duration-300 ease-out group-focus-within/card:border-neon motion-reduce:transition-none"
        />
      </div>
      {aoRemover && <BotaoRemoverDoCatalogo titulo={titulo} aoRemover={aoRemover} />}
    </div>
  );
}

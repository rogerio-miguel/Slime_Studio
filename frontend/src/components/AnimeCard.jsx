import { Link } from 'react-router-dom';
import BadgeDeEpisodiosNovos from './BadgeDeEpisodiosNovos.jsx';

// Linguagem visual portada de Slime_Shell_Web/AnimeCard.jsx (superfície
// escura, borda neon, hover translate leve, tag pill, line-clamp-2 no
// título) — não o componente em si: lá é Tailwind v3 com tokens que não
// existem aqui (bg-surface/text-cyanNeon do OUTRO projeto), usa
// `<div onClick>` sem role/tabIndex/teclado (viola acessibilidade
// obrigatória, CLAUDE.md §4), e o modelo de dados diverge.
//
// Proporção: pôster retrato 2:3 (`aspect-[2/3]`), não paisagem como no Shell
// — as imagens aqui são capa de provedor (AniList/Kitsu), não screenshot de
// episódio. O card não define largura própria: quem chama decide (o slot da
// faixa em `inicio/FaixaDeAnimes.jsx`, ou o grid de `paginas/Galeria.jsx`).
//
// Capa: a decisão de "MVP sem capa" foi revertida (Fase 3). O card renderiza
// `<img>` quando existir `anime.capa_path` (catálogo local) ou
// `anime.capa_url` (item do feed "em alta") — nunca com src vazio/nulo — e
// cai pro layout tipográfico original (borda neon, título ancorado embaixo
// via `mt-auto`) quando não houver capa. Título aceita `anime.titulo`
// (local) ou `anime.titulo_romaji` (feed) pelo mesmo motivo. Sem tag de ano:
// o feed "em alta" (`AnimeEmAlta`) nunca carrega esse dado, então a pill
// aparecia sempre como "sem ano" ali — removida em vez de tratada como
// estado vazio (nenhuma seção depende dela hoje).
//
// Ativação: item já catalogado navega via `<Link>` de verdade (foco/teclado
// de graça) — id vem de `anime.id` (catálogo local) OU `anime.anime_id`
// (item do feed "em alta" já cruzado com o catálogo pelo servidor; mesma
// checagem que `inicio/DestaquePrincipal.jsx` já faz pro CTA do destaque).
// Item ainda não catalogado (nem um nem outro) renderiza como `<button>`
// que chama `aoAtivar()`. `desabilitado` (opcional) marca o botão como
// ocupado/em voo — ex. materialização em andamento — mesmo padrão de
// `disabled` + `aria-disabled` + `cursor-not-allowed opacity-50` já usado
// em `components/BarraDeNavegacao.jsx` pros itens "Em breve".
//
// `aoRemover` (opcional, sem argumentos — quem chama já sabe qual anime via
// closure): quando presente, renderiza um botão de remover como IRMÃO do
// Link/button (nunca aninhado — button dentro de <a>/<button> é inválido) via
// wrapper `group relative` — o `group` mora no wrapper, não no `classes` do
// Link/button, justamente pra cobrir os dois como descendentes (o botão de
// remover é irmão do Link/button, não filho dele; se `group` ficasse só no
// `classes`, `group-hover` nunca casaria com o botão) — botão posicionado
// absoluto sobre a capa. `stopPropagation` evita ativar o Link/button por
// baixo; opacidade some por padrão e só aparece no hover do card
// (`group-hover`) ou no foco do próprio botão (`focus-visible`) — nunca com
// `hidden`/DOM removido, senão ficaria inacessível por Tab.
//
// Elevação no hover/foco (`-translate-y-1`): mora no WRAPPER, não no
// Link/button. O título e seu degradê são filhos do Link e acompanhariam a
// animação de qualquer jeito, mas a badge e o botão de remover são irmãos —
// se o transform ficasse no Link, eles ficariam parados enquanto o resto do
// card sobe. `focus-within` (não `focus-visible`) porque o foco pode cair no
// Link OU no botão de remover, e os dois devem elevar o card inteiro.
export default function AnimeCard({ anime, aoAtivar, aoRemover, desabilitado = false }) {
  const idCatalogado = anime.id ?? anime.anime_id ?? null;
  const capa = anime.capa_path ?? anime.capa_url ?? null;
  const titulo = anime.titulo ?? anime.titulo_romaji;

  // w-full é necessário mesmo com `flex`: `<button>` é elemento de formulário
  // e usa sizing "shrink-to-fit" (largura pelo conteúdo) mesmo sob
  // display:flex, ao contrário de `<a>`, que preenche o container por
  // padrão — sem isto, o card de item ainda não catalogado (variante
  // `<button>`) encolhia pro tamanho do título em vez do slot do grid.
  const classes =
    'relative flex aspect-[2/3] w-full flex-col justify-between overflow-hidden rounded-xl border border-neon-soft bg-surface p-4 text-left outline-none transition-all duration-200 hover:border-neon hover:bg-surface-hover focus-visible:border-neon focus-visible:ring-2 focus-visible:ring-neon';

  // Elevação no wrapper (ver comentário do bloco acima): assim badge e botão
  // de remover, que são irmãos do Link/button, sobem junto com o card. Card
  // desabilitado (`<button disabled>`) não eleva.
  const wrapperBase = 'group relative transition-transform duration-200';
  const wrapper = `${wrapperBase} hover:-translate-y-1 focus-within:-translate-y-1`;

  const conteudo = (
    <>
      {capa && (
        <>
          <img
            src={capa}
            alt=""
            className="absolute inset-0 h-full w-full object-cover"
          />
          <div className="absolute inset-0 bg-gradient-to-t from-black/90 via-black/30 to-transparent" />
        </>
      )}
      <h2 className="relative mt-auto line-clamp-2 text-sm font-semibold leading-snug text-white transition-colors group-hover:text-neon lg:text-base">
        {titulo}
      </h2>
    </>
  );

  const botaoRemover = aoRemover && (
    <button
      type="button"
      onClick={(evento) => {
        evento.preventDefault();
        evento.stopPropagation();
        aoRemover();
      }}
      aria-label={`Remover ${titulo} do catálogo`}
      className="absolute right-2 top-2 z-10 rounded-full bg-black/70 p-1.5 text-white opacity-0 outline-none transition-all duration-200 hover:bg-red-950/80 hover:text-red-400 focus-visible:opacity-100 focus-visible:ring-2 focus-visible:ring-neon group-hover:opacity-100"
    >
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-4 w-4">
        <path strokeLinecap="round" strokeLinejoin="round" d="M6 18 18 6M6 6l12 12" />
      </svg>
    </button>
  );

  // Badge não-interativo, sempre visível (ao contrário de `botaoRemover`, que
  // só aparece no hover) — irmão do Link/button dentro do `group relative`,
  // nunca aninhado no <a>/<button>. Canto oposto ao de remover. `quantidade`
  // é `undefined` quando o card vem do feed "em alta" — o guard do
  // componente já devolve `null` nesse caso.
  const badgeEpisodiosNovos = <BadgeDeEpisodiosNovos quantidade={anime.episodios_novos} />;

  if (idCatalogado != null) {
    return (
      <div className={wrapper}>
        <Link to={`/anime/${idCatalogado}`} className={classes}>
          {conteudo}
        </Link>
        {badgeEpisodiosNovos}
        {botaoRemover}
      </div>
    );
  }

  return (
    <div className={desabilitado ? wrapperBase : wrapper}>
      <button
        type="button"
        onClick={aoAtivar}
        disabled={desabilitado}
        aria-disabled={desabilitado || undefined}
        className={desabilitado ? `${classes} pointer-events-none cursor-not-allowed opacity-50` : classes}
      >
        {conteudo}
      </button>
      {badgeEpisodiosNovos}
      {botaoRemover}
    </div>
  );
}

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
// fileira em `inicio/FileiraDeCards.jsx`, ou o grid de `paginas/Galeria.jsx`).
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
// (`group-hover/card`) ou no foco do próprio botão (`focus-visible`) — nunca
// com `hidden`/DOM removido, senão ficaria inacessível por Tab.
//
// Hover/foco (mecânica do Disney+): o card CRESCE em escala no lugar
// (`scale-105`, `transition-transform duration-300 ease-out`) — os irmãos na
// grade não se mexem, ele cresce por cima (`hover:z-10 focus-within:z-10`,
// senão o card seguinte no DOM cobre a borda direita do card ampliado). Mora
// no WRAPPER, não no Link/button: título e degradê acompanhariam de qualquer
// jeito, mas a badge e o botão de remover são irmãos e ficariam parados se o
// transform estivesse no Link. `focus-within` (não `focus-visible`) porque o
// foco pode cair no Link OU no botão de remover, e os dois devem ampliar o
// card inteiro. `motion-reduce:transition-none` corta a animação (o `scale`
// ainda aplica, só não anima).
//
// Borda neon (4px, cantos `rounded-xl`/12px, acende por cor no hover E no
// foco): overlay `aria-hidden` `absolute inset-0`, ÚLTIMO filho de `conteudo`
// — não `border`/`ring` no Link. `border` real encolheria o content-box e
// deixaria uma moldura de `bg-surface` sempre visível ao redor da capa; um
// `ring` no Link ficaria ATRÁS dos filhos `absolute inset-0` (por causa do
// `overflow-hidden`) e só apareceria nas frestas — mesmo problema resolvido
// no overlay de borda de `inicio/CarrosselDestaques.jsx`.
// `group-focus-within/card:border-neon` é o indicador de foco de teclado: o
// Link/button ficou com `outline-none` e sem `focus-visible:ring`. Card
// desabilitado não renderiza o overlay (`{!desabilitado && …}`) e usa
// `wrapperBase` (sem `hover:`/`focus-within:`) — não cresce nem acende.
// Grupo NOMEADO `group/card` (não `group` puro) — ver comentário em
// `wrapperBase` abaixo: a fileira horizontal tem `group` próprio.
//
// `sobreposicao` (opcional): nó renderizado como IRMÃO do Link/button, DENTRO
// do `wrapper` — então cresce junto no `scale` do hover (ao contrário de um
// wrapper externo, que ficaria estático por cima do card). Usado pelo numeral
// grande da fileira "Top 10" (paginas/Inicio.jsx); posicionamento
// (`absolute`/`z`) e `aria-hidden` são responsabilidade de quem passa.
export default function AnimeCard({
  anime,
  aoAtivar,
  aoRemover,
  desabilitado = false,
  sobreposicao,
}) {
  const idCatalogado = anime.id ?? anime.anime_id ?? null;
  const capa = anime.capa_path ?? anime.capa_url ?? null;
  const titulo = anime.titulo ?? anime.titulo_romaji;

  // w-full é necessário mesmo com `flex`: `<button>` é elemento de formulário
  // e usa sizing "shrink-to-fit" (largura pelo conteúdo) mesmo sob
  // display:flex, ao contrário de `<a>`, que preenche o container por
  // padrão — sem isto, o card de item ainda não catalogado (variante
  // `<button>`) encolhia pro tamanho do título em vez do slot do grid.
  const classes =
    'relative flex aspect-[2/3] w-full flex-col justify-between overflow-hidden rounded-xl bg-surface p-4 text-left outline-none transition-all duration-200 hover:bg-surface-hover';

  // Escala no wrapper (ver bloco de comentário acima): assim a badge e o botão
  // de remover, irmãos do Link/button, crescem junto com o card. Card
  // desabilitado (`<button disabled>`) não escala.
  // `group/card` (grupo NOMEADO, não `group` puro): a fileira horizontal
  // (inicio/FileiraDeCards.jsx) envolve a trilha inteira num `group` próprio
  // pra revelar as setas — com `group` puro aqui, `group-hover:` da borda/
  // título casaria com QUALQUER ancestral `.group` e acenderia todos os cards
  // da fileira de uma vez ao passar o mouse em qualquer ponto dela.
  const wrapperBase = 'group/card relative transition-transform duration-300 ease-out motion-reduce:transition-none';
  const wrapper = `${wrapperBase} hover:z-10 hover:scale-105 focus-within:z-10 focus-within:scale-105`;

  const conteudo = (
    <>
      {capa && (
        <>
          <img
            src={capa}
            alt=""
            loading="lazy"
            className="absolute inset-0 h-full w-full object-cover"
          />
          <div className="absolute inset-0 bg-gradient-to-t from-black/90 via-black/30 to-transparent" />
        </>
      )}
      <h2 className="relative mt-auto line-clamp-2 text-sm font-semibold leading-snug text-white transition-colors group-hover/card:text-neon lg:text-base">
        {titulo}
      </h2>
      {/* Borda neon: overlay por CIMA da capa/degradê (ver bloco de comentário
          no topo). Card desabilitado não recebe o overlay — nem cresce nem
          acende. */}
      {!desabilitado && (
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 rounded-xl border-4 border-transparent transition-colors duration-300 ease-out group-hover/card:border-neon group-focus-within/card:border-neon motion-reduce:transition-none"
        />
      )}
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
      className="absolute right-2 top-2 z-10 rounded-full bg-black/70 p-1.5 text-white opacity-0 outline-none transition-all duration-200 hover:bg-red-950/80 hover:text-red-400 focus-visible:opacity-100 focus-visible:ring-2 focus-visible:ring-neon group-hover/card:opacity-100"
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
        {sobreposicao}
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
      {sobreposicao}
    </div>
  );
}

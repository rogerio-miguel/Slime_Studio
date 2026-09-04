import { Link } from 'react-router-dom';
import BadgeDeEpisodiosNovos from './BadgeDeEpisodiosNovos.jsx';
import BotaoRemoverDoCatalogo from './BotaoRemoverDoCatalogo.jsx';

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
// closure): quando presente, renderiza `<BotaoRemoverDoCatalogo>` como IRMÃO
// do Link/button, nunca aninhado (button dentro de <a>/<button> é inválido).
// Mecânica de opacidade/hover/foco e o SVG do X vivem em
// `components/BotaoRemoverDoCatalogo.jsx`. O `group/card` mora no WRAPPER, não
// no `classes` do Link/button: o botão de remover é irmão do Link/button, então
// se `group/card` ficasse só no `classes` o `group-hover/card:` do botão nunca
// casaria.
//
// Hover/foco (mecânica do Disney+): o card CRESCE em escala no lugar
// (`scale-105`, `transition-transform duration-300 ease-out`) — os irmãos na
// grade não se mexem, ele cresce por cima (`hover:z-10 focus-within:z-10`,
// senão o card seguinte no DOM cobre a borda direita do card ampliado). Mora
// no WRAPPER, não no Link/button: título e degradê acompanhariam de qualquer
// jeito, mas o botão de remover é irmão e ficaria parado se o transform
// estivesse no Link. `focus-within` (não `focus-visible`) porque o
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
//
// `fonte` (opcional): kicker curto acima do título, no mesmo bloco de rodapé do
// badge/título (padrão da linha de estreia de inicio/CartaoDeEstreia.jsx). Usado
// pelos resultados de "outras fontes" da busca (paginas/Inicio.jsx) pra mostrar
// o domínio do site de extração dentro do card, sobre o degradê.
// `estatico` (opcional): renderiza o MESMO card, mas sem navegação (não é
// `<Link>` nem `<button>`), sem a animação de hover/foco (escala + borda que
// acende) e sem o overlay de borda neon. `semLegenda` (opcional): esconde o
// degradê e o bloco de rodapé (fonte/badge/título) — só a capa. Os dois são
// usados juntos no header de `paginas/PaginaDoAnime.jsx`, onde o card é
// ilustração da capa — não um alvo de navegação (já se está na página do
// anime), sem botão de remover e sem repetir o título que já está ao lado.
export default function AnimeCard({
  anime,
  aoAtivar,
  aoRemover,
  desabilitado = false,
  estatico = false,
  semLegenda = false,
  sobreposicao,
  fonte,
}) {
  const idCatalogado = anime.id ?? anime.anime_id ?? null;
  const capa = anime.capa_path ?? anime.capa_url ?? null;
  const titulo = anime.titulo ?? anime.titulo_romaji;

  // w-full é necessário mesmo com `flex`: `<button>` é elemento de formulário
  // e usa sizing "shrink-to-fit" (largura pelo conteúdo) mesmo sob
  // display:flex, ao contrário de `<a>`, que preenche o container por
  // padrão — sem isto, o card de item ainda não catalogado (variante
  // `<button>`) encolhia pro tamanho do título em vez do slot do grid.
  const classesBase =
    'relative flex aspect-[2/3] w-full flex-col justify-between overflow-hidden rounded-xl bg-surface p-4 text-left';
  const classes = `${classesBase} outline-none transition-all duration-200 hover:bg-surface-hover`;

  // Escala no wrapper (ver bloco de comentário acima): assim o botão de remover,
  // irmão do Link/button, cresce junto com o card. Card desabilitado
  // (`<button disabled>`) não escala.
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
          {!semLegenda && (
            <div className="absolute inset-0 bg-gradient-to-t from-black/90 via-black/30 to-transparent" />
          )}
        </>
      )}
      {/* Bloco de baixo: kicker "episódio novo" (quando houver) logo acima do
          título, no padrão da linha de estreia de inicio/CartaoDeEstreia.jsx.
          `mt-auto` migrou do <h2> pra cá pra empurrar o par inteiro pro rodapé
          do card. `quantidade` é `undefined` no card do feed "em alta" — o
          guard de BadgeDeEpisodiosNovos devolve `null` nesse caso. */}
      {!semLegenda && (
        <div className="relative mt-auto flex flex-col gap-1">
          {fonte && (
            <p className="text-xs font-semibold uppercase tracking-wide text-white/70">
              {fonte}
            </p>
          )}
          <BadgeDeEpisodiosNovos quantidade={anime.episodios_novos} />
          <h2 className="line-clamp-2 text-sm font-semibold leading-snug text-white transition-colors group-hover/card:text-neon lg:text-base">
            {titulo}
          </h2>
        </div>
      )}
      {/* Borda neon: overlay por CIMA da capa/degradê (ver bloco de comentário
          no topo). Card desabilitado ou `estatico` não recebe o overlay — nem
          cresce nem acende. */}
      {!desabilitado && !estatico && (
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 rounded-xl border-4 border-transparent transition-colors duration-300 ease-out group-hover/card:border-neon group-focus-within/card:border-neon motion-reduce:transition-none"
        />
      )}
    </>
  );

  if (estatico) {
    return (
      <div className="relative">
        <div className={classesBase}>{conteudo}</div>
        {sobreposicao}
      </div>
    );
  }

  if (idCatalogado != null) {
    return (
      <div className={wrapper}>
        <Link to={`/anime/${idCatalogado}`} className={classes}>
          {conteudo}
        </Link>
        {aoRemover && <BotaoRemoverDoCatalogo titulo={titulo} aoRemover={aoRemover} />}
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
      {aoRemover && <BotaoRemoverDoCatalogo titulo={titulo} aoRemover={aoRemover} />}
      {sobreposicao}
    </div>
  );
}

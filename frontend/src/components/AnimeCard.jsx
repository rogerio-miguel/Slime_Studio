import { Link } from 'react-router-dom';
import textoEpisodiosNovos from './BadgeDeEpisodiosNovos.jsx';
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
// `anime.capa_url` (item do feed "em alta") — nunca com src vazio/nulo.
// COM capa: o título fica ABAIXO do pôster, em fluxo normal — não mais
// sobreposto a um degradê (`bg-gradient-to-t`) por cima da imagem. O degradê
// escurecendo o rodapé da capa deixava uma lasca sem escurecer bem no canto
// arredondado (o clip do `overflow-hidden`+`rounded-xl` e o raster do
// degradê, dois elementos `absolute` empilhados, arredondam subpixel de
// forma independente em alguns motores gráficos) — tirar a legenda de cima
// da imagem elimina o degradê inteiro, não só a lasca. SEM capa: cai pro
// layout tipográfico original (uma caixa só, título ancorado embaixo via
// `mt-auto`) — sem imagem por trás não há degradê pra vazar, então esse
// caminho não muda. Título aceita `anime.titulo` (local) ou
// `anime.titulo_romaji` (feed) pelo mesmo motivo da capa.
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
// no conteúdo do Link/button: o botão de remover é irmão do Link/button, então
// se `group/card` ficasse só lá dentro o `group-hover/card:` do botão nunca
// casaria.
//
// Hover/foco do card (pedido explícito do usuário — sem escala: o card NÃO
// cresce mais no hover/foco, só reage nos dois gatilhos abaixo, cobrindo o
// card INTEIRO — pôster + bloco de legenda, não só a imagem):
//  - Hover de mouse → `hover:bg-surface-hover` direto no Link/button
//    (`classesConteudo`), um cinza sutil (token `surface-hover` do tema,
//    já usado no card "sem capa" abaixo e no card de episódio em lista,
//    components/LinhaDeEpisodio.jsx) sobre `p-2 -m-2` — o padding some o
//    conteúdo visualmente do lugar (a margem negativa cancela o padding), só
//    revela a caixa de fundo maior que o pôster+legenda quando o hover pinta
//    ela. Sem isso a caixa de fundo nasceria já visível fora do hover.
//  - Foco de teclado → `anelFoco`, borda neon só com o gatilho de foco (sem
//    `hover:`): fundo sozinho não tem contraste suficiente pra servir de
//    indicador de foco (~1.1:1 entre `surface` e `surface-hover`, bem abaixo
//    do 3:1 mínimo) — CLAUDE.md §4 proíbe cortar acessibilidade por
//    minimalismo. Overlay `aria-hidden` `absolute inset-0`, ÚLTIMO filho da
//    caixa — não `border`/`ring` real pelo mesmo motivo de sempre (border
//    real encolheria o content-box; ring ficaria atrás dos filhos
//    `absolute inset-0` por causa do `overflow-hidden`, mesmo problema
//    resolvido no overlay de borda de `inicio/CarrosselDestaques.jsx`). Nos
//    dois casos (com/sem capa) envolve o card INTEIRO, não só o pôster.
// `group-focus-within/card:border-neon` no `anelFoco`: o Link/button fica com
// `outline-none` e sem `focus-visible:ring`. Card desabilitado não renderiza
// o overlay (`{!desabilitado && …}`). Grupo NOMEADO `group/card` (não `group`
// puro): a fileira horizontal tem `group` próprio pras setas.
//
// `sobreposicao` (opcional): nó renderizado como IRMÃO do Link/button, DENTRO
// do `wrapper`. Usado pelo numeral grande da fileira "Top 10"
// (paginas/Inicio.jsx); posicionamento
// (`absolute`/`z`) e `aria-hidden` são responsabilidade de quem passa — o
// numeral fica ancorado no topo do wrapper, que é sempre o topo do pôster.
//
// `fonte` (opcional): kicker curto acima do título, no mesmo bloco de rodapé do
// badge/título (padrão da linha de estreia de inicio/CartaoDeEstreia.jsx). Usado
// pelos resultados de "outras fontes" da busca (paginas/Inicio.jsx) pra mostrar
// o domínio do site de extração dentro do card. `text-ink-muted` (não mais
// `text-white/70`): a legenda não fica mais sobre a capa, não precisa de um
// tom pensado pra sobreviver em cima de imagem — usa a mesma cor esmaecida do
// resto do app.
// `aviso` (opcional, string): kicker curto em âmbar no topo do mesmo bloco de
// rodapé — mesmo tom "precisa de atenção" de components/IndicadorDeAtencao.jsx e
// do OverlayDeStatus 'alerta' de components/LinhaDeEpisodio.jsx (não há token de
// erro/danger no @theme). Texto visível, no fluxo de leitura de tela — não um
// ícone mudo. Usado pelos resultados de "correspondência incerta" da busca de
// fontes (paginas/Inicio.jsx): o site indexou o anime só sob um título que não
// bate nenhuma referência canônica. Ausente → nada renderizado a mais.
// `anime.assistido` (do catálogo agregado por franquia, `inicio/franquia.js`):
// quando `true`, o card ganha uma pill "Assistido" no canto do pôster — mesmo
// `bg-neon`/caixa alta do BadgeAssistido de `components/LinhaDeEpisodio.jsx`.
// Só a tag, sem escurecer a capa (decisão de produto, já não fazia sentido
// mesmo antes da mudança de layout). Suprimido em `semLegenda` (card
// só-ilustração do header da página do anime).
//
// `estatico` (opcional): renderiza o MESMO card, mas sem navegação (não é
// `<Link>` nem `<button>`), sem a animação de hover/foco (escala + borda que
// acende) e sem o overlay de borda neon. `semLegenda` (opcional): esconde o
// bloco de legenda (fonte/badge/título) — só a capa. Os dois são usados
// juntos no header de `paginas/PaginaDoAnime.jsx`, onde o card é ilustração
// da capa — não um alvo de navegação (já se está na página do anime), sem
// botão de remover e sem repetir o título que já está ao lado.
export default function AnimeCard({
  anime,
  aoAtivar,
  aoRemover,
  desabilitado = false,
  estatico = false,
  semLegenda = false,
  sobreposicao,
  fonte,
  aviso,
}) {
  const idCatalogado = anime.id ?? anime.anime_id ?? null;
  const capa = anime.capa_path ?? anime.capa_url ?? null;
  const titulo = anime.titulo ?? anime.titulo_romaji;
  const assistido = !semLegenda && Boolean(anime.assistido);

  // Marca "assistido": só a pill no canto do pôster (sem scrim — decisão de
  // produto, o card do catálogo não escurece a capa; o scrim mora só no card
  // de episódio, components/LinhaDeEpisodio.jsx). Canto esquerdo pra não
  // colidir com o botão de remover (canto direito). `absolute` (não
  // `relative`) pelo mesmo motivo do botão de remover — ancora no canto do
  // pôster (`relative` na div do pôster) de forma confiável, não por sorte de
  // fluxo (a `<img>` acima é `absolute`, então hoje a pill seria o único
  // conteúdo em fluxo e "funcionaria" mesmo com `relative`, mas isso quebra
  // no primeiro filho novo que alguém adicionar ali). `h-7` explícito +
  // `inline-flex items-center` (não `py-*`): mesma altura EXATA do botão de
  // remover (`p-1.5` ao redor do ícone `h-4` = 28px = `h-7`) — alinha os dois
  // pelo centro vertical independente da métrica de linha do texto.
  const badgeAssistido = assistido && (
    <span
      className="absolute left-2 top-2 z-10 inline-flex h-7 items-center rounded-2xl bg-black/60 px-2.5 text-[11px] font-semibold uppercase tracking-wide text-white"
      aria-label="já assistido"
    >
      Assistido
    </span>
  );

  // Anel de foco (ver bloco de comentário no topo) — só reage a
  // `group-focus-within/card`, sem gatilho de hover. Card desabilitado ou
  // `estatico` não recebe: nem cresce nem acende.
  const anelFoco = !desabilitado && !estatico && (
    <div
      aria-hidden="true"
      className="pointer-events-none absolute inset-0 rounded-xl border-4 border-transparent transition-colors duration-300 ease-out group-focus-within/card:border-neon motion-reduce:transition-none"
    />
  );

  // Tag "Tn EP.n" logo abaixo do título — pedido explícito do usuário.
  // `numero_temporada` cai pra 1 quando NULL (anime sem franquia resolvida
  // ainda é, na prática, temporada única). O NÚMERO de episódios muda de
  // fonte conforme o item:
  //  - Catalogado (`AnimeSaida`, `anime.episodios_atuais` presente): "quantos
  //    tem AGORA", igual à página do anime — maior nº capturado localmente x
  //    sondagem da fonte real (backend, `api/rotas/animes.py::listar_animes`).
  //  - Item do feed ainda não catalogado (`AnimeEmAltaSaida`, sem
  //    `episodios_atuais`): não tem sondagem própria, cai pro total declarado
  //    pela AniList (`anime.total_episodios`).
  //  - Catalogado mas sondagem/captura ainda vazias (`episodios_atuais` nulo):
  //    cai pro total da AniList (`anime.total_episodios_anilist`) — mesmo
  //    fallback do item de feed, evita a tag sumir à toa.
  // Sem nenhum dos dois, a tag inteira some — nunca "EP. —" ou 0 enganoso.
  const numeroDeEpisodios =
    anime.episodios_atuais ?? anime.total_episodios_anilist ?? anime.total_episodios ?? null;
  // Aviso "episódio novo" (`textoEpisodiosNovos`, texto cru — ver
  // components/BadgeDeEpisodiosNovos.jsx) anexado na MESMA linha da tag de
  // temporada, formato "T1 EP.24 - Novo episódio disponível" (pedido
  // explícito do usuário). Sem tag de temporada (`numeroDeEpisodios` nulo —
  // anime nunca refrescado), cai pra linha própria, mesmo tom neon: nunca
  // esconder a novidade só porque falta o outro dado.
  const avisoNovos = textoEpisodiosNovos(anime.episodios_novos);
  const tagTemporada = numeroDeEpisodios != null && (
    <p className="text-xs font-semibold uppercase tracking-wide text-ink-muted">
      T{anime.numero_temporada ?? 1} EP.{numeroDeEpisodios} 
      {avisoNovos && <span className="text-neon"><span class="text-ink-muted"> - </span>{avisoNovos}</span>}
    </p>
  );

  // Título primeiro (sem cor de hover — pedido explícito do usuário),
  // badges/tags (temporada + episódios novos, aviso, fonte) abaixo dele.
  const legenda = !semLegenda && (
    <>
      <h2 className="line-clamp-2 text-sm font-semibold leading-snug text-white lg:text-base">
        {titulo}
      </h2>
      {tagTemporada}
      {!tagTemporada && avisoNovos && (
        <p className="text-xs font-semibold uppercase tracking-wide text-neon">{avisoNovos}</p>
      )}
      {aviso && (
        <p className="text-xs font-semibold uppercase tracking-wide text-amber-300">{aviso}</p>
      )}
      {fonte && (
        <p className="text-xs font-semibold uppercase tracking-wide text-ink-muted">{fonte}</p>
      )}
    </>
  );

  // w-full é necessário mesmo com `flex`: `<button>` é elemento de formulário
  // e usa sizing "shrink-to-fit" (largura pelo conteúdo) mesmo sob
  // display:flex, ao contrário de `<a>`, que preenche o container por
  // padrão — sem isto, o card de item ainda não catalogado (variante
  // `<button>`) encolhia pro tamanho do título em vez do slot do grid.
  let classesConteudo;
  let conteudo;
  if (capa) {
    // COM capa: pôster (imagem, recorte próprio) + legenda abaixo, mas as
    // duas envolvidas por UMA caixa de hover só (`p-3 -m-3`: o padding some o
    // conteúdo do lugar — a margem negativa cancela o padding no layout do
    // slot, então o pôster não encolhe —, só revelando a caixa maior que
    // pôster+legenda quando `hover:bg-surface-hover` pinta ela; ver bloco de
    // comentário no topo). 12px de cada lado: teto seguro é o `p-[10px]` do
    // slot da grade (GradeDeCatalogo.jsx/FileiraDeCards.jsx) somado ao do
    // vizinho — até ~16px ainda não encosta no pôster ao lado. `relative` pro
    // `anelFoco` (último filho) cobrir a caixa inteira.
    classesConteudo =
      'relative flex w-full flex-col gap-2 rounded-2xl p-3 -m-3 text-left outline-none transition-colors duration-300 ease-out hover:bg-surface-hover motion-reduce:transition-none';
    conteudo = (
      <>
        <div className="relative aspect-[2/3] w-full overflow-hidden rounded-2xl bg-surface">
          <img src={capa} alt="" loading="lazy" className="absolute inset-0 h-full w-full object-cover" />
          {badgeAssistido}
        </div>
        {!semLegenda && <div className="relative flex flex-col gap-1">{legenda}</div>}
        {anelFoco}
      </>
    );
  } else {
    // SEM capa: layout tipográfico original — uma caixa só (`bg-surface`),
    // título ancorado embaixo via `mt-auto`. Sem imagem, não há degradê pra
    // vazar no canto — nada aqui precisa da separação pôster/legenda (já era
    // uma caixa só de hover antes desta mudança).
    classesConteudo =
      'relative flex aspect-[2/3] w-full flex-col justify-between overflow-hidden rounded-xl bg-surface p-4 text-left outline-none transition-all duration-200 hover:bg-surface-hover';
    conteudo = (
      <>
        {badgeAssistido}
        {!semLegenda && <div className="relative mt-auto flex flex-col gap-1">{legenda}</div>}
        {anelFoco}
      </>
    );
  }

  // `group/card` (grupo NOMEADO, não `group` puro): a fileira horizontal
  // (inicio/FileiraDeCards.jsx) envolve a trilha inteira num `group` próprio
  // pra revelar as setas — com `group` puro aqui, `group-hover:` da borda/
  // título casaria com QUALQUER ancestral `.group` e acenderia todos os cards
  // da fileira de uma vez ao passar o mouse em qualquer ponto dela. Sem
  // escala (removida a pedido do usuário): só serve de raiz pro grupo, sem
  // classe própria de hover/foco — quem reage é `classesConteudo`/`anelFoco`.
  const wrapper = 'group/card relative';

  if (estatico) {
    return (
      <div className="relative">
        <div className={classesConteudo}>{conteudo}</div>
        {sobreposicao}
      </div>
    );
  }

  if (idCatalogado != null) {
    return (
      <div className={wrapper}>
        <Link to={`/anime/${idCatalogado}`} className={classesConteudo}>
          {conteudo}
        </Link>
        {aoRemover && <BotaoRemoverDoCatalogo titulo={titulo} aoRemover={aoRemover} />}
        {sobreposicao}
      </div>
    );
  }

  return (
    <div className={wrapper}>
      <button
        type="button"
        onClick={aoAtivar}
        disabled={desabilitado}
        aria-disabled={desabilitado || undefined}
        className={
          desabilitado ? `${classesConteudo} pointer-events-none cursor-not-allowed opacity-50` : classesConteudo
        }
      >
        {conteudo}
      </button>
      {aoRemover && <BotaoRemoverDoCatalogo titulo={titulo} aoRemover={aoRemover} />}
      {sobreposicao}
    </div>
  );
}

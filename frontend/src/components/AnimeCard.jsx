import { useId } from 'react';
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
// closure): quando presente, renderiza `<BotaoRemoverDoCatalogo>` DENTRO da
// própria div da capa (ou, sem capa, dentro da caixa única do card) — mesmo
// lugar de `inicio/CartaoDeEstreia.jsx`, que já ancorava certo (ver rationale
// em components/BotaoRemoverDoCatalogo.jsx). Isso só é seguro porque o
// Link/button deixou de ENVOLVER o conteúdo visual: agora é uma camada
// invisível `absolute inset-0`, IRMÃ do conteúdo (não mais pai dele), cobrindo
// o card inteiro pra navegação/ativação — mesmo padrão "stretched link" que
// `CartaoDeEstreia` não precisa porque não tem Link/button nenhum. Sem essa
// mudança, aninhar `<BotaoRemoverDoCatalogo>` (um `<button>`) dentro da capa
// aninharia ele dentro do Link/button também — inválido (button dentro de
// <a>/<button>). Como a camada de navegação não tem mais texto visível dentro,
// o nome acessível vem de `aria-labelledby` apontando pro badge "Assistido"
// (`idBadge`) e pro bloco de legenda (`idLegenda`) — replica o que antes era
// lido automaticamente por estar tudo dentro do próprio Link.
//
// Hover do card (pedido explícito do usuário — sem escala: o card NÃO cresce
// mais no hover, só reage a `group-hover/card:bg-surface-hover` em
// `classesConteudo` — quem recebe o `:hover` de mouse é a camada de
// navegação (Link/button `absolute inset-0`, irmã dele), então a reação
// precisa passar pelo `group/card` do wrapper, não um `hover:` direto), um
// cinza sutil (token `surface-hover` do tema, já usado no card "sem capa"
// abaixo e no card de episódio em lista, components/LinhaDeEpisodio.jsx)
// sobre `p-2 -m-2` — o padding some o
// conteúdo visualmente do lugar (a margem negativa cancela o padding), só
// revela a caixa de fundo maior que o pôster+legenda quando o hover pinta
// ela. Sem isso a caixa de fundo nasceria já visível fora do hover. Cobre o
// card INTEIRO (pôster + legenda) nos dois casos (com/sem capa).
// Sem indicador de foco de teclado por decisão explícita do usuário
// (2026-09-13) — havia um `anelFoco` aqui (overlay `border-4`, acendendo
// `border-neon` via `group-focus-within/card`), removido junto com todo
// `focus-visible:ring-neon` do sistema (mesma sessão). Grupo `group/card`
// (não `group` puro) continua existindo só porque a fileira horizontal tem
// `group` próprio pras setas — sem isso `group-hover:` da borda/título
// casaria com QUALQUER ancestral `.group`.
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
  // Ids do nome acessível da camada de navegação (ver nota de `aoRemover` no
  // topo do arquivo) — só usados nos ramos com Link/button real (`estatico`
  // não precisa, não navega).
  const idBadge = useId();
  const idLegenda = useId();

  // Marca "assistido": só a pill no canto do pôster (sem scrim — decisão de
  // produto, o card do catálogo não escurece a capa; o scrim mora só no card
  // de episódio, components/LinhaDeEpisodio.jsx). Canto esquerdo pra não
  // colidir com o botão de remover (canto direito). `absolute` (não
  // `relative`) pelo mesmo motivo do botão de remover — ancora no canto do
  // pôster (`relative` na div do pôster) de forma confiável, não por sorte de
  // fluxo (a `<img>` acima é `absolute`, então hoje a pill seria o único
  // conteúdo em fluxo e "funcionaria" mesmo com `relative`, mas isso quebra
  // no primeiro filho novo que alguém adicionar ali). `h-8` explícito +
  // `inline-flex items-center` (não `py-*`): mesma altura EXATA do ícone
  // (`h-8`, sem padding ao redor) do botão de remover
  // (components/BotaoRemoverDoCatalogo.jsx) — alinha os dois pelo centro
  // vertical independente da métrica de linha do texto.
  const badgeAssistido = assistido && (
    <span
      id={idBadge}
      className="absolute left-2 top-2 z-10 inline-flex h-8 items-center rounded-2xl bg-black/60 px-2.5 text-[11px] font-semibold uppercase tracking-wide text-white"
      aria-label="já assistido"
    >
      Assistido
    </span>
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
    // vizinho — até ~16px ainda não encosta no pôster ao lado.
    classesConteudo =
      'relative flex w-full flex-col gap-2 rounded-2xl p-3 -m-3 text-left transition-colors duration-300 ease-out group-hover/card:bg-surface-hover motion-reduce:transition-none';
    conteudo = (
      <>
        <div className="relative aspect-[2/3] w-full overflow-hidden rounded-2xl bg-surface">
          <img src={capa} alt="" loading="lazy" className="absolute inset-0 h-full w-full object-cover" />
          {badgeAssistido}
          {aoRemover && <BotaoRemoverDoCatalogo titulo={titulo} aoRemover={aoRemover} />}
        </div>
        {!semLegenda && (
          <div id={idLegenda} className="relative flex flex-col gap-1">
            {legenda}
          </div>
        )}
      </>
    );
  } else {
    // SEM capa: layout tipográfico original — uma caixa só (`bg-surface`),
    // título ancorado embaixo via `mt-auto`. Sem imagem, não há degradê pra
    // vazar no canto — nada aqui precisa da separação pôster/legenda (já era
    // uma caixa só de hover antes desta mudança).
    classesConteudo =
      'relative flex aspect-[2/3] w-full flex-col justify-between overflow-hidden rounded-xl bg-surface p-4 text-left transition-all duration-200 group-hover/card:bg-surface-hover';
    conteudo = (
      <>
        {badgeAssistido}
        {aoRemover && <BotaoRemoverDoCatalogo titulo={titulo} aoRemover={aoRemover} />}
        {!semLegenda && (
          <div id={idLegenda} className="relative mt-auto flex flex-col gap-1">
            {legenda}
          </div>
        )}
      </>
    );
  }

  // `group/card` (grupo NOMEADO, não `group` puro): a fileira horizontal
  // (inicio/FileiraDeCards.jsx) envolve a trilha inteira num `group` próprio
  // pra revelar as setas — com `group` puro aqui, `group-hover:` da borda/
  // título casaria com QUALQUER ancestral `.group` e acenderia todos os cards
  // da fileira de uma vez ao passar o mouse em qualquer ponto dela. Sem
  // escala (removida a pedido do usuário): só serve de raiz pro grupo, sem
  // classe própria de hover/foco. `classesConteudo` reage via
  // `group-hover/card:` (não `hover:` direto) porque quem recebe o hover do
  // mouse agora é a camada de navegação (Link/button `absolute inset-0`
  // abaixo), irmã dele, não o próprio `classesConteudo` — `:hover` não
  // atravessa pra um irmão, só pro ancestral comum (`wrapper`).
  const wrapper = 'group/card relative';

  if (estatico) {
    return (
      <div className="relative">
        <div className={classesConteudo}>{conteudo}</div>
        {sobreposicao}
      </div>
    );
  }

  // Nome acessível da camada de navegação: `aria-labelledby` junta o badge
  // "Assistido" (quando presente) com o bloco de legenda (título + tags),
  // igual ao texto que seria lido se estivesse tudo dentro do próprio
  // Link/button. `semLegenda` nunca ocorre nestes dois ramos na prática (só
  // combina com `estatico`, ver comentário no topo do arquivo), mas o
  // fallback pro `titulo` cru cobre esse caso defensivamente.
  const idsRotulo = [assistido && idBadge, !semLegenda && idLegenda].filter(Boolean).join(' ');
  const propsRotulo = idsRotulo ? { 'aria-labelledby': idsRotulo } : { 'aria-label': titulo };

  if (idCatalogado != null) {
    return (
      <div className={wrapper}>
        <div className={classesConteudo}>{conteudo}</div>
        <Link to={`/anime/${idCatalogado}`} className="absolute inset-0 outline-none" {...propsRotulo} />
        {sobreposicao}
      </div>
    );
  }

  return (
    <div className={wrapper}>
      <div className={desabilitado ? `${classesConteudo} opacity-50` : classesConteudo}>{conteudo}</div>
      <button
        type="button"
        onClick={aoAtivar}
        disabled={desabilitado}
        aria-disabled={desabilitado || undefined}
        className={
          desabilitado
            ? 'absolute inset-0 cursor-not-allowed outline-none'
            : 'absolute inset-0 outline-none'
        }
        {...propsRotulo}
      />
      {sobreposicao}
    </div>
  );
}

import { useId } from 'react';
import { Link } from 'react-router-dom';
import { Check, Sparkles } from 'lucide-react';
import { textoDeProximaTemporada } from '../inicio/franquia.js';
import textoEpisodiosNovos from './BadgeDeEpisodiosNovos.jsx';
import BotaoRemoverDoCatalogo from './BotaoRemoverDoCatalogo.jsx';
import IconeSalvar from './IconeSalvar.jsx';

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
// `indicarCatalogado` (opcional, default `false`): pill "Já no catálogo"
// (`pillsSuperiores` abaixo) quando `anime.anime_id` não é `null` — só faz
// sentido pra item de FEED (`AnimeEmAltaSaida`, nunca tem `.id` próprio) que
// já bate com o catálogo local, então quem chama precisa optar (pedido
// explícito do usuário pra "Relacionados" de `paginas/PaginaDoAnime.jsx` —
// não ligado por padrão pra não repetir o aviso em toda fileira/carrossel da
// Home que também usa item de feed).
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
// rodapé — mesmo tom "precisa de atenção" do OverlayDeStatus 'alerta' de
// components/LinhaDeEpisodio.jsx (não há token de
// erro/danger no @theme). Texto visível, no fluxo de leitura de tela — não um
// ícone mudo. Usado pelos resultados de "correspondência incerta" da busca de
// fontes (paginas/Inicio.jsx): o site indexou o anime só sob um título que não
// bate nenhuma referência canônica. Ausente → nada renderizado a mais.
// `anime.assistido` (do catálogo agregado por franquia, `inicio/franquia.js`):
// quando `true`, o card ganha uma pill "Assistido" (colapsada, só ícone, fora
// do hover — ver comentário de `badgeAssistido` abaixo) no canto do pôster.
// Suprimido em `semLegenda` (card só-ilustração do header da página do
// anime).
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
  indicarCatalogado = false,
  episodioLancado = null,
  semTagEpisodios = false,
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

  // Marca "assistido": pill dentro do grupo empilhado no canto superior
  // esquerdo do pôster (`pillsSuperiores`, ver abaixo). Colapsada (só ícone)
  // fora do hover, expande mostrando "Assistido" no hover do card — mesma
  // animação de sempre (pedido explícito do usuário, 2026-09-21), preservada
  // ao trocar a pele abaixo. Cor/tamanho do ícone agora seguem o botão de
  // remover (components/BotaoRemoverDoCatalogo.jsx: `h-8 w-8`,
  // `strokeWidth={2.5}`, sem chip de fundo — `drop-shadow` no lugar do
  // `bg-black/80 backdrop-blur-md` de antes), pedido explícito do usuário
  // (2026-09-21), pra poluir menos o canto do pôster. `max-w-0 opacity-0` →
  // `group-hover/card:max-w-32 group-hover/card:opacity-100` no texto (não no
  // `<span>` pai inteiro): encolher o pai junto encolheria também o ícone. O
  // `aria-label` no pai cobre o nome acessível mesmo com o texto colapsado.
  const badgeAssistido = assistido && (
    <span
      id={idBadge}
      className="absolute left-2 top-1 z-10 inline-flex h-8 items-center gap-1 whitespace-nowrap text-sm font-semibold uppercase tracking-wide text-white drop-shadow-[0_1px_3px_rgba(0,0,0,0.9)]"
      aria-label="Já assistido"
    >
      <Check aria-hidden="true" strokeWidth={4} className="h-6 w-6 shrink-0" />
      <span className="max-w-0 overflow-hidden opacity-0 transition-all duration-300 ease-out group-hover/card:max-w-32 group-hover/card:opacity-100 motion-reduce:transition-none">
        Assistido
      </span>
    </span>
  );

  // "Já no catálogo" — ver `indicarCatalogado` no topo do arquivo. Ícone
  // trocado pro mesmo `IconeSalvar` (fita, preenchida = já salvo) de
  // `inicio/CartaoDeEstreia.jsx`/`components/IconeSalvar.jsx` — pedido
  // explícito do usuário (2026-09-21), unifica a linguagem visual de "já
  // tenho isso" nos dois cards. `preenchido` (sólido/branco): esta pill só
  // aparece quando o anime JÁ está catalogado, nunca no estado "ainda não
  // salvo" (contorno) que o ícone também sabe desenhar. Mesma pele de
  // `badgeAssistido` acima (pedido explícito do usuário, 2026-09-21): sem
  // chip de fundo, só `drop-shadow`, mesmo posicionamento (`absolute left-2
  // top-1`) e mesmo tamanho de ícone (`h-6 w-6`) — as duas pills do canto
  // ficam visualmente idênticas, só o ícone/texto mudam. `max-w-48` (não
  // `max-w-32` de lá) porque "Já no catálogo" é bem mais longo que
  // "Assistido", precisa de mais espaço pra não cortar quando expande no
  // hover do card.
  const idBadgeCatalogado = idBadge + '-catalogado';
  const jaCatalogado = indicarCatalogado && !semLegenda && anime.anime_id != null;
  const badgeCatalogado = jaCatalogado && (
    <span
      id={idBadgeCatalogado}
      className="absolute left-2 top-2 z-10 inline-flex h-8 items-center gap-1 whitespace-nowrap text-sm font-semibold uppercase tracking-wide text-white drop-shadow-[0_1px_3px_rgba(0,0,0,0.9)]"
    >
      <IconeSalvar preenchido className="h-8 w-8 shrink-0" />
      <span className="max-w-0 overflow-hidden opacity-0 transition-all duration-300 ease-out group-hover/card:max-w-48 group-hover/card:opacity-100 motion-reduce:transition-none">
        Já no catálogo
      </span>
    </span>
  );

  // Aviso "Nª temporada em ..." — variante curta (`curto: true`, sem
  // "estreia") da mesma função do hero da página do anime
  // (`textoDeProximaTemporada`, `inicio/franquia.js`): o card já deixa claro
  // que é uma temporada futura pelo resto da legenda, "estreia" só ocupa
  // espaço. `anime.proxima_temporada` já vem pronto do backend
  // (`AnimeSaida.proxima_temporada`), inclusive no representante de franquia
  // agrupado por `agruparEmFranquias` (spread do anime representante,
  // `inicio/franquia.js`).
  // Pedido explícito do usuário (2026-09-21): deixou de ser pill sobre o
  // pôster (poluía a imagem, empilhada com Assistido/episódio novo/já no
  // catálogo no mesmo canto) — agora é texto na legenda, encadeado depois de
  // "Tn EP.n" (`tagTemporada` abaixo), calculado aqui em cima pra estar
  // pronto quando `tagTemporada` for montado. `!semLegenda &&` pelo mesmo
  // motivo de `assistido` acima: nos usos `semLegenda` (card-ilustração de
  // paginas/PaginaDoAnime.jsx) o card já está ao lado do próprio texto de
  // próxima temporada no hero da página — repetir aqui seria redundante.
  const avisoProximaTemporada =
    !semLegenda && textoDeProximaTemporada(anime.proxima_temporada, { curto: true });

  // Badge "EP.n" do episódio ESPECÍFICO recém-lançado (fileira "Novos
  // lançamentos" de Inicio.jsx, pedido explícito do usuário, 2026-09-20: virou
  // pill sobre o pôster em vez de texto na legenda — mesmo tratamento visual
  // de `badgeCatalogado` abaixo). `semTagEpisodios` não afeta
  // este badge — os dois props são independentes (`semTagEpisodios` só
  // suprime a tag de TOTAL de episódios abaixo).
  // `h-5 w-5`/`text-sm`: mesmo padrão de tamanho comum às pills-chip do canto
  // (`badgeCatalogado` acima) — sem colapsar/expandir no hover (ao contrário
  // dela): este badge é sempre visível de propósito, é o próprio conteúdo do
  // aviso ("EP.n"), não um rótulo genérico que pode ficar só ícone fora do
  // hover. Centralizado na base do pôster (`absolute bottom-2 left-1/2
  // -translate-x-1/2`, mesmo tratamento de `badgeAviso` abaixo) — pedido
  // explícito do usuário (2026-09-21): saiu do canto superior (`pillsSuperiores`)
  // pra não competir com Assistido/já no catálogo ali. Sem risco de colidir
  // com `badgeAviso` no mesmo ponto: os dois nunca coexistem na prática — a
  // fileira "Novos lançamentos" usa `AnimeEmAltaSaida` (feed), que não tem
  // campo `episodios_novos` (só `AnimeSaida`, catálogo local, tem).
  const idBadgeEpisodio = idBadge + '-episodio';
  const badgeEpisodio = episodioLancado != null && (
    <span
      id={idBadgeEpisodio}
      className="absolute bottom-2 left-1/2 z-10 -translate-x-1/2 inline-flex h-8 items-center gap-1 whitespace-nowrap bg-black/80 backdrop-blur-md px-2.5 text-sm font-semibold uppercase tracking-wide text-white"
    >
      <Sparkles aria-hidden="true" className="h-5 w-5" />
      EP.{episodioLancado}
    </span>
  );

  // Tag "Tn EP.n" (total de episódios) logo abaixo do título — pedido
  // explícito do usuário. `numero_temporada` só existe pra anime JÁ catalogado
  // localmente (resolvido via franquia na materialização,
  // `core/temporada.py`) — item de feed (`AnimeEmAltaSaida`: Top 10, busca)
  // nunca traz esse campo. Antes caía num fallback fixo "T1", que ficava
  // ERRADO pra qualquer franquia de 2ª+ temporada ainda não catalogada
  // (pedido explícito do usuário, 2026-09-20: tirar o "Tn" em vez de arriscar
  // um número errado) — agora omite o prefixo de temporada inteiro quando ele
  // não é conhecido, em vez de adivinhar. Suprimida em dois casos: `semTagEpisodios`
  // (fileira "Top 10", pedido explícito do usuário — o card não quer nenhuma
  // contagem, só pôster/título) e `episodioLancado != null` (fileira "Novos
  // lançamentos" — o episódio específico já aparece no `badgeEpisodio` acima,
  // repetir a contagem TOTAL aqui ao lado dele confundiria qual dos dois
  // números é o lançamento novo). Nesses dois casos, `avisoProximaTemporada`
  // some junto (sem "Tn EP.n" pra encadear depois) — mesmo corte de
  // `semTagEpisodios` já dado pro Top 10 (nenhuma contagem, nenhum aviso). O
  // NÚMERO de episódios muda de fonte conforme o item:
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
  // components/BadgeDeEpisodiosNovos.jsx): voltou a ser pill sobre o pôster
  // (pedido explícito do usuário, 2026-09-21 — tinha ido pra legenda como
  // texto no encadeamento da tag de temporada, voltou por pedido do usuário
  // no mesmo dia), mas agora centralizada na base do pôster
  // (`badgeAviso` abaixo), não mais empilhada no canto com Assistido/já no
  // catálogo — evita competir por espaço com as outras pills lá em cima.
  // `!semLegenda &&` pelo mesmo motivo de `assistido`.
  const avisoNovos = !semLegenda && textoEpisodiosNovos(anime.episodios_novos);
  const idBadgeAviso = idBadge + '-aviso';
  // Centralizada (`left-1/2 -translate-x-1/2`) na base do pôster, não no
  // canto — `bottom-2` espelha o `top-2`/`left-0 top-0` que
  // `BotaoRemoverDoCatalogo`/`pillsSuperiores` usam no topo.
  const badgeAviso = avisoNovos && (
    <span
      id={idBadgeAviso}
      className="absolute bottom-2 left-1/2 z-10 -translate-x-1/2 inline-flex h-8 items-center gap-1 whitespace-nowrap bg-black/80 backdrop-blur-md px-2.5 text-sm font-semibold uppercase tracking-wide text-white"
    >
      <Sparkles aria-hidden="true" className="h-5 w-5" />
      {avisoNovos}
    </span>
  );
  // Rótulo "Dublado"/"Legendado" (`AnimeSaida.versao_confirmada_mais_recente`,
  // backend/api/rotas/animes.py::listar_animes) na mesma linha — `null` sem
  // fonte mapeada ainda OU quando ela não diferencia versão
  // (`desconhecida`): nenhum dos dois rótulos é informação confiável nesse
  // caso, melhor omitir que arriscar errado.
  const rotuloVersao =
    anime.versao_confirmada_mais_recente === 'dublado'
      ? 'Dublado'
      : anime.versao_confirmada_mais_recente === 'legendado'
        ? 'Legendado'
        : null;
  const separador = (
    <span aria-hidden="true" className="text-ink-muted">
      {' '}
      •{' '}
    </span>
  );
  // Separador só entre a versão (ou "Tn EP.n", quando não há versão) e o
  // aviso de próxima temporada encadeado depois — pedido explícito do
  // usuário (2026-09-21) pra diferenciar esse encadeamento do `separador`
  // padrão ("•") usado no resto da legenda.
  const separadorProximaTemporada = (
    <span aria-hidden="true" className="text-ink-muted">
      {' '}
      |{' '}
    </span>
  );
  // Prefixo "Tn " (com o espaço já embutido) só quando a temporada é
  // conhecida de verdade — string vazia caso contrário. Sem temporada
  // conhecida (item de feed, nunca tem `numero_temporada`), o texto vira "n
  // episódios" por extenso em vez de "EP.n" solto — pedido explícito do
  // usuário (2026-09-20): "EP.n" sem o "Tn" na frente lia estranho, teor de
  // rótulo técnico truncado; por extenso deixa claro que é contagem sem
  // precisar do prefixo.
  const rotuloTemporada = anime.numero_temporada != null ? `T${anime.numero_temporada} ` : '';
  const textoContagem = rotuloTemporada
    ? `${rotuloTemporada}EP.${numeroDeEpisodios}`
    : `${numeroDeEpisodios} episódios`;
  const tagTemporada = !semTagEpisodios && episodioLancado == null && numeroDeEpisodios != null && (
    <p className="text-xs font-semibold uppercase tracking-wide text-ink-muted">
      {textoContagem}
      {rotuloVersao && (
        <>
          {separador}
          {rotuloVersao}
        </>
      )}
      {avisoProximaTemporada && (
        <>
          {separadorProximaTemporada}
          {avisoProximaTemporada}
        </>
      )}
    </p>
  );

  // Grupo que ancora as pills do canto superior esquerdo do pôster (pedido
  // explícito do usuário, 2026-09-15) — `badgeAssistido`/`badgeCatalogado` têm
  // posição própria (`absolute left-2 top-1`, ver comentários delas acima) e
  // nunca coexistem na prática — os dois únicos call sites de
  // `indicarCatalogado` (`paginas/Inicio.jsx`/`paginas/PaginaDoAnime.jsx`)
  // montam um `anime` sem campo `assistido`, então as duas pills não competem
  // pelo mesmo canto. `absolute` (não `relative`) no wrapper ancora no canto
  // do pôster (`relative` na div da capa) de forma confiável. `badgeEpisodio`/
  // `badgeAviso` (episódio novo/recém-lançado) não entram aqui — ficam
  // centralizadas na base do pôster (ver comentário delas acima);
  // `avisoProximaTemporada` continua como texto na legenda (ver comentário
  // dela acima).
  const pillsSuperiores = (badgeAssistido || badgeCatalogado) && (
    <div className="absolute left-0 top-0 z-10 flex flex-col items-start gap-1.5">
      {badgeAssistido}
      {badgeCatalogado}
    </div>
  );

  // Título primeiro (sem cor de hover — pedido explícito do usuário),
  // badges/tags (temporada, aviso, fonte) abaixo dele — próxima temporada
  // continua encadeada aqui como texto; episódio novo voltou a ser badge
  // sobre o pôster (`badgeAviso` acima, centralizada na base).
  const legenda = !semLegenda && (
    <>
      <h2 className="line-clamp-2 text-sm font-semibold leading-snug text-white lg:text-base">
        {titulo}
      </h2>
      {tagTemporada}
      {aviso && (
        <p className="text-xs font-semibold uppercase tracking-wide text-neon">{aviso}</p>
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
    // comentário no topo). 12px de cada lado: o slot da grade/fileira
    // (GradeDeCatalogo.jsx/FileiraDeCards.jsx) não tem mais padding nenhum
    // (removido a pedido do usuário, 2026-09-15) — o halo de hover INVADE o
    // pôster vizinho agora (consequência conhecida, documentada no topo de
    // GradeDeCatalogo.jsx; não corrigido aqui).
    classesConteudo =
      'relative flex w-full flex-col gap-2  p-3 -m-3 text-left transition-colors duration-300 ease-out group-hover/card:bg-surface-hover motion-reduce:transition-none';
    conteudo = (
      <>
        <div className="relative aspect-[2/3] w-full overflow-hidden bg-surface">
          <img src={capa} alt="" loading="lazy" className="absolute inset-0 h-full w-full object-cover" />
          {pillsSuperiores}
          {badgeEpisodio}
          {badgeAviso}
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
        {pillsSuperiores}
        {badgeEpisodio}
        {badgeAviso}
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

  // Nome acessível da camada de navegação: `aria-labelledby` junta os badges
  // "EP.n" (episódio recém-lançado), "Assistido", "Já no catálogo" e o aviso
  // de episódio novo, quando presentes, nessa ordem — não é mais a ordem
  // visual (EP.n/aviso de episódio novo migraram pra base do pôster,
  // `badgeEpisodio`/`badgeAviso`; Assistido/Já no catálogo seguem no canto,
  // `pillsSuperiores`), só a ordem de leitura — com o bloco de legenda
  // (título + tags, que ainda inclui o aviso de próxima temporada como
  // texto), igual ao texto que seria lido se estivesse tudo dentro do
  // próprio Link/button.
  // `semLegenda` nunca ocorre nestes dois ramos na prática (só combina com
  // `estatico`, ver comentário no topo do arquivo), mas o fallback pro
  // `titulo` cru cobre esse caso defensivamente.
  const idsRotulo = [
    episodioLancado != null && idBadgeEpisodio,
    assistido && idBadge,
    jaCatalogado && idBadgeCatalogado,
    avisoNovos && idBadgeAviso,
    !semLegenda && idLegenda,
  ]
    .filter(Boolean)
    .join(' ');
  const propsRotulo = idsRotulo ? { 'aria-labelledby': idsRotulo } : { 'aria-label': titulo };

  if (idCatalogado != null) {
    return (
      <div className={wrapper}>
        <div className={classesConteudo}>{conteudo}</div>
        <Link
          to={`/anime/${idCatalogado}`}
          className="absolute inset-0 cursor-pointer outline-none"
          {...propsRotulo}
        />
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
            : 'absolute inset-0 cursor-pointer outline-none'
        }
        {...propsRotulo}
      />
      {sobreposicao}
    </div>
  );
}

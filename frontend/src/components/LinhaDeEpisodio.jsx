import { useState } from 'react';
import { Link } from 'react-router-dom';
import { IconePlay } from '../player/Icones.jsx';

// Re-exportado: `src/inicio/` não pode importar de `src/player/` direto
// (fronteira Clean Architecture documentada em paginas/Inicio.jsx, D5 do
// plano) — `inicio/CarrosselDestaques.jsx` reusa o MESMO ícone do CTA
// "Assistir agora"/"Continuar assistindo" passando por aqui, não duplicando o
// SVG.
export { IconePlay };

// Miniatura decorativa do episódio — still TMDB do episódio quando existe,
// senão a arte do próprio anime (TMDB/AniList, `PaginaDoAnime.jsx::
// thumbDoAnime`); NUNCA MAIS uma imagem raspada do site de captura (pedido
// explícito do usuário: baixar um episódio não deve trocar a imagem exibida
// — `api/servicos/fontes.py::_sobrepor_stills_de_episodios`/`jobs.py::
// still_de_episodio` já garantem isso no servidor, ver `PaginaDoAnime.jsx`).
// `src={thumb}` direto: ao contrário da antiga thumb da fonte, esta URL
// sempre vem de um provedor de metadados servido por CDN pública (sem risco
// de hotlink/vazar IP do usuário) — não precisa mais do proxy `GET
// /api/thumb` (`api/rotas/thumb.py`, que segue existindo só pro caso o
// backend volte a precisar dele). `alt=""` porque o número/título do
// episódio já está em texto ao lado (img puramente decorativa). Some sozinha
// quando `thumb` é vazio (nem still nem arte do anime disponível, nada
// renderiza, sem buraco no layout) ou se a URL falhar ao carregar
// (`onError`) — `falhouEm` compara com `thumb` pra voltar a tentar quando a
// linha troca de origem (still → arte do anime, por ex.).
export function MiniaturaDoEpisodio({ thumb, modo }) {
  const [falhouEm, setFalhouEm] = useState(null);
  if (!thumb || falhouEm === thumb) return null;
  return (
    <img
      key={thumb}
      src={thumb}
      alt=""
      loading="lazy"
      onError={() => setFalhouEm(thumb)}
      // modo grade: a thumb preenche o retângulo 16/9 recortado em
      // `absolute inset-0` — número do episódio e ação ficam FORA dela, na
      // legenda abaixo (ver CartaoDeEpisodio); modo lista: mesma linguagem, a
      // thumb 16/9 encosta na borda esquerda do card (o `overflow-hidden` +
      // `rounded-lg` da raiz recorta os cantos) — sem borda/arredondamento
      // próprios.
      className={
        modo === 'grade'
          ? 'absolute inset-0 h-full w-full object-cover'
          : 'aspect-[16/9] w-28 shrink-0 object-cover sm:w-32'
      }
    />
  );
}

// Espelha PaginaDoAnime.jsx::ROTULO_VERSAO — duplicado em vez de importado
// (componente não deve depender da página que o renderiza; mesma lógica de
// PaginaDoAnime.jsx::SITE_LOCAL, que espelha um enum do backend em vez de
// importar). Usado só na nota de origem do ramo `liberadoOuDescartado`
// abaixo, quando o episódio descartado é do mesmo domínio ativo mas de
// versão diferente (legendado/dublado).
const ROTULO_VERSAO = {
  legendado: 'Legendado',
  dublado: 'Dublado',
  desconhecida: 'Desconhecida (site não confirma)',
};

// Card (modo grade) / linha (modo lista) de episódio como alvo de clique
// único, em três formas escolhidas pelos props recebidos:
//  - `para` (+ `estadoDeRota`) → <Link> pro player (ramo `pronto`);
//  - `aoClicar` (+ `desabilitado`/`rotuloAcessivel`) → <button> que dispara a
//    captura (ramos acionáveis);
//  - nenhum dos dois → <div> estático: rótulo não numérico (captura fora de
//    escopo) ou episódio em processamento (não clicável hoje). Mesmas
//    classes-base do card, mas sem `cursor-pointer`, sem hover/escala e sem a
//    borda neon — nada aqui recebe clique nem foco de teclado.
// A ação/estado do episódio vive só como texto na legenda (FaixaDeConteudo,
// prop `legenda`) ou como overlay sobre a thumb (OverlayDeStatus, `children`)
// — nunca num <button>/<Link> aninhado DENTRO do Link/button de navegação
// (HTML inválido, button/a dentro de button/a). Modo GRADE tem uma exceção
// controlada pra isso: `sobreposicao` (opcional — menu de ações sobre a
// miniatura, `components/CartaoContinuarAssistindo.jsx`) entra como IRMÃO do
// Link/button, nunca como filho — ver bloco de comentário mais abaixo sobre a
// estrutura "stretched link" do modo grade.
//
// `children` vs `legenda`: `children` é tudo que fica DENTRO da caixa
// recortada (miniatura + overlays sobre ela); `legenda` é sempre a
// `FaixaDeConteudo` do chamador. Modo LISTA: sem diferença visual, os dois
// entram juntos na mesma caixa (não há recorte por aspect-ratio ali, o
// problema abaixo não existe). Modo GRADE: a caixa recortada
// (`aspect-[16/9]`, `overflow-hidden`, `rounded-lg`) envolve só `children`;
// `legenda` fica ABAIXO dela, em fluxo normal, FORA do recorte — mesma
// correção de components/AnimeCard.jsx (lá, pôster/legenda do card de
// catálogo): o degradê que dava contraste ao rodapé por cima da miniatura
// deixava uma lasca sem escurecer no canto arredondado em alguns motores
// gráficos (dois elementos `absolute` — imagem e degradê — recortados pelo
// mesmo `overflow-hidden`, arredondando subpixel de forma independente).
// Tirar a legenda de cima da miniatura elimina o degradê inteiro.
//
// Hover/foco — modo GRADE (pedido do usuário — sem escala): desde que
// `sobreposicao` existe, o Link/button de navegação virou uma camada
// `absolute inset-0` IRMÃ da moldura visual (miniatura+legenda), não mais o
// próprio elemento que as envolve — mesma estrutura "stretched link" de
// `components/AnimeCard.jsx`, necessária pra caber um `<button>` de menu sem
// aninhar em outro elemento interativo (ver comentário logo acima). `p-2
// -m-2` na moldura visual soma padding e margem negativa pra não deslocar
// miniatura+legenda, só revelar `bg-surface-hover` maior que os dois juntos —
// `group-hover/cartao:` funciona porque `:hover` BORBULHA pra ancestrais
// (o wrapper com `group/cartao` fica em `:hover` sempre que o mouse está
// sobre QUALQUER descendente, Link/button incluso). `bordaNeon` mora dentro
// da miniatura e é só indicador de FOCO por teclado — mas usa
// `group-has-[:focus-visible]/cartao:border-neon` (não `group-focus-visible`,
// que exigiria o PRÓPRIO wrapper estar focado): `:focus-visible` NÃO
// borbulha como `:hover`, só `:has()` enxerga o estado de um descendente a
// partir do ancestral. Fundo sozinho não tem contraste suficiente pra
// servir de indicador de foco (~1.1:1 entre `surface`/`surface-hover`, abaixo
// do 3:1 mínimo — CLAUDE.md §4 não permite cortar acessibilidade). Modo
// LISTA, linha full-width — sem essa estrutura (nenhum chamador precisa de
// `sobreposicao` ali, ver comentário da função): a caixa inteira
// (miniatura+legenda) continua sendo o próprio alvo interativo, como antes —
// `hover:bg-surface-hover` já cobria tudo; só a borda perdeu o gatilho de
// hover, mesmo motivo de acessibilidade. O alvo fica `outline-none` (foco vem
// só da borda). `desabilitado` = captura em voo: bloqueia o clique.
// `boxShadow` (via `estilo`): só no modo lista agora (drop shadow curta, os
// cards ficam a 8px um do outro) — o modo grade PERDEU a sombra (antes
// espelhava a do catálogo, `SOMBRA_SLIDE_ATIVO`; pedido do usuário, mora numa
// caixa própria que já ganhou o realce de hover/foco, não precisa mais da
// sombra pra se destacar).
export function CartaoDeEpisodio({
  modo,
  cor,
  para,
  estadoDeRota,
  aoClicar,
  desabilitado,
  rotuloAcessivel,
  legenda,
  sobreposicao,
  children,
}) {
  const emGrade = modo === 'grade';
  const estilo = {
    boxShadow: emGrade
      ? undefined
      : 'rgba(0,0,0,0.38) 0 8px 10px -4px, rgba(0,0,0,0.28) 0 2px 4px -3px',
  };
  const classeCaixa = `relative flex w-full overflow-hidden bg-surface text-left text-sm ${cor} ${
    emGrade ? 'aspect-[16/9] ' : ''
  }`;

  // `sobreposicao` (opcional, só modo grade — pedido do usuário quando
  // `components/CartaoContinuarAssistindo.jsx` ganhou um menu de ações sobre
  // a miniatura): nó renderizado como IRMÃO do Link/button de navegação,
  // nunca como filho — mesmo raciocínio de `components/AnimeCard.jsx`
  // (`sobreposicao` de lá, pro numeral do Top 10). É por isso que o modo
  // grade abaixo virou uma estrutura de "stretched link" (Link/button
  // `absolute inset-0`, camada IRMÃ do conteúdo visual, não mais pai dele):
  // um `<button>` de menu dentro do Link/button original seria HTML inválido
  // (button aninhado em button/a) — já documentado no topo do arquivo como
  // regra ("nunca um <button>/<Link> aninhado DENTRO do card").
  if (emGrade) {
    // `cor` repetido aqui: a legenda mora FORA da caixa recortada, então
    // precisa da própria herança de cor/peso de fonte (ex. o
    // `font-semibold` do ramo "nunca capturado" chegando até o aviso de
    // "rótulo não numérico", que não define peso próprio).
    if (!para && !aoClicar) {
      return (
        <div className="relative">
          <div className={`flex w-full flex-col gap-1.5 text-left text-sm ${cor}`}>
            <div className={classeCaixa} style={estilo}>
              {children}
            </div>
            {legenda}
          </div>
          {sobreposicao}
        </div>
      );
    }

    // Indicador de FOCO por teclado (ver bloco de comentário no topo do
    // arquivo, motivo de contraste) — `group-has-[:focus-visible]/cartao`
    // (não `group-focus-visible/cartao`, que exigiria o PRÓPRIO elemento
    // `group/cartao` estar focado): o Link/button de navegação agora é IRMÃO
    // do wrapper `group/cartao`, não o próprio wrapper, e `:focus-visible`
    // não borbulha pra ancestrais como `:hover` borbulha — só `:has()`
    // enxerga o estado de um descendente a partir do ancestral.
    const bordaNeon = (
      <span
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 rounded-2xl border-4 border-transparent transition-colors duration-300 ease-out group-has-[:focus-visible]/cartao:border-neon motion-reduce:transition-none"
      />
    );
    // Moldura de hover única cobrindo miniatura+legenda — `p-2 -m-2` soma
    // padding e margem negativa pra não deslocar o conteúdo, só revelar
    // `bg-surface-hover` maior que os dois juntos quando o hover dispara
    // (`:hover` SIM borbulha pra ancestrais, então `group-hover/cartao`
    // funciona normalmente aqui mesmo com o Link/button agora sendo irmão,
    // não pai). Sem escala (removida a pedido do usuário): só o fundo reage.
    // `w-[calc(100%+1rem)]` no lugar de `w-full`: com largura EXPLÍCITA
    // (100%), a margem negativa só EMPURRA a caixa pra esquerda em vez de
    // esticar ela pros dois lados (isso só aconteceria com `width:auto`, que
    // o grid estica sozinho) — na última coluna da grade a caixa ficava 8px
    // curta do fim de verdade, destoando da barra de ações acima. Somando o
    // `1rem` (as duas margens de 0.5rem) na largura, a caixa volta a
    // transbordar 8px pros dois lados igualmente (mesmo efeito do
    // `AnimeCard.jsx`), sem deslocar o conjunto pra esquerda.
    const classeVisual =
      `relative flex w-[calc(100%+1rem)] flex-col gap-1.5 text-left text-sm ${cor} ` +
      'p-2 -m-2 transition-colors duration-300 ease-out group-hover/cartao:bg-surface-hover motion-reduce:transition-none';

    return (
      <div className="group/cartao relative">
        <div className={classeVisual}>
          <div className={classeCaixa} style={estilo}>
            {children}
          </div>
          {legenda}
          {bordaNeon}
        </div>
        {para ? (
          <Link
            to={para}
            state={estadoDeRota}
            className="absolute inset-0 cursor-pointer outline-none"
            aria-label={rotuloAcessivel}
          />
        ) : (
          <button
            type="button"
            onClick={aoClicar}
            disabled={desabilitado}
            aria-label={rotuloAcessivel}
            className="absolute inset-0 cursor-pointer outline-none disabled:cursor-progress"
          />
        )}
        {sobreposicao}
      </div>
    );
  }

  // Lista: sem mudança — a caixa inteira (`classeCaixa`) é o alvo interativo,
  // `children` e `legenda` entram juntos nela. Sem suporte a `sobreposicao`
  // (nenhum chamador em modo lista precisa disso hoje).
  if (!para && !aoClicar) {
    return (
      <div className={classeCaixa} style={estilo}>
        {children}
        {legenda}
      </div>
    );
  }

  // Só indicador de FOCO agora (ver bloco de comentário no topo) — sem
  // gatilho de hover.
  const bordaNeon = (
    <span
      aria-hidden="true"
      className="pointer-events-none absolute inset-0 rounded-lg border-2 border-transparent transition-colors duration-300 ease-out group-focus-visible/cartao:border-neon motion-reduce:transition-none"
    />
  );
  const classe = `group/cartao ${classeCaixa} cursor-pointer outline-none transition-colors duration-200 hover:bg-surface-hover`;
  if (para) {
    return (
      <Link to={para} state={estadoDeRota} className={classe} style={estilo}>
        {children}
        {legenda}
        {bordaNeon}
      </Link>
    );
  }
  return (
    <button
      type="button"
      onClick={aoClicar}
      disabled={desabilitado}
      aria-label={rotuloAcessivel}
      style={estilo}
      className={`${classe} disabled:cursor-progress`}
    >
      {children}
      {legenda}
      {bordaNeon}
    </button>
  );
}

// Rótulos em `core/enums.py::StatusJob`/`StatusEpisodio` (backend) — mesmos
// valores StrEnum, traduzidos aqui pra exibição. Exportado (com `tomDoStatus`/
// `OverlayDeStatus` abaixo): `components/CartaoContinuarAssistindo.jsx`
// (prateleira cross-anime da Inicio) reusa o mesmo overlay de status pro
// ramo "processando" em vez de reimplementar o mapa rótulo/spinner.
export const ROTULOS_STATUS = {
  na_fila: 'Na fila',
  baixando: 'Baixando',
  validando_fonte: 'Validando fonte',
  transcodificando: 'Transcodificando',
  extraindo_frames: 'Extraindo frames',
  upscaling: 'Upscaling',
  remontando: 'Remontando',
  empacotando_hls: 'Empacotando',
  pronto: 'Pronto',
  falhou: 'Falhou',
  falhou_extracao: 'Falhou na extração',
  aguardando_intervencao: 'Precisa de atenção',
  cancelando: 'Cancelando',
  cancelado: 'Cancelado',
  pausado: 'Pausado',
  pendente: 'Pendente',
  somente_720p: 'Somente 720p',
};

// Estados de status (backend `core/enums.py::StatusJob`/`StatusEpisodio`)
// agrupados pelo ornamento que o overlay do modo grade usa: 'progresso' =
// pipeline em curso, ganha spinner; 'alerta' = falha/intervenção, ícone
// estático de atenção (um spinner sugeriria avanço onde nada avança);
// 'neutro' (default — cobre os terminais parados `cancelado`/`pausado`/
// `somente_720p` e QUALQUER status não mapeado, incl. `pendente`) = só o
// rótulo. `pronto` nunca chega aqui (tem ramo próprio).
const STATUS_EM_PROGRESSO = new Set([
  'na_fila',
  'validando_fonte',
  'baixando',
  'transcodificando',
  'extraindo_frames',
  'upscaling',
  'remontando',
  'empacotando_hls',
  'cancelando',
]);
const STATUS_DE_ALERTA = new Set(['falhou', 'falhou_extracao', 'aguardando_intervencao']);

export function tomDoStatus(status) {
  if (STATUS_EM_PROGRESSO.has(status)) return 'progresso';
  if (STATUS_DE_ALERTA.has(status)) return 'alerta';
  return 'neutro';
}

// Overlay de status centralizado sobre a miniatura 16/9 — SÓ modo grade
// (no modo lista o status segue como texto inline ao lado do rótulo,
// inalterado). Scrim (`bg-black/50`) + `backdrop-blur-sm` dão legibilidade
// ao rótulo sobre qualquer thumb; como a legenda (FaixaDeConteudo) mora fora
// da caixa recortada da miniatura (ver CartaoDeEpisodio), este overlay nunca
// disputa espaço com o número/título do episódio — os dois nem se sobrepõem
// mais. `tom`:
//  - 'progresso': só a animação (anel de borda parcial girando) — SEM texto
//    visível (pedido do usuário, 2026-09-2x: a ilha dinâmica da navbar já
//    mostra o rótulo do status por extenso, ver BarraDeNavegacao.jsx/
//    PaginaDoAnime.jsx::statusCapturaIlha; repetir o texto no card virou
//    ruído). O rótulo continua no DOM como `sr-only` (não `aria-hidden`) —
//    quem usa leitor de tela ainda precisa ouvir a transição de status
//    mesmo sem a pista visual, CLAUDE.md §4 não permite cortar isso. A
//    animação em si segue decorativa/`aria-hidden` e some em
//    `motion-reduce` (o texto sr-only já comunica o estado sem ela).
//  - 'alerta': ícone "⚠" estático (sem spinner) em âmbar — mesmo tom "precisa
//    de atenção" usado no rodapé de AnimeCard.jsx; não há token de
//    erro/danger no @theme (index.css). Rótulo continua VISÍVEL aqui: sem
//    animação nenhuma pra substituir a informação, e "Falhou"/"Precisa de
//    atenção" não têm um equivalente por extenso na ilha (que só fala de
//    progresso/conclusão).
//  - 'neutro': nada além do rótulo, em cor esmaecida (`text-ink-muted`) —
//    inalterado (cobre cancelado/pausado/somente_720p/pendente, nenhum
//    pedido do usuário tocou este ramo).
export function OverlayDeStatus({ rotulo, tom }) {
  const corDoRotulo =
    tom === 'alerta' ? 'text-amber-300' : tom === 'neutro' ? 'text-ink-muted' : 'text-white';
  return (
    <span className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-black/50 p-3 text-center backdrop-blur-sm">
      {tom === 'progresso' && (
        <span
          aria-hidden="true"
          className="h-5 w-5 animate-spin rounded-full border-2 border-white/25 border-t-white motion-reduce:hidden"
        />
      )}
      {tom === 'alerta' && (
        <span aria-hidden="true" className="text-xl leading-none text-amber-300">
          ⚠
        </span>
      )}
      <span
        aria-live="polite"
        className={`text-xs font-semibold uppercase tracking-wide ${corDoRotulo} ${
          tom === 'progresso' ? 'sr-only' : ''
        }`}
      >
        {rotulo}
      </span>
    </span>
  );
}

// Pista de "pronto pra assistir" no ramo `pronto` — o mesmo `IconePlay` do
// player (player/Icones.jsx), reaproveitado em vez de redesenhar o triângulo,
// num disco translúcido centralizado sobre a thumb. `fill="currentColor"`:
// por padrão o ícone é só contorno (`propsBase` de Icones.jsx); preenchido é
// o MESMO ajuste que o botão "Assistir agora"/"Continuar assistindo" do
// carrossel já usa (`inicio/CarrosselDestaques.jsx`) — os dois ficam
// visualmente idênticos, não só o mesmo componente. Mesmo slot central do
// OverlayDeStatus: spinner = processando, ⚠ = alerta, ▶ = pronto formam um
// sistema visual único, um estado por card. `pointer-events-none` deixa o
// clique atravessar pro <Link> do CartaoDeEpisodio (o card inteiro é o alvo);
// `aria-hidden` (herdado do IconePlay) porque o <Link> já tira o nome
// acessível do conteúdo ("Episódio N — título"). Acende no hover via
// `group/cartao`. Modo grade: centralizado no card todo. Modo lista:
// centralizado na caixa da miniatura à esquerda (mesmas medidas de
// MiniaturaDoEpisodio); sem thumb, cai numa faixa estreita à esquerda pra
// não flutuar sobre o texto.
export function IndicadorDePlay({ emGrade, temThumb }) {
  const posicao = emGrade
    ? 'absolute inset-0'
    : temThumb
      ? 'absolute left-0 top-0 aspect-[16/9] w-28 sm:w-32'
      : 'absolute inset-y-0 left-0 w-14';
  return (
    <span className={`pointer-events-none flex items-center justify-center ${posicao}`}>
      <span
        className={`flex items-center justify-center rounded-full bg-white text-black transition duration-200 ease-out group-hover/cartao:brightness-90 group-hover/cartao:scale-110 motion-reduce:transition-none ${
          emGrade ? 'h-12 w-12' : 'h-9 w-9'
        }`}
      >
        <IconePlay
          width={undefined}
          height={undefined}
          fill="currentColor"
          className={emGrade ? 'h-6 w-6 translate-x-0.5' : 'h-4 w-4 translate-x-px'}
        />
      </span>
    </span>
  );
}

// Rótulo do episódio — idêntico nos dois modos (grade e lista) e nos quatro
// ramos: "EP.{numero}", com " - {titulo}" anexado quando o registro traz
// título (TMDB, `PaginaDoAnime.jsx::linhas`). `line-clamp-2` sempre: um
// título longo ocupa no máx. 2 linhas e é cortado com reticências, tanto na
// legenda abaixo da miniatura (grade) quanto na linha da lista. `naoNumerico`
// (numero == null, ex. "Especial"): o rótulo cru da fonte entra no lugar de
// "EP.N".
// Exportado: `CartaoContinuarAssistindo.jsx` (prateleira da Inicio) reusa o
// MESMO rótulo "EP.N - Título" em vez de reimplementar o formato à mão —
// mesmo `titulo` (TMDB) que `ContinuarAssistindoSaida.titulo` já traz do
// backend (backend/api/esquemas.py).
// `temporada` (opcional, só a prateleira "Continuar assistindo" passa): prefixo
// "T2 · " — lá o card de cada anime não tem seletor de temporada por perto.
export function RotuloEpisodio({ numero, rotulo, titulo, temporada }) {
  const prefixo = temporada != null ? `T${temporada} ` : '';
  return (
    <span className="line-clamp-2 text-sm font-semibold text-white">
      {numero == null ? rotulo : `${prefixo}EP.${numero}${titulo ? ` - ${titulo}` : ''}`}
    </span>
  );
}

// Sinopse do episódio (TMDB, mesmo overlay de `titulo`/`thumb`) — logo abaixo
// do rótulo, nos dois modos (grade e lista). `line-clamp-2`: sinopse pode ser
// um parágrafo inteiro, cortada com reticências pra não estourar a altura do
// card/linha; sem sinopse (TMDB não achou ou sem tradução pt-BR), não
// renderiza nada — nunca um espaço vazio no lugar.
export function SinopseEpisodio({ sinopse }) {
  if (!sinopse) return null;
  return <p className="line-clamp-2 text-xs text-ink-muted">{sinopse}</p>;
}

// "Assistido": o episódio foi visto até o fim (`assistido_em`) — distinto da
// pista de "pronto pra assistir" (IndicadorDePlay, centralizada sobre a thumb).
// Mesmo estilo nos ramos `pronto` e `liberadoOuDescartado`. `flutuante`
// (pedido explícito do usuário, 2026-09-15): modo GRADE move o badge pra
// DENTRO da caixa recortada, ancorado no canto inferior direito da miniatura
// — mesmo texto/tipografia, só a posição muda (sem ícone, sem fundo novo); o
// contraste contra a thumb vem do `ScrimAssistido` já aplicado por baixo dele
// nesse modo. Modo lista continua sem `flutuante`, em fluxo normal no
// `trailing` da legenda (FaixaDeConteudo).
function BadgeAssistido({ flutuante = false }) {
  return (
    <span
      className={`px-2.5 py-0.5 bg-black/80 text-xs font-semibold uppercase tracking-wide text-white ${
        flutuante ? 'absolute bottom-2 right-2 z-10' : ''
      }`}
      aria-label="já assistido"
    >
      Assistido
    </span>
  );
}

// Scrim sobre a miniatura quando o episódio já foi assistido — SÓ modo grade
// (no modo lista o BadgeAssistido no trailing já dá o contraste). Escurece o
// card pra ele recuar dos não assistidos, mesmo `bg-[#0b0b0d]/60` do overlay de
// "assistido" do card de catálogo (components/AnimeCard.jsx). Fica ANTES do
// IndicadorDePlay, do rodapé em degradê e da borda neon na árvore — nada disso
// é esmaecido, só a imagem. `aria-hidden`: o BadgeAssistido carrega o rótulo.
function ScrimAssistido() {
  return <span aria-hidden="true" className="absolute inset-0 bg-[#0b0b0d]/10" />;
}

// Verbo de captura como texto — renderizado SÓ no modo lista. No modo grade
// não há texto de ação em repouso (a affordance é o card: cursor/escala/borda
// neon) e o "Capturando…" transitório vira OverlayDeStatus sobre a thumb.
function RotuloDeAcao({ verbo, capturando }) {
  return (
    <span className="shrink-0 text-sm font-semibold uppercase tracking-wide text-neon">
      {capturando ? 'Capturando…' : verbo}
    </span>
  );
}

// Faixa de conteúdo textual do card — uma moldura só pros dois modos. Grade:
// legenda ABAIXO da miniatura, em fluxo normal (`CartaoDeEpisodio` já a
// recebe fora da caixa recortada via prop `legenda` — ver rationale lá; sem
// degradê nenhum, a miniatura fica limpa). Lista: coluna ao lado da
// miniatura (o padding mora aqui, não na raiz, pra a thumb encostar na
// borda esquerda). Primeira linha: `rotulo` à esquerda (pode quebrar em 2
// linhas) e `trailing` à direita (badge "✓ assistido", verbo de captura,
// status inline, nota de origem ou o aviso de rótulo não numérico),
// alinhados pelo topo com `justify-between`. `sinopse` (SinopseEpisodio, TMDB)
// vem logo abaixo do rótulo; `extra` (a barra de progresso do ramo `pronto`)
// vem depois dela.
export function FaixaDeConteudo({ modo, rotulo, trailing, sinopse, extra }) {
  return (
    <span
      className={
        modo === 'grade'
          ? 'flex flex-col gap-1.5 pt-2'
          : 'flex min-w-0 flex-1 flex-col justify-center gap-1.5 px-3 py-2.5'
      }
    >
      <span className="flex items-start justify-between gap-2">
        {rotulo}
        {trailing}
      </span>
      {sinopse}
      {extra}
    </span>
  );
}

// Uma posição de episódio na grade/lista da página do anime. Decide só o ramo
// de render, o alvo de clique e o conteúdo de cada slot — o enquadramento fica
// nos componentes (CartaoDeEpisodio, FaixaDeConteudo, RotuloEpisodio). Ordem e
// condição dos quatro ramos:
// (1) `episodio.status === 'pronto'`: link pro player (alvo <Link>), com barra
//     de progresso quando `episodio.progresso_s` (Feature "continuar
//     assistindo") já tem valor;
// (2) `episodio.status === 'liberado'` (Feature "liberar arquivo ao terminar")
//     OU `episodio.status === 'falhou'` (esgotou as retentativas de extração,
//     `worker/executor.py::_MAX_TENTATIVAS_EXTRACAO`) OU episódio local existe
//     mas foi descartado da fonte/versão ativas pelo filtro de
//     `PaginaDoAnime.jsx::pertenceAFonteAtiva` (Feature "episódios grudados",
//     `episodioDescartado`): ramo de captura (alvo <button>), com badge
//     "✓ assistido" quando aplicável (nunca no caso `falhou`, que nunca
//     terminou de baixar) e verbo "Recapturar" em vez de "Capturar" — o
//     backend (D2, `api/servicos/jobs.py::criar_job_site`) reaproveita a linha
//     existente nesses três casos, em vez de deixar o aviso de falha preso
//     pra sempre (nem recarregar a página resolvia, já que `falhou` é estado
//     persistido no `Episodio`, não algo que uma nova aba limpa). No caso
//     `episodioDescartado` de MESMO site mas versão diferente da ativa, uma
//     nota "(versão real)" indica a origem (ver `notaOrigem` abaixo). A nota
//     "(via {site})" pra `episodioDescartado` de outro site foi removida a
//     pedido do usuário — ruído visual ao trocar de fonte;
// (3) capturado mas ainda em processamento: status ao vivo, cruzado com `job`
//     do WS quando disponível. Alvo estático <div> (não clicável hoje) — não
//     cobre mais `falhou` (ramo 2 acima trata a retentativa);
// (4) nunca capturado: o card/linha inteiro dispara a captura (alvo <button>),
//     ou alvo estático <div> quando `numero` é `null` (rótulo não numérico na
//     fonte, ex. "Especial": aparece na lista mas capturá-lo está fora de
//     escopo por ora).
//   Exibição do estado de captura por modo: no modo LISTA a ação
// ("Capturar"/"Recapturar"/"Capturando…", RotuloDeAcao) e o status do pipeline
// são texto inline ao lado do rótulo (o `trailing` da FaixaDeConteudo). No
// modo GRADE não há texto de ação em repouso — a affordance é o card
// (cursor/escala/borda neon) — e todo estado NÃO terminal (status ao vivo do
// ramo 3, "Capturando…" transitório dos ramos 2 e 4) aparece como overlay
// central sobre a thumb (`OverlayDeStatus`): spinner nos estados de progresso,
// "⚠" em falha/intervenção, só rótulo nos neutros. Rótulo (RotuloEpisodio,
// idêntico nos dois modos), sinopse (SinopseEpisodio, TMDB), "✓ assistido",
// nota de origem, barra de progresso do ramo `pronto` e o aviso de
// `naoNumerico` seguem nos dois modos.
export default function LinhaDeEpisodio({
  numero,
  rotulo,
  colisao,
  episodio,
  episodioDescartado,
  // URL da thumb do episódio (ou `null`) — `PaginaDoAnime.jsx::linhas`:
  // still TMDB do episódio (`remotos.dados`, já overlaid pelo servidor) com
  // `thumbDoAnime` (`anime.banner_path ?? anime.capa_path`) como fallback.
  // Renderizada por `MiniaturaDoEpisodio`; os 4 ramos de render abaixo a
  // exibem.
  thumb,
  // Título/sinopse do episódio (ou `null`) — `PaginaDoAnime.jsx::linhas`:
  // mesma prioridade remoto-depois-local de `thumb` acima, mas sem fallback
  // pra arte do anime (não existe "sinopse genérica"). Usados por
  // `RotuloEpisodio`/`SinopseEpisodio` nos 4 ramos de render abaixo.
  titulo,
  sinopse,
  // `PaginaDoAnime.jsx::remotos.dados?.dominio ?? null` — domínio da fonte
  // remota ativa (`null` enquanto ainda carrega/erra/está ambígua). Usado só
  // pra decidir a nota de origem do `episodioDescartado` no ramo
  // `liberadoOuDescartado` abaixo; sem valor, a nota fica suprimida (mesmo
  // critério conservador de `pertenceAFonteAtiva`, que também não filtra
  // com domínio desconhecido).
  dominioAtivo,
  // `PaginaDoAnime.jsx::versaoAtiva` — só usado quando `episodioDescartado`
  // é do MESMO domínio ativo mas de versão diferente (ver nota de origem
  // abaixo); nos outros ramos deste componente não é lido.
  versaoAtiva,
  // `PaginaDoAnime.jsx::modoVisualizacao` — 'lista' (default): linha
  // horizontal, thumb 16/9 à esquerda e o conteúdo ao lado; 'grade': a thumb
  // 16/9 é o card, com número/ação na legenda ABAIXO dela (ver
  // CartaoDeEpisodio). Muda o enquadramento (className da raiz, posição da
  // miniatura) e, nos ramos de captura, o quanto o card cresce no hover —
  // nunca qual conteúdo cada ramo renderiza.
  modo = 'lista',
  job,
  aoCapturar,
  capturando,
  animeId,
  animeTitulo,
  // `anime.numero_temporada` (PaginaDoAnime.jsx) — vai pro título do player
  // (PaginaDoPlayer.jsx). Ao contrário do H1/seletor da página do anime, o
  // player mostra mesmo com uma temporada só (sem seletor lá pra já dizer
  // "qual temporada").
  numeroTemporada,
}) {
  const naoNumerico = numero == null;
  const emGrade = modo === 'grade';

  // "Capturando…" transitório sobre a thumb — só no modo grade (no modo lista
  // esse mesmo estado é o texto de RotuloDeAcao). Compartilhado pelos ramos
  // `liberadoOuDescartado` e de captura nova.
  const overlayCapturando =
    emGrade && capturando ? <OverlayDeStatus rotulo="Capturando…" tom="progresso" /> : null;

  // `colisao` (calculado em `PaginaDoAnime.jsx`, `remotosDoNumero.length > 1`)
  // é verdadeiro só quando existe mais de um rótulo remoto de fato mapeando
  // pro mesmo `numero` inteiro (ex. "7" e "07" — extractors/base.py::
  // EpisodioRemoto) — não basta o rótulo divergir textualmente do número:
  // uma fonte que sempre zero-preenche ("07", "08", ...) sem nenhuma colisão
  // real não deve acender este aviso em toda linha. Mostrado entre
  // parênteses pra o usuário notar a ambiguidade (o contrato de captura
  // ainda só aceita `numero`, então as linhas colidentes disparam a mesma
  // captura — o backend resolve de forma determinística e loga,
  // extractors/servico.py e api/servicos/jobs.py).
  const rotuloDivergente = !naoNumerico && colisao && rotulo != null && rotulo !== String(numero);

  if (episodio?.status === 'pronto') {
    // `duracao_s` pode ser `null` (worker não conseguiu sondar) — sem ele
    // não dá pra calcular fração, a barra simplesmente não aparece.
    const percentualAssistido =
      episodio.progresso_s > 0 && episodio.duracao_s
        ? Math.min(100, Math.round((episodio.progresso_s / episodio.duracao_s) * 100))
        : null;
    const minutosRestantes =
      percentualAssistido != null
        ? Math.max(1, Math.round((episodio.duracao_s - episodio.progresso_s) / 60))
        : null;
    return (
      <CartaoDeEpisodio
        modo={modo}
        cor="text-white"
        para={`/assistir/${episodio.id}`}
        estadoDeRota={{
          episodio: { numero, animeId, animeTitulo, titulo: episodio.titulo, numeroTemporada },
        }}
        legenda={
          <FaixaDeConteudo
            modo={modo}
            rotulo={<RotuloEpisodio numero={numero} rotulo={rotulo} titulo={titulo} />}
            trailing={!emGrade && episodio.assistido_em ? <BadgeAssistido /> : null}
            sinopse={<SinopseEpisodio sinopse={sinopse} />}
            extra={
              // Modo lista continua com a barra JUNTO do texto (não há
              // miniatura recortada pra sobrepor — ver comentário da barra
              // abaixo, só modo grade).
              !emGrade && percentualAssistido != null ? (
                <span className="flex items-center gap-2">
                  <span
                    role="progressbar"
                    aria-label="progresso de reprodução"
                    aria-valuenow={percentualAssistido}
                    aria-valuemin={0}
                    aria-valuemax={100}
                    className="h-1 flex-1 overflow-hidden rounded-full bg-border-chrome"
                  >
                    <span
                      style={{ width: `${percentualAssistido}%` }}
                      className="block h-full rounded-full bg-neon"
                    />
                  </span>
                  <span className="shrink-0 text-xs text-ink-muted font-semibold">
                    faltam {minutosRestantes} min
                  </span>
                </span>
              ) : emGrade && minutosRestantes != null ? (
                <span className="text-xs font-semibold text-ink-muted">
                  faltam {minutosRestantes} min
                </span>
              ) : null
            }
          />
        }
      >
        <MiniaturaDoEpisodio thumb={thumb} modo={modo} />
        {emGrade && episodio.assistido_em && <ScrimAssistido />}
        <IndicadorDePlay emGrade={emGrade} temThumb={!!thumb} />
        {emGrade && episodio.assistido_em && <BadgeAssistido flutuante />}
        {/* Barra de progresso estilo Netflix sobre a própria miniatura — só
            modo grade (a caixa 16:9 recortada existe só ali, ver
            `classeCaixa`/`MiniaturaDoEpisodio` acima; modo lista mantém a
            barra ao lado do texto, no `extra` acima). Mesmo tratamento de
            `components/CartaoContinuarAssistindo.jsx`, 2026-09-21. */}
        {emGrade && percentualAssistido != null && (
          <span
            role="progressbar"
            aria-label="progresso de reprodução"
            aria-valuenow={percentualAssistido}
            aria-valuemin={0}
            aria-valuemax={100}
            className="absolute inset-x-0 bottom-0 z-10 h-1 bg-white/25"
          >
            <span style={{ width: `${percentualAssistido}%` }} className="block h-full bg-neon" />
          </span>
        )}
      </CartaoDeEpisodio>
    );
  }

  // `falhou`: tentativa de captura anterior esgotou as retentativas do worker
  // (`worker/executor.py::_MAX_TENTATIVAS_EXTRACAO`) e marcou o episódio como
  // falho definitivamente — sem tratar esse status aqui, a linha caía no ramo
  // (3) abaixo (estático, não clicável) e o aviso de falha ficava preso pra
  // sempre, mesmo recarregando a página (o backend já reaproveita `FALHOU` do
  // mesmo jeito que `LIBERADO`, ver `api/servicos/jobs.py::criar_job_site`).
  const permiteRecaptura = episodio?.status === 'liberado' || episodio?.status === 'falhou';
  const liberadoOuDescartado = permiteRecaptura ? episodio : episodioDescartado;
  if (liberadoOuDescartado) {
    // Nota de origem: só o caso "mesmo domínio da fonte ativa, versão
    // diferente" (ex. dublado gravado enquanto a fonte ativa agora pede
    // legendado) — a versão real é o que explica a divergência. O antigo
    // "(via {site})" pra um `episodioDescartado` de OUTRO domínio foi
    // removido a pedido do usuário (ruído visual ao lado do "✓ assistido"
    // quando se troca de fonte). `episodioDescartado.versao === 'desconhecida'`
    // nunca cai aqui na prática — mesmo domínio + 'desconhecida' já faz
    // `pertenceAFonteAtiva` (PaginaDoAnime.jsx) aceitar o episódio como da
    // fonte ativa; mantido por completude (`ROTULO_VERSAO` cobre 'desconhecida').
    // `dominioAtivo == null` (loading/erro/fonte ambígua) suprime a nota
    // pelo mesmo critério conservador de `pertenceAFonteAtiva`.
    let notaOrigem = null;
    if (
      episodioDescartado &&
      dominioAtivo != null &&
      episodioDescartado.site_origem === dominioAtivo &&
      episodioDescartado.versao !== versaoAtiva
    ) {
      notaOrigem = ROTULO_VERSAO[episodioDescartado.versao] ?? episodioDescartado.versao;
    }
    // Trailing: "✓ assistido" (de qualquer uma das duas fontes, só modo
    // lista — modo grade renderiza a versão flutuante sobre a miniatura, ver
    // `conteudo` abaixo), a nota de origem entre parênteses e — só no modo
    // lista, só com número — o verbo "Recapturar". No modo grade o
    // "Capturando…" transitório é overlay (overlayCapturando) e não há verbo
    // em repouso; `naoNumerico` (defensivo, um episódio liberado sempre tem
    // número) também não recapura.
    const mostraAssistidoTrailing = !emGrade && liberadoOuDescartado.assistido_em;
    const mostraAcao = !emGrade && !naoNumerico;
    const trailing =
      mostraAssistidoTrailing || notaOrigem || mostraAcao ? (
        <span className="flex shrink-0 items-start gap-2">
          {mostraAssistidoTrailing && <BadgeAssistido />}
          {notaOrigem && <span className="text-sm font-semibold text-white">({notaOrigem})</span>}
          {mostraAcao && <RotuloDeAcao verbo="Recapturar" capturando={capturando} />}
        </span>
      ) : null;
    const conteudo = (
      <>
        <MiniaturaDoEpisodio thumb={thumb} modo={modo} />
        {emGrade && liberadoOuDescartado.assistido_em && <ScrimAssistido />}
        {overlayCapturando}
        {emGrade && liberadoOuDescartado.assistido_em && <BadgeAssistido flutuante />}
      </>
    );
    const legenda = (
      <FaixaDeConteudo
        modo={modo}
        rotulo={<RotuloEpisodio numero={numero} rotulo={rotulo} titulo={titulo} />}
        trailing={trailing}
        sinopse={<SinopseEpisodio sinopse={sinopse} />}
      />
    );
    if (naoNumerico) {
      return (
        <CartaoDeEpisodio modo={modo} cor="text-ink-muted" legenda={legenda}>
          {conteudo}
        </CartaoDeEpisodio>
      );
    }
    return (
      <CartaoDeEpisodio
        modo={modo}
        cor="text-ink-muted"
        aoClicar={() => aoCapturar(numero)}
        desabilitado={capturando}
        rotuloAcessivel={`Recapturar episódio ${numero}`}
        legenda={legenda}
      >
        {conteudo}
      </CartaoDeEpisodio>
    );
  }

  if (episodio) {
    const statusAtual = job?.status ?? episodio.status;
    const rotuloStatus = ROTULOS_STATUS[statusAtual] ?? statusAtual;
    // Janela de corrida rara (mesma que `jaRecarregadoRef` de
    // PaginaDoAnime.jsx existe pra fechar): o WS já reporta `job.status ===
    // 'pronto'` por um instante ANTES do `episodios.recarregar()` daquele
    // efeito resolver e este episódio migrar pro ramo `pronto` de verdade
    // (topo do arquivo, com <Link> pro player). Sem este guard, esse instante
    // renderizava uma "badge" com o texto "Pronto" (tom 'neutro', sem
    // animação nenhuma — `tomDoStatus('pronto')` não está em nenhum dos dois
    // Sets) que o usuário achou redundante/confusa: o episódio ainda não é
    // clicável nesta linha (seguimos no ramo estático), então "Pronto" aqui
    // parecia um estado real quando é só transitório — pedido do usuário,
    // 2026-09-2x, remover. A notificação de conclusão de verdade já vem pela
    // ilha dinâmica (`statusCapturaIlha`/`capturaProntaIlha`,
    // BarraDeNavegacao.jsx). Sem substituto visual aqui: por baixo de 1
    // render depois o `recarregar()` já troca a linha pro ramo `pronto` real.
    const emTransicaoParaPronto = statusAtual === 'pronto';
    // Ramo não clicável nos dois modos (alvo estático <div>) — comportamento
    // atual mantido. Modo lista: o status fica ao lado do rótulo com
    // `aria-live` pro leitor de tela anunciar cada transição do pipeline sem
    // precisar de foco. Modo grade: esse mesmo status vira overlay central
    // sobre a thumb (spinner nos estados de progresso — sem texto visível,
    // ver OverlayDeStatus —, "⚠" + texto em falha/intervenção, só o rótulo
    // nos terminais neutros) — e a faixa fica só com o rótulo do episódio.
    return (
      <CartaoDeEpisodio
        modo={modo}
        cor="text-ink-muted"
        legenda={
          <FaixaDeConteudo
            modo={modo}
            rotulo={<RotuloEpisodio numero={numero} rotulo={rotulo} titulo={titulo} />}
            trailing={
              emGrade || emTransicaoParaPronto ? null : (
                <span aria-live="polite" className="shrink-0">
                  {rotuloStatus}
                </span>
              )
            }
            sinopse={<SinopseEpisodio sinopse={sinopse} />}
          />
        }
      >
        <MiniaturaDoEpisodio thumb={thumb} modo={modo} />
        {emGrade && !emTransicaoParaPronto && (
          <OverlayDeStatus rotulo={rotuloStatus} tom={tomDoStatus(statusAtual)} />
        )}
      </CartaoDeEpisodio>
    );
  }

  // Ramo "nunca capturado": o card/linha inteiro dispara a captura. `rotulo`
  // divergente do número só quando há colisão real de rótulos remotos
  // (`rotuloDivergente`): nota `(rótulo "X" na fonte)` logo abaixo do rótulo.
  // `naoNumerico` (rótulo não numérico na fonte, ex. "Especial"): o contrato
  // de captura só aceita `numero`, o card não é clicável (alvo estático <div>)
  // e o aviso — que é informação, não ação — aparece nos DOIS modos.
  const conteudoCaptura = (
    <>
      <MiniaturaDoEpisodio thumb={thumb} modo={modo} />
      {overlayCapturando}
    </>
  );
  const legendaCaptura = (
    <FaixaDeConteudo
      modo={modo}
      rotulo={
        rotuloDivergente ? (
          <span>
            <RotuloEpisodio numero={numero} rotulo={rotulo} titulo={titulo} />
            <span className="mt-0.5 block text-xs text-ink-muted">
              (rótulo "{rotulo}" na fonte)
            </span>
          </span>
        ) : (
          <RotuloEpisodio numero={numero} rotulo={rotulo} titulo={titulo} />
        )
      }
      trailing={
        naoNumerico ? (
          <span className="text-xs text-ink-muted">Captura indisponível — rótulo não numérico</span>
        ) : emGrade ? null : (
          <RotuloDeAcao verbo="Capturar" capturando={capturando} />
        )
      }
      sinopse={<SinopseEpisodio sinopse={sinopse} />}
    />
  );
  if (naoNumerico) {
    return (
      <CartaoDeEpisodio modo={modo} cor="text-white font-semibold" legenda={legendaCaptura}>
        {conteudoCaptura}
      </CartaoDeEpisodio>
    );
  }
  return (
    <CartaoDeEpisodio
      modo={modo}
      cor="text-white font-semibold"
      aoClicar={() => aoCapturar(numero)}
      desabilitado={capturando}
      rotuloAcessivel={`Capturar episódio ${numero}`}
      legenda={legendaCaptura}
    >
      {conteudoCaptura}
    </CartaoDeEpisodio>
  );
}

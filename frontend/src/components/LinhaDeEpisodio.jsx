import { useState } from 'react';
import { Link } from 'react-router-dom';
import { SOMBRA_SLIDE_ATIVO } from '../inicio/CarrosselDestaques.jsx';
import { IconePlay } from '../player/Icones.jsx';

// Re-exportado: `src/inicio/` não pode importar de `src/player/` direto
// (fronteira Clean Architecture documentada em paginas/Inicio.jsx, D5 do
// plano) — `inicio/DestaqueGrande.jsx` reusa o MESMO ícone do CTA "Assistir
// agora"/"Continuar assistindo" passando por aqui, não duplicando o SVG.
export { IconePlay };

// Miniatura decorativa do episódio (thumb da fonte). `src` SEMPRE via o proxy
// `GET /api/thumb` — nunca `src={thumb}` direto: o proxy existe pra não vazar
// o IP do usuário pro site pirata e pra contornar hotlink (embute o `Referer`).
// `alt=""` porque o número/título do episódio já está em texto ao lado (img
// puramente decorativa). Some sozinha quando `thumb` é vazio (nada renderiza,
// sem buraco no layout) ou quando o proxy responde 404 (`onError`) — a fonte
// pode não ter a imagem daquele episódio. `falhouEm` guarda a URL que falhou
// e é comparada com `thumb`: se a linha trocar de origem (ex. thumb remota →
// `capa_path` após a captura), a nova URL volta a ser tentada.
export function MiniaturaDoEpisodio({ thumb, modo }) {
  const [falhouEm, setFalhouEm] = useState(null);
  if (!thumb || falhouEm === thumb) return null;
  return (
    <img
      key={thumb}
      src={`/api/thumb?url=${encodeURIComponent(thumb)}`}
      alt=""
      loading="lazy"
      onError={() => setFalhouEm(thumb)}
      // modo grade: a thumb É o card — preenche o retângulo 16/9 em
      // `absolute inset-0`, com o número do episódio e a ação sobre um degradê
      // no rodapé; modo lista: mesma linguagem, a thumb 16/9 encosta na borda
      // esquerda do card (o `overflow-hidden` + `rounded-lg` da raiz recorta os
      // cantos) — sem borda/arredondamento próprios.
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
// A ação/estado do episódio vive só como texto no rodapé (FaixaDeConteudo) ou
// como overlay sobre a thumb (OverlayDeStatus) — nunca num <button>/<Link>
// aninhado DENTRO do card.
// Hover/foco no idioma do card do catálogo (components/AnimeCard.jsx →
// paginas/Galeria.jsx): modo grade cresce no lugar (`scale`, `z-10` pra passar
// por cima dos vizinhos da grade) com a borda neon acendendo; modo lista,
// linha full-width, sem escala — só realce de fundo + a borda neon. A borda
// acesa em `group-focus-visible` é o indicador de foco de teclado (o alvo fica
// `outline-none`, igual ao AnimeCard). `desabilitado` = captura em voo:
// bloqueia o clique.
// `boxShadow` (via `estilo`, derivado do `modo`): grade usa a drop shadow dos
// cards do catálogo (fonte única em inicio/CarrosselDestaques.jsx); lista, com
// os cards a 8px um do outro, usa uma sombra bem mais curta — a do catálogo
// empilhada linha após linha "suja" o fundo entre elas.
export function CartaoDeEpisodio({
  modo,
  cor,
  para,
  estadoDeRota,
  aoClicar,
  desabilitado,
  rotuloAcessivel,
  children,
}) {
  const emGrade = modo === 'grade';
  const estilo = {
    boxShadow: emGrade
      ? SOMBRA_SLIDE_ATIVO
      : 'rgba(0,0,0,0.38) 0 8px 10px -4px, rgba(0,0,0,0.28) 0 2px 4px -3px',
  };
  const classeBase = `relative flex w-full overflow-hidden rounded-lg bg-surface text-left text-sm ${cor}${
    emGrade ? ' aspect-[16/9]' : ''
  }`;

  if (!para && !aoClicar) {
    return (
      <div className={classeBase} style={estilo}>
        {children}
      </div>
    );
  }

  const classe = `group/cartao ${classeBase} cursor-pointer outline-none ${
    emGrade
      ? 'transition-transform duration-300 ease-out hover:z-10 hover:scale-105 focus-visible:z-10 focus-visible:scale-105 motion-reduce:transition-none'
      : 'transition-colors duration-200 hover:bg-surface-hover'
  }`;
  const bordaNeon = (
    <span
      aria-hidden="true"
      className={`pointer-events-none absolute inset-0 rounded-lg border-transparent transition-colors duration-300 ease-out group-hover/cartao:border-neon group-focus-visible/cartao:border-neon motion-reduce:transition-none ${
        emGrade ? 'border-4' : 'border-2'
      }`}
    />
  );
  if (para) {
    return (
      <Link to={para} state={estadoDeRota} className={classe} style={estilo}>
        {children}
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
      {bordaNeon}
    </button>
  );
}

// Rótulos em `core/enums.py::StatusJob`/`StatusEpisodio` (backend) — mesmos
// valores StrEnum, traduzidos aqui pra exibição.
const ROTULOS_STATUS = {
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

function tomDoStatus(status) {
  if (STATUS_EM_PROGRESSO.has(status)) return 'progresso';
  if (STATUS_DE_ALERTA.has(status)) return 'alerta';
  return 'neutro';
}

// Overlay de status centralizado sobre a miniatura 16/9 — SÓ modo grade
// (no modo lista o status segue como texto inline ao lado do rótulo,
// inalterado). Scrim (`bg-black/50`) + `backdrop-blur-sm` dão legibilidade
// ao rótulo sobre qualquer thumb; o componente fica ANTES do rodapé em
// degradê na árvore de cada ramo, então o número/título do episódio no
// rodapé pinta por cima e não é borrado nem esmaecido. `tom`:
//  - 'progresso': spinner (anel de borda parcial girando). É decorativo
//    (`aria-hidden`) e some em `motion-reduce` — a preferência de menos
//    movimento não pode deixar um anel girando pra sempre, e o rótulo já
//    comunica o estado sem ele.
//  - 'alerta': ícone "⚠" estático (sem spinner) em âmbar — mesmo tom do
//    IndicadorDeAtencao, único precedente de "precisa de atenção" no app;
//    não há token de erro/danger no @theme (index.css).
//  - 'neutro': nada além do rótulo, em cor esmaecida (`text-ink-muted`).
// O rótulo carrega o `aria-live="polite"` que no modo lista vive no status
// inline (trailing da FaixaDeConteudo) do ramo `if (episodio)`.
function OverlayDeStatus({ rotulo, tom }) {
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
        className={`text-xs font-semibold uppercase tracking-wide ${corDoRotulo}`}
      >
        {rotulo}
      </span>
    </span>
  );
}

// Pista de "pronto pra assistir" no ramo `pronto` — o mesmo `IconePlay` do
// player (player/Icones.jsx), reaproveitado em vez de redesenhar o triângulo,
// num disco translúcido centralizado sobre a thumb. Mesmo slot central do
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
        className={`flex items-center justify-center rounded-full bg-black/45 text-white ring-1 ring-white/50 backdrop-blur-sm transition duration-200 ease-out group-hover/cartao:bg-black/70 group-hover/cartao:ring-white motion-reduce:transition-none ${
          emGrade ? 'h-14 w-14' : 'h-9 w-9'
        }`}
      >
        <IconePlay
          width={undefined}
          height={undefined}
          className={emGrade ? 'h-6 w-6 translate-x-0.5' : 'h-4 w-4 translate-x-px'}
        />
      </span>
    </span>
  );
}

// Rótulo do episódio — idêntico nos dois modos (grade e lista) e nos quatro
// ramos: "Episódio {numero}", com "— {titulo}" anexado quando o registro traz
// título. `line-clamp-2` sempre: um título longo ocupa no máx. 2 linhas e é
// cortado com reticências, tanto no rodapé em degradê da grade quanto na linha
// da lista. `naoNumerico` (numero == null, ex. "Especial"): o rótulo cru da
// fonte entra no lugar de "Episódio N".
function RotuloEpisodio({ numero, rotulo, titulo }) {
  return (
    <span className="line-clamp-2 text-sm font-semibold text-white">
      {numero == null ? rotulo : `Episódio ${numero}${titulo ? ` — ${titulo}` : ''}`}
    </span>
  );
}

// "Assistido": o episódio foi visto até o fim (`assistido_em`) — distinto da
// pista de "pronto pra assistir" (IndicadorDePlay, centralizada sobre a thumb).
// Pill de fundo neon (mesmo `bg-neon` do accent do app); mesmo estilo nos ramos
// `pronto` e `liberadoOuDescartado`.
function BadgeAssistido() {
  return (
    <span
      className="shrink-0 bg-black/60 px-2.5 py-0.5 text-xs font-semibold uppercase tracking-wide text-white"
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
  return <span aria-hidden="true" className="absolute inset-0 bg-[#0b0b0d]/60" />;
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
// rodapé absoluto sobre a thumb, com degradê pra legibilidade do texto por
// cima da imagem. Lista: coluna ao lado da miniatura (o padding mora aqui, não
// na raiz, pra a thumb encostar na borda esquerda). Primeira linha: `rotulo`
// à esquerda (pode quebrar em 2 linhas) e `trailing` à direita (badge "✓
// assistido", verbo de captura, status inline, nota de origem ou o aviso de
// rótulo não numérico), alinhados pelo topo com `justify-between`. `extra` (a
// barra de progresso do ramo `pronto`) vem abaixo.
export function FaixaDeConteudo({ modo, rotulo, trailing, extra }) {
  return (
    <span
      className={
        modo === 'grade'
          ? 'absolute inset-x-0 bottom-0 flex flex-col gap-1.5 bg-gradient-to-t from-black/95 via-black/60 to-transparent p-3'
          : 'flex min-w-0 flex-1 flex-col justify-center gap-1.5 px-3 py-2.5'
      }
    >
      <span className="flex items-start justify-between gap-2">
        {rotulo}
        {trailing}
      </span>
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
//     OU episódio local existe mas foi descartado da fonte/versão ativas pelo
//     filtro de `PaginaDoAnime.jsx::pertenceAFonteAtiva` (Feature "episódios
//     grudados", `episodioDescartado`): ramo de captura (alvo <button>), mas
//     com badge "✓ assistido" (quando `assistido_em` de qualquer uma das duas
//     fontes) e verbo "Recapturar" em vez de "Capturar" — o backend (D2,
//     `api/servicos/jobs.py::criar_job_site`) reaproveita a linha existente
//     nesses dois casos. No caso `episodioDescartado`, uma nota "(via {site})"
//     ou "(versão real)" indica a origem quando difere da fonte ativa (nunca
//     as duas juntas — site diferente já basta pra explicar e tem prioridade,
//     ver `notaOrigem` abaixo) — sem isso, "✓ assistido" pareceria vir da
//     fonte que o usuário navega agora;
// (3) capturado mas ainda em processamento (ou falhou): status ao vivo,
//     cruzado com `job` do WS quando disponível. Alvo estático <div> (não
//     clicável hoje);
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
// idêntico nos dois modos), "✓ assistido", nota de origem, barra de progresso
// do ramo `pronto` e o aviso de `naoNumerico` seguem nos dois modos.
export default function LinhaDeEpisodio({
  numero,
  rotulo,
  colisao,
  episodio,
  episodioDescartado,
  // URL absoluta da thumbnail do episódio na fonte (ou `null`) — montada em
  // `PaginaDoAnime.jsx` a partir de `EpisodioSaida.capa_path` /
  // `EpisodioRemotoSaida.thumb_url`. Renderizada por `MiniaturaDoEpisodio`
  // (sempre via o proxy `/api/thumb`); os 4 ramos de render abaixo a exibem.
  thumb,
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
  // 16/9 É o card, com número/ação sobre um degradê no rodapé. Muda o
  // enquadramento (className da raiz, posição da miniatura) e, nos ramos de
  // captura, o quanto o card cresce no hover (ver CartaoDeEpisodio) — nunca
  // qual conteúdo cada ramo renderiza.
  modo = 'lista',
  job,
  aoCapturar,
  capturando,
  animeId,
  animeTitulo,
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
        estadoDeRota={{ episodio: { numero, animeId, animeTitulo, titulo: episodio.titulo } }}
      >
        <MiniaturaDoEpisodio thumb={thumb} modo={modo} />
        {emGrade && episodio.assistido_em && <ScrimAssistido />}
        <IndicadorDePlay emGrade={emGrade} temThumb={!!thumb} />
        <FaixaDeConteudo
          modo={modo}
          rotulo={<RotuloEpisodio numero={numero} rotulo={rotulo} titulo={episodio.titulo} />}
          trailing={episodio.assistido_em ? <BadgeAssistido /> : null}
          extra={
            percentualAssistido != null ? (
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
            ) : null
          }
        />
      </CartaoDeEpisodio>
    );
  }

  const liberadoOuDescartado = episodio?.status === 'liberado' ? episodio : episodioDescartado;
  if (liberadoOuDescartado) {
    // Nota de origem: só faz sentido quando o "✓ assistido"/"Recapturar"
    // vem de `episodioDescartado` (registro de OUTRA fonte/versão que não a
    // ativa, `PaginaDoAnime.jsx::pertenceAFonteAtiva`) — nunca quando é o
    // próprio `episodio` da fonte ativa em estado terminal `liberado`, caso
    // em que `episodioDescartado` é sempre `null` (PaginaDoAnime.jsx só
    // popula `episodioDescartado` quando `episodio` é nulo). Sem isto,
    // "Episódio 18 ✓ assistido" numa fonte cujo catálogo remoto só vai até
    // 16 fica sem pista de que aquele registro é de outra fonte.
    // `dominioAtivo == null` (loading/erro/fonte ambígua) suprime a nota
    // pelo mesmo critério conservador de `pertenceAFonteAtiva`.
    let notaOrigem = null;
    if (episodioDescartado && dominioAtivo != null) {
      // 'local' (backend/core/enums.py::SITE_LOCAL, mesmo literal usado sem
      // import em PaginaDoAnime.jsx::SITE_LOCAL) não conta como "outra
      // fonte" com sentido pro usuário — captura manual não tem "site" pra
      // nomear.
      if (
        episodioDescartado.site_origem !== dominioAtivo &&
        episodioDescartado.site_origem !== 'local'
      ) {
        notaOrigem = `via ${episodioDescartado.site_origem}`;
      } else if (
        episodioDescartado.site_origem === dominioAtivo &&
        episodioDescartado.versao !== versaoAtiva
      ) {
        // Mesmo domínio da fonte ativa, versão diferente (ex. dublado
        // gravado enquanto a fonte ativa agora pede legendado) — mostrar o
        // domínio de novo não ajudaria (seria idêntico ao ativo), a versão
        // real é o que explica a divergência. `episodioDescartado.versao ===
        // 'desconhecida'` nunca cai aqui na prática — mesmo domínio +
        // 'desconhecida' já faz `pertenceAFonteAtiva` (PaginaDoAnime.jsx)
        // aceitar o episódio como pertencente à fonte ativa, então ele nunca
        // vira `episodioDescartado` nesse caso; mantido mesmo assim por
        // completude (`ROTULO_VERSAO` cobre 'desconhecida').
        notaOrigem = ROTULO_VERSAO[episodioDescartado.versao] ?? episodioDescartado.versao;
      }
    }
    // Trailing: "✓ assistido" (de qualquer uma das duas fontes), a nota de
    // origem entre parênteses e — só no modo lista, só com número — o verbo
    // "Recapturar". No modo grade o "Capturando…" transitório é overlay
    // (overlayCapturando) e não há verbo em repouso; `naoNumerico` (defensivo,
    // um episódio liberado sempre tem número) também não recapura.
    const mostraAcao = !emGrade && !naoNumerico;
    const trailing =
      liberadoOuDescartado.assistido_em || notaOrigem || mostraAcao ? (
        <span className="flex shrink-0 items-start gap-2">
          {liberadoOuDescartado.assistido_em && <BadgeAssistido />}
          {notaOrigem && <span className="text-sm font-semibold text-white">({notaOrigem})</span>}
          {mostraAcao && <RotuloDeAcao verbo="Recapturar" capturando={capturando} />}
        </span>
      ) : null;
    const conteudo = (
      <>
        <MiniaturaDoEpisodio thumb={thumb} modo={modo} />
        {emGrade && liberadoOuDescartado.assistido_em && <ScrimAssistido />}
        {overlayCapturando}
        <FaixaDeConteudo
          modo={modo}
          rotulo={<RotuloEpisodio numero={numero} rotulo={rotulo} />}
          trailing={trailing}
        />
      </>
    );
    if (naoNumerico) {
      return (
        <CartaoDeEpisodio modo={modo} cor="text-ink-muted">
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
      >
        {conteudo}
      </CartaoDeEpisodio>
    );
  }

  if (episodio) {
    const statusAtual = job?.status ?? episodio.status;
    const rotuloStatus = ROTULOS_STATUS[statusAtual] ?? statusAtual;
    // Ramo não clicável nos dois modos (alvo estático <div>) — comportamento
    // atual mantido. Modo lista: o status fica ao lado do rótulo com
    // `aria-live` pro leitor de tela anunciar cada transição do pipeline sem
    // precisar de foco. Modo grade: esse mesmo status vira overlay central
    // sobre a thumb (o `aria-live` viaja junto, dentro do OverlayDeStatus) —
    // spinner nos estados de progresso, "⚠" em falha/intervenção, só o rótulo
    // nos terminais neutros — e a faixa fica só com o rótulo do episódio.
    return (
      <CartaoDeEpisodio modo={modo} cor="text-ink-muted">
        <MiniaturaDoEpisodio thumb={thumb} modo={modo} />
        {emGrade && <OverlayDeStatus rotulo={rotuloStatus} tom={tomDoStatus(statusAtual)} />}
        <FaixaDeConteudo
          modo={modo}
          rotulo={<RotuloEpisodio numero={numero} rotulo={rotulo} titulo={episodio.titulo} />}
          trailing={
            emGrade ? null : (
              <span aria-live="polite" className="shrink-0">
                {rotuloStatus}
              </span>
            )
          }
        />
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
      <FaixaDeConteudo
        modo={modo}
        rotulo={
          rotuloDivergente ? (
            <span>
              <RotuloEpisodio numero={numero} rotulo={rotulo} />
              <span className="mt-0.5 block text-xs text-ink-muted">
                (rótulo "{rotulo}" na fonte)
              </span>
            </span>
          ) : (
            <RotuloEpisodio numero={numero} rotulo={rotulo} />
          )
        }
        trailing={
          naoNumerico ? (
            <span className="text-xs text-ink-muted">Captura indisponível — rótulo não numérico</span>
          ) : emGrade ? null : (
            <RotuloDeAcao verbo="Capturar" capturando={capturando} />
          )
        }
      />
    </>
  );
  if (naoNumerico) {
    return (
      <CartaoDeEpisodio modo={modo} cor="text-white font-semibold">
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
    >
      {conteudoCaptura}
    </CartaoDeEpisodio>
  );
}

import { useState } from 'react';
import { Link } from 'react-router-dom';
import { SOMBRA_SLIDE_ATIVO } from '../inicio/CarrosselDestaques.jsx';

// Miniatura decorativa do episódio (thumb da fonte). `src` SEMPRE via o proxy
// `GET /api/thumb` — nunca `src={thumb}` direto: o proxy existe pra não vazar
// o IP do usuário pro site pirata e pra contornar hotlink (embute o `Referer`).
// `alt=""` porque o número/título do episódio já está em texto ao lado (img
// puramente decorativa). Some sozinha quando `thumb` é vazio (nada renderiza,
// sem buraco no layout) ou quando o proxy responde 404 (`onError`) — a fonte
// pode não ter a imagem daquele episódio. `falhouEm` guarda a URL que falhou
// e é comparada com `thumb`: se a linha trocar de origem (ex. thumb remota →
// `capa_path` após a captura), a nova URL volta a ser tentada.
function MiniaturaDoEpisodio({ thumb, modo }) {
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
// único: o player (estado "pronto" → vira <Link>, passe `para`/`estadoDeRota`)
// ou a captura (demais estados acionáveis → vira <button>, passe `aoClicar`/
// `desabilitado`). Substitui os <button>/<Link> internos que antes ficavam
// DENTRO do card — a ação vira só texto no rodapé (ver os ramos).
// Hover/foco no idioma do card do catálogo (components/AnimeCard.jsx →
// paginas/Galeria.jsx): modo grade cresce no lugar (`scale`, `z-10` pra passar
// por cima dos vizinhos da grade) com a borda neon acendendo; modo lista,
// linha full-width, sem escala — só realce de fundo + a borda neon. A borda
// acesa em `group-focus-visible` é o indicador de foco de teclado (o alvo fica
// `outline-none`, igual ao AnimeCard). `desabilitado` = captura em voo:
// bloqueia o clique.
function CartaoDeEpisodio({
  modo,
  cor,
  estilo,
  para,
  estadoDeRota,
  aoClicar,
  desabilitado,
  rotuloAcessivel,
  children,
}) {
  const emGrade = modo === 'grade';
  const classe = `group/cartao relative flex w-full cursor-pointer overflow-hidden rounded-lg bg-surface text-left text-sm outline-none ${cor} ${
    emGrade
      ? 'aspect-[16/9] transition-transform duration-300 ease-out hover:z-10 hover:scale-105 focus-visible:z-10 focus-visible:scale-105 motion-reduce:transition-none'
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

// Uma posição de episódio na grade da página do anime — quatro estados:
// (1) já capturado e pronto: link pro player, com barra de progresso quando
// `episodio.progresso_s` (Feature "continuar assistindo") já tem valor;
// (2) `episodio.status === 'liberado'` (Feature "liberar arquivo ao
// terminar") OU episódio local existe mas foi descartado da fonte/versão
// ativas pelo filtro de `PaginaDoAnime.jsx::pertenceAFonteAtiva` (Feature
// "episódios grudados", `episodioDescartado`): ramo de captura, mas com
// badge "✓ assistido" (quando `assistido_em` de qualquer uma das duas fontes)
// e rótulo "Recapturar" em vez de "Capturar" — o backend (D2,
// `api/servicos/jobs.py::criar_job_site`) reaproveita a linha existente
// nesses dois casos em vez de criar outra; no caso `episodioDescartado`, uma
// nota "(via {site})" ou "(versão real)" indica a origem quando difere da
// fonte ativa (nunca as duas juntas — site diferente já basta pra explicar a
// divergência e tem prioridade, ver `notaOrigem` abaixo) — sem isso, "✓
// assistido" pareceria vir da fonte que o usuário está navegando agora;
// (3) capturado mas ainda em
// processamento (ou falhou): status ao vivo, cruzado com `job` do WS quando
// disponível; (4) nunca capturado: o card/linha inteiro dispara a captura
// (CartaoDeEpisodio), com "Capturar" só como texto — não clicável quando
// `numero` é `null` (rótulo não numérico na fonte, ex. "Especial": aparece na
// lista mas capturá-lo está fora de escopo por ora).
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

  // className da raiz de cada um dos 4 ramos de render. `cor` = só as classes
  // de texto/estado que variam por ramo (o fundo `bg-surface` e a ausência de
  // borda são comuns aos dois modos — lista e grade compartilham a linguagem
  // de card: sem borda serrilhada, `bg-surface`, sombra). No modo grade a raiz
  // é a própria thumb 16/9 (`overflow-hidden` recorta a imagem `absolute
  // inset-0` + o rodapé sobreposto); no modo lista, a thumb encosta na borda
  // esquerda e o conteúdo vem ao lado.
  const classeRaiz = (cor) =>
    emGrade
      ? `relative flex aspect-[16/9] overflow-hidden rounded-lg bg-surface text-sm ${cor}`
      : `flex overflow-hidden rounded-lg bg-surface text-sm ${cor}`;

  // Modo grade: a mesma drop shadow dos cards do catálogo (fonte única em
  // inicio/CarrosselDestaques.jsx). Modo lista: os cards ficam a 8px um do
  // outro, então uma sombra bem mais curta e suave — a do catálogo, empilhada
  // linha após linha, "suja" o fundo entre elas.
  const estiloCartao = {
    boxShadow: emGrade
      ? SOMBRA_SLIDE_ATIVO
      : 'rgba(0,0,0,0.38) 0 8px 10px -4px, rgba(0,0,0,0.28) 0 2px 4px -3px',
  };

  // Rodapé sobreposto à thumb no modo grade: degradê pra legibilidade do
  // número/ação por cima da imagem. `items-end` mantém o botão alinhado à base
  // enquanto um rótulo longo quebra em linhas acima.
  const CLASSE_RODAPE_GRADE =
    'absolute inset-x-0 bottom-0 flex items-end justify-between gap-2 bg-gradient-to-t from-black/95 via-black/60 to-transparent p-3';

  // Bloco de conteúdo (rótulo + ação/status) ao lado da miniatura no modo
  // lista — o padding mora aqui, não na raiz, pra a thumb encostar na borda.
  const CLASSE_CONTEUDO_LISTA =
    'flex min-w-0 flex-1 items-center justify-between gap-3 px-3 py-2.5';

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
    // Rótulo, badge "assistido" e barra de progresso: mesmo conteúdo nos dois
    // modos, só o enquadramento muda (linha ao lado da miniatura no modo lista,
    // rodapé sobre a thumb no modo grade).
    const tituloEpisodio = (
      <span className={'font-semibold' + (emGrade ? ' line-clamp-2' : '')}>
        Episódio {numero}
        {episodio.titulo ? ` — ${episodio.titulo}` : ''}
      </span>
    );
    const badgeAssistido = episodio.assistido_em ? (
      <span className="shrink-0 text-xs text-ink-muted" aria-label="já assistido">
        ✓ assistido
      </span>
    ) : null;
    const barraProgresso =
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
          <span className="shrink-0 text-xs text-ink-muted font-semibold">faltam {minutosRestantes} min</span>
        </span>
      ) : null;
    return (
      <CartaoDeEpisodio
        modo={modo}
        cor="text-white"
        estilo={estiloCartao}
        para={`/assistir/${episodio.id}`}
        estadoDeRota={{ episodio: { numero, animeId, animeTitulo, titulo: episodio.titulo } }}
      >
        <MiniaturaDoEpisodio thumb={thumb} modo={modo} />
        {emGrade ? (
          <span className="absolute inset-x-0 bottom-0 flex flex-col gap-1.5 bg-gradient-to-t from-black/95 via-black/60 to-transparent p-3">
            <span className="flex items-start justify-between gap-2">
              {tituloEpisodio}
              {badgeAssistido}
            </span>
            {barraProgresso}
          </span>
        ) : (
          <span className="flex min-w-0 flex-1 flex-col justify-center gap-1.5 px-3 py-2.5">
            <span className="flex items-center justify-between gap-2">
              {tituloEpisodio}
              {badgeAssistido}
            </span>
            {barraProgresso}
          </span>
        )}
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
      if (episodioDescartado.site_origem !== dominioAtivo && episodioDescartado.site_origem !== 'local') {
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
    // Label + badges: mesmo conteúdo nos dois modos, só o enquadramento muda —
    // linha ao lado da miniatura no modo lista, rodapé sobre a thumb no modo
    // grade.
    const rotuloComNotas = (
      <span>
        {naoNumerico ? rotulo : <span className="text-sm text-white font-semibold">Episódio {numero}</span>}
        {liberadoOuDescartado.assistido_em && (
          <span className="ml-3 text-sm text-white font-semibold" aria-label="já assistido">
            ✓ assistido
          </span>
        )}
        {notaOrigem && <span className="ml-2 text-sm text-white font-semibold">({notaOrigem})</span>}
      </span>
    );
    // "Recapturar" é só TEXTO — o card/linha inteiro (CartaoDeEpisodio) é o alvo
    // de clique. `naoNumerico` (defensivo; um episódio liberado/assistido
    // sempre tem número) não tem o que recapturar: card não clicável, sem a
    // ação.
    const conteudoLiberado = (
      <>
        <MiniaturaDoEpisodio thumb={thumb} modo={modo} />
        <div className={emGrade ? CLASSE_RODAPE_GRADE : CLASSE_CONTEUDO_LISTA}>
          {rotuloComNotas}
          {!naoNumerico && (
            <span className="shrink-0 text-xs font-semibold uppercase tracking-wide text-neon">
              {capturando ? 'Capturando…' : 'Recapturar'}
            </span>
          )}
        </div>
      </>
    );
    if (naoNumerico) {
      return (
        <div className={classeRaiz('text-ink-muted')} style={estiloCartao}>
          {conteudoLiberado}
        </div>
      );
    }
    return (
      <CartaoDeEpisodio
        modo={modo}
        cor="text-ink-muted"
        estilo={estiloCartao}
        aoClicar={() => aoCapturar(numero)}
        desabilitado={capturando}
        rotuloAcessivel={`Recapturar episódio ${numero}`}
      >
        {conteudoLiberado}
      </CartaoDeEpisodio>
    );
  }

  if (episodio) {
    const statusAtual = job?.status ?? episodio.status;
    const rotuloStatus = ROTULOS_STATUS[statusAtual] ?? statusAtual;
    const rotuloEpisodio = <span>Episódio {numero}</span>;
    const statusAoVivo = (
      <span aria-live="polite" className="shrink-0">
        {rotuloStatus}
      </span>
    );
    return (
      <div className={classeRaiz('text-ink-muted')} style={estiloCartao}>
        <MiniaturaDoEpisodio thumb={thumb} modo={modo} />
        <div className={emGrade ? CLASSE_RODAPE_GRADE : CLASSE_CONTEUDO_LISTA}>
          {rotuloEpisodio}
          {statusAoVivo}
        </div>
      </div>
    );
  }

  const rotuloComDivergencia = (
    <span>
      {naoNumerico ? rotulo : `Episódio ${numero}`}
      {rotuloDivergente && (
        <span className="ml-2 text-xs text-ink-muted">(rótulo "{rotulo}" na fonte)</span>
      )}
    </span>
  );
  // "Capturar" é só TEXTO — o card/linha inteiro (CartaoDeEpisodio) é o alvo de
  // clique. `naoNumerico` (rótulo não numérico na fonte, ex. "Especial"): o
  // contrato de captura só aceita `numero`, então o card não é clicável e o
  // texto vira o aviso.
  const conteudoCaptura = (
    <>
      <MiniaturaDoEpisodio thumb={thumb} modo={modo} />
      <div className={emGrade ? CLASSE_RODAPE_GRADE : CLASSE_CONTEUDO_LISTA}>
        {rotuloComDivergencia}
        {naoNumerico ? (
          <span className="text-xs text-ink-muted">Captura indisponível — rótulo não numérico</span>
        ) : (
          <span className="shrink-0 text-xs font-semibold uppercase tracking-wide text-neon">
            {capturando ? 'Capturando…' : 'Capturar'}
          </span>
        )}
      </div>
    </>
  );
  if (naoNumerico) {
    return (
      <div className={classeRaiz(' text-white font-semibold')} style={estiloCartao}>
        {conteudoCaptura}
      </div>
    );
  }
  return (
    <CartaoDeEpisodio
      modo={modo}
      cor="text-white font-semibold"
      estilo={estiloCartao}
      aoClicar={() => aoCapturar(numero)}
      desabilitado={capturando}
      rotuloAcessivel={`Capturar episódio ${numero}`}
    >
      {conteudoCaptura}
    </CartaoDeEpisodio>
  );
}

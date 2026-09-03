import { useState } from 'react';
import { Link } from 'react-router-dom';

// Miniatura decorativa do episódio (thumb da fonte). `src` SEMPRE via o proxy
// `GET /api/thumb` — nunca `src={thumb}` direto: o proxy existe pra não vazar
// o IP do usuário pro site pirata e pra contornar hotlink (embute o `Referer`).
// `alt=""` porque o número/título do episódio já está em texto ao lado (img
// puramente decorativa). Some sozinha quando `thumb` é vazio (nada renderiza,
// sem buraco no layout) ou quando o proxy responde 404 (`onError`) — a fonte
// pode não ter a imagem daquele episódio. `falhouEm` guarda a URL que falhou
// e é comparada com `thumb`: se a linha trocar de origem (ex. thumb remota →
// `capa_path` após a captura), a nova URL volta a ser tentada.
function MiniaturaDoEpisodio({ thumb }) {
  const [falhouEm, setFalhouEm] = useState(null);
  if (!thumb || falhouEm === thumb) return null;
  return (
    <img
      key={thumb}
      src={`/api/thumb?url=${encodeURIComponent(thumb)}`}
      alt=""
      loading="lazy"
      onError={() => setFalhouEm(thumb)}
      className="aspect-[16/9] w-24 shrink-0 rounded-md border border-border-chrome object-cover"
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
// disponível; (4) nunca capturado: botão que dispara a captura —
// desabilitado quando `numero` é `null` (rótulo não numérico na fonte, ex.
// "Especial": aparece na lista mas capturá-lo está fora de escopo por ora).
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
  job,
  aoCapturar,
  capturando,
  animeId,
  animeTitulo,
}) {
  const naoNumerico = numero == null;
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
      <Link
        to={`/assistir/${episodio.id}`}
        state={{ episodio: { numero, animeId, animeTitulo, titulo: episodio.titulo } }}
        className="flex items-center gap-3 rounded-lg border border-neon-soft bg-surface px-4 py-2 text-sm text-white outline-none transition-colors hover:border-neon hover:bg-surface-hover focus-visible:border-neon focus-visible:ring-2 focus-visible:ring-neon"
      >
        <MiniaturaDoEpisodio thumb={thumb} />
        <span className="flex min-w-0 flex-1 flex-col gap-1.5">
          <span className="flex items-center justify-between">
            <span>
              Episódio {numero}
              {episodio.titulo ? ` — ${episodio.titulo}` : ''}
            </span>
            {episodio.assistido_em && (
              <span className="text-xs text-ink-muted" aria-label="já assistido">
                ✓ assistido
              </span>
            )}
          </span>
          {percentualAssistido != null && (
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
              <span className="text-xs text-ink-muted">faltam {minutosRestantes} min</span>
            </span>
          )}
        </span>
      </Link>
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
    return (
      <div className="flex items-center justify-between gap-3 rounded-lg border border-dashed border-border-chrome px-4 py-2 text-sm text-ink-muted">
        <span className="flex min-w-0 items-center gap-3">
          <MiniaturaDoEpisodio thumb={thumb} />
          <span>
            {naoNumerico ? rotulo : `Episódio ${numero}`}
            {liberadoOuDescartado.assistido_em && (
              <span className="ml-2 text-xs text-ink-muted" aria-label="já assistido">
                ✓ assistido
              </span>
            )}
            {notaOrigem && <span className="ml-2 text-xs text-ink-muted">({notaOrigem})</span>}
          </span>
        </span>
        <button
          type="button"
          onClick={() => {
            if (naoNumerico) return;
            aoCapturar(numero);
          }}
          disabled={capturando}
          aria-disabled={capturando || naoNumerico}
          className={`rounded border border-neon-soft px-3 py-1 text-xs font-semibold uppercase tracking-wide text-neon outline-none transition-colors hover:border-neon focus-visible:ring-2 focus-visible:ring-neon disabled:cursor-not-allowed disabled:opacity-50${
            naoNumerico ? ' cursor-not-allowed opacity-50' : ''
          }`}
        >
          {capturando ? 'Capturando…' : 'Recapturar'}
        </button>
      </div>
    );
  }

  if (episodio) {
    const statusAtual = job?.status ?? episodio.status;
    const rotuloStatus = ROTULOS_STATUS[statusAtual] ?? statusAtual;
    return (
      <div className="flex items-center justify-between rounded-lg border border-border-chrome bg-surface px-4 py-2 text-sm text-ink-muted">
        <span className="flex min-w-0 items-center gap-3">
          <MiniaturaDoEpisodio thumb={thumb} />
          <span>Episódio {numero}</span>
        </span>
        <span aria-live="polite">{rotuloStatus}</span>
      </div>
    );
  }

  return (
    <div className="flex items-center justify-between gap-3 rounded-lg border border-dashed border-border-chrome px-4 py-2 text-sm text-ink-muted">
      <span className="flex min-w-0 items-center gap-3">
        <MiniaturaDoEpisodio thumb={thumb} />
        <span>
          {naoNumerico ? rotulo : `Episódio ${numero}`}
          {rotuloDivergente && (
            <span className="ml-2 text-xs text-ink-muted">(rótulo "{rotulo}" na fonte)</span>
          )}
        </span>
      </span>
      <div className="flex items-center gap-2">
        {naoNumerico && (
          <span className="text-xs text-ink-muted">
            Captura indisponível — rótulo não numérico
          </span>
        )}
        <button
          type="button"
          // Fica focável mesmo quando `naoNumerico` (não usa `disabled`
          // nativo pra esse caso) — `disabled` tira o elemento da ordem de
          // tabulação, e um usuário de teclado nunca chegaria a ler o texto
          // explicativo acima. `aria-disabled` + bloquear o clique aqui
          // dentro preserva o foco/leitura por leitor de tela.
          onClick={() => {
            if (naoNumerico) return;
            aoCapturar(numero);
          }}
          disabled={capturando}
          aria-disabled={capturando || naoNumerico}
          className={`rounded border border-neon-soft px-3 py-1 text-xs font-semibold uppercase tracking-wide text-neon outline-none transition-colors hover:border-neon focus-visible:ring-2 focus-visible:ring-neon disabled:cursor-not-allowed disabled:opacity-50${
            naoNumerico ? ' cursor-not-allowed opacity-50' : ''
          }`}
        >
          {capturando ? 'Capturando…' : 'Capturar'}
        </button>
      </div>
    </div>
  );
}

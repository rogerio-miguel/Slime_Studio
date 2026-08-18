import { Link } from 'react-router-dom';

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

// Uma posição de episódio na grade da página do anime — três estados:
// (1) já capturado e pronto: link pro player; (2) capturado mas ainda em
// processamento (ou falhou): status ao vivo, cruzado com `job` do WS quando
// disponível; (3) não capturado: botão que dispara a captura — desabilitado
// quando `numero` é `null` (rótulo não numérico na fonte, ex. "Especial":
// aparece na lista mas capturá-lo está fora de escopo por ora).
export default function LinhaDeEpisodio({
  numero,
  rotulo,
  colisao,
  episodio,
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
    return (
      <Link
        to={`/assistir/${episodio.id}`}
        state={{ episodio: { numero, animeId, animeTitulo, titulo: episodio.titulo } }}
        className="flex items-center justify-between rounded-lg border border-neon-soft bg-surface px-4 py-2 text-sm text-white outline-none transition-colors hover:border-neon hover:bg-surface-hover focus-visible:border-neon focus-visible:ring-2 focus-visible:ring-neon"
      >
        <span>
          Episódio {numero}
          {episodio.titulo ? ` — ${episodio.titulo}` : ''}
        </span>
        {episodio.assistido_em && (
          <span className="text-xs text-ink-muted" aria-label="já assistido">
            ✓ assistido
          </span>
        )}
      </Link>
    );
  }

  if (episodio) {
    const statusAtual = job?.status ?? episodio.status;
    const rotuloStatus = ROTULOS_STATUS[statusAtual] ?? statusAtual;
    return (
      <div className="flex items-center justify-between rounded-lg border border-border-chrome bg-surface px-4 py-2 text-sm text-ink-muted">
        <span>Episódio {numero}</span>
        <span aria-live="polite">{rotuloStatus}</span>
      </div>
    );
  }

  return (
    <div className="flex items-center justify-between gap-3 rounded-lg border border-dashed border-border-chrome px-4 py-2 text-sm text-ink-muted">
      <span>
        {naoNumerico ? rotulo : `Episódio ${numero}`}
        {rotuloDivergente && (
          <span className="ml-2 text-xs text-ink-muted">(rótulo "{rotulo}" na fonte)</span>
        )}
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

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
// disponível; (3) não capturado: botão que dispara a captura.
export default function LinhaDeEpisodio({
  numero,
  episodio,
  job,
  aoCapturar,
  capturando,
  animeId,
  animeTitulo,
}) {
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
    const rotulo = ROTULOS_STATUS[statusAtual] ?? statusAtual;
    return (
      <div className="flex items-center justify-between rounded-lg border border-border-chrome bg-surface px-4 py-2 text-sm text-ink-muted">
        <span>Episódio {numero}</span>
        <span aria-live="polite">{rotulo}</span>
      </div>
    );
  }

  return (
    <div className="flex items-center justify-between rounded-lg border border-dashed border-border-chrome px-4 py-2 text-sm text-ink-muted">
      <span>Episódio {numero}</span>
      <button
        type="button"
        onClick={() => aoCapturar(numero)}
        disabled={capturando}
        className="rounded border border-neon-soft px-3 py-1 text-xs font-semibold uppercase tracking-wide text-neon outline-none transition-colors hover:border-neon disabled:cursor-not-allowed disabled:opacity-50 focus-visible:ring-2 focus-visible:ring-neon"
      >
        {capturando ? 'Capturando…' : 'Capturar'}
      </button>
    </div>
  );
}

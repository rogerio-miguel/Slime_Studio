import { useEffect, useRef, useState } from 'react';

const _DURACAO_MS = 3000;
const _ROTULO_POR_STATUS = {
  pronto: { texto: 'concluído', tom: 'sucesso' },
  falhou: { texto: 'falhou', tom: 'erro' },
  falhou_extracao: { texto: 'falhou na extração', tom: 'erro' },
  aguardando_intervencao: { texto: 'precisa de atenção', tom: 'erro' },
};

let proximoId = 0;

// Toast efêmero em transição de status (pronto/falhou/…) vindo do WS —
// diffing contra o snapshot anterior via ref, não um segundo Map de
// controle: `jobsPorEpisodio` já é a fonte de verdade
// (App.jsx::Shell -> useEventosDeJobs.js). Primeira mensagem recebida
// (snapshot inicial de cada montagem — login ou reconexão após logout) só
// semeia a referência, sem gerar toast: senão todo job já `pronto` na hora
// de abrir a página disparava uma rajada de toasts "velhos".
export default function Toasts({ jobsPorEpisodio }) {
  const [toasts, setToasts] = useState([]);
  const anteriorRef = useRef(new Map());
  const primeiraMensagemRef = useRef(true);
  const timeoutsRef = useRef(new Set());

  useEffect(() => {
    if (primeiraMensagemRef.current) {
      primeiraMensagemRef.current = false;
      anteriorRef.current = jobsPorEpisodio;
      return;
    }

    const anterior = anteriorRef.current;
    const novos = [];
    for (const [episodioId, job] of jobsPorEpisodio) {
      const rotulo = _ROTULO_POR_STATUS[job.status];
      if (rotulo && anterior.get(episodioId)?.status !== job.status) {
        novos.push({
          id: `${episodioId}-${proximoId++}`,
          tom: rotulo.tom,
          texto: `${job.anime_titulo} — episódio ${job.episodio_numero}: ${rotulo.texto}`,
        });
      }
    }
    anteriorRef.current = jobsPorEpisodio;

    if (novos.length === 0) return;
    setToasts((atual) => [...atual, ...novos]);
    novos.forEach((toast) => {
      const timeoutId = setTimeout(() => {
        timeoutsRef.current.delete(timeoutId);
        setToasts((atual) => atual.filter((t) => t.id !== toast.id));
      }, _DURACAO_MS);
      timeoutsRef.current.add(timeoutId);
    });
  }, [jobsPorEpisodio]);

  // Cleanup só no desmonte (ex. sessão expira com toast ainda visível):
  // cancela qualquer setTimeout pendente pra nunca chamar `setToasts` fora
  // do ciclo de vida do componente. Efeito à parte, com deps vazias, pra não
  // cancelar timeouts saudáveis a cada nova mensagem do WS.
  useEffect(() => {
    const timeouts = timeoutsRef.current;
    return () => {
      timeouts.forEach(clearTimeout);
      timeouts.clear();
    };
  }, []);

  if (toasts.length === 0) return null;

  return (
    <div aria-live="polite" className="fixed bottom-4 right-4 z-50 flex flex-col gap-2">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          role="status"
          className={`rounded-lg border px-4 py-2 text-sm shadow-lg ${
            toast.tom === 'erro'
              ? 'border-red-500/40 bg-red-950/90 text-red-200'
              : 'border-neon-soft bg-surface text-white'
          }`}
        >
          {toast.texto}
        </div>
      ))}
    </div>
  );
}

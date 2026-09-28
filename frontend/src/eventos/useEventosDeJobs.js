import { useEffect, useRef, useState } from 'react';

const _BACKOFF_INICIAL_MS = 1000;
const _BACKOFF_MAXIMO_MS = 30000;

function urlWebSocket() {
  const protocolo = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${protocolo}//${window.location.host}/ws/admin`;
}

// Conexão única a `/ws/admin` no nível do app (chamado uma vez em
// App.jsx::Shell), sempre ativa — sem gate de autenticação (D5 do plano de
// remoção). Constrói `Map(episodio_id -> job)` a partir do snapshot inicial +
// updates subsequentes, pra cruzar com a grade de episódios de
// PaginaDoAnime.jsx.
//
// Shape do job aqui != `JobSaida` do REST (backend/api/eventos.py:31-44):
// tem `episodio_id`/`anime_id`/`anime_titulo`/`episodio_numero`, não tem
// `duracao_esperada_s`/`iniciado_em`.
//
// Qualquer close (1013 fila estourada, queda de rede) -> reconecta com
// backoff exponencial simples.
//
// `snapshotId` (contador, começa em 0): incrementa a cada mensagem tipo
// "snapshot" (conexão inicial OU qualquer reconexão) — nunca em
// "job_atualizado". Existe só pra quem consome `jobsPorEpisodio` e precisa
// DIFERENCIAR "acabei de receber o estado inteiro de novo" de "um job mudou
// ao vivo" (`hooks/useStatusDeCapturaIlha.js`): sem isso, o consumidor não
// tem como saber se um job com status `pronto`/alerta que já aparece no
// Map é uma TRANSIÇÃO real (deveria notificar) ou só o estado que já existia
// antes da conexão (não deveria — bug real medido: o Map começa vazio
// `useState(() => new Map())`, então o primeiro snapshot de verdade parece
// uma transição gigante de "nada" pra "6 jobs", disparando notificação
// falsa assim que a página carrega).
export function useEventosDeJobs() {
  const [jobsPorEpisodio, setJobsPorEpisodio] = useState(() => new Map());
  const [snapshotId, setSnapshotId] = useState(0);
  const tentativaRef = useRef(0);

  useEffect(() => {
    let socket;
    let timeoutReconexao;
    let cancelado = false;

    function conectar() {
      socket = new WebSocket(urlWebSocket());

      socket.onopen = () => {
        tentativaRef.current = 0;
      };

      socket.onmessage = (evento) => {
        try {
          const mensagem = JSON.parse(evento.data);
          if (mensagem.tipo === 'snapshot') {
            setJobsPorEpisodio(new Map(mensagem.jobs.map((job) => [job.episodio_id, job])));
            setSnapshotId((id) => id + 1);
          } else if (mensagem.tipo === 'job_atualizado') {
            setJobsPorEpisodio((atual) => {
              const proximo = new Map(atual);
              proximo.set(mensagem.job.episodio_id, mensagem.job);
              return proximo;
            });
          }
        } catch (erro) {
          console.error('mensagem inválida de /ws/admin', erro);
        }
      };

      socket.onclose = () => {
        if (cancelado) return;
        const atraso = Math.min(
          _BACKOFF_INICIAL_MS * 2 ** tentativaRef.current,
          _BACKOFF_MAXIMO_MS
        );
        tentativaRef.current += 1;
        timeoutReconexao = setTimeout(conectar, atraso);
      };

      socket.onerror = () => {
        socket.close();
      };
    }

    conectar();

    return () => {
      cancelado = true;
      clearTimeout(timeoutReconexao);
      socket?.close();
    };
  }, []);

  return { jobsPorEpisodio, snapshotId };
}

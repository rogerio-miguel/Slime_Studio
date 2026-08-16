import { useEffect, useRef, useState } from 'react';
import { notificarSessaoExpirada } from '../api/cliente.js';

const _BACKOFF_INICIAL_MS = 1000;
const _BACKOFF_MAXIMO_MS = 30000;

function urlWebSocket() {
  const protocolo = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${protocolo}//${window.location.host}/ws/admin`;
}

// Conexão única a `/ws/admin` no nível do app (chamado uma vez em
// App.jsx::Shell) — viva só enquanto `autenticado`. Constrói
// `Map(episodio_id -> job)` a partir do snapshot inicial + updates
// subsequentes, pra cruzar com a grade de episódios de PaginaDoAnime.jsx.
//
// Shape do job aqui != `JobSaida` do REST (backend/api/eventos.py:31-44):
// tem `episodio_id`/`anime_titulo`/`episodio_numero`, não tem
// `duracao_esperada_s`/`iniciado_em`.
//
// Fecha 1008 (não autenticado) -> não reconecta, aciona o mesmo fluxo de
// sessão expirada do 401 REST. Qualquer outro close (1013 fila estourada,
// queda de rede) -> reconecta com backoff exponencial simples.
export function useEventosDeJobs(autenticado) {
  const [jobsPorEpisodio, setJobsPorEpisodio] = useState(() => new Map());
  const tentativaRef = useRef(0);

  useEffect(() => {
    if (!autenticado) {
      setJobsPorEpisodio(new Map());
      return;
    }

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

      socket.onclose = (evento) => {
        if (cancelado) return;
        if (evento.code === 1008) {
          notificarSessaoExpirada();
          return;
        }
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
  }, [autenticado]);

  return jobsPorEpisodio;
}

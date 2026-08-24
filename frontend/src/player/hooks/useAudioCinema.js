import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { montarGrafoCinema, ajustarCinema } from '../audioCinema.js';
import { usePreferencia } from './usePreferencia.js';

// Áudio cinema (bass boost + compressor + crossfeed pra fone) — hook fino
// sobre audioCinema.js: cuida do ciclo de vida (criação lazy dentro de
// gesto, resume automático, fechamento no unmount/pagehide, estado de erro)
// que no protótipo (bench.js) mexia direto no DOM
// (`document.getElementById('btn-cinema').disabled`, listener solto em
// 'play'). Aqui o estado de erro só é devolvido — quem desenha o botão
// decide como reagir.
export function useAudioCinema(videoRef) {
  const [habilitado, setHabilitado] = usePreferencia('slime.cinemaAudio', false);
  const [falhou, setFalhou] = useState(false);
  // Espelha grafoRef.current só pra disparar o efeito de resume() logo
  // abaixo assim que o grafo nasce — não existe AudioContext pra registrar
  // 'statechange' antes disso, e grafoRef (ref) não dispara re-render.
  const [grafoAtivo, setGrafoAtivo] = useState(false);
  const grafoRef = useRef(null);

  // Criação de fato do grafo, usada tanto por garantirGrafo() (primeiro
  // play com a preferência já ligada) quanto por alternar() (ligar o
  // cinema no meio da sessão) — único ponto que mexe em montarGrafoCinema,
  // pra não duplicar o try/catch/resume entre os dois chamadores. Continua
  // sendo chamada só dentro de gesto real do usuário nos dois casos:
  // AudioContext/createMediaElementSource exigem isso pela autoplay
  // policy, e criar fora de um gesto deixaria a página MUDA —
  // createMediaElementSource desvia o áudio nativo do <video> pro grafo
  // assim que é chamado, mesmo que o contexto resultante nasça suspenso.
  const criarGrafo = useCallback(
    (habilitadoNoInicio) => {
      try {
        grafoRef.current = montarGrafoCinema(videoRef.current, habilitadoNoInicio);
        setGrafoAtivo(true);
      } catch (err) {
        setFalhou(true);
        console.error('[Áudio] Falha ao montar a cadeia cinema, seguindo com áudio nativo:', err);
        return null;
      }
      grafoRef.current.context.resume().catch(() => {});
      return grafoRef.current;
    },
    [videoRef]
  );

  // Só monta o grafo se o cinema estiver LIGADO — com o cinema desligado o
  // áudio segue 100% nativo, sem pagar a latência/risco de suspensão nem o
  // AudioContext extra por quem nunca ligou o recurso. O grafo continua
  // montado mesmo se o usuário desligar depois (ver alternar() abaixo): é
  // o roteamento irreversível de createMediaElementSource, não um bug — a
  // única forma de voltar ao áudio 100% nativo seria remontar o <video>.
  const garantirGrafo = useCallback(() => {
    if (grafoRef.current) {
      grafoRef.current.context.resume().catch(() => {});
      return grafoRef.current;
    }
    if (!habilitado || falhou) return null; // desligado, ou já falhou uma vez: não tenta de novo
    return criarGrafo(habilitado);
  }, [habilitado, falhou, criarGrafo]);

  const alternar = useCallback(
    (novoValor) => {
      if (falhou) return; // grafo já falhou uma vez: não persiste nem tenta de novo (mesma regra de garantirGrafo)
      setHabilitado(novoValor);
      if (!grafoRef.current) {
        if (!novoValor) return; // desligando sem grafo: só a preferência muda
        if (!criarGrafo(novoValor)) return; // montagem falhou agora, `falhou` já reflete isso
      }
      ajustarCinema(grafoRef.current, novoValor);
    },
    [falhou, setHabilitado, criarGrafo]
  );

  // Rede de segurança, não criação: recupera o AudioContext quando o
  // browser suspende sozinho — inclusive no meio da reprodução, o caso
  // Bluetooth confirmado (troca de perfil A2DP↔HSP suspende o contexto sem
  // pausar o vídeo). 'play'/'playing'/'seeked' cobrem retomada depois de
  // pausa/stall/seek; 'statechange' no próprio AudioContext é o único que
  // pega a suspensão espontânea no meio do play — só dispara resume() se
  // ainda estiver suspenso E o vídeo não estiver pausado de propósito.
  // O efeito depende de grafoAtivo porque o AudioContext só existe depois
  // que o grafo nasce (montagem agora é condicional): precisa reexecutar e
  // registrar o listener de 'statechange' assim que isso acontecer.
  useEffect(() => {
    const video = videoRef.current;
    const grafo = grafoRef.current;
    if (!video || !grafo) return;
    const aoRetomar = () => grafo.context.resume().catch(() => {});
    const aoMudarEstado = () => {
      if (grafo.context.state === 'suspended' && !video.paused) aoRetomar();
    };
    video.addEventListener('play', aoRetomar);
    video.addEventListener('playing', aoRetomar);
    video.addEventListener('seeked', aoRetomar);
    grafo.context.addEventListener('statechange', aoMudarEstado);
    return () => {
      video.removeEventListener('play', aoRetomar);
      video.removeEventListener('playing', aoRetomar);
      video.removeEventListener('seeked', aoRetomar);
      grafo.context.removeEventListener('statechange', aoMudarEstado);
    };
  }, [videoRef, grafoAtivo]);

  // Fecha o AudioContext ao sair da página (pagehide) e também ao
  // desmontar este componente (cleanup do próprio efeito) — cobre a
  // navegação interna do SPA, que não dispara pagehide: PaginaDoPlayer.jsx
  // usa `key={episodioId}`, então trocar de episódio remonta Player/
  // PlayerAtivo inteiro, e sem esse cleanup cada episódio assistido na
  // mesma sessão deixava um AudioContext pra trás, nunca fechado.
  // `event.persisted` indica bfcache (não destruição de fato) — nesse caso
  // fechar quebraria a página se o usuário voltar. Mesmo racional do
  // device WebGPU em motorAnime4k.js.
  // Seguro sob StrictMode (mount→cleanup→mount sintético logo na
  // montagem): o grafo só nasce dentro de um gesto real do usuário (play/
  // clique), muito depois desse double-invoke — no cleanup sintético
  // grafoRef.current ainda é null.
  useEffect(() => {
    function aoSairDaPagina(event) {
      if (event.persisted) return;
      grafoRef.current?.context.close().catch(() => {});
      grafoRef.current = null;
    }
    window.addEventListener('pagehide', aoSairDaPagina);
    return () => {
      window.removeEventListener('pagehide', aoSairDaPagina);
      grafoRef.current?.context.close().catch(() => {});
      grafoRef.current = null;
    };
  }, []);

  return useMemo(
    () => ({ habilitado, falhou, garantirGrafo, alternar }),
    [habilitado, falhou, garantirGrafo, alternar]
  );
}

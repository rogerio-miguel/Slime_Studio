import { useCallback, useEffect, useRef, useState } from 'react';
import { montarGrafoCinema, ajustarCinema } from '../audioCinema.js';
import { usePreferencia } from './usePreferencia.js';

// Áudio cinema (bass boost + compressor + crossfeed pra fone) — hook fino
// sobre audioCinema.js: cuida do ciclo de vida (criação lazy dentro de
// gesto, resume automático, fechamento no pagehide, estado de erro) que no
// protótipo (bench.js) mexia direto no DOM
// (`document.getElementById('btn-cinema').disabled`, listener solto em
// 'play'). Aqui o estado de erro só é devolvido — quem desenha o botão
// decide como reagir.
export function useAudioCinema(videoRef) {
  const [habilitado, setHabilitado] = usePreferencia('slime.cinemaAudio', false);
  const [falhou, setFalhou] = useState(false);
  const grafoRef = useRef(null);

  // Inicialização lazy, disparada só dentro de gesto real do usuário:
  // AudioContext/createMediaElementSource exigem gesto pela autoplay
  // policy, e criar isso fora de um handler de gesto (ex. no
  // loadedmetadata) deixaria a página MUDA — createMediaElementSource
  // desvia o áudio nativo do <video> pro grafo assim que é chamado, mesmo
  // que o contexto resultante nasça suspenso.
  const garantirGrafo = useCallback(() => {
    if (grafoRef.current || falhou) {
      grafoRef.current?.context.resume().catch(() => {});
      return grafoRef.current;
    }
    try {
      grafoRef.current = montarGrafoCinema(videoRef.current, habilitado);
    } catch (err) {
      setFalhou(true);
      console.error('[Áudio] Falha ao montar a cadeia cinema, seguindo com áudio nativo:', err);
      return null;
    }
    grafoRef.current.context.resume().catch(() => {});
    return grafoRef.current;
  }, [videoRef, habilitado, falhou]);

  const alternar = useCallback(
    (novoValor) => {
      setHabilitado(novoValor);
      if (!grafoRef.current) return; // grafo ainda não existe (nenhum gesto aconteceu) — só a preferência foi salva
      ajustarCinema(grafoRef.current, novoValor);
    },
    [setHabilitado]
  );

  // Rede de segurança, não criação: se o navegador suspender o AudioContext
  // sozinho (ex. depois de uma pausa longa), retoma ao voltar a tocar. Não
  // cria o grafo aqui — só garantirGrafo() (chamado a partir de gesto real)
  // faz isso.
  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    const aoRetomar = () => grafoRef.current?.context.resume().catch(() => {});
    video.addEventListener('play', aoRetomar);
    return () => video.removeEventListener('play', aoRetomar);
  }, [videoRef]);

  // Fecha o AudioContext explicitamente ao sair da página. `event.persisted`
  // indica bfcache (não destruição de fato) — nesse caso fechar quebraria a
  // página se o usuário voltar. Mesmo racional do device WebGPU em
  // motorAnime4k.js.
  useEffect(() => {
    function aoSairDaPagina(event) {
      if (event.persisted) return;
      grafoRef.current?.context.close().catch(() => {});
    }
    window.addEventListener('pagehide', aoSairDaPagina);
    return () => window.removeEventListener('pagehide', aoSairDaPagina);
  }, []);

  return { habilitado, falhou, garantirGrafo, alternar };
}

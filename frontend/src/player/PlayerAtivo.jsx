import { useCallback, useMemo, useRef } from 'react';
import BarraDeControles from './BarraDeControles.jsx';
import HudTelemetria from './HudTelemetria.jsx';
import GlowAmbiente from './GlowAmbiente.jsx';
import { PRESET_PADRAO, PRESETS } from './presets.js';
import { useFonteDeVideo } from './hooks/useFonteDeVideo.js';
import { useMotorAnime4k } from './hooks/useMotorAnime4k.js';
import { useAudioCinema } from './hooks/useAudioCinema.js';
import { useTelemetriaDeVideo } from './hooks/useTelemetriaDeVideo.js';
import { useAtalhosDeTeclado } from './hooks/useAtalhosDeTeclado.js';
import { usePreferencia } from './hooks/usePreferencia.js';
import { usePontoDeAssistido } from './hooks/usePontoDeAssistido.js';
import './player.css';

// Único dono dos refs de DOM (video/canvas/frame/palco) e do estado que
// nenhum hook filho é dono sozinho — cada hook abaixo cuida de UM
// subsistema (fonte, motor WebGPU, áudio, telemetria, atalhos) e
// PlayerAtivo só encadeia. Árvore de 3 níveis (PlayerAtivo →
// BarraDeControles/Hud/Glow), prop drilling é o mínimo correto: sem
// contexto/store nesta etapa (D8).
//
// Existe separado de Player.jsx (que só guarda erroFatal/o guard de
// navigator.gpu) porque os efeitos donos de cada subsistema abaixo (sessão
// WebGPU, grafo de áudio, loop de telemetria, listener de teclado, conexão
// HLS) precisam parar de rodar assim que um erro fatal é reportado por
// qualquer um deles via `aoFalhar` — Player.jsx desmonta este componente
// inteiro nesse caso, e o cleanup de cada hook roda sozinho pelo mecanismo
// de unmount do React, sem precisar de um flag `ativo` reimplementado em
// cada hook.
export default function PlayerAtivo({ fonte, titulo, aoFalhar, aoAtingirAssistido }) {
  const videoRef = useRef(null);
  const canvasRef = useRef(null);
  const frameRef = useRef(null);
  const palcoRef = useRef(null);

  const [presetAtual, setPresetAtual] = usePreferencia('slime.preset', PRESET_PADRAO);
  const [hudVisivel, setHudVisivel] = usePreferencia('slime.hudVisivel', false);

  const dimensoesDaFonte = useFonteDeVideo(videoRef, fonte, aoFalhar);

  const { adaptador } = useMotorAnime4k({
    videoRef,
    canvasRef,
    presetId: presetAtual,
    dimensoesDaFonte,
    aoFalhar,
  });

  const audioCinema = useAudioCinema(videoRef);

  const telemetria = useTelemetriaDeVideo({ videoRef, adaptador });

  usePontoDeAssistido(videoRef, aoAtingirAssistido);

  const alternarReproducao = useCallback(() => {
    // Gesto do usuário — ponto de entrada pro áudio cinema quando o play é
    // o primeiro gesto da sessão.
    audioCinema.garantirGrafo();
    const video = videoRef.current;
    if (!video) return;
    if (video.paused) video.play();
    else video.pause();
  }, [audioCinema]);

  const alternarMudo = useCallback(() => {
    const video = videoRef.current;
    if (!video) return;
    video.muted = !video.muted;
  }, []);

  const alternarTelaCheia = useCallback(() => {
    if (!document.fullscreenElement) palcoRef.current?.requestFullscreen?.();
    else document.exitFullscreen?.();
  }, []);

  const alternarHud = useCallback(() => setHudVisivel((atual) => !atual), [setHudVisivel]);

  const alternarCinema = useCallback(() => {
    audioCinema.garantirGrafo();
    audioCinema.alternar(!audioCinema.habilitado);
  }, [audioCinema]);

  const acoesDeTeclado = useMemo(
    () => ({ alternarReproducao, alternarTelaCheia, alternarMudo, alternarHud, alternarCinema }),
    [alternarReproducao, alternarTelaCheia, alternarMudo, alternarHud, alternarCinema]
  );
  useAtalhosDeTeclado({ videoRef, acoes: acoesDeTeclado });

  const frameAr = dimensoesDaFonte ? dimensoesDaFonte.width / dimensoesDaFonte.height : 1.777778;

  return (
    <div
      className="fullscreen-stage"
      ref={palcoRef}
      role="region"
      aria-label={titulo || 'Player de vídeo'}
    >
      <div className="frame" ref={frameRef} style={{ '--frame-ar': frameAr }}>
        {dimensoesDaFonte && <GlowAmbiente videoRef={videoRef} elementoDeMedidaRef={frameRef} />}
        {/* Vídeo invisível (opacity 0 via player.css) — só alimenta o
            pipeline WebGPU e o áudio. Nunca remonta (D3): createMediaElementSource
            (áudio cinema) e hls.attachMedia se prendem ao elemento. */}
        <video ref={videoRef} playsInline preload="auto" />
        {/* Canvas de saída remonta a cada troca de preset (key, D3): cada
            sessão do pipeline Anime4K precisa de contexto WebGPU virgem. */}
        <canvas key={presetAtual} ref={canvasRef} id="output-canvas" />
        <HudTelemetria
          visivel={hudVisivel}
          presetLabel={PRESETS[presetAtual]?.label ?? presetAtual}
          resolucao={canvasRef.current ? `${canvasRef.current.width}×${canvasRef.current.height}` : '—'}
          telemetria={telemetria}
        />
        <BarraDeControles
          videoRef={videoRef}
          presetAtual={presetAtual}
          aoTrocarPreset={setPresetAtual}
          aoAlternarReproducao={alternarReproducao}
          aoAlternarMudo={alternarMudo}
          aoAlternarTelaCheia={alternarTelaCheia}
          aoAlternarHud={alternarHud}
          aoAlternarCinema={alternarCinema}
          cinemaHabilitado={audioCinema.habilitado}
        />
      </div>
    </div>
  );
}

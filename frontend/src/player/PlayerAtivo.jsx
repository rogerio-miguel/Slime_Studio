import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import BarraDeControles from './BarraDeControles.jsx';
import HudTelemetria from './HudTelemetria.jsx';
import GlowAmbiente from './GlowAmbiente.jsx';
import { DEGRAUS_ADAPTATIVOS, PRESET_PADRAO, PRESETS, contarPasses } from './presets.js';
import { useFonteDeVideo } from './hooks/useFonteDeVideo.js';
import { useMotorAnime4k } from './hooks/useMotorAnime4k.js';
import { useControleAdaptativo } from './hooks/useControleAdaptativo.js';
import { useAudioCinema } from './hooks/useAudioCinema.js';
import { useTelemetriaDeVideo } from './hooks/useTelemetriaDeVideo.js';
import { useAtalhosDeTeclado } from './hooks/useAtalhosDeTeclado.js';
import { usePreferencia } from './hooks/usePreferencia.js';
import { usePontoDeAssistido } from './hooks/usePontoDeAssistido.js';
import { usePosicaoDeReproducao } from './hooks/usePosicaoDeReproducao.js';
import { useOcultarPorInatividade } from './hooks/useOcultarPorInatividade.js';
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
export default function PlayerAtivo({
  fonte,
  titulo,
  aoFalhar,
  aoAtingirAssistido,
  retomarDe,
  aoSalvarProgresso,
  focoTituloRef,
}) {
  const videoRef = useRef(null);
  const canvasRef = useRef(null);
  const frameRef = useRef(null);
  const palcoRef = useRef(null);

  // 'auto' = degradação adaptativa (useControleAdaptativo percorre
  // DEGRAUS_ADAPTATIVOS); qualquer outro valor = um preset fixo escolhido na
  // mão. Chave nova de propósito: 'slime.preset' antigo continua órfão no
  // localStorage, mas reusá-lo faria o teste ao vivo começar em modo manual
  // sem sinal de por quê.
  const [qualidade, setQualidade] = usePreferencia('slime.qualidade', 'auto');
  const [hudVisivel, setHudVisivel] = usePreferencia('slime.hudVisivel', false);
  // Piso que a GPU aguentou por último — semeia o degrau inicial pra não sondar
  // do topo (e travar) toda vez que abre um episódio.
  const [degrauAutoSalvo, setDegrauAutoSalvo] = usePreferencia('slime.degrauAuto', 0);
  const auto = qualidade === 'auto';

  const dimensoesDaFonte = useFonteDeVideo(videoRef, fonte, aoFalhar);

  const { indiceDeDegrau, diagnostico, degradarPorFalhaDeGpu } = useControleAdaptativo({
    videoRef,
    ativo: auto,
    chaveDeSessao: fonte,
    degrauSalvo: degrauAutoSalvo,
    aoDegrauEstavel: setDegrauAutoSalvo,
  });

  const presetManual = PRESETS[qualidade] ? qualidade : PRESET_PADRAO;
  const presetAtual = auto ? DEGRAUS_ADAPTATIVOS[indiceDeDegrau] : presetManual;

  // Falha de render()/`device.lost` (via useMotorAnime4k): em modo automático
  // desce um degrau em vez de matar o player; só propaga como fatal no piso
  // ou em modo manual. Identidade estável — se dependesse de `presetAtual` o
  // efeito do motor reconstruiria a sessão a cada troca de degrau.
  const autoRef = useRef(auto);
  useEffect(() => {
    autoRef.current = auto;
  }, [auto]);
  const aoFalharDoMotor = useCallback(
    (erro) => {
      if (autoRef.current && degradarPorFalhaDeGpu()) return;
      aoFalhar(erro);
    },
    [aoFalhar, degradarPorFalhaDeGpu]
  );

  const { adaptador, medidor } = useMotorAnime4k({
    videoRef,
    canvasRef,
    presetId: presetAtual,
    dimensoesDaFonte,
    aoFalhar: aoFalharDoMotor,
  });

  // Amostra o medidor de GPU pro HUD (só instrumentação nesta fase — a
  // política preditiva ainda não consome). Poll de 500ms: `ler()` só faz
  // mediana de ~24 números, custo desprezível.
  const [metricaGpu, setMetricaGpu] = useState(null);
  useEffect(() => {
    if (!medidor) {
      setMetricaGpu(null);
      return;
    }
    const id = setInterval(() => setMetricaGpu(medidor.ler()), 500);
    return () => clearInterval(id);
  }, [medidor]);

  const audioCinema = useAudioCinema(videoRef);

  const telemetria = useTelemetriaDeVideo({ videoRef, adaptador });

  usePontoDeAssistido(videoRef, aoAtingirAssistido);
  usePosicaoDeReproducao(videoRef, aoSalvarProgresso, retomarDe);
  useOcultarPorInatividade(videoRef, palcoRef);

  const alternarReproducao = useCallback(() => {
    // Gesto do usuário — ponto de entrada pro áudio cinema quando a
    // preferência já vem ligada do localStorage ao entrar na página (o
    // primeiro play precisa materializar o grafo). Com o cinema desligado
    // isso agora é no-op: garantirGrafo só monta o grafo se `habilitado`
    // for true.
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
    audioCinema.alternar(!audioCinema.habilitado);
  }, [audioCinema]);

  const acoesDeTeclado = useMemo(
    () => ({ alternarReproducao, alternarTelaCheia, alternarMudo, alternarHud, alternarCinema }),
    [alternarReproducao, alternarTelaCheia, alternarMudo, alternarHud, alternarCinema]
  );
  useAtalhosDeTeclado({ videoRef, acoes: acoesDeTeclado });

  return (
    <div
      className="fullscreen-stage"
      ref={palcoRef}
      role="region"
      aria-label={titulo || 'Player de vídeo'}
    >
      <div className="frame" ref={frameRef}>
        {dimensoesDaFonte && <GlowAmbiente videoRef={videoRef} elementoDeMedidaRef={frameRef} />}
        {/* Vídeo invisível (opacity 0 via player.css) — só alimenta o
            pipeline WebGPU e o áudio. Nunca remonta (D3): createMediaElementSource
            (áudio cinema) e hls.attachMedia se prendem ao elemento. */}
        <video ref={videoRef} playsInline preload="auto" />
        {/* Canvas de saída remonta a cada troca de preset (key, D3): cada
            sessão do pipeline Anime4K precisa de contexto WebGPU virgem. */}
        <canvas key={presetAtual} ref={canvasRef} id="output-canvas" />
        {/* Título como overlay dentro do .frame, não mais <header> externo
            em PaginaDoPlayer.jsx: reaproveita a classe `.controls`
            (player.css) — mesmo mecanismo de fade-in/out em hover/focus-
            within que já rege BarraDeControles, só ancorado no topo
            (top-0). `.controls-topo` só ajusta a direção do nudge de
            entrada (ver player.css) — opacity/transition/pointer-events
            continuam vindo de `.controls`, nada duplicado. Sem link "←
            voltar" de propósito (removido a pedido do usuário) — sair do
            player é só navegação de volta do navegador/atalho, sem
            afordance própria aqui. */}
        <div className="controls controls-topo absolute inset-x-0 top-0 flex items-center gap-4 px-4 py-3">
          <h1 ref={focoTituloRef} tabIndex={-1} className="text-2xl font-medium text-white outline-none">
            {titulo}
          </h1>
        </div>
        <HudTelemetria
          visivel={hudVisivel}
          modo={auto ? `Auto · degrau ${indiceDeDegrau + 1}/${DEGRAUS_ADAPTATIVOS.length}` : 'Manual'}
          presetLabel={PRESETS[presetAtual]?.label ?? presetAtual}
          resolucao={canvasRef.current ? `${canvasRef.current.width}×${canvasRef.current.height}` : '—'}
          telemetria={telemetria}
          diagnostico={diagnostico}
          metricaGpu={metricaGpu}
          passes={contarPasses(PRESETS[presetAtual]?.blocos ?? [])}
        />
        <BarraDeControles
          videoRef={videoRef}
          presetAtual={qualidade}
          aoTrocarPreset={setQualidade}
          aoAlternarReproducao={alternarReproducao}
          aoAlternarMudo={alternarMudo}
          aoAlternarTelaCheia={alternarTelaCheia}
          aoAlternarHud={alternarHud}
          aoAlternarCinema={alternarCinema}
          cinemaHabilitado={audioCinema.habilitado}
          cinemaFalhou={audioCinema.falhou}
        />
      </div>
    </div>
  );
}

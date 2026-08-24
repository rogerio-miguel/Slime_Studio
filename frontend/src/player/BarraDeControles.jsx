import { useEffect, useRef, useState } from 'react';
import SeletorDePreset from './SeletorDePreset.jsx';
import { IconePlay, IconePausa, IconeVolumeAlto, IconeVolumeMudo, IconeFones, IconeTelaCheia } from './Icones.jsx';

function formatarTempo(segundos) {
  if (!Number.isFinite(segundos)) return '0:00';
  const m = Math.floor(segundos / 60);
  const s = Math.floor(segundos % 60)
    .toString()
    .padStart(2, '0');
  return `${m}:${s}`;
}

const classeBotao =
  'inline-flex items-center justify-center rounded-md border border-border-chrome bg-[#222] px-2.5 py-1.5 text-white hover:bg-[#2a2a2a] ' +
  'aria-pressed:bg-[#1d4b2b] aria-pressed:border-[#3ea05f] aria-pressed:text-[#d9ffe6] ' +
  'focus-visible:outline focus-visible:outline-2 focus-visible:outline-white focus-visible:outline-offset-2';

// Componente controlado: não guarda a fonte de verdade da reprodução — isso
// vive no <video> (videoRef, de Player.jsx). Este componente só espelha o
// estado do elemento (via listeners) em controles de UI; ações (play, mudo,
// tela cheia, HUD, cinema) são callbacks recebidos de Player.jsx — as
// mesmas que useAtalhosDeTeclado.js aciona pelo teclado, sem duplicar
// lógica. Porte de bench.js:wireControls (630-714), pra dentro de efeitos
// de React em vez de addEventListener solto num módulo de topo.
export default function BarraDeControles({
  videoRef,
  presetAtual,
  aoTrocarPreset,
  aoAlternarReproducao,
  aoAlternarMudo,
  aoAlternarTelaCheia,
  aoAlternarHud,
  aoAlternarCinema,
  cinemaHabilitado,
  cinemaFalhou,
}) {
  const [tocando, setTocando] = useState(false);
  const [progresso, setProgresso] = useState(0);
  const [tempoAtual, setTempoAtual] = useState(0);
  const [duracao, setDuracao] = useState(NaN);
  const [mudo, setMudo] = useState(false);
  const [volume, setVolume] = useState(1);
  const seekingRef = useRef(false);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;

    const aoTocar = () => setTocando(true);
    const aoPausar = () => setTocando(false);
    const aoAtualizarTempo = () => {
      if (!seekingRef.current && video.duration) {
        setProgresso((video.currentTime / video.duration) * 100);
      }
      setTempoAtual(video.currentTime);
      setDuracao(video.duration);
    };
    // Cobre slider de volume, mute button E os atalhos de teclado (↑/↓/M) —
    // todos mexem em video.volume/video.muted direto; este listener único
    // mantém a UI sincronizada com qualquer um deles, sem duplicar lógica.
    const aoMudarVolume = () => {
      setVolume(video.volume);
      setMudo(video.muted);
    };

    video.addEventListener('play', aoTocar);
    video.addEventListener('pause', aoPausar);
    video.addEventListener('timeupdate', aoAtualizarTempo);
    video.addEventListener('volumechange', aoMudarVolume);
    aoMudarVolume(); // estado inicial

    return () => {
      video.removeEventListener('play', aoTocar);
      video.removeEventListener('pause', aoPausar);
      video.removeEventListener('timeupdate', aoAtualizarTempo);
      video.removeEventListener('volumechange', aoMudarVolume);
    };
  }, [videoRef]);

  function aoMoverSeek(event) {
    seekingRef.current = true;
    const video = videoRef.current;
    const novoProgresso = Number(event.target.value);
    setProgresso(novoProgresso);
    if (video?.duration) video.currentTime = (novoProgresso / 100) * video.duration;
  }

  function aoSoltarSeek() {
    seekingRef.current = false;
  }

  function aoDigitarVolume(event) {
    const video = videoRef.current;
    if (!video) return;
    video.volume = Number(event.target.value);
    video.muted = video.volume === 0;
  }

  return (
    <div
      className="controls absolute inset-x-0 bottom-0 flex flex-wrap items-center gap-3 px-3.5 pt-6 pb-3"
      style={{ background: 'linear-gradient(to top, rgba(0,0,0,0.85), rgba(0,0,0,0))' }}
      role="group"
      aria-label="Controles de reprodução"
    >
      <button type="button" onClick={aoAlternarReproducao} aria-label={tocando ? 'Pausar' : 'Reproduzir'} className={classeBotao}>
        {tocando ? <IconePausa /> : <IconePlay />}
      </button>
      <input
        type="range"
        min="0"
        max="100"
        step="0.01"
        value={progresso}
        onInput={aoMoverSeek}
        onChange={aoSoltarSeek}
        aria-label="Posição no vídeo"
        aria-valuetext={`${formatarTempo(tempoAtual)} de ${formatarTempo(duracao)}`}
        className="min-w-[120px] flex-1 accent-white"
      />
      {/* aria-hidden mantido de propósito: o mesmo tempo já é anunciado via
          aria-valuetext do slider de seek acima — expor aqui também
          duplicaria a informação pro leitor de tela, não a esconderia. */}
      <span
        aria-hidden="true"
        className="min-w-[92px] rounded bg-black/70 px-2 py-0.5 text-center text-[0.85rem] text-[#ccc] [font-variant-numeric:tabular-nums]"
      >
        {formatarTempo(tempoAtual)} / {formatarTempo(duracao)}
      </span>
      <button type="button" onClick={aoAlternarMudo} aria-label={mudo ? 'Ativar som' : 'Mudo'} className={classeBotao}>
        {mudo ? <IconeVolumeMudo /> : <IconeVolumeAlto />}
      </button>
      <input
        type="range"
        min="0"
        max="1"
        step="0.01"
        value={volume}
        onInput={aoDigitarVolume}
        aria-label="Volume"
        className="w-20 accent-white"
      />
      <button
        type="button"
        onClick={aoAlternarCinema}
        disabled={cinemaFalhou}
        aria-pressed={cinemaFalhou ? false : cinemaHabilitado}
        aria-label={
          cinemaFalhou
            ? 'Áudio cinema indisponível: a cadeia de áudio falhou ao montar, seguindo com áudio nativo'
            : 'Áudio cinema (graves + crossfeed para fone)'
        }
        title={cinemaFalhou ? 'Áudio cinema indisponível: a cadeia de áudio falhou ao montar, seguindo com áudio nativo' : undefined}
        className={`${classeBotao} disabled:cursor-not-allowed disabled:opacity-50`}
      >
        <IconeFones />
      </button>
      <SeletorDePreset presetAtual={presetAtual} aoTrocar={aoTrocarPreset} />
      <button type="button" onClick={aoAlternarTelaCheia} aria-label="Tela cheia" className={classeBotao}>
        <IconeTelaCheia />
      </button>
      <button type="button" onClick={aoAlternarHud} aria-label="Alternar HUD" className={classeBotao}>
        HUD
      </button>
    </div>
  );
}

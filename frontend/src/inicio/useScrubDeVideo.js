import { useCallback, useEffect, useRef, useState } from 'react';

const _FPS = 24;
const _DURACAO_UM_FRAME_S = 1 / _FPS;
const _VELOCIDADE_LERP = 0.12;
const _LIMIAR_CHEGANDO = 0.75;
const _LIMIAR_REVELADO = 1;

function calcularFase(progresso) {
  if (progresso >= _LIMIAR_REVELADO) return 'revelado';
  if (progresso >= _LIMIAR_CHEGANDO) return 'chegando';
  return 'entrada';
}

// Quantiza pra fronteira de frame do vídeo all-intra (24fps — ver nota "já
// feito" no plano) — o +0.001 evita que o seek caia exatamente na borda do
// keyframe, onde alguns decoders arredondam pro frame anterior.
function quantizarParaFrame(tempoS) {
  return Math.round(tempoS * _FPS) / _FPS + 0.001;
}

function progressoDoScroll() {
  return Math.min(Math.max(window.scrollY / (2 * window.innerHeight), 0), 1);
}

// Scrub do hero controlado por scroll (CenarioDeEntrada.jsx, via
// paginas/Inicio.jsx) — sem lib nova (Escada de Minimalismo, CLAUDE.md).
//
// Regra crítica de perf: o handler de scroll NUNCA chama `setState` por
// pixel — escreve só um alvo (`alvoRef`); um loop `requestAnimationFrame`
// interpola até lá (`atual += (alvo - atual) * 0.12`) e escreve
// `video.currentTime` direto, imperativo, quantizado a fronteira de frame,
// pulando escritas com delta menor que 1 frame ou enquanto o vídeo ainda não
// tem dados suficientes (`readyState < 2`). O state React (`fase`) só muda
// nas 3 transições discretas (entrada/chegando/revelado), nunca por pixel.
//
// `prefers-reduced-motion`: não monta o scrub — vídeo pula direto pro
// último frame, fase inicial já é `revelado` (paginas/Inicio.jsx zera a
// altura do spacer nesse modo). Ouve mudança de preferência em runtime, já
// que o usuário pode alternar a preferência do SO com a página aberta.
export function useScrubDeVideo(videoRef) {
  const [fase, setFase] = useState('entrada');
  const [movimentoReduzido, setMovimentoReduzido] = useState(
    () => window.matchMedia('(prefers-reduced-motion: reduce)').matches
  );
  const alvoRef = useRef(0);
  const atualRef = useRef(0);
  const faseRef = useRef('entrada');

  useEffect(() => {
    const consulta = window.matchMedia('(prefers-reduced-motion: reduce)');
    const aoMudarPreferencia = (evento) => setMovimentoReduzido(evento.matches);
    consulta.addEventListener('change', aoMudarPreferencia);
    return () => consulta.removeEventListener('change', aoMudarPreferencia);
  }, []);

  // Usado pelo botão "Pular introdução" (primeiro elemento focável do DOM,
  // paginas/Inicio.jsx) — sem isto, quem navega só por teclado não tem como
  // passar da introdução de 8s. Rola até o limiar de `revelado` (em vez de
  // só trocar a fase) pra um scroll manual seguinte não desfazer o pulo.
  //
  // Se `loadedmetadata` ainda não disparou, `video.duration` é `NaN` — não
  // `undefined`, então `??` não pega. Só escreve em `atualRef`/`alvoRef`
  // quando a duração já é um número finito válido; do contrário deixa os
  // refs como estão e o listener de `loadedmetadata` (`aoRolar`, já com o
  // scroll na posição alvo) resolve o alvo assim que a duração chegar.
  const pularIntroducao = useCallback(() => {
    const video = videoRef.current;
    const duracao = video && Number.isFinite(video.duration) ? video.duration : 0;
    if (duracao > 0) {
      atualRef.current = duracao;
      alvoRef.current = duracao;
      video.currentTime = duracao;
    }
    faseRef.current = 'revelado';
    setFase('revelado');
    window.scrollTo(0, 2 * window.innerHeight);
  }, [videoRef]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return undefined;

    if (movimentoReduzido) {
      const irParaUltimoFrame = () => {
        video.currentTime = video.duration;
      };
      video.addEventListener('loadedmetadata', irParaUltimoFrame);
      faseRef.current = 'revelado';
      setFase('revelado');
      return () => video.removeEventListener('loadedmetadata', irParaUltimoFrame);
    }

    function aoRolar() {
      const progresso = progressoDoScroll();
      alvoRef.current = progresso * (video.duration || 0);
      const novaFase = calcularFase(progresso);
      if (novaFase !== faseRef.current) {
        faseRef.current = novaFase;
        setFase(novaFase);
      }
    }

    let ultimoEscritoS = 0;
    let quadro;
    function passo() {
      atualRef.current += (alvoRef.current - atualRef.current) * _VELOCIDADE_LERP;
      const diferenca = Math.abs(atualRef.current - ultimoEscritoS);
      if (video.readyState >= 2 && diferenca >= _DURACAO_UM_FRAME_S) {
        video.currentTime = quantizarParaFrame(atualRef.current);
        ultimoEscritoS = atualRef.current;
      }
      quadro = requestAnimationFrame(passo);
    }

    // `loadedmetadata` também dispara `aoRolar` — sem isto, um scroll que
    // acontece antes do vídeo carregar a duração ficaria com o alvo preso
    // em 0 (duration ainda `NaN`/0 no momento do cálculo).
    window.addEventListener('scroll', aoRolar, { passive: true });
    window.addEventListener('resize', aoRolar);
    video.addEventListener('loadedmetadata', aoRolar);
    aoRolar();
    quadro = requestAnimationFrame(passo);

    return () => {
      window.removeEventListener('scroll', aoRolar);
      window.removeEventListener('resize', aoRolar);
      video.removeEventListener('loadedmetadata', aoRolar);
      cancelAnimationFrame(quadro);
    };
  }, [videoRef, movimentoReduzido]);

  return { fase, movimentoReduzido, pularIntroducao };
}

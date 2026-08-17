import { useCallback, useEffect, useRef, useState } from 'react';
import { usePrefersReducedMotion } from './usePrefersReducedMotion.js';

const _FPS = 24;
const _DURACAO_UM_FRAME_S = 1 / _FPS;
const _VELOCIDADE_LERP = 0.12;
const _LIMIAR_CHEGANDO = 0.75;
const _LIMIAR_REVELADO = 1;

// Altura do spacer transparente que dirige o scrub (paginas/Inicio.jsx é
// quem consome esta constante pro `style={{ height }}` do spacer) — fonte
// única de verdade. Antes esse valor vivia duplicado como "2 * innerHeight"
// aqui embaixo e "300vh" no spacer, e os dois dessincronizaram: `fase`
// virava 'revelado' a 200vh de scroll, mas `<main>` só começava a entrar na
// tela a 300vh (fim do spacer), sobrando 100vh de vazio que o usuário tinha
// que rolar "às cegas" depois da introdução já ter acabado.
export const ALTURA_INTRO_VH = 300;
const _MULTIPLICADOR_SCROLL = ALTURA_INTRO_VH / 100;

// Janela da logo do hero (progresso 0-1, mesma linha do tempo do vídeo). A
// navbar só aparece em `revelado` (progresso 1, BarraDeNavegacao.jsx), não
// mais em `chegando` (0.75) — então o orçamento de `_INICIO` até `_FIM` vai
// até perto de 1.0, não mais até 0.75. Pra ajustar: `_INICIO`→`_PICO_INICIO`
// é quanto tempo ela demora pra aparecer (fade-in); `_PICO_INICIO`→
// `_PICO_FIM` é quanto tempo fica totalmente opaca; `_FIM` mais perto de 1
// atrasa o sumiço (mas em 1 o vídeo já travou no último frame e o conteúdo
// principal assume — manter folga). Requer
// `_INICIO < _PICO_INICIO < _PICO_FIM < _FIM < 1` — fora dessa ordem
// `calcularEstiloDaLogo` quebra (corte brusco em vez de fade suave).
const _PROGRESSO_LOGO_INICIO = 0.36;
const _PROGRESSO_LOGO_PICO_INICIO = 0.5;
const _PROGRESSO_LOGO_PICO_FIM = 0.84;
const _PROGRESSO_LOGO_FIM = 0.92;

// Escala cresce de forma contínua do início ao fim da janela inteira
// (inclusive durante o pico de opacidade, sem travar) — sensação de câmera
// se aproximando, como se a logo fizesse parte da profundidade da cena, não
// um overlay parado por cima do vídeo. Nunca encolhe de volta.
const _LOGO_ESCALA_INICIO = 0.8;
const _LOGO_ESCALA_FIM = 1.6;

function calcularFase(progresso) {
  if (progresso >= _LIMIAR_REVELADO) return 'revelado';
  if (progresso >= _LIMIAR_CHEGANDO) return 'chegando';
  return 'entrada';
}

// Opacidade/escala da logo por progresso — calculada aqui e escrita direto
// no DOM dentro de `passo()` (mesma regra de perf do resto do arquivo:
// nunca via state React).
function calcularEstiloDaLogo(progressoSuave) {
  if (progressoSuave <= _PROGRESSO_LOGO_INICIO || progressoSuave >= _PROGRESSO_LOGO_FIM) {
    return { opacidade: 0, escala: _LOGO_ESCALA_INICIO };
  }
  const tEscala =
    (progressoSuave - _PROGRESSO_LOGO_INICIO) / (_PROGRESSO_LOGO_FIM - _PROGRESSO_LOGO_INICIO);
  const escala = _LOGO_ESCALA_INICIO + tEscala * (_LOGO_ESCALA_FIM - _LOGO_ESCALA_INICIO);

  if (progressoSuave <= _PROGRESSO_LOGO_PICO_INICIO) {
    const tOpacidade =
      (progressoSuave - _PROGRESSO_LOGO_INICIO) /
      (_PROGRESSO_LOGO_PICO_INICIO - _PROGRESSO_LOGO_INICIO);
    return { opacidade: tOpacidade, escala };
  }
  if (progressoSuave <= _PROGRESSO_LOGO_PICO_FIM) {
    return { opacidade: 1, escala };
  }
  const tOpacidade =
    (progressoSuave - _PROGRESSO_LOGO_PICO_FIM) / (_PROGRESSO_LOGO_FIM - _PROGRESSO_LOGO_PICO_FIM);
  return { opacidade: 1 - tOpacidade, escala };
}

// Quantiza pra fronteira de frame do vídeo all-intra (24fps — ver nota "já
// feito" no plano) — o +0.001 evita que o seek caia exatamente na borda do
// keyframe, onde alguns decoders arredondam pro frame anterior.
function quantizarParaFrame(tempoS) {
  return Math.round(tempoS * _FPS) / _FPS + 0.001;
}

function progressoDoScroll() {
  return Math.min(
    Math.max(window.scrollY / (_MULTIPLICADOR_SCROLL * window.innerHeight), 0),
    1
  );
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
export function useScrubDeVideo(videoRef, logoRef) {
  const [fase, setFase] = useState('entrada');
  const movimentoReduzido = usePrefersReducedMotion();
  const alvoRef = useRef(0);
  const atualRef = useRef(0);
  const faseRef = useRef('entrada');

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
    window.scrollTo(0, _MULTIPLICADOR_SCROLL * window.innerHeight);
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
      if (logoRef?.current && Number.isFinite(video.duration) && video.duration > 0) {
        const { opacidade, escala } = calcularEstiloDaLogo(atualRef.current / video.duration);
        logoRef.current.style.opacity = opacidade;
        logoRef.current.style.transform = `scale(${escala})`;
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

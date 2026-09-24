import { useRef, useState } from 'react';

// Tempo total de pressão (ms) até completar o gesto e disparar a ação
// ampliada (1m30, ver BarraDeControles.jsx). `ATRASO_REVELACAO_MS` é a
// janela de graça ANTES do anel começar a aparecer — sem ela, qualquer
// toque comum (que sempre dura >0ms) piscaria o anel; com ela, o progresso
// visual só nasce depois desse atraso e ainda assim fecha o círculo
// inteiro exatamente em `DURACAO_MS` de pressão total.
const DURACAO_MS = 600;
const ATRASO_REVELACAO_MS = 150;

// Gesto "toque = ação normal (10s), segurar ~600ms = ação ampliada (1m30)"
// dos botões de skip do trio central (BarraDeControles.jsx) — pedido do
// usuário, 2026-09-24, pra não precisar de nenhum botão novo na barra: a
// caixa já existente do skip de 10s ganha o anel em volta de si mesma.
// `aoTocar` é disparado pelo onClick NATIVO do botão (não por
// pointerup/pointerdown) — isso dá suporte de teclado de graça (Enter/Espaço
// num botão focado sempre gera `click` sem passar por aqui, então some
// direto pro toque de 10s, sem gesto de segurar via teclado). O par
// pointerdown/pointerup só decide se esse `click` que vai vir em seguida
// deve ser suprimido, porque virou um "segurar" (completo ou cancelado).
export function useSegurarParaPular(aoTocar, aoCompletarSegurar) {
  const [progresso, setProgresso] = useState(0);
  const inicioRef = useRef(0);
  const quadroRef = useRef(null);
  const completoRef = useRef(false);
  const suprimirCliqueRef = useRef(false);

  function pararAnimacao() {
    if (quadroRef.current != null) cancelAnimationFrame(quadroRef.current);
    quadroRef.current = null;
  }

  function animarSubida() {
    const decorrido = performance.now() - inicioRef.current;
    const fracaoVisivel = (decorrido - ATRASO_REVELACAO_MS) / (DURACAO_MS - ATRASO_REVELACAO_MS);
    setProgresso(Math.min(1, Math.max(0, fracaoVisivel)));
    if (decorrido >= DURACAO_MS) {
      completoRef.current = true;
      aoCompletarSegurar();
      return;
    }
    quadroRef.current = requestAnimationFrame(animarSubida);
  }

  // Desenha o anel de volta a 0 na mesma velocidade angular da subida — não
  // um fade genérico — pra parecer que o gesto está sendo "desfeito", não só
  // escondido. Duração proporcional ao progresso atual: um anel 20% cheio
  // desfaz em 20% do tempo que levaria pra fechar.
  function animarDescida(progressoInicial) {
    const inicio = performance.now();
    const duracaoDescida = progressoInicial * (DURACAO_MS - ATRASO_REVELACAO_MS);
    function passo() {
      const decorrido = performance.now() - inicio;
      const proximo = duracaoDescida <= 0 ? 0 : progressoInicial * Math.max(0, 1 - decorrido / duracaoDescida);
      setProgresso(proximo);
      quadroRef.current = proximo > 0 ? requestAnimationFrame(passo) : null;
    }
    passo();
  }

  function aoPressionar(event) {
    // Ignora clique secundário/do meio — só o botão principal do mouse (touch
    // e caneta não têm `button` significativo, chegam como 0 por padrão).
    if (event.pointerType === 'mouse' && event.button !== 0) return;
    // Garante que pointerup chegue aqui mesmo se o dedo/cursor sair da área
    // do botão antes de soltar (comum em touch) — sem isso o gesto ficaria
    // "preso" segurando pra sempre.
    event.currentTarget.setPointerCapture?.(event.pointerId);
    pararAnimacao();
    completoRef.current = false;
    suprimirCliqueRef.current = false;
    inicioRef.current = performance.now();
    quadroRef.current = requestAnimationFrame(animarSubida);
  }

  function finalizar() {
    pararAnimacao();
    if (completoRef.current) {
      // 1m30 já disparou nesta pressão — só reseta o anel; o clique nativo
      // que ainda vai chegar não pode virar TAMBÉM um skip de 10s.
      suprimirCliqueRef.current = true;
      setProgresso(0);
      return;
    }
    if (progresso > 0) {
      // Anel já tinha começado a aparecer: isso é um "segurar" cancelado,
      // não um toque — sem ação nenhuma, só desfaz o anel.
      suprimirCliqueRef.current = true;
      animarDescida(progresso);
    }
    // progresso === 0 e não completou: toque rápido de verdade — deixa o
    // `click` nativo (ainda por vir) disparar `aoTocar` normalmente.
  }

  function aoClicar() {
    if (suprimirCliqueRef.current) {
      suprimirCliqueRef.current = false;
      return;
    }
    aoTocar?.();
  }

  return {
    progresso,
    handlers: {
      onPointerDown: aoPressionar,
      onPointerUp: finalizar,
      onPointerLeave: finalizar,
      onPointerCancel: finalizar,
      onClick: aoClicar,
    },
  };
}

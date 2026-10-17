import { useEffect } from 'react';

// Auto-ocultar por inatividade (padrão YouTube/Netflix). Duas decisões que o
// código não conta sozinho:
//
// 1. O estado vive no DOM (classList do palco), não em useState: o único
//    consumidor do flag é player.css — nenhum componente React lê "inativo",
//    então virar estado React só custaria um re-render da árvore toda do
//    player (canvas WebGPU, HUD, barra) a cada mostrar/ocultar.
// 2. Quem garante acessibilidade continua sendo o CSS: a regra correspondente
//    em player.css neutraliza esta classe enquanto houver :focus-visible
//    dentro do palco. Aqui só decidimos QUANDO marcar inatividade — nunca
//    "pode esconder com o foco de teclado dentro".
//
// Pausado também esconde: mesmo com o vídeo parado, ficar sem tocar em nada
// por ATRASO_MS oculta barra/título (a pedido do usuário) — qualquer
// pointermove/tecla/foco reabre na hora, então a UI nunca fica inacessível.
const CLASSE_PALCO_INATIVO = 'palco-inativo'; // par com player.css
const ATRASO_MS = 1000;

export function useOcultarPorInatividade(videoRef, palcoRef) {
  useEffect(() => {
    const video = videoRef.current;
    const palco = palcoRef.current;
    if (!video || !palco) return undefined;

    let temporizador = 0;

    function ocultar() {
      palco.classList.add(CLASSE_PALCO_INATIVO);
    }

    function reiniciarContagem() {
      palco.classList.remove(CLASSE_PALCO_INATIVO);
      clearTimeout(temporizador);
      temporizador = setTimeout(ocultar, ATRASO_MS);
    }

    // Ponteiro só conta dentro do palco (mexer o mouse na navbar não é
    // atividade no player); teclado é global porque os atalhos do player
    // (useAtalhosDeTeclado) também escutam em document — apertar espaço/seta
    // com o foco no <body> tem que revelar a UI que o atalho acabou de mudar.
    // focusout também reinicia, não só focusin: sem ele, sair de um botão com
    // Tab esconderia a UI na hora — o temporizador já teria estourado por
    // baixo da trava de :focus-visible, e a classe estaria só esperando o
    // foco sair pra ter efeito.
    const eventosDoPalco = ['pointermove', 'pointerdown', 'focusin', 'focusout'];
    const eventosDoVideo = ['play', 'pause', 'ended'];

    eventosDoPalco.forEach((evento) => palco.addEventListener(evento, reiniciarContagem));
    document.addEventListener('keydown', reiniciarContagem);
    eventosDoVideo.forEach((evento) => video.addEventListener(evento, reiniciarContagem));

    reiniciarContagem();

    return () => {
      clearTimeout(temporizador);
      eventosDoPalco.forEach((evento) => palco.removeEventListener(evento, reiniciarContagem));
      document.removeEventListener('keydown', reiniciarContagem);
      eventosDoVideo.forEach((evento) => video.removeEventListener(evento, reiniciarContagem));
      palco.classList.remove(CLASSE_PALCO_INATIVO);
    };
  }, [videoRef, palcoRef]);
}

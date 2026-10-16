import { useEffect } from 'react';

// Atalhos globais de teclado — porte do switch original (bench.js:716-758).
// A guarda original ignorava o atalho pra QUALQUER <input>/<button>/<select>
// focado, pensada pra evitar, ex., Espaço acionando o clique nativo do botão
// focado E o atalho ao mesmo tempo. Ampla demais na prática: como clicar em
// qualquer botão da barra deixa o foco nele, TODOS os atalhos (setas, F, M,
// H, C) morriam até clicar de novo no vídeo — bug relatado pelo usuário.
// Restrita agora só às combinações que realmente colidem: Espaço/Enter
// ativam nativamente o que estiver focado (só importa pra <button>); setas
// navegam o valor de um <input type=range> focado (progresso/volume) — o
// resto do teclado passa direto pro atalho global não importa o que esteja
// focado. `acoes` contém os callbacks compartilhados com
// BarraDeControles.jsx (mesma lógica pros dois pontos de entrada, sem
// duplicar).
const TECLAS_DE_SETA = ['arrowleft', 'arrowright', 'arrowup', 'arrowdown'];

export function useAtalhosDeTeclado({ videoRef, acoes }) {
  useEffect(() => {
    function aoTeclar(event) {
      const alvo = event.target;
      const tecla = event.key.toLowerCase();
      if (alvo instanceof HTMLButtonElement && (tecla === ' ' || tecla === 'enter')) return;
      if (alvo instanceof HTMLInputElement && TECLAS_DE_SETA.includes(tecla)) return;
      if (alvo instanceof HTMLSelectElement) return;

      const video = videoRef.current;
      if (!video) return;

      switch (tecla) {
        case ' ':
          event.preventDefault();
          acoes.alternarReproducao();
          break;
        case 'arrowleft':
          video.currentTime = Math.max(0, video.currentTime - 5);
          break;
        case 'arrowright':
          video.currentTime = Math.min(video.duration || Infinity, video.currentTime + 5);
          break;
        case 'arrowup':
          event.preventDefault();
          video.volume = Math.min(1, video.volume + 0.05);
          video.muted = false;
          break;
        case 'arrowdown':
          event.preventDefault();
          video.volume = Math.max(0, video.volume - 0.05);
          break;
        case 'f':
          acoes.alternarTelaCheia();
          break;
        case 'm':
          acoes.alternarMudo();
          break;
        case 'h':
          acoes.alternarHud();
          break;
        case 'c':
          acoes.alternarCinema();
          break;
        case 'p':
          acoes.avancarNoventa();
          break;
        default:
          break;
      }
    }

    // Clique de mouse num botão/slider da barra deixa o foco nele, e aí
    // Espaço reativaria o botão (ex.: "avançar" de novo em vez de pausar) e as
    // setas moveriam o slider em vez de buscar 5s. Soltar o foco após clique de
    // mouse (detail > 0) devolve o teclado aos atalhos globais; clique gerado
    // por teclado (detail === 0) mantém o foco, preservando a navegação por Tab.
    function aoClicar(event) {
      if (event.detail === 0) return;
      const controle = event.target instanceof Element
        ? event.target.closest('button, input[type="range"]')
        : null;
      controle?.blur();
    }

    document.addEventListener('keydown', aoTeclar);
    document.addEventListener('click', aoClicar);
    return () => {
      document.removeEventListener('keydown', aoTeclar);
      document.removeEventListener('click', aoClicar);
    };
  }, [videoRef, acoes]);
}

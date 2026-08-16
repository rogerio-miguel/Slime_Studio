import { useEffect } from 'react';

// Atalhos globais de teclado — porte do switch original (bench.js:716-758),
// mesma guarda: ignora o atalho quando o foco está num <input>/<button>
// (evita, por exemplo, Espaço acionando o clique nativo do botão focado E o
// atalho ao mesmo tempo). Também ignora <select> — diferente do protótipo
// (onde presets eram links em página separada), SeletorDePreset.jsx é um
// <select> dentro da barra de controles, e sem este guard Espaço/setas
// ficam interceptados pelo handler global e quebram a navegação nativa do
// dropdown. `acoes` contém os callbacks compartilhados com
// BarraDeControles.jsx (mesma lógica pros dois pontos de entrada, sem
// duplicar).
export function useAtalhosDeTeclado({ videoRef, acoes }) {
  useEffect(() => {
    function aoTeclar(event) {
      if (
        event.target instanceof HTMLInputElement ||
        event.target instanceof HTMLButtonElement ||
        event.target instanceof HTMLSelectElement
      )
        return;
      const video = videoRef.current;
      if (!video) return;

      switch (event.key.toLowerCase()) {
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
        default:
          break;
      }
    }

    document.addEventListener('keydown', aoTeclar);
    return () => document.removeEventListener('keydown', aoTeclar);
  }, [videoRef, acoes]);
}

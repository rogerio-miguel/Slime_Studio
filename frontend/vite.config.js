import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // anime4k-webgpu é CJS (ver comentário em player/presets.js sobre o
  // import de namespace, que é o que resolve o interop de verdade). Incluir
  // aqui só evita o reload de página que o Vite dispara quando descobre essa
  // dependência tardiamente, no primeiro import — otimização de DX, não
  // correção de bug.
  optimizeDeps: {
    include: ['anime4k-webgpu'],
  },
  server: {
    // Same-origin (dev server e API sob a mesma origem) — o cookie HttpOnly
    // de sessão viaja em qualquer request, inclusive o manifesto/segmentos
    // HLS que `player/fonteHls.js` carrega via hls.js (que roda com
    // `video.crossOrigin = 'anonymous'`; cross-origin de verdade excluiria
    // o cookie e o hls.js tomaria 401). Fase 4, ESPECIFICACAO.md §5/§10.
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      '/ws': { target: 'ws://127.0.0.1:8000', ws: true },
    },
  },
});

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
    // Sem isto o Vite cai pra 5174 quando a 5173 está ocupada, e a API (allowlist de `Origin`
    // em `api/main.py::_ORIGENS_PERMITIDAS`) passa a responder 403 às escritas.
    strictPort: true,
    // Same-origin (dev server e API sob a mesma origem) — o cookie HttpOnly
    // de sessão viaja em qualquer request, inclusive o manifesto/segmentos
    // HLS que `player/fonteHls.js` carrega via hls.js (que roda com
    // `video.crossOrigin = 'anonymous'`; cross-origin de verdade excluiria
    // o cookie e o hls.js tomaria 401). Fase 4, ESPECIFICACAO.md §5/§10.
    // `configure` registra um listener de erro em cada proxy — sem isto, um
    // EPIPE ao escrever numa conexão que já fechou do outro lado (aba
    // recarregada/fechada em pleno WS de `/ws`, backend reiniciando por
    // `--reload`) sobe como exceção não tratada no processo do Vite em vez
    // de só logar; a conexão específica ainda cai, mas o dev server não
    // deveria arriscar sair fora por causa disso.
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        configure: (proxy) =>
          proxy.on('error', (err) => console.error('[proxy /api]', err.message)),
      },
      '/ws': {
        target: 'ws://127.0.0.1:8000',
        ws: true,
        configure: (proxy) =>
          proxy.on('error', (err) => console.error('[proxy /ws]', err.message)),
      },
    },
  },
});

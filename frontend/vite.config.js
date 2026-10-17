import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

// CSP só em Report-Only: a violação aparece no console do navegador ("[Report Only] Refused
// to ..."), nada é bloqueado. Quando o console estiver limpo no uso real, trocar o nome do
// header para `Content-Security-Policy` (enforce). `frame-ancestors` e `object-src 'none'`
// valem mesmo sem script; `img-src https:` porque os CDNs de capa variam por provedor
// (AniList/TMDB/Kitsu); `blob:` em `media-src`/`worker-src` é do hls.js (MediaSource e worker).
// No dev o Vite injeta o preâmbulo do React Refresh como script inline, então só lá entra
// `'unsafe-inline'` em `script-src`.
const politicaCsp = (dev) =>
  [
    "default-src 'self'",
    `script-src 'self'${dev ? " 'unsafe-inline'" : ''}`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob: https:",
    "media-src 'self' blob:",
    "connect-src 'self'",
    "worker-src 'self' blob:",
    "font-src 'self' data:",
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'self'",
    "frame-ancestors 'none'",
  ].join('; ');

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
  // Build servido por `vite preview`: sem o `'unsafe-inline'` de script do dev.
  preview: {
    headers: { 'Content-Security-Policy-Report-Only': politicaCsp(false) },
  },
  server: {
    headers: { 'Content-Security-Policy-Report-Only': politicaCsp(true) },
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

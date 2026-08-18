import videoEntrada from '../assets/video_entrada.mp4';
import logo from '../assets/logo.png';

// Camada de fundo fixa (position: fixed; inset: 0; z-0) da Inicio — não
// sticky (ver plano). Fica atrás de todo o resto da página (spacer
// transparente, navbar, conteúdo revelado) e nunca é desmontada: o "reveal"
// é só o conteúdo normal-flow cobrindo-a conforme o usuário rola pra além do
// spacer de 300vh (paginas/Inicio.jsx).
//
// Decorativo (`aria-hidden`), sem controles, currentTime controlado
// imperativamente por useScrubDeVideo.js — nunca via state React.
//
// Um degrau mais escuro que a versão anterior em cada fase (Feature
// "continuar assistindo": a prateleira nova soma-se ao conteúdo revelado que
// já fica sobre este vídeo — `<main>` não tem fundo opaco próprio — e
// precisa de mais contraste). Ainda não opaco em nenhuma fase (o vídeo
// nunca fica totalmente escondido).
const _OPACIDADE_SCRIM_POR_FASE = {
  entrada: 'opacity-40',
  chegando: 'opacity-65',
  revelado: 'opacity-90',
};

export default function CenarioDeEntrada({ videoRef, logoRef, fase }) {
  return (
    <div aria-hidden="true" className="fixed inset-0 z-0 overflow-hidden bg-black">
      <video
        ref={videoRef}
        src={videoEntrada}
        muted
        playsInline
        preload="auto"
        tabIndex={-1}
        className="h-full w-full object-cover"
      />
      <div
        className={`absolute inset-0 bg-gradient-to-t from-black via-black/40 to-black/20 transition-opacity duration-700 ease-out ${_OPACIDADE_SCRIM_POR_FASE[fase]}`}
      />
      {/* Opacidade/escala escritas por frame em useScrubDeVideo.js (via
          logoRef), não por classe/transition — aparece perto da metade do
          scroll, como se emergisse de dentro das portas da cena. */}
      <img
        ref={logoRef}
        src={logo}
        alt=""
        className="pointer-events-none absolute inset-0 m-auto h-auto w-[min(85vw,38rem)] opacity-0"
      />
    </div>
  );
}

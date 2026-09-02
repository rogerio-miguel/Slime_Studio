import logoVideo from '../assets/logo-video.mp4';

// Camada de fundo fixa (position: fixed; inset: 0; z-0) da Inicio. Fica atrás
// de todo o resto da página (navbar, conteúdo revelado) e nunca é
// desmontada: o "reveal" é o conteúdo normal-flow (paginas/Inicio.jsx)
// cobrindo-a quando a fase vira `revelado`.
//
// O vídeo da logo toca uma vez, sem controles, e dispara `aoTerminar`
// (prop) no fim — paginas/Inicio.jsx usa isso pra virar a fase pra
// `revelado`, que dispara a transição de opacidade abaixo (fade suave: o
// vídeo dissolve e o <main> entra por baixo, não um corte).
//
// Reduced-motion (`movimentoReduzido`, prop derivada de
// inicio/useIntroPorVideo.js): o vídeo nem monta — fase já nasce `revelado`
// no hook, então este container já começa transparente.
//
// Decorativo (`aria-hidden`), sem controles.
export default function CenarioDeEntrada({ fase, movimentoReduzido, aoTerminar }) {
  return (
    <div
      aria-hidden="true"
      className={`fixed inset-0 z-0 overflow-hidden bg-black transition-opacity duration-700 ease-out ${
        fase === 'revelado' ? 'opacity-0' : 'opacity-100'
      }`}
    >
      {!movimentoReduzido && (
        <video
          src={logoVideo}
          autoPlay
          muted
          playsInline
          onEnded={aoTerminar}
          className="pointer-events-none absolute inset-0 h-full w-full object-cover"
        />
      )}
    </div>
  );
}

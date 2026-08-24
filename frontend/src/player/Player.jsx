import { useCallback, useState } from 'react';
import PlayerAtivo from './PlayerAtivo.jsx';

// Dispatcher fino: dono só de erroFatal e do guard de navigator.gpu ausente.
// Tudo que é "player em funcionamento" — refs de DOM, hooks de subsistema
// (fonte, motor WebGPU, áudio, telemetria, atalhos) e a JSX ativa — vive em
// PlayerAtivo. Quando `aoFalhar` seta erroFatal aqui, React desmonta
// PlayerAtivo por inteiro (troca de branch no return abaixo): cada efeito
// dono de um subsistema lá dentro (sessão WebGPU, grafo de áudio, loop de
// telemetria, listener de teclado, conexão HLS) limpa sozinho via o
// mecanismo de cleanup do React — não algo que precisa ser reimplementado
// com um flag `ativo` espalhado por hook.
export default function Player({
  fonte,
  titulo,
  aoAtingirAssistido,
  retomarDe,
  aoSalvarProgresso,
  focoTituloRef,
}) {
  // Checagem de navigator.gpu ausente é o primeiro guard.
  const [erroFatal, setErroFatal] = useState(() =>
    typeof navigator !== 'undefined' && !navigator.gpu
      ? 'WebGPU não está disponível neste navegador. Use Chrome/Edge com WebGPU habilitado (verifique chrome://gpu).'
      : null
  );

  const aoFalhar = useCallback((erro) => setErroFatal(erro.message), []);

  if (erroFatal) {
    return (
      <div
        role="alert"
        className="mx-auto my-10 max-w-lg rounded-lg border border-[#600] bg-[#2a0000] px-6 py-5 text-center text-[#fdd]"
      >
        {erroFatal}
      </div>
    );
  }

  return (
    <PlayerAtivo
      fonte={fonte}
      titulo={titulo}
      aoFalhar={aoFalhar}
      aoAtingirAssistido={aoAtingirAssistido}
      retomarDe={retomarDe}
      aoSalvarProgresso={aoSalvarProgresso}
      focoTituloRef={focoTituloRef}
    />
  );
}

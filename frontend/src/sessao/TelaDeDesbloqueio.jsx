import { useId, useState } from 'react';
import { NaoAutenticado } from '../api/cliente.js';
import { useFocoAoMontar } from '../hooks/useFocoAoMontar.js';
import { useSessao } from './SessaoContexto.jsx';

// Gate de acesso: renderizado no lugar de qualquer rota enquanto
// `!autenticado` (App.jsx). Token só existe em JS entre o `onChange` e o
// `await desbloquear()` — nunca persistido, nunca logado.
export default function TelaDeDesbloqueio() {
  const { desbloquear } = useSessao();
  const [token, setToken] = useState('');
  const [erro, setErro] = useState(null);
  const [enviando, setEnviando] = useState(false);
  const focoTitulo = useFocoAoMontar();
  const idCampo = useId();

  async function aoSubmeter(event) {
    event.preventDefault();
    if (!token.trim() || enviando) return;
    setEnviando(true);
    setErro(null);
    try {
      await desbloquear(token.trim());
    } catch (erroCapturado) {
      const mensagem =
        erroCapturado instanceof NaoAutenticado
          ? 'Token inválido.'
          : 'Não foi possível verificar o token — tente novamente.';
      setErro(mensagem);
      console.error('falha ao desbloquear sessão', erroCapturado);
    } finally {
      setToken('');
      setEnviando(false);
    }
  }

  return (
    <div className="mx-auto flex max-w-sm flex-col items-center gap-6 px-6 py-20 text-center">
      <h1 ref={focoTitulo} tabIndex={-1} className="text-xl font-medium text-white outline-none">
        Slime Studio
      </h1>
      <form onSubmit={aoSubmeter} className="flex w-full flex-col gap-3">
        <label htmlFor={idCampo} className="text-left text-sm text-ink-muted">
          Token de acesso
        </label>
        <input
          id={idCampo}
          type="password"
          autoComplete="current-password"
          value={token}
          onChange={(event) => setToken(event.target.value)}
          className="rounded-md border border-border-chrome bg-surface px-3 py-2 text-sm text-white outline-none focus-visible:border-neon focus-visible:ring-2 focus-visible:ring-neon"
        />
        {erro && (
          <p role="alert" className="text-left text-sm text-red-400">
            {erro}
          </p>
        )}
        <button
          type="submit"
          disabled={enviando}
          className="rounded-md border border-neon-soft bg-surface px-4 py-2 text-sm font-semibold text-neon outline-none transition-colors hover:border-neon disabled:cursor-not-allowed disabled:opacity-50 focus-visible:ring-2 focus-visible:ring-neon"
        >
          {enviando ? 'Verificando…' : 'Desbloquear'}
        </button>
      </form>
    </div>
  );
}

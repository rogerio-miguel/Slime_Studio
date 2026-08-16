import { createContext, useCallback, useContext, useEffect, useState } from 'react';
import { definirTratadorDeSessaoExpirada } from '../api/cliente.js';
import { desbloquear as desbloquearNaApi, obterEstadoSessao, sair as sairNaApi } from '../api/recursos.js';

const SessaoContext = createContext(null);

// Único ponto que sabe o estado de autenticação. Boot consulta
// `GET /api/auth/estado` (contrato confirmado: nunca 401, então sem
// tratamento de erro de autenticação aqui — só de rede/servidor fora do
// ar). Registra o callback que `cliente.js` dispara em QUALQUER 401 (REST
// direto, ou repassado de `useEventosDeJobs.js` no close 1008 do WS), sem
// precisar de prop drilling do estado de sessão até cada chamador.
export function SessaoProvider({ children }) {
  const [autenticado, setAutenticado] = useState(false);
  const [carregando, setCarregando] = useState(true);

  useEffect(() => {
    definirTratadorDeSessaoExpirada(() => setAutenticado(false));
    return () => definirTratadorDeSessaoExpirada(null);
  }, []);

  useEffect(() => {
    let cancelado = false;
    obterEstadoSessao()
      .then((estado) => {
        if (!cancelado) setAutenticado(estado.autenticado);
      })
      .catch((erro) => {
        console.error('falha ao consultar estado de sessão', erro);
      })
      .finally(() => {
        if (!cancelado) setCarregando(false);
      });
    return () => {
      cancelado = true;
    };
  }, []);

  // Token nunca vive em JS além do instante deste `await` — quem chama
  // (TelaDeDesbloqueio.jsx) descarta o valor do campo logo em seguida,
  // sucesso ou falha.
  const desbloquear = useCallback(async (token) => {
    await desbloquearNaApi(token);
    setAutenticado(true);
  }, []);

  const sair = useCallback(async () => {
    try {
      await sairNaApi();
    } finally {
      setAutenticado(false);
    }
  }, []);

  return (
    <SessaoContext.Provider value={{ autenticado, carregando, desbloquear, sair }}>
      {children}
    </SessaoContext.Provider>
  );
}

export function useSessao() {
  const contexto = useContext(SessaoContext);
  if (!contexto) throw new Error('useSessao precisa estar dentro de <SessaoProvider>');
  return contexto;
}

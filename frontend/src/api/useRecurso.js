import { useCallback, useEffect, useState } from 'react';
import { escutar } from './invalidacao.js';

// Cobre o caminho comum de "GET com loading/erro/dados" nas páginas — não é
// um client de cache genérico (SWR/React Query seriam overkill pro tamanho
// do projeto, Escada de Minimalismo do CLAUDE.md). `buscar` é reinvocado
// sempre que algo em `deps` muda; `recarregar()` força uma nova chamada sem
// depender de mudança de dependência (ex. após um POST que altera o mesmo
// recurso).
//
// `chave` (opcional, string ou array de strings) assina `invalidacao.js`: se
// alguma mutação em `api/recursos.js` invalidar essa chave enquanto este
// hook está montado, ele recarrega sozinho — cobre o caso de a escrita ter
// sido disparada por OUTRA página, já desmontada (ex. sair do player fecha
// `PaginaDoPlayer.jsx` antes do POST de saída resolver; quando resolve, a
// `PaginaDoAnime.jsx` já montada reage). Sem `chave`, comportamento idêntico
// ao anterior.
export function useRecurso(buscar, deps, chave) {
  const [dados, setDados] = useState(null);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState(null);
  const [versao, setVersao] = useState(0);

  const recarregar = useCallback(() => setVersao((v) => v + 1), []);

  useEffect(() => {
    let cancelado = false;
    setCarregando(true);
    setErro(null);
    buscar()
      .then((resultado) => {
        if (!cancelado) setDados(resultado);
      })
      .catch((erroCapturado) => {
        if (!cancelado) setErro(erroCapturado);
      })
      .finally(() => {
        if (!cancelado) setCarregando(false);
      });
    return () => {
      cancelado = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, versao]);

  const chaves = chave == null ? [] : Array.isArray(chave) ? chave : [chave];
  useEffect(() => {
    const cancelar = chaves.map((c) => escutar(c, recarregar));
    return () => cancelar.forEach((fn) => fn());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chaves.join(','), recarregar]);

  return { dados, carregando, erro, recarregar };
}

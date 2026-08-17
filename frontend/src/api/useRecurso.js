import { useCallback, useEffect, useState } from 'react';

// Cobre o caminho comum de "GET com loading/erro/dados" nas páginas — não é
// um client de cache genérico (SWR/React Query seriam overkill pro tamanho
// do projeto, Escada de Minimalismo do CLAUDE.md). `buscar` é reinvocado
// sempre que algo em `deps` muda; `recarregar()` força uma nova chamada sem
// depender de mudança de dependência (ex. após um POST que altera o mesmo
// recurso).
export function useRecurso(buscar, deps) {
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

  return { dados, carregando, erro, recarregar };
}

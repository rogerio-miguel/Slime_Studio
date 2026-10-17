import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { buscarAnimes } from '../api/recursos.js';
import { useRecurso } from '../api/useRecurso.js';

// Estado da busca da navbar (Início e Descobrir; a Galeria só filtra o próprio
// catálogo). A busca na AniList só dispara no submit (Enter na navbar) — evita
// martelar a AniList a cada tecla. Limpa junto com o campo pra não deixar resultado
// de busca antiga visível depois que o usuário apaga tudo.
//
// Os resultados trocam a página inteira, o que encolhe o documento e o navegador joga
// a rolagem pro topo; por isso a posição é guardada ao começar a digitar e devolvida
// quando a busca é apagada (e a página dos resultados começa no topo).
export function useBuscaDeAnimes() {
  const [termoBusca, setTermoBusca] = useState('');
  const termoBuscaNormalizado = termoBusca.trim().toLowerCase();
  const buscando = termoBuscaNormalizado !== '';

  const rolagemAntesDaBuscaRef = useRef(null);
  const alterarTermoBusca = useCallback(
    (valor) => {
      if (valor.trim() !== '' && !buscando) {
        rolagemAntesDaBuscaRef.current = window.scrollY;
        window.scrollTo({ top: 0, behavior: 'instant' });
      }
      setTermoBusca(valor);
    },
    [buscando],
  );
  useLayoutEffect(() => {
    if (buscando || rolagemAntesDaBuscaRef.current === null) return;
    window.scrollTo({ top: rolagemAntesDaBuscaRef.current, behavior: 'instant' });
    rolagemAntesDaBuscaRef.current = null;
  }, [buscando]);

  const [termoBuscaSubmetido, setTermoBuscaSubmetido] = useState('');
  useEffect(() => {
    if (termoBuscaNormalizado === '') setTermoBuscaSubmetido('');
  }, [termoBuscaNormalizado]);

  const submeterBusca = useCallback(() => {
    setTermoBuscaSubmetido(termoBusca.trim());
  }, [termoBusca]);

  const buscaBiblioteca = useRecurso(
    () => (termoBuscaSubmetido ? buscarAnimes(termoBuscaSubmetido) : Promise.resolve([])),
    [termoBuscaSubmetido],
  );

  // Guarda contra o campo ter sido editado depois do último Enter: enquanto
  // `termoBusca` diverge de `termoBuscaSubmetido`, os cards de
  // `buscaBiblioteca.dados` são de uma busca antiga e não devem ser
  // renderizados (risco de materializar o anime errado) — a seção mostra um
  // aviso de "desatualizado" no lugar até o usuário apertar Enter de novo.
  const resultadosDesatualizados =
    termoBuscaSubmetido !== '' && termoBusca.trim() !== termoBuscaSubmetido;

  return {
    termoBusca,
    setTermoBusca: alterarTermoBusca,
    termoBuscaNormalizado,
    buscando,
    termoBuscaSubmetido,
    submeterBusca,
    buscaBiblioteca,
    resultadosBiblioteca: buscaBiblioteca.dados ?? [],
    resultadosDesatualizados,
    buscaBibliotecaAtiva: termoBuscaSubmetido !== '' && !resultadosDesatualizados,
  };
}

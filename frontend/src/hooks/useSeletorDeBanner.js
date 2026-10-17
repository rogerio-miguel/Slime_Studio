import { useCallback, useEffect, useState } from 'react';
import { escolherBanner, listarBannersDoAnime, restaurarBanner } from '../api/recursos.js';
import { useRecurso } from '../api/useRecurso.js';
import { imagemEmAltaResolucao } from '../inicio/CarrosselDestaques.jsx';

// Estado do modo "Trocar banner" da página do anime. Nesse modo as opções e os
// botões aparecem na ilha da navbar (`components/SeletorDeBanner.jsx`) e o PRÓPRIO
// hero da página mostra ao vivo a opção marcada (`urlDaPrevia`). As opções vêm do TMDB já ordenadas pelo servidor
// (`GET /api/animes/{id}/banners`) e a escolha vale para a franquia inteira. O que
// vai ao servidor é o `arquivo` do candidato, nunca uma URL.
//
// "Aplicar" só habilita com uma escolha diferente da atual (`podeAplicar`), pra
// não gravar sem querer. Esc cancela, exceto com a gravação em voo.
export function useSeletorDeBanner({ aberto, animeId, bannerAtual, aoSalvar, aoFechar }) {
  const [escolhido, setEscolhido] = useState(null);
  const [salvando, setSalvando] = useState(false);
  const [erroAoSalvar, setErroAoSalvar] = useState(null);

  // Sem isto, a escolha (ou o erro) de uma abertura anterior vazaria pra próxima.
  useEffect(() => {
    if (!aberto) return;
    setEscolhido(null);
    setErroAoSalvar(null);
  }, [aberto]);

  const busca = useRecurso(
    () => (aberto ? listarBannersDoAnime(animeId) : Promise.resolve([])),
    [aberto, animeId]
  );
  const carregando = aberto && busca.carregando;
  const erroAoBuscar = aberto && !busca.carregando && busca.erro != null;
  const candidatos = aberto && !busca.carregando && busca.erro == null ? (busca.dados ?? []) : null;

  // A URL salva é `.../original/<arquivo>`; o candidato é identificado só pelo `arquivo`.
  const arquivoAtual =
    candidatos?.find((candidato) => bannerAtual?.endsWith(candidato.arquivo))?.arquivo ?? null;
  const selecionado = escolhido ?? arquivoAtual;

  // Arte do hero ao vivo: a opção marcada, na MESMA resolução que o hero usa depois de
  // aplicada (`imagemEmAltaResolucao`, `original`) — com w1280 a prévia ficava mais
  // mole que o resultado. `null` = a arte real do anime.
  const candidatoEscolhido = candidatos?.find((c) => c.arquivo === escolhido);
  const urlDaPrevia =
    aberto && candidatoEscolhido ? imagemEmAltaResolucao(candidatoEscolhido.miniatura_url) : null;

  const executar = async (acao) => {
    setSalvando(true);
    setErroAoSalvar(null);
    try {
      await acao();
      aoSalvar();
    } catch (erroCapturado) {
      console.error('falha ao salvar o banner', erroCapturado);
      setErroAoSalvar('Não foi possível salvar o banner — tente novamente.');
    } finally {
      setSalvando(false);
    }
  };

  const cancelar = useCallback(() => {
    if (!salvando) aoFechar();
  }, [salvando, aoFechar]);

  useEffect(() => {
    if (!aberto) return undefined;
    const aoTeclar = (evento) => {
      if (evento.key === 'Escape') cancelar();
    };
    document.addEventListener('keydown', aoTeclar);
    return () => document.removeEventListener('keydown', aoTeclar);
  }, [aberto, cancelar]);

  return {
    candidatos,
    carregando,
    erroAoBuscar,
    recarregar: busca.recarregar,
    selecionado,
    arquivoAtual,
    urlDaPrevia,
    salvando,
    erroAoSalvar,
    podeAplicar: escolhido != null && escolhido !== arquivoAtual,
    escolher: setEscolhido,
    aplicar: () => executar(() => escolherBanner(animeId, escolhido)),
    restaurar: () => executar(() => restaurarBanner(animeId)),
    cancelar,
  };
}

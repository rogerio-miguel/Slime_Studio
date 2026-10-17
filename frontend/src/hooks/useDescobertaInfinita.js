import { useCallback, useEffect, useRef, useState } from 'react';
import { listarDescoberta } from '../api/recursos.js';
import { chaveDoItemDoFeed } from '../inicio/fileiras.js';

// Grade da Descobrir com carregamento ao rolar. O backend entrega páginas de 50
// (uma chamada à AniList cada); a grade revela 20 por vez (`revelarMais`) a partir
// do que já foi carregado, e a página seguinte é buscada ANTES de o usuário chegar
// nela — sempre que sobram menos de `TAMANHO_DO_LOTE` cards por revelar — então a
// rolagem quase nunca espera a rede. Trocar `genero` zera tudo e recomeça da página
// 1; resposta de um gênero anterior que chega depois da troca é descartada
// (`geracaoRef`). Na troca o conteúdo ANTIGO fica na tela (`trocando` = true) até a
// página 1 do gênero novo chegar e substituí-lo — esvaziar na hora deixava a página
// preta pelo tempo da API. `versao` sobe quando a página 1 resolve: quem exibe o conteúdo
// (parede do cabeçalho e grade) troca de camada em crossfade nesse momento.
// Item repetido entre páginas (a popularidade se mexe entre as buscas) é descartado.
const TAMANHO_DO_LOTE = 20;

export function useDescobertaInfinita(genero) {
  const [carregados, setCarregados] = useState([]);
  const [quantidadeVisivel, setQuantidadeVisivel] = useState(TAMANHO_DO_LOTE);
  // Sobe a cada página 1 resolvida (chegou ou falhou): é a identidade do "conteúdo do
  // gênero atual" pra o cabeçalho e a grade trocarem em crossfade.
  const [versao, setVersao] = useState(0);
  const [temMaisNoServidor, setTemMaisNoServidor] = useState(true);
  const [buscando, setBuscando] = useState(false);
  // `true` até a página 1 do gênero atual chegar (ou falhar): o que está em
  // `carregados` ainda é do gênero anterior (ou não há nada, na 1ª carga).
  const [trocando, setTrocando] = useState(true);
  const [erro, setErro] = useState(null);
  const proximaPaginaRef = useRef(1);
  const geracaoRef = useRef(0);
  // Geração da requisição em voo (`null` = nenhuma): trava pedidos duplicados do
  // mesmo gênero sem travar o primeiro pedido do gênero novo.
  const emVooRef = useRef(null);

  const buscarProximaPagina = useCallback(async () => {
    const geracao = geracaoRef.current;
    if (emVooRef.current === geracao) return;
    emVooRef.current = geracao;
    const numero = proximaPaginaRef.current;
    setBuscando(true);
    setErro(null);
    try {
      const pagina = await listarDescoberta({ genero, pagina: numero });
      if (geracao !== geracaoRef.current) return;
      proximaPaginaRef.current = numero + 1;
      if (numero === 1) {
        setCarregados(pagina.itens);
        setQuantidadeVisivel(TAMANHO_DO_LOTE);
        setVersao((atual) => atual + 1);
        setTrocando(false);
      } else {
        setCarregados((atual) => {
          const vistos = new Set(atual.map(chaveDoItemDoFeed));
          return [...atual, ...pagina.itens.filter((item) => !vistos.has(chaveDoItemDoFeed(item)))];
        });
      }
      setTemMaisNoServidor(pagina.tem_mais);
    } catch (erroCapturado) {
      if (geracao === geracaoRef.current) {
        setErro(erroCapturado);
        if (numero === 1) {
          // Sem a página 1 não há o que mostrar do gênero novo; o conteúdo antigo
          // sairia errado ao lado do erro.
          setCarregados([]);
          setVersao((atual) => atual + 1);
          setTrocando(false);
        }
      }
    } finally {
      if (geracao === geracaoRef.current) setBuscando(false);
      if (emVooRef.current === geracao) emVooRef.current = null;
    }
  }, [genero]);

  // Declarado ANTES do efeito de busca: numa troca de gênero o reset roda primeiro.
  useEffect(() => {
    geracaoRef.current += 1;
    proximaPaginaRef.current = 1;
    setTrocando(true);
    setTemMaisNoServidor(true);
    setErro(null);
  }, [genero]);

  // Primeira página e adiantamento das seguintes. Não tenta de novo sozinho depois
  // de um erro (o botão "Tentar novamente" é quem chama `buscarProximaPagina`).
  const faltamPorRevelar = carregados.length - quantidadeVisivel;
  useEffect(() => {
    if ((trocando || faltamPorRevelar < TAMANHO_DO_LOTE) && temMaisNoServidor && !buscando && !erro) {
      buscarProximaPagina();
    }
  }, [trocando, faltamPorRevelar, temMaisNoServidor, buscando, erro, buscarProximaPagina]);

  const revelarMais = useCallback(() => {
    setQuantidadeVisivel((atual) => atual + TAMANHO_DO_LOTE);
  }, []);

  return {
    itens: carregados.slice(0, quantidadeVisivel),
    // Tudo que já chegou do servidor (não só o que a grade revelou): é o que a parede do
    // cabeçalho usa, e ela cresce conforme as páginas vêm.
    todosCarregados: carregados,
    versao,
    // Durante a troca o fim da grade é do gênero antigo: não pede nem revela mais.
    temMais: !trocando && (faltamPorRevelar > 0 || temMaisNoServidor),
    // Só "carregando" quando não há nada na tela, ou o usuário esgotou o que tinha e
    // espera a rede. Na troca, o conteúdo antigo cobre a espera (`trocando`).
    carregando: buscando && (carregados.length === 0 || (!trocando && faltamPorRevelar <= 0)),
    trocando,
    erro,
    carregarMais: revelarMais,
    tentarNovamente: buscarProximaPagina,
  };
}

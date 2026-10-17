import { useCallback, useEffect, useRef, useState } from 'react';
import AnimeCard from '../components/AnimeCard.jsx';
import BarraDeNavegacao from '../components/BarraDeNavegacao.jsx';
import BotaoDeEstado from '../components/mascote/BotaoDeEstado.jsx';
import EstadoComMascote from '../components/mascote/EstadoComMascote.jsx';
import { useBuscaDeAnimes } from '../hooks/useBuscaDeAnimes.js';
import { useDescobertaInfinita } from '../hooks/useDescobertaInfinita.js';
import { useMaterializarAnime } from '../hooks/useMaterializarAnime.js';
import { useStatusDeCapturaIlha } from '../hooks/useStatusDeCapturaIlha.js';
import CabecalhoDeDescobrir from '../inicio/CabecalhoDeDescobrir.jsx';
import TrocaComCrossfade from '../inicio/TrocaComCrossfade.jsx';
import { chaveDoItemDoFeed } from '../inicio/fileiras.js';
import { GENEROS_DE_DESCOBERTA, traduzirGenero } from '../inicio/generos.js';
import GradeDeCatalogo from '../inicio/GradeDeCatalogo.jsx';
import ResultadosDaBusca from '../inicio/ResultadosDaBusca.jsx';
import { PADDING_TITULO_GRADE } from '../inicio/tamanhoDeCard.js';
import { usePrefersReducedMotion } from '../inicio/usePrefersReducedMotion.js';

// Rota "/descobrir" — no lugar do antigo link "Gêneros". Uma grade só, por
// popularidade, que carrega mais ao rolar (`GET /api/animes/descobrir`, páginas de 50
// reveladas 20 a 20 com a seguinte adiantada, hooks/useDescobertaInfinita.js). Os chips do cabeçalho escolhem o gênero;
// a grade recomeça nele, também sem fim. Sem as fileiras temáticas: o endpoint
// `/fileiras-tematicas` e `inicio/fileirasTematicas.js` seguem existindo, só não
// são usados aqui.
//
// Clicar num item não catalogado materializa o anime e navega (mesmo fluxo da Home,
// hooks/useMaterializarAnime.js); item já catalogado vira <Link> direto no próprio
// `AnimeCard`. A busca da navbar (hooks/useBuscaDeAnimes.js) é a mesma da Home: digitar
// troca a página inteira (cabeçalho e grade) pelos resultados (inicio/ResultadosDaBusca.jsx)
// e esconde o filtro de gênero da ilha, que não se aplica a ela.

// Quanto antes do fim da grade o próximo lote é pedido: o usuário não chega a ver o fim.
const ANTECEDENCIA_DO_CARREGAMENTO = '800px 0px';

// Painel de gêneros da ilha da navbar (o mesmo da Galeria, ilha/RegiaoDoPainelDeFiltros.jsx):
// mesmas opções dos chips do cabeçalho ("Todos" = valor vazio, como no filtro da
// Galeria).
const OPCOES_DE_GENERO = [
  { valor: '', rotulo: 'Todos' },
  ...GENEROS_DE_DESCOBERTA.map((genero) => ({ valor: genero, rotulo: traduzirGenero(genero) })),
];

export default function Descobrir({ jobsPorEpisodio, snapshotId }) {
  const {
    statusCapturaIlha,
    aoClicarStatusCapturaIlha,
    capturaProntaIlha,
    aoClicarCapturaProntaIlha,
    erroCapturaIlha,
    aoClicarErroCapturaIlha,
  } = useStatusDeCapturaIlha(jobsPorEpisodio, snapshotId);
  const materializacao = useMaterializarAnime();
  const { materializarEIrPara, chaveEmMaterializacao, erro: erroMaterializacao } = materializacao;
  const busca = useBuscaDeAnimes();
  const { termoBusca, setTermoBusca, buscando, submeterBusca } = busca;

  const movimentoReduzido = usePrefersReducedMotion();
  const [generoEscolhido, setGeneroEscolhido] = useState(null);
  // Fica `true` até a animação de volta do painel terminar (`aoFechar`), não só até o
  // pedido de fechar — mesmo contrato do painel da Galeria.
  const [painelAberto, setPainelAberto] = useState(false);
  // Chips e menu da ilha chamam o mesmo: a grade recomeça no gênero novo e a página
  // volta ao topo (onde o cabeçalho já mostra a parede dele).
  const escolherGenero = useCallback(
    (genero) => {
      setGeneroEscolhido(genero);
      window.scrollTo({ top: 0, behavior: movimentoReduzido ? 'auto' : 'smooth' });
    },
    [movimentoReduzido],
  );
  const {
    itens,
    todosCarregados,
    versao,
    temMais,
    carregando,
    trocando,
    erro,
    carregarMais,
    tentarNovamente,
  } =
    useDescobertaInfinita(generoEscolhido);

  // Observador do fim da grade. Recriado a cada lote (`itens.length`): se a grade
  // ainda não passa da tela, o novo observador dispara na hora e pede o seguinte.
  const fimRef = useRef(null);
  useEffect(() => {
    const fim = fimRef.current;
    if (!fim || !temMais || carregando || erro) return undefined;
    const observador = new IntersectionObserver(
      ([entrada]) => {
        if (entrada.isIntersecting) carregarMais();
      },
      { rootMargin: ANTECEDENCIA_DO_CARREGAMENTO },
    );
    observador.observe(fim);
    return () => observador.disconnect();
  }, [temMais, carregando, erro, carregarMais, itens.length]);

  const renderCard = (item) => (
    <AnimeCard
      anime={{ titulo: item.titulo_romaji, capa_url: item.capa_url, anime_id: item.anime_id }}
      aoAtivar={() => materializarEIrPara(item)}
      desabilitado={chaveEmMaterializacao === chaveDoItemDoFeed(item)}
      indicarCatalogado
    />
  );

  const primeiroCarregamento = itens.length === 0 && carregando;
  const recuoDoTexto = { paddingInline: PADDING_TITULO_GRADE };

  return (
    <>
      <BarraDeNavegacao
        transparente
        filtroSelecionado={generoEscolhido ?? ''}
        aoMudarFiltro={(valor) => escolherGenero(valor || null)}
        termoBusca={termoBusca}
        aoMudarBusca={(valor) => {
          setTermoBusca(valor);
          // O painel de gêneros some durante a busca; fechado, não reaparece aberto depois.
          if (valor) setPainelAberto(false);
        }}
        aoSubmeterBusca={submeterBusca}
        opcoesFiltro={buscando ? undefined : OPCOES_DE_GENERO}
        painelDeFiltros={buscando ? undefined : {
          aberto: painelAberto,
          aoAbrir: () => setPainelAberto(true),
          aoFechar: () => setPainelAberto(false),
          resumo: generoEscolhido ? traduzirGenero(generoEscolhido) : 'Todos os gêneros',
          filtrosAtivos: generoEscolhido ? 1 : 0,
          aoLimpar: () => escolherGenero(null),
          tituloDoFiltro: 'Gênero',
          rotuloAberto: 'Gêneros',
          rotuloAcessivel: 'Filtrar por gênero',
        }}
        statusCapturaIlha={statusCapturaIlha}
        aoClicarStatusCapturaIlha={aoClicarStatusCapturaIlha}
        capturaProntaIlha={capturaProntaIlha}
        aoClicarCapturaProntaIlha={aoClicarCapturaProntaIlha}
        erroCapturaIlha={erroCapturaIlha}
        aoClicarErroCapturaIlha={aoClicarErroCapturaIlha}
      />

      <main className={`relative z-10 min-h-screen bg-black ${buscando ? 'pt-22' : 'pb-20'}`}>
        {buscando ? (
          <ResultadosDaBusca busca={busca} materializacao={materializacao} />
        ) : (
          <>
            <CabecalhoDeDescobrir
              itensDeFundo={todosCarregados}
              versao={versao}
              generos={GENEROS_DE_DESCOBERTA}
              generoEscolhido={generoEscolhido}
              aoEscolherGenero={escolherGenero}
              erro={erroMaterializacao}
            />

            {/* `relative z-10`: o cabeçalho tem `-mb-32` (o topo da grade espia sob o fade,
                como na página do anime) e, sendo posicionado, pintaria por cima do que
                vem depois sem isto. */}
            <section aria-labelledby="titulo-da-grade" className="relative z-10 mt-10">
              <h2
                id="titulo-da-grade"
                style={recuoDoTexto}
                className="text-2xl font-semibold text-white"
              >
                {generoEscolhido ? traduzirGenero(generoEscolhido) : 'Mais populares'}
              </h2>

              {primeiroCarregamento && (
                <p style={recuoDoTexto} className="mt-6 text-sm text-ink-muted">
                  Carregando títulos…
                </p>
              )}

              {erro && itens.length === 0 && (
                <div style={recuoDoTexto} className="mt-6">
                  <EstadoComMascote alerta mensagem="Não foi possível carregar os títulos.">
                    <BotaoDeEstado onClick={tentarNovamente}>Tentar novamente</BotaoDeEstado>
                  </EstadoComMascote>
                </div>
              )}

              {!carregando && !erro && itens.length === 0 && (
                <div style={recuoDoTexto} className="mt-6">
                  <EstadoComMascote mensagem="Nenhum título encontrado neste gênero." />
                </div>
              )}

              {/* Na troca de gênero os cards antigos ficam na tela (levemente esmaecidos e sem
                  clique) até a lista nova chegar; quando chega, as duas camadas trocam em
                  crossfade (inicio/TrocaComCrossfade.jsx) — nunca há tela vazia. A camada
                  que sai é cortada na altura de uma tela pra não esticar a página. */}
              <div
                aria-busy={trocando}
                className={`relative transition-opacity duration-300 ${trocando ? 'pointer-events-none opacity-70' : 'opacity-100'}`}
              >
                <TrocaComCrossfade
                  chave={versao}
                  classeDaCamadaSaindo="absolute inset-x-0 top-0 max-h-svh overflow-hidden"
                >
                  <GradeDeCatalogo
                    itens={itens}
                    tamanho="pequeno"
                    comSombra={false}
                    comAnimacao={false}
                    chaveDoItem={chaveDoItemDoFeed}
                    renderItem={renderCard}
                  />
                </TrocaComCrossfade>
              </div>

              {/* Fim da grade: o observador pede o próximo lote (`temMais`), e os dois
                  estados terminais têm o slime, como nos outros estados vazios do app. */}
              {itens.length > 0 && temMais && !erro && (
                <div ref={fimRef} aria-hidden="true" className="h-px" />
              )}
              {itens.length > 0 && carregando && (
                <p role="status" style={recuoDoTexto} className="text-sm text-ink-muted">
                  Carregando mais…
                </p>
              )}
              {itens.length > 0 && erro && (
                <EstadoComMascote alerta compacto mensagem="Não foi possível carregar mais títulos.">
                  <BotaoDeEstado onClick={tentarNovamente}>Tentar novamente</BotaoDeEstado>
                </EstadoComMascote>
              )}
              {itens.length > 0 && !temMais && !erro && (
                <EstadoComMascote compacto mensagem="Você chegou ao fim da lista." />
              )}
            </section>
          </>
        )}
      </main>
    </>
  );
}

import { useCallback, useEffect, useId, useMemo, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import {
  buscarAnimes,
  criarAnime,
  listarAnimes,
  listarAnimesEmAlta,
  listarContinuarAssistindo,
  listarFileirasTematicas,
  listarProximaTemporada,
} from '../api/recursos.js';
import { useRecurso } from '../api/useRecurso.js';
import AnimeCard from '../components/AnimeCard.jsx';
import BarraDeNavegacao from '../components/BarraDeNavegacao.jsx';
import CartaoContinuarAssistindo from '../components/CartaoContinuarAssistindo.jsx';
import CenarioDeEntrada from '../inicio/CenarioDeEntrada.jsx';
// DestaquePrincipal desativado temporariamente (pivot de produto, Fase 4) —
// o arquivo continua em inicio/DestaquePrincipal.jsx, não é código morto,
// só não é renderizado por enquanto.
import CarrosselDestaques from '../inicio/CarrosselDestaques.jsx';
import CartaoDeEstreia from '../inicio/CartaoDeEstreia.jsx';
import DestaqueGrande from '../inicio/DestaqueGrande.jsx';
import FileiraDeCards from '../inicio/FileiraDeCards.jsx';
import { topDaTemporada } from '../inicio/fileiras.js';
import { rotularFileiras } from '../inicio/fileirasTematicas.js';
import GradeDeCatalogo from '../inicio/GradeDeCatalogo.jsx';
import { intercalarDestaques } from '../inicio/intercalarDestaques.js';
import { recorteVisivelDoCarrossel } from '../inicio/janelaDeDestaques.js';
import { PADDING_TITULO_GRADE } from '../inicio/tamanhoDeCard.js';
import { useIntroPorVideo } from '../inicio/useIntroPorVideo.js';

// Rota "/" — introdução cinematográfica tocada por vídeo: fundo preto sólido
// com o vídeo da logo (inicio/CenarioDeEntrada.jsx) tocando uma vez; ao
// terminar, a interface principal do streaming (navbar + carrossel hero
// "Destaques da temporada") aparece suavemente (fade de opacidade). O hook
// inicio/useIntroPorVideo.js só deriva as 2 fases (entrada/revelado).
//
// Conteúdo (branch `!buscando`): o carrossel hero seguido das fileiras
// horizontais (inicio/FileiraDeCards.jsx), nesta ordem — "Próximas estreias",
// "Continuar assistindo", "Top 10 da semana", fileiras temáticas ("Isekai",
// "Família encontrada" etc.). "Top 10" é recorte puro do feed
// `GET /api/animes/em-alta` (inicio/fileiras.js); "Próximas estreias" vem do
// feed próprio `GET /api/animes/proxima-temporada` (próxima temporada da
// AniList — o feed "em alta" só traz o que já está no ar); "Continuar
// assistindo" de `GET /api/episodios/continuar-assistindo`; as fileiras
// temáticas vêm de `GET /api/animes/fileiras-tematicas`, uma por tema
// pré-definido no backend, traduzidas e recortadas em
// inicio/fileirasTematicas.js. Cada fileira some sozinha quando sua lista
// está vazia (guard no próprio FileiraDeCards). As fileiras por gênero
// (`fileirasPorGenero` em fileiras.js) saíram da Home e ainda não têm página
// nova — a função segue exportada, o render não.
//
// "Destaques grandes" (inicio/DestaqueGrande.jsx) — 2 cards banner+info,
// seção ADICIONAL que não substitui carrossel nem "Top 10": 2 itens
// ALEATÓRIOS (amostraAleatoria) do feed `em-alta` INTEIRO menos o recorte que
// o carrossel exibe agora (recorteVisivelDoCarrossel) — de propósito NÃO
// repete os animes do carrossel. Fica intercalada ao longo de TODAS as
// fileiras da home (`fileirasDaHome` — "Próximas estreias", "Continuar
// assistindo", "Top 10" e as temáticas), não só as temáticas, via
// inicio/intercalarDestaques.js. Some sozinha quando não sobra item fora do
// recorte do carrossel (mesma exibição silenciosa).
// "Seu catálogo" segue FORA da Inicio de propósito — o catálogo local (listar,
// abrir, remover) mora inteiro em `paginas/Galeria.jsx` (rota "/animes",
// linkada na navbar). `DestaquePrincipal` também não está nesta ordem (pivot
// de produto anterior) — ver import comentado abaixo.
//
// Busca ao vivo (navbar, controlada aqui): digitar substitui inteiramente
// "Destaques da temporada" por (1) uma grade sobre o catálogo LOCAL
// (`listarAnimes`, filtro em memória a cada tecla) e (2) "Adicionar da
// biblioteca" — busca na AniList (`buscarAnimes`, só no Enter), cujos cards
// materializam o anime no catálogo ao clicar (`materializarEIrPara`, mesmo
// fluxo dos cards do feed). Sem `aoRemover` nos resultados, de propósito: a
// gestão do catálogo (remover) fica centralizada em
// `Galeria.jsx`/`PaginaDoAnime.jsx`, esta página não duplica isso.
//
// Fronteira Clean Architecture (D5 do plano): esta página e tudo em
// src/inicio/ só importam de src/api/, components/ e react-router-dom —
// nada de src/player/ (a única ligação com o player é a rota
// "/assistir/:episodioId", string, não import).

// Sorteia `tamanho` itens distintos de `lista`, sem repetir e sem mutar a
// entrada (`[...lista]` antes do `splice`). Usada só pelos "destaques
// grandes" (ver `destaquesGrandes` abaixo) — função pura, testável sem
// precisar montar o componente.
function amostraAleatoria(lista, tamanho) {
  const copia = [...lista];
  const amostra = [];
  while (amostra.length < tamanho && copia.length > 0) {
    const indice = Math.floor(Math.random() * copia.length);
    amostra.push(copia.splice(indice, 1)[0]);
  }
  return amostra;
}

export default function Inicio() {
  const navigate = useNavigate();
  const idResultadosBiblioteca = useId();
  const { fase, movimentoReduzido, revelar } = useIntroPorVideo();
  const location = useLocation();

  // Clique na logo (BarraDeNavegacao.jsx) navega pra "/" com
  // `state.revelado` — em vez de reiniciar a introdução do zero, pula
  // direto pro estado final (mesmo mecanismo do botão "Pular introdução").
  // `replace` limpa o state depois de consumido, senão um refresh ou
  // "voltar" do navegador reexecutaria o pulo.
  useEffect(() => {
    if (location.state?.revelado) {
      revelar();
      navigate('.', { replace: true, state: null });
    }
  }, [location.state, revelar, navigate]);

  const emAlta = useRecurso(listarAnimesEmAlta, []);
  const catalogo = useRecurso(listarAnimes, []);
  // Prateleira "Continuar assistindo" — independente do feed `em-alta`
  // (posição em episódio já capturado). Mesma exibição silenciosa da
  // Galeria: em carregando/erro/vazio a fileira simplesmente não aparece.
  const continuando = useRecurso(listarContinuarAssistindo, []);
  // "Próximas estreias" — feed próprio da próxima temporada da AniList (não
  // sai do feed `em-alta`, que só lista o que já está no ar). Mesma exibição
  // silenciosa: em carregando/erro/vazio a fileira não aparece.
  const proximaTemporada = useRecurso(listarProximaTemporada, []);

  // Fileiras temáticas — `GET /api/animes/fileiras-tematicas`. Mesma exibição
  // silenciosa das demais fileiras auto-hospedadas: em carregando/erro a
  // seção simplesmente não aparece (sem aviso visível), e cada fileira some
  // sozinha se vier vazia (guard em FileiraDeCards). A tradução de `chave`
  // para rótulo PT e o corte de itens (backend traz até 50 de propósito)
  // ficam em `rotularFileiras` (inicio/fileirasTematicas.js).
  const fileirasTematicas = useRecurso(listarFileirasTematicas, []);
  const fileirasRotuladas = useMemo(
    () => rotularFileiras(fileirasTematicas.dados ?? []),
    [fileirasTematicas.dados]
  );

  // "Top 10" — recorte puro do feed `em-alta` (inicio/fileiras.js). `?? []`
  // porque `emAlta.dados` é `null` até a primeira resposta. (As fileiras por
  // gênero — `fileirasPorGenero`, ainda exportada de fileiras.js — saíram da
  // Home; vão pra uma página própria.)
  const top10 = useMemo(() => topDaTemporada(emAlta.dados ?? []), [emAlta.dados]);

  // "Destaques grandes" — 2 itens ALEATÓRIOS do feed `em-alta` INTEIRO (até
  // 50), EXCLUINDO o recorte que o carrossel exibe agora
  // (recorteVisivelDoCarrossel, ./janelaDeDestaques.js — mesma fórmula do
  // `base` do carrossel): as duas seções não mostram os mesmos animes. Sem
  // sinopse — ao contrário do carrossel de destaques, o `DestaqueGrande` fica
  // só no essencial (título + meta + CTA). `rank` = posição
  // no feed `em-alta` (já ordenado por trending/popularidade da AniList) + 1 —
  // vira a pill "#N em alta"; `indexOf` casa por referência (o feed não é
  // clonado em nenhum ponto). `amostraAleatoria` roda dentro do `useMemo` — só
  // sorteia de novo quando o feed ou `continuando` mudam de fato, não a cada
  // re-render por digitação na busca ou outro estado alheio. `continuarEm`:
  // entrada correspondente em `continuando.dados` (mesma prateleira "Continuar
  // assistindo" já carregada) — decide o rótulo do CTA.
  const destaquesGrandes = useMemo(() => {
    const feed = emAlta.dados ?? [];
    const naJanela = new Set(recorteVisivelDoCarrossel(feed));
    const disponiveis = feed.filter((item) => !naJanela.has(item));
    const continuandoPorAnime = new Map(
      (continuando.dados ?? []).map((entrada) => [entrada.anime_id, entrada])
    );
    return amostraAleatoria(disponiveis, 2).map((item) => ({
      item,
      rank: feed.indexOf(item) + 1,
      continuarEm: item.anime_id != null ? (continuandoPorAnime.get(item.anime_id) ?? null) : null,
    }));
  }, [emAlta.dados, continuando.dados]);

  const [chaveEmMaterializacao, setChaveEmMaterializacao] = useState(null);
  const [erroMaterializacao, setErroMaterializacao] = useState(null);

  const [termoBusca, setTermoBusca] = useState('');
  const termoBuscaNormalizado = termoBusca.trim().toLowerCase();
  const buscando = termoBuscaNormalizado !== '';

  // Mesmo padrão de filtro em memória de `Galeria.jsx` — sem endpoint de
  // busca no backend, a lista local já carregada é pequena o bastante (uso
  // pessoal) pra não justificar um novo endpoint.
  const animesFiltrados = useMemo(
    () => (catalogo.dados ?? []).filter((anime) => anime.titulo.toLowerCase().includes(termoBuscaNormalizado)),
    [catalogo.dados, termoBuscaNormalizado]
  );

  // Busca na biblioteca (AniList): ao contrário do filtro local acima (ao
  // vivo, a cada tecla), só dispara no submit (Enter na navbar) — evita
  // martelar a AniList a cada tecla. Limpa junto com o campo pra não deixar
  // resultado de busca antiga visível depois que o usuário apaga tudo.
  const [termoBuscaSubmetido, setTermoBuscaSubmetido] = useState('');
  useEffect(() => {
    if (termoBuscaNormalizado === '') setTermoBuscaSubmetido('');
  }, [termoBuscaNormalizado]);

  const submeterBusca = useCallback(() => {
    setTermoBuscaSubmetido(termoBusca.trim());
  }, [termoBusca]);

  const buscaBiblioteca = useRecurso(
    () => (termoBuscaSubmetido ? buscarAnimes(termoBuscaSubmetido) : Promise.resolve([])),
    [termoBuscaSubmetido]
  );
  const resultadosBiblioteca = buscaBiblioteca.dados ?? [];

  // Guarda contra o campo ter sido editado depois do último Enter: enquanto
  // `termoBusca` diverge de `termoBuscaSubmetido`, os cards de
  // `buscaBiblioteca.dados` são de uma busca antiga e não devem ser
  // renderizados (risco de materializar o anime errado) — a seção mostra um
  // aviso de "desatualizado" no lugar até o usuário apertar Enter de novo.
  const resultadosDesatualizados =
    termoBuscaSubmetido !== '' && termoBusca.trim() !== termoBuscaSubmetido;
  const buscaBibliotecaAtiva = termoBuscaSubmetido !== '' && !resultadosDesatualizados;

  // Guard de concorrência + estado de erro + navegação pro anime criado,
  // compartilhado pelos cards do feed e pelos resultados da biblioteca.
  const materializar = useCallback(
    async (chave, criar) => {
      if (chaveEmMaterializacao != null) return;
      setChaveEmMaterializacao(chave);
      setErroMaterializacao(null);
      try {
        const criado = await criar();
        navigate(`/anime/${criado.id}`);
      } catch (erroCapturado) {
        console.error('falha ao adicionar anime ao catálogo', erroCapturado);
        setErroMaterializacao('Não foi possível adicionar este anime ao catálogo — tente novamente.');
      } finally {
        setChaveEmMaterializacao(null);
      }
    },
    [chaveEmMaterializacao, navigate]
  );

  // Ação dos cards do feed ("Destaques da temporada") E dos resultados da
  // busca na biblioteca: materializa o item AniList no catálogo local
  // (`POST /api/admin/animes`, get-or-create por slug no servidor — reenvio
  // acidental não duplica; um resultado de busca já catalogado só navega) e vai
  // pro anime. Banner, cor dominante, título em inglês e — para itens do feed
  // "em alta" — a sinopse vão no payload pra alimentar o hero de
  // `PaginaDoAnime` já no primeiro render. O que faltar (ex. sinopse num
  // resultado de busca, que não a traz) é preenchido no primeiro carregamento
  // da página (`agendar_enriquecimento_de_metadados`).
  const materializarEIrPara = useCallback(
    (item) =>
      materializar(item.anilist_id ?? item.titulo_romaji, () =>
        criarAnime({
          titulo: item.titulo_romaji,
          tituloIngles: item.titulo_ingles ?? undefined,
          anilistId: item.anilist_id ?? undefined,
          capaUrl: item.capa_url ?? item.banner_url ?? undefined,
          bannerUrl: item.banner_url ?? undefined,
          capaCor: item.capa_cor ?? undefined,
          generos: item.generos ?? undefined,
          sinopse: item.sinopse ?? undefined,
        })
      ),
    [materializar]
  );

  // "Próximas estreias": os cards NÃO navegam. O anime da próxima temporada
  // ainda não existe em nenhuma fonte extratora — abrir `/anime/:id` levaria a
  // uma página sem episódios e com resolução de fonte fadada a falhar. O botão
  // "Salvar" materializa no catálogo local (`POST /api/admin/animes`,
  // get-or-create por slug) como bookmark. `estreiasSalvas` guarda as chaves
  // salvas nesta sessão pra virar o botão na hora: o feed cru é cacheado no
  // servidor (TTL 6h), então sem isso o card só refletiria `anime_id` num
  // reload posterior.
  const [estreiasSalvas, setEstreiasSalvas] = useState(() => new Set());
  const [chaveSalvandoEstreia, setChaveSalvandoEstreia] = useState(null);

  const salvarEstreia = useCallback(
    async (item) => {
      const chave = item.anilist_id ?? item.titulo_romaji;
      if (chaveSalvandoEstreia != null) return;
      setChaveSalvandoEstreia(chave);
      setErroMaterializacao(null);
      try {
        await criarAnime({
          titulo: item.titulo_romaji,
          tituloIngles: item.titulo_ingles ?? undefined,
          anilistId: item.anilist_id ?? undefined,
          capaUrl: item.capa_url ?? item.banner_url ?? undefined,
          bannerUrl: item.banner_url ?? undefined,
          capaCor: item.capa_cor ?? undefined,
          generos: item.generos ?? undefined,
          sinopse: item.sinopse ?? undefined,
        });
        setEstreiasSalvas((atual) => new Set(atual).add(chave));
      } catch (erroCapturado) {
        console.error('falha ao salvar estreia no catálogo', erroCapturado);
        setErroMaterializacao('Não foi possível salvar este anime — tente novamente.');
      } finally {
        setChaveSalvandoEstreia(null);
      }
    },
    [chaveSalvandoEstreia]
  );

  // renderItem/chaveDoItem da fileira "Top 10", alimentada pelo feed `em-alta` —
  // mesmo contrato que a busca em fontes já usa: card de item ainda não
  // catalogado que materializa e navega ao ativar; todos ficam desabilitados
  // enquanto uma materialização está em voo. `sobreposicao` (opcional) vai pro
  // AnimeCard como irmão do card DENTRO do wrapper, pra crescer junto no hover
  // — é por onde entra o numeral do Top 10.
  const chaveDoItemDoFeed = (item) => item.anilist_id ?? item.titulo_romaji;
  const renderCardDoFeed = (item, sobreposicao) => (
    <AnimeCard
      anime={item}
      aoAtivar={() => materializarEIrPara(item)}
      desabilitado={chaveEmMaterializacao != null}
      sobreposicao={sobreposicao}
    />
  );

  // Fileiras horizontais da home NA ORDEM em que aparecem, cada uma já como
  // nó pronto (com `key`). Só entram as que de fato vão renderizar (lista não
  // vazia) — assim o `passo` de intercalarDestaques conta prateleiras visíveis,
  // não fantasmas. Antes só as fileiras temáticas alimentavam a intercalação
  // dos "destaques grandes"; agora TODAS entram, então um destaque pode cair
  // logo depois de "Próximas estreias"/"Continuar assistindo"/"Top 10", não só
  // no meio dos temas. Montado no corpo do render (não `useMemo`): são ~10
  // objetos + JSX leve, e memoizar exigiria arrastar toda a lista de callbacks
  // de materialização pras deps.
  const fileirasDaHome = [
    (proximaTemporada.dados ?? []).length > 0 && {
      chave: 'proximas-estreias',
      node: (
        <FileiraDeCards
          key="proximas-estreias"
          titulo="Próximas estreias"
          itens={proximaTemporada.dados}
          comSombra={false}
          chaveDoItem={chaveDoItemDoFeed}
          renderItem={(item) => {
            const chave = chaveDoItemDoFeed(item);
            return (
              <CartaoDeEstreia
                item={item}
                salvo={item.anime_id != null || estreiasSalvas.has(chave)}
                salvando={chaveSalvandoEstreia === chave}
                aoSalvar={() => salvarEstreia(item)}
              />
            );
          }}
        />
      ),
    },
    (continuando.dados ?? []).length > 0 && {
      chave: 'continuar-assistindo',
      node: (
        <FileiraDeCards
          key="continuar-assistindo"
          titulo="Continuar assistindo"
          itens={continuando.dados}
          tamanho="episodio"
          comSombra={false}
          chaveDoItem={(item) => item.episodio_id}
          renderItem={(item) => <CartaoContinuarAssistindo item={item} />}
        />
      ),
    },
    top10.length > 0 && {
      chave: 'top-10',
      node: (
        <FileiraDeCards
          key="top-10"
          titulo="Top 10 da semana"
          itens={top10}
          comSombra={false}
          chaveDoItem={chaveDoItemDoFeed}
          // Numeral grande estilo Netflix/Disney+ DENTRO do card: canto
          // superior esquerdo, sobre a arte (`z-10`), com sombra forte pra
          // legibilidade (o topo do pôster não tem o degradê do rodapé).
          // `aria-hidden`/`pointer-events-none`: decorativo, não rouba o
          // clique. Vai como `sobreposicao` do AnimeCard (irmão do card no
          // wrapper).
          renderItem={(item, indice) =>
            renderCardDoFeed(
              item,
              <span
                aria-hidden="true"
                className="pointer-events-none absolute left-2 top-0 z-10 select-none font-black leading-none text-white text-[3.5rem] drop-shadow-[0_2px_10px_rgba(0,0,0,0.95)] sm:text-[4.5rem] lg:text-[5.5rem]"
              >
                {indice + 1}
              </span>
            )
          }
        />
      ),
    },
    ...fileirasRotuladas.map((fileira) => ({
      chave: fileira.chave,
      node: (
        <FileiraDeCards
          key={fileira.chave}
          titulo={fileira.rotulo}
          itens={fileira.itens}
          comSombra={false}
          chaveDoItem={chaveDoItemDoFeed}
          renderItem={(item) => renderCardDoFeed(item)}
        />
      ),
    })),
  ].filter(Boolean);

  // Intercala os "destaques grandes" ao longo de TODAS as fileiras da home
  // (ver inicio/intercalarDestaques.js) — lista final de blocos pro `.map()`
  // do render.
  const blocosDeConteudo = intercalarDestaques(fileirasDaHome, destaquesGrandes);

  return (
    <>
      {fase !== 'revelado' && (
        <button
          type="button"
          onClick={revelar}
          className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-30 focus:rounded-md focus:border focus:border-neon-soft focus:bg-surface focus:px-4 focus:py-2 focus:text-sm focus:font-semibold focus:text-neon focus:outline-none focus-visible:ring-2 focus-visible:ring-neon"
        >
          Pular introdução
        </button>
      )}

      <CenarioDeEntrada fase={fase} movimentoReduzido={movimentoReduzido} aoTerminar={revelar} />

      <BarraDeNavegacao
        fase={fase}
        transparente
        termoBusca={termoBusca}
        aoMudarBusca={setTermoBusca}
        aoSubmeterBusca={submeterBusca}
      />

      <main
        inert={fase !== 'revelado'}
        // `min-h-screen`: evita uma página curta demais (ex. resultado de
        // busca vazio) quando ainda não há conteúdo suficiente pra preencher
        // 1 viewport.
        // `bg-black` (não mais `bg-[#17171b]`, cor exata do `body` do
        // Disney+): preto sólido, igual à Galeria (paginas/Galeria.jsx) —
        // as fileiras e os resultados de busca não levam mais sombra
        // (`comSombra={false}`, mesmo motivo de lá). Efeito colateral aceito:
        // a sombra própria do card "Destaque grande" (inicio/DestaqueGrande.jsx,
        // `boxShadow: SOMBRA_SLIDE_ATIVO`, não mudou) só aparecia sobre esse
        // cinza — sobre preto sólido ela fica praticamente invisível.
        className={`relative z-10 min-h-screen bg-black pt-22 transition-opacity duration-700 ease-out ${
          fase === 'revelado' ? 'opacity-100' : 'opacity-0'
        }`}
      >
        {buscando ? (
          // `pb-20`: só aqui, não em <main> — este bloco rola normalmente e
          // precisa de respiro no fim (o branch de destaques abaixo põe o
          // próprio respiro na <section> que envolve o carrossel). Sem `px`
          // horizontal: as <GradeDeCatalogo> aplicam o gutter de 3.7% medindo
          // a viewport inteira (igual às fileiras da Home) — um `px` aqui
          // encolheria esse container e os cards sairiam mais estreitos. Os
          // títulos e textos de estado recuperam o alinhamento com a borda do
          // card via `paddingInline: PADDING_TITULO_GRADE` (só o gutter — o
          // slot da grade não tem padding próprio), mesmo tratamento de
          // paginas/Galeria.jsx.
          <section aria-label="Resultados da busca" className="pb-20">
            <h2
              style={{ paddingInline: PADDING_TITULO_GRADE }}
              className="mt-20 text-2xl font-semibold text-white"
            >
              Resultados para “{termoBusca.trim()}”
            </h2>
            {/* Estados transitórios do catálogo local — condições inalteradas.
                O wrapper só repõe o `paddingInline` que antes vinha do `px` da
                <section>; cada mensagem leva o próprio `mt-[22px]` (mesmo
                respiro título->conteúdo que a grade traz no `pt-[22px]`). */}
            <div style={{ paddingInline: PADDING_TITULO_GRADE }}>
              {catalogo.carregando && (
                <p className="mt-[22px] text-sm text-ink-muted">Carregando catálogo…</p>
              )}
              {catalogo.erro && (
                <div
                  role="alert"
                  className="mt-[22px] rounded-md border border-red-500/40 bg-red-950/40 px-4 py-3 text-sm text-red-300"
                >
                  Não foi possível carregar o catálogo.{' '}
                  <button type="button" onClick={catalogo.recarregar} className="underline">
                    Tentar novamente
                  </button>
                </div>
              )}
              {!catalogo.carregando && !catalogo.erro && animesFiltrados.length === 0 && (
                <p className="mt-[22px] text-sm text-ink-muted">
                  Nenhum anime encontrado para “{termoBusca.trim()}”.
                </p>
              )}
            </div>
            {!catalogo.carregando && !catalogo.erro && animesFiltrados.length > 0 && (
              <GradeDeCatalogo
                itens={animesFiltrados}
                tamanho="pequeno"
                comSombra={false}
                chaveDoItem={(anime) => anime.id}
                renderItem={(anime) => <AnimeCard anime={anime} />}
              />
            )}

            <section aria-labelledby={idResultadosBiblioteca}>
              <h2
                id={idResultadosBiblioteca}
                style={{ paddingInline: PADDING_TITULO_GRADE }}
                className="mt-12 text-2xl font-semibold text-white"
              >
                Adicionar da biblioteca
              </h2>
              {/* Textos de estado — wrapper só repõe o `paddingInline`; a grade
                  de resultados fica FORA dele (o `paddingInline` dobraria o
                  gutter dos cards). */}
              <div style={{ paddingInline: PADDING_TITULO_GRADE }}>
                {erroMaterializacao && (
                  <div role="alert" className="mt-[22px]">
                    <p className="text-sm text-red-400">{erroMaterializacao}</p>
                  </div>
                )}
                {termoBuscaSubmetido === '' && (
                  <p className="mt-[22px] text-sm text-ink-muted">
                    Aperte Enter para buscar na biblioteca.
                  </p>
                )}
                {termoBuscaSubmetido !== '' && resultadosDesatualizados && (
                  <p className="mt-[22px] text-sm text-ink-muted">
                    Aperte Enter para atualizar os resultados.
                  </p>
                )}
                {buscaBibliotecaAtiva && buscaBiblioteca.carregando && (
                  <p className="mt-[22px] text-sm text-ink-muted">Buscando na biblioteca…</p>
                )}
                {buscaBibliotecaAtiva && buscaBiblioteca.erro && (
                  <div
                    role="alert"
                    className="mt-[22px] rounded-md border border-red-500/40 bg-red-950/40 px-4 py-3 text-sm text-red-300"
                  >
                    Não foi possível buscar na biblioteca.{' '}
                    <button type="button" onClick={buscaBiblioteca.recarregar} className="underline">
                      Tentar novamente
                    </button>
                  </div>
                )}
                {buscaBibliotecaAtiva &&
                  !buscaBiblioteca.carregando &&
                  !buscaBiblioteca.erro &&
                  resultadosBiblioteca.length === 0 && (
                    <p className="mt-[22px] text-sm text-ink-muted">
                      Nada encontrado na biblioteca para “{termoBuscaSubmetido}”.
                    </p>
                  )}
              </div>
              {buscaBibliotecaAtiva &&
                !buscaBiblioteca.carregando &&
                !buscaBiblioteca.erro &&
                resultadosBiblioteca.length > 0 && (
                  <GradeDeCatalogo
                    itens={resultadosBiblioteca}
                    tamanho="pequeno"
                    comSombra={false}
                    chaveDoItem={(item) => item.anilist_id ?? item.titulo_romaji}
                    renderItem={(item) => {
                      const chave = item.anilist_id ?? item.titulo_romaji;
                      return (
                        <AnimeCard
                          anime={{ titulo: item.titulo_romaji, capa_url: item.capa_url }}
                          aoAtivar={() => materializarEIrPara(item)}
                          desabilitado={chaveEmMaterializacao === chave}
                          aviso={item.anime_id != null ? 'Já no catálogo' : undefined}
                        />
                      );
                    }}
                  />
                )}
            </section>
          </section>
        ) : (
          <>
            {emAlta.carregando && (
              <p className="mx-auto max-w-6xl px-6 pb-16 pt-10 text-sm text-ink-muted">
                Carregando destaques da temporada…
              </p>
            )}
            {emAlta.erro && (
              <div className="mx-auto max-w-6xl px-6 pb-16 pt-10">
                <div
                  role="alert"
                  className="rounded-md border border-red-500/40 bg-red-950/40 px-4 py-3 text-sm text-red-300"
                >
                  Não foi possível carregar os destaques da temporada.{' '}
                  <button type="button" onClick={emAlta.recarregar} className="underline">
                    Tentar novamente
                  </button>
                </div>
              </div>
            )}
            {erroMaterializacao && (
              <div role="alert" className="px-4 pb-8 sm:px-6 lg:px-8">
                <p className="text-sm text-red-400">{erroMaterializacao}</p>
              </div>
            )}

            {!emAlta.carregando && !emAlta.erro && (emAlta.dados ?? []).length > 0 && (
              // `-mt-22`: cancela o `pt-22` do <main> pra o hero encostar no
              // y=0 real da viewport, por trás da navbar fixa/transparente
              // (BarraDeNavegacao.jsx já documenta esse contrato: "sem fundo
              // enquanto a página está no topo... aparece atrás da navbar").
              // Sem isso o banner começava abaixo da faixa da navbar, como
              // uma seção separada — não é o layout de referência (AnimeFire).
              // Sem padding horizontal nem `max-w` de propósito — o carrossel
              // é full-bleed (encosta nas bordas da viewport); os estados de
              // carregando/erro do feed seguem na coluna `max-w-6xl`.
              // `-mb-32`: puxa a fileira seguinte pra dentro do fade da base do
              // hero, deixando o título dela + o topo dos cards "espiar" sob o
              // gradiente (padrão AnimeFire — mais peek que os ~90px do wrapper
              // deles porque nossa fileira tem título maior + `pt` da trilha).
              // Pré-requisito pro título não sumir: o <div> das fileiras abaixo
              // tem `relative z-10` — sem isso o `<h2>` da primeira fileira
              // (`position:static`) fica ATRÁS do banner/gradiente do slide, que
              // são `position:absolute` e pintam depois. Com o `z-10` o título
              // pinta sobre a base escura do hero e fica legível; as bolinhas de
              // paginação (`lg:bottom-[14.3vh]`) ficam ~8px acima dele. O
              // gradiente é `pointer-events-none`, então a sobreposição não
              // rouba clique dos cards. Casado com `pt-0` no <div> das fileiras.
              <section className="-mt-22 -mb-32">
                {/* `ativa`: gate do auto-avanço do carrossel (ver
                    CarrosselDestaques.jsx) — a fase só vira "revelado"
                    quando <main> deixa de estar inert/opacity-0; sem o
                    gate o carrossel trocaria de slide enquanto ainda
                    invisível atrás da introdução. */}
                <CarrosselDestaques
                  itens={emAlta.dados}
                  ativa={fase === 'revelado'}
                  aoMaterializar={materializarEIrPara}
                  materializando={chaveEmMaterializacao != null}
                />
              </section>
            )}

            {/* Fileiras horizontais abaixo do hero — FORA do guard de `emAlta`.
                "Continuar assistindo" vem de dados locais
                (`GET /api/episodios/continuar-assistindo`) e não pode sumir
                quando a AniList cai. "Próximas estreias" (feed próprio) e
                "Top 10" (recorte de `em-alta`) se auto-escondem quando suas
                listas chegam vazias — feed indisponível vira fileira ausente,
                não erro. A ordem e o guard de lista vazia de cada prateleira
                moram em `fileirasDaHome` (corpo do componente), que também é a
                lista que intercala os "destaques grandes".
                `relative z-10`: promove todo o bloco de fileiras pra um
                contexto de empilhamento acima do hero. Sem isso o `<h2>` da
                primeira fileira (`position:static`) fica ATRÁS do banner e do
                gradiente do carrossel, que são `position:absolute` e pintam
                depois — o título "Próximas estreias" sumia sob a base do hero.
                `pb-20`: respiro do fim da página. `space-y-10`: separa as
                prateleiras. `pt-0`: com o carrossel presente, o respiro entre
                hero e lista vem do `-mb-32` da <section> acima (peek da
                primeira fileira sob o fade). Sem carrossel (feed vazio/erro),
                `space-y-10`/`pb-20` e o `pt-22` do <main> já dão respiro. */}
            <div className="relative z-10 space-y-10 pb-20 pt-0">
              {blocosDeConteudo.map((bloco) =>
                bloco.tipo === 'destaque' ? (
                  <DestaqueGrande
                    key={bloco.chave}
                    item={bloco.destaque.item}
                    rank={bloco.destaque.rank}
                    continuarEm={bloco.destaque.continuarEm}
                    aoMaterializar={materializarEIrPara}
                    materializando={chaveEmMaterializacao != null}
                  />
                ) : (
                  bloco.fileira.node
                )
              )}
            </div>

          </>
        )}
      </main>
    </>
  );
}

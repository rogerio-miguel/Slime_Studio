import { useCallback, useEffect, useId, useMemo, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import {
  buscarEmFontes,
  confirmarFonte,
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
import { PADDING_TITULO } from '../inicio/tamanhoDeCard.js';
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
// seção ADICIONAL que não substitui carrossel nem "Top 10": reaproveita 2
// itens ALEATÓRIOS de `top10` (amostraAleatoria) e fica intercalada ENTRE as
// fileiras temáticas (não antes/depois do bloco inteiro), via
// inicio/intercalarDestaques.js. Some sozinha se `top10` estiver vazio
// (mesma exibição silenciosa).
// "Seu catálogo" segue FORA da Inicio de propósito — o catálogo local (listar,
// abrir, remover) mora inteiro em `paginas/Galeria.jsx` (rota "/animes",
// linkada na navbar). `DestaquePrincipal` também não está nesta ordem (pivot
// de produto anterior) — ver import comentado abaixo.
//
// Busca ao vivo (navbar, controlada aqui): digitar substitui inteiramente
// "Destaques da temporada" por uma grade de resultados sobre o catálogo
// local (`listarAnimes`) — o feed de provedor não tem busca. Sem
// `aoRemover` nos resultados, de propósito: a gestão do catálogo (remover)
// fica centralizada em `Galeria.jsx`/`PaginaDoAnime.jsx`, esta página não
// duplica isso.
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
  const idResultadosFontes = useId();
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

  // "Destaques grandes" — 2 itens ALEATÓRIOS do Top 10 (não os primeiros: o
  // pedido é variar a cada carregamento, não fixar sempre os mesmos 2 do topo
  // do ranking). Repetição com a fileira "Top 10" é aceitável (mesmo padrão de
  // streaming). `sinopse`/`continuarEm` já resolvidos aqui pra
  // DestaqueGrande.jsx só renderizar. `amostraAleatoria` roda dentro do
  // `useMemo` — só sorteia de novo quando `top10` muda de fato (reload do
  // feed), não a cada re-render por digitação na busca ou outro estado alheio.
  // `sinopse`: cruza por `anime_id` com `catalogo.dados` (já carregado acima,
  // sem request extra por card) — `AnimeSaida` (`GET /api/animes`) expõe
  // `sinopse` 1:1 com a coluna. Só fica ausente pra anime ainda não
  // catalogado (`item.anime_id == null`), caminho normal do componente (o
  // parágrafo simplesmente não aparece).
  // `continuarEm`: entrada correspondente em `continuando.dados` (mesma
  // prateleira "Continuar assistindo" já carregada) — decide o rótulo do CTA.
  const destaquesGrandes = useMemo(() => {
    const catalogoPorId = new Map((catalogo.dados ?? []).map((anime) => [anime.id, anime]));
    const continuandoPorAnime = new Map(
      (continuando.dados ?? []).map((entrada) => [entrada.anime_id, entrada])
    );
    return amostraAleatoria(top10, 2).map((item) => ({
      item,
      sinopse: item.anime_id != null ? (catalogoPorId.get(item.anime_id)?.sinopse ?? null) : null,
      continuarEm: item.anime_id != null ? (continuandoPorAnime.get(item.anime_id) ?? null) : null,
    }));
  }, [top10, catalogo.dados, continuando.dados]);

  // Intercala os destaques grandes entre as fileiras temáticas (ver
  // inicio/intercalarDestaques.js) — produz a lista final de blocos que o
  // `.map()` do render usa no lugar de `fileirasRotuladas` cru.
  const blocosDeConteudo = useMemo(
    () => intercalarDestaques(fileirasRotuladas, destaquesGrandes),
    [fileirasRotuladas, destaquesGrandes]
  );

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

  // Busca em outras fontes (sites de extração, ainda não catalogados): ao
  // contrário do filtro local acima (ao vivo, a cada tecla), só dispara no
  // submit (Enter na navbar) — evita martelar sites externos a cada tecla.
  // Limpa junto com o campo pra não deixar resultado de busca antiga visível
  // depois que o usuário apaga tudo.
  const [termoBuscaSubmetido, setTermoBuscaSubmetido] = useState('');
  useEffect(() => {
    if (termoBuscaNormalizado === '') setTermoBuscaSubmetido('');
  }, [termoBuscaNormalizado]);

  const submeterBuscaEmFontes = useCallback(() => {
    setTermoBuscaSubmetido(termoBusca.trim());
  }, [termoBusca]);

  const buscaEmFontes = useRecurso(
    () =>
      termoBuscaSubmetido
        ? buscarEmFontes(termoBuscaSubmetido, 'padrao')
        : Promise.resolve({
            resultados: [],
            fontes: [],
            termo_alternativo: null,
            dominio_alternativo: null,
          }),
    [termoBuscaSubmetido]
  );
  const resultadosFontes = buscaEmFontes.dados?.resultados ?? [];
  const fontesConsultadas = buscaEmFontes.dados?.fontes ?? [];
  // Preenchido quando os resultados vieram de um termo diferente do digitado
  // (variante de regex reduzida ou, por último, título alternativo do mesmo
  // anime via provedor — romaji/inglês) — avisa o usuário em vez de trocar o
  // resultado em silêncio (busca fuzzy pode casar anime errado).
  const termoAlternativo = buscaEmFontes.dados?.termo_alternativo ?? null;
  // Preenchido quando quem respondeu não foi o site padrão (ex. teve que
  // cair pro AnimesDrive) — sinal a mais além do termo: o usuário também
  // precisa saber que a fonte não é a de sempre, não só que o termo mudou.
  const dominioAlternativo = buscaEmFontes.dados?.dominio_alternativo ?? null;
  const fontesIndisponiveis = fontesConsultadas.filter((fonte) => fonte.indisponivel);
  // Toda fonte consultada falhou/está em cooldown — "não consegui nem
  // tentar", diferente de "busquei e não achei nada" (pelo menos uma fonte
  // respondeu de fato). `fontesConsultadas.length > 0` evita marcar como
  // "nenhuma fonte disponível" antes da resposta chegar (array vazio inicial).
  const todasFontesIndisponiveis =
    fontesConsultadas.length > 0 && fontesIndisponiveis.length === fontesConsultadas.length;

  // Guarda contra o campo ter sido editado depois do último Enter: enquanto
  // `termoBusca` diverge de `termoBuscaSubmetido`, os cards de
  // `buscaEmFontes.dados` são de uma busca antiga e não devem ser renderizados
  // (risco de materializar o anime errado) — a seção mostra um aviso de
  // "desatualizado" no lugar até o usuário apertar Enter de novo.
  const resultadosDeFonteDesatualizados =
    termoBuscaSubmetido !== '' && termoBusca.trim() !== termoBuscaSubmetido;

  // Helper compartilhado por materializarEIrPara/materializarFonteEIrPara: os
  // dois fluxos só diferem na chave usada e na chamada que de fato cria/
  // confirma o anime — guard de concorrência, estado de erro e navegação pro
  // anime criado são idênticos.
  const materializar = useCallback(
    async (chave, criarEConfirmar) => {
      if (chaveEmMaterializacao != null) return;
      setChaveEmMaterializacao(chave);
      setErroMaterializacao(null);
      try {
        const criado = await criarEConfirmar();
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

  // Ação disparada pelos cards da grade "Destaques da temporada": materializa
  // o item do feed no catálogo local (`POST /api/admin/animes`, get-or-create
  // por slug no servidor — reenvio acidental não duplica) e navega pro anime
  // criado. Banner e cor dominante vão no payload (o feed "em alta" os traz por
  // item) pra alimentar o hero de `PaginaDoAnime`; a sinopse continua fora — o
  // feed não a fornece e ela é preenchida no primeiro carregamento da página.
  const materializarEIrPara = useCallback(
    (item) =>
      materializar(item.anilist_id ?? item.titulo_romaji, () =>
        criarAnime({
          titulo: item.titulo_romaji,
          anilistId: item.anilist_id ?? undefined,
          capaUrl: item.capa_url ?? item.banner_url ?? undefined,
          bannerUrl: item.banner_url ?? undefined,
          capaCor: item.capa_cor ?? undefined,
          generos: item.generos ?? undefined,
        })
      ),
    [materializar]
  );

  // Mesma lógica de materialização acima, mas para um candidato de site de
  // extração (subseção "Resultados em outras fontes"): cria o anime e já
  // confirma a fonte (`POST .../fontes/confirmar`) — sem isso, o job de
  // captura pediria confirmação de novo na página do anime.
  //
  // `capaUrl` precisa vir junto: `resultado.capa_url` já saiu resolvido do
  // backend (`api/servicos/busca.py::enriquecer_capas` cobre qualquer fonte
  // sem capa própria via AniList/Kitsu antes de chegar aqui) — sem repassar,
  // `criarAnime` chega sem capa nenhuma e força `enriquecer_anime_criado` a
  // reconsultar o provedor do zero por título, uma segunda tentativa
  // best-effort independente que pode falhar silenciosamente e descartar a
  // capa que já tínhamos em mãos.
  const materializarFonteEIrPara = useCallback(
    (resultado) =>
      materializar(`${resultado.dominio}:${resultado.identificador}`, async () => {
        const criado = await criarAnime({
          titulo: resultado.titulo_exibicao,
          capaUrl: resultado.capa_url ?? undefined,
        });
        await confirmarFonte(criado.id, {
          dominio: resultado.dominio,
          identificador: resultado.identificador,
          tituloExibicao: resultado.titulo_exibicao,
          url: resultado.url,
          versao: resultado.versao ?? null,
        });
        return criado;
      }),
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
          anilistId: item.anilist_id ?? undefined,
          capaUrl: item.capa_url ?? item.banner_url ?? undefined,
          bannerUrl: item.banner_url ?? undefined,
          capaCor: item.capa_cor ?? undefined,
          generos: item.generos ?? undefined,
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
        aoSubmeterBusca={submeterBuscaEmFontes}
      />

      <main
        inert={fase !== 'revelado'}
        // `min-h-screen`: evita uma página curta demais (ex. resultado de
        // busca vazio) quando ainda não há conteúdo suficiente pra preencher
        // 1 viewport.
        // `bg-[#17171b]`: cor exata do `body` do Disney+ (medida ao vivo). É
        // ela que faz a sombra do card do carrossel aparecer — sobre um preto
        // mais fechado (ex. `bg-surface/70`) a sombra 69% preta some.
        className={`relative z-10 min-h-screen bg-[#17171b] pt-22 transition-opacity duration-700 ease-out ${
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
          // card via `paddingInline: PADDING_TITULO` (gutter 3.7% + 10px do
          // slot), mesmo tratamento de paginas/Galeria.jsx.
          <section aria-label="Resultados da busca" className="pb-20">
            <h2
              style={{ paddingInline: PADDING_TITULO }}
              className="mt-20 text-2xl font-semibold text-white"
            >
              Resultados para “{termoBusca.trim()}”
            </h2>
            {/* Estados transitórios do catálogo local — condições inalteradas.
                O wrapper só repõe o `paddingInline` que antes vinha do `px` da
                <section>; cada mensagem leva o próprio `mt-[22px]` (mesmo
                respiro título->conteúdo que a grade traz no `pt-[22px]`). */}
            <div style={{ paddingInline: PADDING_TITULO }}>
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
                chaveDoItem={(anime) => anime.id}
                renderItem={(anime) => <AnimeCard anime={anime} />}
              />
            )}

            <section aria-labelledby={idResultadosFontes}>
              <h2
                id={idResultadosFontes}
                style={{ paddingInline: PADDING_TITULO }}
                className="mt-12 text-2xl font-semibold text-white"
              >
                Resultados em outras fontes
              </h2>
              {/* Textos de estado da busca em fontes — condições inalteradas.
                  Wrapper só pra repor o `paddingInline`; cada mensagem leva o
                  próprio `mt-[22px]`. A grade de resultados fica FORA deste
                  wrapper (o `paddingInline` dobraria o gutter dos cards). */}
              <div style={{ paddingInline: PADDING_TITULO }}>
                {erroMaterializacao && (
                  <div role="alert" className="mt-[22px]">
                    <p className="text-sm text-red-400">{erroMaterializacao}</p>
                  </div>
                )}
                {termoBuscaSubmetido === '' && (
                  <p className="mt-[22px] text-sm text-ink-muted">
                    Aperte Enter para buscar em outras fontes.
                  </p>
                )}
                {termoBuscaSubmetido !== '' && resultadosDeFonteDesatualizados && (
                  <p className="mt-[22px] text-sm text-ink-muted">
                    Aperte Enter para atualizar os resultados em outras fontes.
                  </p>
                )}
                {termoBuscaSubmetido !== '' && !resultadosDeFonteDesatualizados && buscaEmFontes.carregando && (
                  <p className="mt-[22px] text-sm text-ink-muted">Buscando em outras fontes…</p>
                )}
                {termoBuscaSubmetido !== '' && !resultadosDeFonteDesatualizados && buscaEmFontes.erro && (
                  <div
                    role="alert"
                    className="mt-[22px] rounded-md border border-red-500/40 bg-red-950/40 px-4 py-3 text-sm text-red-300"
                  >
                    Não foi possível buscar em outras fontes.{' '}
                    <button type="button" onClick={buscaEmFontes.recarregar} className="underline">
                      Tentar novamente
                    </button>
                  </div>
                )}
                {termoBuscaSubmetido !== '' &&
                  !resultadosDeFonteDesatualizados &&
                  !buscaEmFontes.carregando &&
                  !buscaEmFontes.erro &&
                  resultadosFontes.length === 0 &&
                  todasFontesIndisponiveis && (
                    <div
                      role="alert"
                      className="mt-[22px] rounded-md border border-red-500/40 bg-red-950/40 px-4 py-3 text-sm text-red-300"
                    >
                      <p>
                        Nenhuma fonte está disponível agora
                        {fontesIndisponiveis.some((fonte) => fonte.motivo)
                          ? ': ' +
                            fontesIndisponiveis
                              .map((fonte) =>
                                fonte.motivo ? `${fonte.dominio} (${fonte.motivo})` : fonte.dominio
                              )
                              .join('; ')
                          : '.'}
                      </p>
                      <button type="button" onClick={buscaEmFontes.recarregar} className="underline">
                        Tentar novamente
                      </button>
                    </div>
                  )}
                {termoBuscaSubmetido !== '' &&
                  !resultadosDeFonteDesatualizados &&
                  !buscaEmFontes.carregando &&
                  !buscaEmFontes.erro &&
                  resultadosFontes.length === 0 &&
                  !todasFontesIndisponiveis && (
                    <p className="mt-[22px] text-sm text-ink-muted">
                      Nenhum anime encontrado em outras fontes para “{termoBuscaSubmetido}”.
                    </p>
                  )}
              </div>
              {termoBuscaSubmetido !== '' &&
                !resultadosDeFonteDesatualizados &&
                !buscaEmFontes.carregando &&
                !buscaEmFontes.erro &&
                resultadosFontes.length > 0 && (
                  <>
                    {(termoAlternativo || dominioAlternativo) && (
                      <p
                        style={{ paddingInline: PADDING_TITULO }}
                        className="mt-[22px] text-sm text-ink-muted"
                      >
                        {termoAlternativo ? (
                          <>
                            Nenhum resultado para “{termoBuscaSubmetido}”. Mostrando resultados
                            para “{termoAlternativo}”
                            {dominioAlternativo && <> em {dominioAlternativo}</>}.
                          </>
                        ) : (
                          <>Resultados de {dominioAlternativo}.</>
                        )}
                      </p>
                    )}
                    <GradeDeCatalogo
                      itens={resultadosFontes}
                      tamanho="pequeno"
                      chaveDoItem={(resultado) => `${resultado.dominio}:${resultado.identificador}`}
                      renderItem={(resultado) => {
                        const chave = `${resultado.dominio}:${resultado.identificador}`;
                        return (
                          <AnimeCard
                            anime={{ titulo: resultado.titulo_exibicao, capa_url: resultado.capa_url }}
                            aoAtivar={() => materializarFonteEIrPara(resultado)}
                            desabilitado={chaveEmMaterializacao === chave}
                            fonte={resultado.dominio}
                          />
                        );
                      }}
                    />
                    {fontesIndisponiveis.length > 0 && (
                      <p
                        style={{ paddingInline: PADDING_TITULO }}
                        className="mt-4 text-xs text-ink-muted"
                      >
                        Não foi possível consultar:{' '}
                        {fontesIndisponiveis.map((fonte) => fonte.dominio).join(', ')}.
                      </p>
                    )}
                  </>
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
              // `pt-4`: só o respiro vertical do topo. Sem `pb-*` aqui — o
              // espaçamento até a primeira fileira (e o do fim da página) vem
              // do `<div>` que envolve as fileiras abaixo. Sem padding
              // horizontal nem `max-w` de propósito — o carrossel é full-bleed
              // (encosta nas bordas da viewport, como a área do carrossel do
              // Disney+); os estados de carregando/erro do feed seguem na
              // coluna `max-w-6xl`.
              <section className="pt-4">
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
                não erro. `pb-20`: respiro do fim da página. `space-y-10`:
                separa as prateleiras. `pt-4`: respiro do topo quando o
                carrossel não está presente (com carrossel, soma ao `pt-4`
                dele — gap aceitável). */}
            <div className="space-y-10 pb-20 pt-4">
              <FileiraDeCards
                titulo="Próximas estreias"
                itens={proximaTemporada.dados}
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

              <FileiraDeCards
                titulo="Continuar assistindo"
                itens={continuando.dados}
                tamanho="episodio"
                chaveDoItem={(item) => item.episodio_id}
                renderItem={(item) => <CartaoContinuarAssistindo item={item} />}
              />

              <FileiraDeCards
                titulo="Top 10 da semana"
                itens={top10}
                chaveDoItem={chaveDoItemDoFeed}
                // Numeral grande estilo Netflix/Disney+ DENTRO do card:
                // canto superior esquerdo, sobre a arte (`z-10`), com
                // sombra forte pra legibilidade (o topo do pôster não tem
                // o degradê que o rodapé tem). `aria-hidden`/
                // `pointer-events-none`: decorativo, não rouba o clique.
                // Vai como `sobreposicao` do AnimeCard (irmão do card
                // dentro do wrapper) pra crescer junto no `scale` do hover.
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

              {blocosDeConteudo.map((bloco) =>
                bloco.tipo === 'destaque' ? (
                  <DestaqueGrande
                    key={bloco.chave}
                    item={bloco.destaque.item}
                    sinopse={bloco.destaque.sinopse}
                    continuarEm={bloco.destaque.continuarEm}
                    aoMaterializar={materializarEIrPara}
                    materializando={chaveEmMaterializacao != null}
                  />
                ) : (
                  <FileiraDeCards
                    key={bloco.chave}
                    titulo={bloco.fileira.rotulo}
                    itens={bloco.fileira.itens}
                    chaveDoItem={chaveDoItemDoFeed}
                    renderItem={(item) => renderCardDoFeed(item)}
                  />
                )
              )}
            </div>

          </>
        )}
      </main>
    </>
  );
}

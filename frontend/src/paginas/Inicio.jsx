import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { ErroDeApi } from '../api/cliente.js';
import {
  buscarAnimes,
  criarAnime,
  criarJobSite,
  listarAnimes,
  listarAnimesEmAlta,
  listarContinuarAssistindo,
  listarProximaTemporada,
  removerAnime,
} from '../api/recursos.js';
import { useRecurso } from '../api/useRecurso.js';
import AnimeCard from '../components/AnimeCard.jsx';
import BarraDeNavegacao from '../components/BarraDeNavegacao.jsx';
import CartaoContinuarAssistindo from '../components/CartaoContinuarAssistindo.jsx';
// DestaquePrincipal desativado temporariamente (pivot de produto, Fase 4) —
// o arquivo continua em inicio/DestaquePrincipal.jsx, não é código morto,
// só não é renderizado por enquanto.
import CarrosselDestaques, { IconeEmAlta } from '../inicio/CarrosselDestaques.jsx';
import CartaoDeEstreia from '../inicio/CartaoDeEstreia.jsx';
// DestaqueGrande e as fileiras temáticas ocultos a pedido do usuário
// (2026-09-13) — arquivos/endpoints continuam existindo (inicio/DestaqueGrande.jsx,
// inicio/fileirasTematicas.js, inicio/intercalarDestaques.js,
// inicio/janelaDeDestaques.js), só não são renderizados/computados por enquanto.
import FileiraDeCards from '../inicio/FileiraDeCards.jsx';
import { ordenarPorEstreia, topDaTemporada } from '../inicio/fileiras.js';
import GradeDeCatalogo from '../inicio/GradeDeCatalogo.jsx';
import { PADDING_TITULO_GRADE } from '../inicio/tamanhoDeCard.js';

// Rota "/" — interface principal do streaming: navbar + carrossel hero
// "Destaques da temporada" seguido das fileiras horizontais. A introdução
// cinematográfica por vídeo (CenarioDeEntrada.jsx, useIntroPorVideo.js) foi
// removida a pedido do usuário (2026-09-15) — a página renderiza direto, sem
// fase de reveal.
//
// Conteúdo (branch `!buscando`): o carrossel hero seguido das fileiras
// horizontais (inicio/FileiraDeCards.jsx), nesta ordem — "Próximas estreias",
// "Continuar assistindo", "Top 10 em alta". "Top 10" é recorte puro do feed
// `GET /api/animes/em-alta` (inicio/fileiras.js); "Próximas estreias" vem do
// feed próprio `GET /api/animes/proxima-temporada` (próxima temporada da
// AniList — o feed "em alta" só traz o que já está no ar); "Continuar
// assistindo" de `GET /api/episodios/continuar-assistindo`. Cada fileira some
// sozinha quando sua lista está vazia (guard no próprio FileiraDeCards). As
// fileiras temáticas (`GET /api/animes/fileiras-tematicas`,
// inicio/fileirasTematicas.js) e as fileiras por gênero (`fileirasPorGenero`
// em fileiras.js) estão fora da Home — ver nota de import comentado acima.
//
// "Destaques grandes" (inicio/DestaqueGrande.jsx, intercalados via
// inicio/intercalarDestaques.js) também estão ocultos — ver nota de import
// comentado acima.
// "Seu catálogo" segue FORA da Inicio de propósito — o catálogo local (listar,
// abrir, remover) mora inteiro em `paginas/Galeria.jsx` (rota "/animes",
// linkada na navbar). `DestaquePrincipal` também não está nesta ordem (pivot
// de produto anterior) — ver import comentado abaixo.
//
// Busca ao vivo (navbar, controlada aqui): digitar substitui inteiramente
// "Destaques da temporada" por (1) uma grade sobre o catálogo LOCAL
// (`listarAnimes`, filtro em memória a cada tecla) e (2) "Adicionar da
// biblioteca" — busca na AniList (`buscarAnimes`, só no Enter). Item ainda
// não catalogado materializa ao clicar (`materializarEIrPara`, mesmo fluxo
// dos cards do feed); item já catalogado (`item.anime_id` presente) passa
// pro `AnimeCard` como `anime.anime_id` — o próprio card já sabe virar
// `<Link>` direto pra ele nesse caso (ver topo de `components/AnimeCard.jsx`)
// em vez de materializar de novo, com a pill "Já no catálogo"
// (`indicarCatalogado`, pedido explícito do usuário, mesmo padrão do
// "Relacionados" de `paginas/PaginaDoAnime.jsx`). Sem `aoRemover` nos
// resultados, de propósito: a gestão do catálogo (remover) fica centralizada
// em `Galeria.jsx`/`PaginaDoAnime.jsx`, esta página não duplica isso.
//
// Fronteira Clean Architecture (D5 do plano): esta página e tudo em
// src/inicio/ só importam de src/api/, components/ e react-router-dom —
// nada de src/player/ (a única ligação com o player é a rota
// "/assistir/:episodioId", string, não import).

// `jobsPorEpisodio` — mesmo Map do WS que `App.jsx` já sobe pro app inteiro
// (`useEventosDeJobs`), até agora só descido pra `PaginaDoAnime`. A prateleira
// "Continuar assistindo" ganha o mesmo status ao vivo de captura no ramo
// `processando` (ver `components/CartaoContinuarAssistindo.jsx`).

// Poll de `still_pendente`/`sondagem_em_andamento` (ver efeito abaixo). O
// teto (4s x 16 = ~64s) mira o teto comum de sondagem de fonte
// (`extractors/resiliencia.py::_TETO_ESPERA_S`, 45s) com folga — a busca de
// still TMDB é bem mais rápida (timeout de 9s, `progresso.py`) e resolve bem
// antes disso, então o efeito para sozinho cedo nesse caso (dependência vira
// `false` assim que a pendência resolve, sem esperar o teto). O caminho raro
// de sondagem via navegador visível (bypass de Turnstile, até 225s,
// `_TETO_ESPERA_NAVEGADOR_S`) pode passar do teto — nesse caso o episódio só
// aparece no próximo gatilho de poll (nova pendência) ou reload manual, sem
// piorar o caso comum de scraping leve.
const _INTERVALO_POLL_STILL_MS = 4000;
const _MAX_TENTATIVAS_POLL_STILL = 16;
export default function Inicio({ jobsPorEpisodio }) {
  const navigate = useNavigate();
  const idResultadosBiblioteca = useId();

  const emAlta = useRecurso(listarAnimesEmAlta, []);
  // Chave 'animes' (invalidacao.js): recarrega sozinho quando `criarAnime`/
  // `removerAnime` resolve em qualquer lugar do app (ex. materializar um
  // item do feed abaixo), sem precisar de um `recarregar()` manual aqui.
  const catalogo = useRecurso(listarAnimes, [], 'animes');
  // Prateleira "Continuar assistindo" — independente do feed `em-alta`
  // (posição em episódio já capturado, ou próximo passo dele — extensão do
  // catálogo/página do anime, 2026-09-18: um item por ANIME, cobrindo
  // "continuar", "próximo já pronto", "próximo pra capturar"/"episódio novo").
  // Mesma exibição silenciosa da Galeria: em carregando/erro/vazio a fileira
  // simplesmente não aparece. Chave 'episodios': recarrega quando
  // `salvarProgresso`/`marcarAssistido`/`liberarEpisodio` resolve (ex. saiu do
  // player e voltou pra Home) — captura disparada aqui (`capturarProximo`
  // abaixo) não passa por essa chave (mesmo motivo de `PaginaDoAnime.jsx`:
  // `criarJobSite` não invalida sozinho), por isso chama `continuando.
  // recarregar()` explicitamente no sucesso.
  // `GET /continuar-assistindo` devolve um envelope (`{itens, sondagem_em_
  // andamento}`, não lista crua) desde 2026-09-19 — precisa do nível da
  // resposta pra `sondagem_em_andamento` (ver comentário do poll abaixo).
  const continuando = useRecurso(listarContinuarAssistindo, [], 'episodios');
  const itensContinuar = continuando.dados?.itens ?? [];
  // Poll leve, enquanto (1) algum card `capturavel` está com `still_pendente`
  // (busca de still/título/sinopse TMDB em segundo plano,
  // `progresso.py::_aplicar_still_capturavel`) OU (2) o backend sinaliza
  // `sondagem_em_andamento` — uma sondagem de fonte (`sondagem.
  // agendar_sondagens`, disparada pelo próprio `listar_continuar_assistindo`
  // pros animes desta prateleira) ainda rodando em segundo plano. O 2º caso
  // cobre o que uma flag por item não resolve: um anime cujo próximo episódio
  // ainda não existe SOME inteiro de `itens` até a sondagem confirmar a
  // contagem da fonte — não tem item pra pendurar `still_pendente`. Nenhum
  // dos dois bloqueia a resposta original; sem isso o usuário só via o card
  // certo (still OU episódio novo capturável) depois de um F5 manual. Para
  // sozinho assim que as duas pendências resolvem ou ao atingir o teto de
  // tentativas; sem nenhuma (o caso comum), o efeito nem agenda o timer —
  // zero custo pro resto da página.
  const precisaPollDeContinuar =
    itensContinuar.some((item) => item.still_pendente) ||
    continuando.dados?.sondagem_em_andamento === true;
  useEffect(() => {
    if (!precisaPollDeContinuar) return undefined;
    let tentativas = 0;
    const intervalo = setInterval(() => {
      tentativas += 1;
      continuando.recarregar();
      if (tentativas >= _MAX_TENTATIVAS_POLL_STILL) clearInterval(intervalo);
    }, _INTERVALO_POLL_STILL_MS);
    return () => clearInterval(intervalo);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [precisaPollDeContinuar]);
  // Mesmo fix de `PaginaDoAnime.jsx` (`jaRecarregadoRef`): sem isto, um card
  // `processando` cujo job termina fica preso mostrando "Pronto" (texto do
  // `OverlayDeStatus`, via `job.status` já atualizado pelo WS) sem nunca virar
  // o ramo `pronto` de fato (ícone de play + link `/assistir/:id`) — só o
  // ícone É a mudança de variante, que só um `item.variante === 'pronto'` do
  // REST resolve, e nada aqui força esse refetch quando o job conclui fora da
  // janela do poll de still/sondagem acima. Guard por `episodio_id:job.id`
  // evita reagendar `recarregar()` a cada tick de QUALQUER job ativo no app
  // (`jobsPorEpisodio` é o Map global do WS) uma vez que o par já disparou.
  const jaRecarregadoContinuarRef = useRef(new Set());
  useEffect(() => {
    const naoVistos = itensContinuar.filter((item) => {
      if (item.variante !== 'processando' || item.episodio_id == null) return false;
      const job = jobsPorEpisodio?.get(item.episodio_id);
      if (!job || job.status !== 'pronto') return false;
      return !jaRecarregadoContinuarRef.current.has(`${item.episodio_id}:${job.id}`);
    });
    if (naoVistos.length > 0) {
      naoVistos.forEach((item) => {
        const job = jobsPorEpisodio.get(item.episodio_id);
        jaRecarregadoContinuarRef.current.add(`${item.episodio_id}:${job.id}`);
      });
      continuando.recarregar();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobsPorEpisodio, itensContinuar, continuando.recarregar]);
  // "Próximas estreias" — feed próprio da próxima temporada da AniList (não
  // sai do feed `em-alta`, que só lista o que já está no ar). Mesma exibição
  // silenciosa: em carregando/erro/vazio a fileira não aparece.
  const proximaTemporada = useRecurso(listarProximaTemporada, []);
  // Ordenada por data de estreia crescente (`ordenarPorEstreia`) — os itens
  // ainda sem nenhum sinal de data ficam no final da fileira, e a lista
  // reordena sozinha assim que o warm de lançamento preenche uma data nova.
  const proximaTemporadaOrdenada = useMemo(
    () => ordenarPorEstreia(proximaTemporada.dados),
    [proximaTemporada.dados]
  );

  // "Top 10" — recorte puro do feed `em-alta` (inicio/fileiras.js). `?? []`
  // porque `emAlta.dados` é `null` até a primeira resposta. (As fileiras por
  // gênero — `fileirasPorGenero`, ainda exportada de fileiras.js — saíram da
  // Home; vão pra uma página própria.)
  const top10 = useMemo(() => topDaTemporada(emAlta.dados ?? []), [emAlta.dados]);

  // Captura disparada pelo ramo `capturavel` de `CartaoContinuarAssistindo`
  // (nunca capturado ou recaptura de `LIBERADO`/`FALHOU`) — mesmo
  // `criarJobSite` e mesmo tratamento de erro de `PaginaDoAnime.jsx::
  // capturar`, só sem a UI de troca de fonte/confirmação de ambiguidade:
  // aqui a fonte já foi resolvida antes (pré-requisito do próprio item
  // aparecer como `capturavel`, `backend/api/servicos/progresso.py`), então
  // `fonte_ambigua` é o caso raro de a fonte ter ficado ambígua de novo desde
  // a última resolução — em vez de duplicar o modal de `DialogoDeFonteAmbigua`
  // aqui, o aviso linka pra página do anime, que já sabe resolver isso.
  // `animeIdComFonteAmbigua` guarda só o `id` (não o payload de candidatos)
  // pro link — a resolução de fato acontece lá, não aqui.
  const [chaveCapturando, setChaveCapturando] = useState(null);
  const [erroCaptura, setErroCaptura] = useState(null);
  const [animeIdComFonteAmbigua, setAnimeIdComFonteAmbigua] = useState(null);

  const chaveDoItemContinuar = (item) => item.anime_id;

  const capturarProximo = useCallback(
    async (item) => {
      const chave = chaveDoItemContinuar(item);
      if (chaveCapturando != null) return;
      setChaveCapturando(chave);
      setErroCaptura(null);
      setAnimeIdComFonteAmbigua(null);
      try {
        // Mesmo degrade de `PaginaDoAnime.jsx::capturar`: 'desconhecida' é só
        // classificação de exibição (fonte não diferencia legendado/dublado),
        // nunca um pedido válido — o request cai pra 'legendado'.
        const versaoPedida = item.versao === 'desconhecida' ? 'legendado' : item.versao;
        await criarJobSite({
          animeId: item.anime_id,
          numero: item.numero,
          tipo: 'regular',
          versao: versaoPedida,
        });
        continuando.recarregar();
      } catch (erroCapturado) {
        if (erroCapturado instanceof ErroDeApi && erroCapturado.detail?.motivo === 'fonte_ambigua') {
          setAnimeIdComFonteAmbigua(item.anime_id);
        } else if (
          erroCapturado instanceof ErroDeApi &&
          erroCapturado.detail?.motivo === 'episodio_ja_existe'
        ) {
          continuando.recarregar();
        } else {
          console.error('falha ao capturar episódio pela Home', erroCapturado);
          setErroCaptura('Não foi possível capturar este episódio — tente novamente.');
        }
      } finally {
        setChaveCapturando(null);
      }
    },
    [chaveCapturando, continuando]
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
          formato: item.formato ?? undefined,
        })
      ),
    [materializar]
  );

  // "Próximas estreias": os cards NÃO navegam. O anime da próxima temporada
  // ainda não existe em nenhuma fonte extratora — abrir `/anime/:id` levaria a
  // uma página sem episódios e com resolução de fonte fadada a falhar. O ícone
  // de fita é um TOGGLE: clicar salva (`POST /api/admin/animes`, get-or-create
  // por slug) como bookmark; clicar de novo já salvo remove essa temporada
  // (`DELETE /api/admin/animes/{id}`, mesma `removerAnime` da Galeria). Sem
  // dialog de confirmação aqui de propósito — ao contrário da Galeria, um
  // bookmark de estreia nunca tem episódio/captura associado pra perder, é só
  // desmarcar; a interação esperada é o toggle instantâneo (like/bookmark do
  // Instagram, não uma exclusão "pesada").
  //
  // `estreiasSalvas` guarda as CHAVES salvas nesta sessão pra virar o ícone na
  // hora: o feed cru é cacheado no servidor (TTL 6h), então sem isso o card só
  // refletiria `anime_id` num reload posterior. `estreiasSalvasIds` guarda o
  // `id` retornado por `criarAnime` pra essas mesmas chaves — necessário pra
  // remover depois um item que NASCEU sem `item.anime_id` (materializado
  // nesta sessão, o feed em si não é mutado). `estreiasRemovidas` é o inverso:
  // chaves cujo `anime_id` o SERVIDOR já reporta (feed cacheado antigo), mas
  // que foram removidas nesta sessão — sem isso o card voltaria a aparecer
  // "salvo" a cada re-render até o feed expirar.
  const [estreiasSalvas, setEstreiasSalvas] = useState(() => new Set());
  const [estreiasSalvasIds, setEstreiasSalvasIds] = useState(() => new Map());
  const [estreiasRemovidas, setEstreiasRemovidas] = useState(() => new Set());
  const [chaveSalvandoEstreia, setChaveSalvandoEstreia] = useState(null);

  // Mesma chave usada por TODOS os feeds AniList não catalogados desta página
  // ("Próximas estreias", "Top 10", fileiras temáticas) — declarada aqui em
  // vez de mais abaixo (junto de `renderCardDoFeed`) porque o bloco de
  // "Próximas estreias" precisa dela primeiro.
  const chaveDoItemDoFeed = (item) => item.anilist_id ?? item.titulo_romaji;
  const estreiaEstaSalva = (item) => {
    const chave = chaveDoItemDoFeed(item);
    return (item.anime_id != null || estreiasSalvas.has(chave)) && !estreiasRemovidas.has(chave);
  };

  const alternarEstreiaSalva = useCallback(
    async (item) => {
      const chave = chaveDoItemDoFeed(item);
      if (chaveSalvandoEstreia != null) return;
      // Mesma regra de `estreiaEstaSalva`, inline: chamar a função de fora
      // puxaria ela pras deps do `useCallback` sem necessidade (ela já lê as
      // duas MESMAS variáveis de estado que já estão na lista abaixo).
      const jaSalvo =
        (item.anime_id != null || estreiasSalvas.has(chave)) && !estreiasRemovidas.has(chave);
      setChaveSalvandoEstreia(chave);
      setErroMaterializacao(null);
      try {
        if (jaSalvo) {
          const id = item.anime_id ?? estreiasSalvasIds.get(chave);
          await removerAnime(id);
          setEstreiasRemovidas((atual) => new Set(atual).add(chave));
          setEstreiasSalvas((atual) => {
            if (!atual.has(chave)) return atual;
            const novo = new Set(atual);
            novo.delete(chave);
            return novo;
          });
        } else {
          const criado = await criarAnime({
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
          setEstreiasSalvasIds((atual) => new Map(atual).set(chave, criado.id));
          setEstreiasRemovidas((atual) => {
            if (!atual.has(chave)) return atual;
            const novo = new Set(atual);
            novo.delete(chave);
            return novo;
          });
        }
      } catch (erroCapturado) {
        console.error(
          jaSalvo ? 'falha ao remover estreia do catálogo' : 'falha ao salvar estreia no catálogo',
          erroCapturado
        );
        setErroMaterializacao(
          jaSalvo
            ? 'Não foi possível remover este anime — tente novamente.'
            : 'Não foi possível salvar este anime — tente novamente.'
        );
      } finally {
        setChaveSalvandoEstreia(null);
      }
    },
    [chaveSalvandoEstreia, estreiasSalvas, estreiasSalvasIds, estreiasRemovidas]
  );

  // renderItem da fileira "Top 10", alimentada pelo feed `em-alta` — mesmo
  // contrato que a busca em fontes já usa: card de item ainda não catalogado
  // que materializa e navega ao ativar; todos ficam desabilitados enquanto uma
  // materialização está em voo. `sobreposicao` (opcional) vai pro AnimeCard
  // como irmão do card DENTRO do wrapper, pra crescer junto no hover — é por
  // onde entra o numeral do Top 10. `chaveDoItemDoFeed` declarada mais acima,
  // junto do estado de "Próximas estreias".
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
  // vazia). Montado no corpo do render (não `useMemo`): são poucos objetos +
  // JSX leve.
  const fileirasDaHome = [
    (proximaTemporada.dados ?? []).length > 0 && {
      chave: 'proximas-estreias',
      node: (
        <FileiraDeCards
          key="proximas-estreias"
          titulo="Próximas estreias"
          itens={proximaTemporadaOrdenada}
          tamanho="pequeno"
          comSombra={false}
          chaveDoItem={chaveDoItemDoFeed}
          renderItem={(item) => {
            const chave = chaveDoItemDoFeed(item);
            return (
              <CartaoDeEstreia
                item={item}
                salvo={estreiaEstaSalva(item)}
                salvando={chaveSalvandoEstreia === chave}
                aoSalvar={() => alternarEstreiaSalva(item)}
              />
            );
          }}
        />
      ),
    },
    itensContinuar.length > 0 && {
      chave: 'continuar-assistindo',
      // `chaveDoItem` por `anime_id` (não mais `episodio_id`, que agora vem
      // nulo no ramo `capturavel` sem episódio) — um card por anime, ver
      // `backend/api/servicos/progresso.py`.
      node: (
        <FileiraDeCards
          key="continuar-assistindo"
          titulo="Continuar assistindo"
          itens={itensContinuar}
          tamanho="episodio"
          comSombra={false}
          chaveDoItem={chaveDoItemContinuar}
          renderItem={(item) => (
            <CartaoContinuarAssistindo
              item={item}
              job={item.episodio_id != null ? jobsPorEpisodio?.get(item.episodio_id) : null}
              aoCapturar={capturarProximo}
              capturando={chaveCapturando === chaveDoItemContinuar(item)}
            />
          )}
        />
      ),
    },
    top10.length > 0 && {
      chave: 'top-10',
      node: (
        <FileiraDeCards
          key="top-10"
          titulo="Top 10 em alta"
          itens={top10}
          tamanho="pequeno"
          comSombra={false}
          chaveDoItem={chaveDoItemDoFeed}
          // Numeral do Top 10: selo escuro com blur (`bg-black/80
          // backdrop-blur-md`, mesmo tratamento do badge "Assistido" de
          // `components/AnimeCard.jsx`) no canto superior esquerdo do pôster
          // (`z-10`) — substitui a variante anterior de numeral grande
          // translúcido sangrando pra fora do canto (`-left-6 -top-4`, sem
          // fundo próprio), que ficava difícil de ler sobre capas claras.
          // `aria-hidden`/`pointer-events-none`: decorativo, não rouba o
          // clique. Vai como `sobreposicao` do AnimeCard (irmão do card no
          // wrapper). `IconeEmAlta` (chama) ao lado do número: mesmo ícone da
          // pill "#N em alta" do hero (inicio/CarrosselDestaques.jsx).
          renderItem={(item, indice) =>
            renderCardDoFeed(
              item,
              <div
                aria-hidden="true"
                className="pointer-events-none absolute left-4 top-6 z-10 flex h-8 items-center gap-1 bg-black/80 px-2 backdrop-blur-md"
              >
                <IconeEmAlta/>
                <span className="font-semibold text-white">#{indice + 1}</span>
              </div>
            )
          }
        />
      ),
    },
  ].filter(Boolean);

  return (
    <>
      <BarraDeNavegacao
        transparente
        termoBusca={termoBusca}
        aoMudarBusca={setTermoBusca}
        aoSubmeterBusca={submeterBusca}
      />

      <main
        // `min-h-screen`: evita uma página curta demais (ex. resultado de
        // busca vazio) quando ainda não há conteúdo suficiente pra preencher
        // 1 viewport.
        // `bg-black` (não mais `bg-[#17171b]`, cor exata do `body` do
        // Disney+): preto sólido, igual à Galeria (paginas/Galeria.jsx) —
        // as fileiras e os resultados de busca não levam mais sombra
        // (`comSombra={false}`, mesmo motivo de lá).
        className="relative z-10 min-h-screen bg-black pt-22"
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
                          anime={{
                            titulo: item.titulo_romaji,
                            capa_url: item.capa_url,
                            anime_id: item.anime_id,
                          }}
                          aoAtivar={() => materializarEIrPara(item)}
                          desabilitado={chaveEmMaterializacao === chave}
                          indicarCatalogado
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
            {erroCaptura && (
              <div role="alert" className="px-4 pb-8 sm:px-6 lg:px-8">
                <p className="text-sm text-red-400">{erroCaptura}</p>
              </div>
            )}
            {/* `fonte_ambigua` num clique de "capturar" da prateleira — caso
                raro (a fonte já tinha sido resolvida antes pra este item
                aparecer aqui). Em vez de duplicar `DialogoDeFonteAmbigua` sem
                o contexto de fonte/versão que `PaginaDoAnime.jsx` tem à mão,
                linka pra lá — a página do anime já sabe resolver. */}
            {animeIdComFonteAmbigua != null && (
              <div role="alert" className="px-4 pb-8 sm:px-6 lg:px-8">
                <p className="text-sm text-red-400">
                  A fonte deste anime ficou ambígua desde a última captura.{' '}
                  <Link to={`/anime/${animeIdComFonteAmbigua}`} className="underline">
                    Resolver na página do anime
                  </Link>
                  .
                </p>
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
              // `-mb-24` (6rem — reduzido de `-mb-32`/8rem a pedido do usuário,
              // 2026-09-20): puxa a fileira seguinte pra dentro do fade da base
              // do hero, deixando o título dela + o topo dos cards "espiar" sob
              // o gradiente (padrão AnimeFire). O valor anterior (8rem) deixava
              // o título "Próximas estreias" quase colado nas bolinhas de
              // paginação (`lg:bottom-[14.3vh]`, ~8px de distância) — poluição
              // visual reportada pelo usuário depois de checar ao vivo no
              // navegador. 6rem abre mais respiro entre as duas camadas sem
              // eliminar o peek. Pré-requisito pro título não sumir: o <div>
              // das fileiras abaixo tem `relative z-10` — sem isso o `<h2>` da
              // primeira fileira (`position:static`) fica ATRÁS do banner/
              // gradiente do slide, que são `position:absolute` e pintam
              // depois. Com o `z-10` o título pinta sobre a base escura do
              // hero e fica legível. O gradiente é `pointer-events-none`,
              // então a sobreposição não rouba clique dos cards. Casado com
              // `pt-0` no <div> das fileiras.
              <section className="-mt-22 -mb-28">
                <CarrosselDestaques
                  itens={emAlta.dados}
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
                moram em `fileirasDaHome` (corpo do componente).
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
              {fileirasDaHome.map((fileira) => fileira.node)}
            </div>

          </>
        )}
      </main>
    </>
  );
}

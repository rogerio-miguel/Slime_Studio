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
  listarNovosLancamentos,
  listarProximaTemporada,
  marcarEpisodioAssistido,
  removerAnime,
} from '../api/recursos.js';
import { useRecurso } from '../api/useRecurso.js';
import AnimeCard from '../components/AnimeCard.jsx';
import BarraDeNavegacao from '../components/BarraDeNavegacao.jsx';
import CartaoContinuarAssistindo from '../components/CartaoContinuarAssistindo.jsx';
import { useAtualizacaoPeriodica } from '../hooks/useAtualizacaoPeriodica.js';
import { useStatusDeCapturaIlha } from '../hooks/useStatusDeCapturaIlha.js';
// DestaquePrincipal desativado temporariamente (pivot de produto, Fase 4) —
// o arquivo continua em inicio/DestaquePrincipal.jsx, não é código morto,
// só não é renderizado por enquanto.
import CarrosselDestaques from '../inicio/CarrosselDestaques.jsx';
import CartaoDeEstreia from '../inicio/CartaoDeEstreia.jsx';
import FileiraDeCards from '../inicio/FileiraDeCards.jsx';
import { agruparPorDiaDeEstreia, ordenarPorEstreia, topDaTemporada } from '../inicio/fileiras.js';
import GradeDeCatalogo from '../inicio/GradeDeCatalogo.jsx';
import ListaDeLancamentos from '../inicio/ListaDeLancamentos.jsx';
import CoverflowDeEmAlta from '../inicio/CoverflowDeEmAlta.jsx';
import SecaoDaHome from '../inicio/SecaoDaHome.jsx';
import SlotDoDiaDeEstreia from '../inicio/SlotDoDiaDeEstreia.jsx';
import { PADDING_TITULO_GRADE } from '../inicio/tamanhoDeCard.js';
import { usePrefersReducedMotion } from '../inicio/usePrefersReducedMotion.js';
import EstadoComMascote from '../components/mascote/EstadoComMascote.jsx';
import BotaoDeEstado from '../components/mascote/BotaoDeEstado.jsx';

const LIMITE_PROXIMAS_ESTREIAS = 20;
const INTERVALO_NOVOS_LANCAMENTOS_MS = 2 * 60 * 1000;

// Rota "/" — interface principal do streaming: navbar + carrossel hero
// "Destaques da temporada" seguido das fileiras horizontais. A introdução
// cinematográfica por vídeo (CenarioDeEntrada.jsx, useIntroPorVideo.js) foi
// removida a pedido do usuário (2026-09-15) — a página renderiza direto, sem
// fase de reveal.
//
// Conteúdo (branch `!buscando`): o carrossel hero seguido de 4 seções
// principais, nesta ordem — "Continue de onde parou", "Top 10 em alta"
// (coverflow), "Acabou de sair" e "Próximas estreias" (redesenho de 2026-10-07;
// Top 10 e "Acabou de sair" trocaram de lugar em 2026-10-10 e voltaram em
// 2026-10-14, ver `fileirasDaHome`).
// As fileiras temáticas por gênero e os banners `DestaqueGrande` saíram da Home
// no mesmo dia, a pedido do usuário (os arquivos `inicio/DestaqueGrande.jsx` e
// `inicio/fileirasTematicas.js` e o endpoint seguem existindo, só não são
// renderizados aqui).
//
// "Acabou de sair" vem do feed próprio `GET /api/animes/novos-lancamentos`
// (agenda de exibição da AniList, um anime por card — o mais recente a ter
// lançado episódio primeiro); "Top 10" é recorte puro do feed
// `GET /api/animes/em-alta` (inicio/fileiras.js); "Próximas estreias" vem do
// feed próprio `GET /api/animes/proxima-temporada` (próxima temporada da
// AniList — o feed "em alta" só traz o que já está no ar); "Continuar
// assistindo" de `GET /api/episodios/continuar-assistindo`. Cada seção some
// sozinha quando não tem dado (guard em `fileirasDaHome`). As fileiras por
// gênero (`fileirasPorGenero` em fileiras.js) seguem fora da Home — página
// própria, ainda não construída.
// "Seu catálogo" segue FORA da Inicio de propósito — o catálogo local (listar,
// abrir, remover) mora inteiro em `paginas/Galeria.jsx` (rota "/animes",
// linkada na navbar). `DestaquePrincipal` também não está nesta ordem (pivot
// de produto anterior) — ver import comentado abaixo.
//
// Busca ao vivo (navbar, controlada aqui): digitar substitui inteiramente
// "Destaques da temporada" por (1) uma grade sobre o catálogo LOCAL
// (`listarAnimes`, filtro em memória a cada tecla) e (2) "Adicionar ao
// catálogo" — busca na AniList (`buscarAnimes`, só no Enter). Item ainda
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
// src/inicio/ só importam de src/api/, components/, hooks/ e
// react-router-dom — nada de src/player/ (a única ligação com o player é a
// rota "/assistir/:episodioId", string, não import). `hooks/
// useStatusDeCapturaIlha.js` (usado abaixo) não quebra isso: só importa de
// components/LinhaDeEpisodio.jsx e react-router-dom, sem tocar player/.

// `jobsPorEpisodio` — mesmo Map do WS que `App.jsx` já sobe pro app inteiro
// (`useEventosDeJobs`), descido pra `PaginaDoAnime`, `Galeria` e agora
// também aqui — a prateleira "Continuar assistindo" ganha o mesmo status ao
// vivo de captura no ramo `processando` (`components/
// CartaoContinuarAssistindo.jsx`), e a própria ilha dinâmica da navbar
// (`statusCapturaIlha`/`capturaProntaIlha`/`erroCapturaIlha`, ver
// `BarraDeNavegacao` abaixo) passa a existir na Home — pendência do
// checkpoint anterior ("Home decide depois"), resolvida: como esta página já
// montava `BarraDeNavegacao`, só faltava ligar o mesmo hook global que
// Galeria/PaginaDoAnime já usam (`hooks/useStatusDeCapturaIlha.js`).

// Poll de `still_pendente` (ver efeito abaixo). O teto (4s x 16 = ~64s) cobre a
// busca de still TMDB (timeout de 9s, `progresso.py`), que resolve bem antes —
// o efeito para sozinho cedo (dependência vira `false` assim que a pendência
// resolve, sem esperar o teto).
const _INTERVALO_POLL_STILL_MS = 4000;
const _MAX_TENTATIVAS_POLL_STILL = 16;
export default function Inicio({ jobsPorEpisodio, snapshotId }) {
  const navigate = useNavigate();
  const idResultadosBiblioteca = useId();
  const {
    statusCapturaIlha,
    aoClicarStatusCapturaIlha,
    capturaProntaIlha,
    aoClicarCapturaProntaIlha,
    erroCapturaIlha,
    aoClicarErroCapturaIlha,
  } = useStatusDeCapturaIlha(jobsPorEpisodio, snapshotId);

  const emAlta = useRecurso(listarAnimesEmAlta, []);
  // "Novos lançamentos" — feed próprio (`GET /api/animes/novos-lancamentos`,
  // agenda de exibição da AniList), independente do "em alta" (trending) e do
  // "próxima temporada" (ainda não estreou). Mesma exibição silenciosa:
  // carregando/erro/vazio a fileira simplesmente não aparece.
  const novosLancamentos = useRecurso(listarNovosLancamentos, []);
  // Episódio sai a qualquer hora: sem isto a fileira só mudaria com reload.
  useAtualizacaoPeriodica(novosLancamentos.recarregar, INTERVALO_NOVOS_LANCAMENTOS_MS);
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
  const continuando = useRecurso(listarContinuarAssistindo, [], 'episodios');
  const itensContinuar = continuando.dados ?? [];
  // Episódio novo na fonte chega pelo zelador do backend, sem ninguém abrir a página.
  useAtualizacaoPeriodica(continuando.atualizar, INTERVALO_NOVOS_LANCAMENTOS_MS);
  // Poll leve enquanto algum card `capturavel` está com `still_pendente` (busca de
  // still/título/sinopse TMDB em segundo plano, `progresso.py::
  // _aplicar_still_capturavel`): sem ele o usuário só veria o card certo depois de um
  // F5. Para sozinho quando a pendência resolve ou ao atingir o teto de tentativas;
  // sem pendência (o caso comum) o efeito nem agenda o timer.
  const precisaPollDeContinuar = itensContinuar.some((item) => item.still_pendente);
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
  // janela do poll de still acima. Guard por `episodio_id:job.id`
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
  // Corte DEPOIS de ordenar: ficam as 20 estreias mais próximas, e os itens sem
  // data (final da lista) são os que saem.
  const proximaTemporadaOrdenada = useMemo(
    () => ordenarPorEstreia(proximaTemporada.dados).slice(0, LIMITE_PROXIMAS_ESTREIAS),
    [proximaTemporada.dados]
  );

  // "Top 10" — recorte puro do feed `em-alta` (inicio/fileiras.js). `?? []`
  // porque `emAlta.dados` é `null` até a primeira resposta. (As fileiras por
  // gênero — `fileirasPorGenero`, ainda exportada de fileiras.js — saíram da
  // Home; vão pra uma página própria.)
  const top10 = useMemo(() => topDaTemporada(emAlta.dados ?? []), [emAlta.dados]);
  // O carrossel sorteia só do que sobra depois do Top 10 (que vem logo abaixo
  // dele): o mesmo título não aparece nos dois. Feed com no máximo 10 itens não
  // tem "sobra" — aí o carrossel usa o feed inteiro em vez de sumir.
  const itensDoCarrossel = useMemo(() => {
    const feed = emAlta.dados ?? [];
    return feed.length > top10.length ? feed.slice(top10.length) : feed;
  }, [emAlta.dados, top10]);
  const rankingInicialDoCarrossel = itensDoCarrossel === emAlta.dados ? 0 : top10.length;

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

  // "Marcar como assistido" do menu de `CartaoContinuarAssistindo.jsx` —
  // restrito a ESTE episódio (`item.numero`), não ao anime inteiro (pedido
  // explícito do usuário, 2026-09-21: a prateleira mostra só o PRÓXIMO
  // episódio, marcar em lote a partir dela surpreendia). Sem `recarregar()`
  // manual no sucesso: `marcarEpisodioAssistido` já invalida a chave
  // 'episodios' (api/invalidacao.js), a mesma que `continuando` assina —
  // o slot avança sozinho (ou some, se era o último) quando resolve.
  // `fonte_ambigua` reusa `animeIdComFonteAmbigua`/o aviso já renderizado
  // pra `capturarProximo` acima (mesmo caso raro, mesmo link pra resolver na
  // página do anime) — não duplica estado nem mensagem pra isso.
  const [animeMarcandoAssistido, setAnimeMarcandoAssistido] = useState(null);
  const [erroMarcarAssistido, setErroMarcarAssistido] = useState(null);

  const aoMarcarAssistidoDoContinuar = useCallback(
    async (item) => {
      if (animeMarcandoAssistido != null) return;
      setAnimeMarcandoAssistido(item.anime_id);
      setErroMarcarAssistido(null);
      setAnimeIdComFonteAmbigua(null);
      try {
        const versaoPedida = item.versao === 'desconhecida' ? 'legendado' : item.versao;
        await marcarEpisodioAssistido(item.anime_id, item.numero, versaoPedida);
      } catch (erroCapturado) {
        if (erroCapturado instanceof ErroDeApi && erroCapturado.detail?.motivo === 'fonte_ambigua') {
          setAnimeIdComFonteAmbigua(item.anime_id);
        } else {
          console.error('falha ao marcar anime como assistido pela Home', erroCapturado);
          setErroMarcarAssistido(
            `Não foi possível marcar "${item.anime_titulo}" como assistido — tente novamente.`
          );
        }
        continuando.recarregar();
      } finally {
        setAnimeMarcandoAssistido(null);
      }
    },
    [animeMarcandoAssistido, continuando]
  );

  const [chaveEmMaterializacao, setChaveEmMaterializacao] = useState(null);
  const [erroMaterializacao, setErroMaterializacao] = useState(null);

  // Sinopse completa aberta pelo carrossel (inicio/CarrosselDestaques.jsx): vive
  // aqui, e não nele, porque o painel é da ilha da navbar (BarraDeNavegacao.jsx),
  // irmã do carrossel. `porPonteiro` = aberta por mouse/toque.
  const [sinopseNaIlha, setSinopseNaIlha] = useState(null);
  const aoFecharSinopse = useCallback(() => {
    // O dialog devolve o foco ao botão que o abriu; aberto por mouse/toque, isso
    // deixaria a <section> do carrossel "com foco dentro".
    if (sinopseNaIlha?.porPonteiro) document.activeElement?.blur();
    setSinopseNaIlha(null);
  }, [sinopseNaIlha]);
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
  // ("Próximas estreias", "Top 10", "Acabou de sair") — declarada aqui porque o
  // bloco de "Próximas estreias" precisa dela primeiro.
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

  // Navegação por seção na ilha dinâmica — dropdown reaproveitado do filtro
  // da Galeria (`opcoesSecoes`/`secaoSelecionada`/`aoMudarSecao`, mesmo
  // contrato de `opcoesFiltro`/`filtroSelecionado`/`aoMudarFiltro`, ver
  // `BarraDeNavegacao.jsx`), com scroll-spy pra rótulo "atual" e âncoras
  // `data-secao`/`ref` em cada uma das 4 seções principais (rótulos em
  // `ROTULOS_SECAO_NAV` abaixo; as fileiras temáticas e os banners saíram da
  // Home em 2026-10-07, então a ilha lista só estas). Duas tentativas
  // anteriores de navegação por seção foram revertidas — ver o histórico em
  // `BarraDeNavegacao.jsx` (topo do arquivo).
  //
  // `refsSecao`: mapa mutável `chave -> elemento` (não `useState`, a lista
  // de refs não precisa re-renderizar nada por si só) preenchido pelo `ref`
  // de callback de cada wrapper em `fileirasDaHome` abaixo. `secaoAtual`
  // (rótulo "atual" no dropdown) é decidido por `IntersectionObserver`: uma
  // faixa fina logo abaixo da navbar (`rootMargin` negativo no topo) até
  // 70% da viewport (negativo no fim) — a seção cujo topo está dentro dessa
  // faixa é a "atual". `intersecoesRef` guarda o estado de intersecção mais
  // recente de CADA seção (o observer dispara por alvo, não por página
  // inteira); a cada disparo, a seção atual vira a ÚLTIMA (mais abaixo, na
  // ordem de RENDER da página, ver `opcoesSecoes` mais abaixo) que ainda
  // está intersectando — é o mesmo efeito de "em qual seção o topo da
  // viewport já entrou".
  //
  // `ROTULOS_SECAO_NAV`: `chave` da seção -> rótulo na ilha.
  const ROTULOS_SECAO_NAV = {
    'proximas-estreias': 'Próximas estreias',
    'continuar-assistindo': 'Continue de onde parou',
    'top-10': 'Top 10 em alta',
    'novos-lancamentos': 'Acabou de sair',
  };
  const refsSecao = useRef({});
  const refSecao = useCallback(
    (chave) => (elemento) => {
      refsSecao.current[chave] = elemento;
    },
    []
  );
  const intersecoesSecaoRef = useRef(new Map());
  const [secaoAtual, setSecaoAtual] = useState(null);
  const movimentoReduzidoSecoes = usePrefersReducedMotion();

  const aoMudarSecao = useCallback(
    (valor) => {
      const elemento = refsSecao.current[valor];
      if (!elemento) return;
      // Offset fixo (não mede a navbar em runtime): `h-20` (80px) da navbar
      // + respiro — mesma ordem de grandeza do `pt-22` do `<main>` abaixo.
      const topo = elemento.getBoundingClientRect().top + window.scrollY - 100;
      window.scrollTo({ top: topo, behavior: movimentoReduzidoSecoes ? 'auto' : 'smooth' });
    },
    [movimentoReduzidoSecoes]
  );

  // Fileiras horizontais da home NA ORDEM em que aparecem, cada uma já como
  // nó pronto (com `key`). Só entram as que de fato vão renderizar (lista não
  // vazia). Montado no corpo do render (não `useMemo`): são poucos objetos +
  // JSX leve.
  //
  // As 4 seções principais abrem a página: continuar → Top 10 → lançamentos →
  // estreias (Top 10 voltou pro 2º lugar em 2026-10-14, pedido do usuário: o
  // coverflow casa com o banner do hero e fecha a vitrine). Do mais pessoal ao
  // mais geral, e dentro do geral do "agora" pro "em breve". O Top 10 sai do
  // mesmo feed do hero (`em-alta`), então o carrossel exclui os títulos dele
  // (`itensDoCarrossel`) pra não repetir. Cada uma tem título grande
  // (`SecaoDaHome`, ou `destaque` na `FileiraDeCards` do "continuar").
  // Posição de cada estreia dentro do seu dia (`primeiro`/`ultimo`) pra
  // `SlotDoDiaDeEstreia` desenhar a marca do dia acima dos cards.
  const posicaoNoDiaDeEstreia = new Map(
    agruparPorDiaDeEstreia(proximaTemporadaOrdenada).flatMap((grupo) =>
      grupo.itens.map((item, indice) => [
        chaveDoItemDoFeed(item),
        { data: grupo.data, primeiro: indice === 0, ultimo: indice === grupo.itens.length - 1 },
      ])
    )
  );

  const fileirasDaHome = [
    itensContinuar.length > 0 && {
      chave: 'continuar-assistindo',
      // `chaveDoItem` por `anime_id` (não mais `episodio_id`, que agora vem
      // nulo no ramo `capturavel` sem episódio) — um card por anime, ver
      // `backend/api/servicos/progresso.py`. Fileira rolável (não grade): a
      // lista inteira fica acessível, sem teto de itens; `destaque` mantém o
      // título na escala das outras seções principais.
      node: (
        <div
          key="continuar-assistindo"
          ref={refSecao('continuar-assistindo')}
          data-secao="continuar-assistindo"
        >
          <FileiraDeCards
            titulo="Continue de onde parou"
            descricao="Seus animes em andamento, a um clique do próximo episódio."
            destaque
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
                aoMarcarAssistido={aoMarcarAssistidoDoContinuar}
                marcando={animeMarcandoAssistido === item.anime_id}
              />
            )}
          />
        </div>
      ),
    },
    top10.length > 0 && {
      chave: 'top-10',
      // `pt-14`/`pb-10` somam ao `space-y-14` do contêiner e ao `pt-8` da seção de
      // baixo: 8rem (128px) do fim da seção de cima até o topo do pôster e 8rem do
      // fim do bloco de texto até o título da de baixo.
      node: (
        <div key="top-10" ref={refSecao('top-10')} data-secao="top-10" className="pb-10 pt-14">
          <SecaoDaHome titulo="Top 10 em alta" descricao="Os dez títulos mais vistos agora." cabecalhoOculto>
            <CoverflowDeEmAlta
              itens={top10}
              chaveDoItem={chaveDoItemDoFeed}
              aoAbrirSinopse={setSinopseNaIlha}
              aoAtivar={materializarEIrPara}
              desabilitado={chaveEmMaterializacao != null}
            />
          </SecaoDaHome>
        </div>
      ),
    },
    (novosLancamentos.dados ?? []).length > 0 && {
      chave: 'novos-lancamentos',
      node: (
        <div
          key="novos-lancamentos"
          ref={refSecao('novos-lancamentos')}
          data-secao="novos-lancamentos"
          className="pt-2"
        >
          <SecaoDaHome titulo="Acabou de sair" descricao="Episódios novos que acabaram de entrar no ar.">
            <ListaDeLancamentos
              itens={novosLancamentos.dados}
              chaveDoItem={chaveDoItemDoFeed}
              aoAtivar={materializarEIrPara}
              desabilitado={chaveEmMaterializacao != null}
            />
          </SecaoDaHome>
        </div>
      ),
    },
    (proximaTemporada.dados ?? []).length > 0 && {
      chave: 'proximas-estreias',
      node: (
        <div key="proximas-estreias" ref={refSecao('proximas-estreias')} data-secao="proximas-estreias">
          <SecaoDaHome
            titulo="Próximas estreias"
            descricao="Salve no catálogo para acompanhar os títulos que ainda vão estrear."
          >
            <FileiraDeCards
              semCabecalho
              titulo="Lista de próximas estreias"
              itens={proximaTemporadaOrdenada}
              tamanho="pequeno"
              comSombra={false}
              chaveDoItem={chaveDoItemDoFeed}
              renderItem={(item) => (
                <SlotDoDiaDeEstreia {...posicaoNoDiaDeEstreia.get(chaveDoItemDoFeed(item))}>
                  <CartaoDeEstreia
                    item={item}
                    salvo={estreiaEstaSalva(item)}
                    salvando={chaveSalvandoEstreia === chaveDoItemDoFeed(item)}
                    aoSalvar={() => alternarEstreiaSalva(item)}
                    semTextoDeData={posicaoNoDiaDeEstreia.get(chaveDoItemDoFeed(item))?.data != null}
                  />
                </SlotDoDiaDeEstreia>
              )}
            />
          </SecaoDaHome>
        </div>
      ),
    },
  ].filter(Boolean);

  // `opcoesSecoes`: as seções que renderizaram nesta carga (`fileirasDaHome` já
  // filtrou lista vazia), NA MESMA ORDEM de `fileirasDaHome` — ordem de render
  // = ordem de scroll da página, o que o dropdown e o scroll-spy abaixo
  // assumem. Rótulo vem de `ROTULOS_SECAO_NAV`.
  const opcoesSecoes = fileirasDaHome.map((fileira) => ({
    valor: fileira.chave,
    rotulo: ROTULOS_SECAO_NAV[fileira.chave],
  }));

  // Reobserva quando a lista de seções presentes muda (feed carregou/mudou)
  // — a dep usa a lista de chaves serializada (join) pra não re-rodar o
  // efeito a cada render sem motivo.
  const chavesSecaoNavOrdenadas = opcoesSecoes.map((opcao) => opcao.valor);
  const chavesSecaoNavChave = chavesSecaoNavOrdenadas.join(',');
  useEffect(() => {
    const elementos = chavesSecaoNavOrdenadas.map((chave) => refsSecao.current[chave]).filter(Boolean);
    if (elementos.length === 0) return undefined;
    const atualizarSecaoAtual = () => {
      let atual = null;
      for (const chave of chavesSecaoNavOrdenadas) {
        if (intersecoesSecaoRef.current.get(chave)) atual = chave;
      }
      if (atual) setSecaoAtual(atual);
    };
    // `rootMargin`: só conta como "atual" a seção cujo topo está entre 100px
    // abaixo do topo da viewport (logo abaixo da navbar) e 70% da altura da
    // tela — faixa fina perto do topo, mesmo espírito de scroll-spy clássico
    // (Bootstrap/Bulma).
    const observer = new IntersectionObserver(
      (entradas) => {
        entradas.forEach((entrada) => {
          intersecoesSecaoRef.current.set(entrada.target.dataset.secao, entrada.isIntersecting);
        });
        atualizarSecaoAtual();
      },
      { rootMargin: '-100px 0px -70% 0px' }
    );
    elementos.forEach((elemento) => observer.observe(elemento));
    return () => observer.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chavesSecaoNavChave]);

  return (
    <>
      {/* `opcoesSecoes`/`secaoSelecionada`/`aoMudarSecao`: a "ilha dinâmica"
          da navbar vira seletor de seção da própria Início em vez de filtro
          de catálogo (ver comentário completo mais acima e em
          `BarraDeNavegacao.jsx`) — some sozinho durante `buscando` (a
          busca substitui as fileiras por uma grade, as âncoras não existem
          nesse branch). */}
      <BarraDeNavegacao
        transparente
        termoBusca={termoBusca}
        aoMudarBusca={setTermoBusca}
        aoSubmeterBusca={submeterBusca}
        sinopse={sinopseNaIlha && { ...sinopseNaIlha, aoFechar: aoFecharSinopse }}
        opcoesSecoes={buscando ? undefined : opcoesSecoes}
        secaoSelecionada={secaoAtual}
        aoMudarSecao={aoMudarSecao}
        statusCapturaIlha={statusCapturaIlha}
        aoClicarStatusCapturaIlha={aoClicarStatusCapturaIlha}
        capturaProntaIlha={capturaProntaIlha}
        aoClicarCapturaProntaIlha={aoClicarCapturaProntaIlha}
        erroCapturaIlha={erroCapturaIlha}
        aoClicarErroCapturaIlha={aoClicarErroCapturaIlha}
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
                <EstadoComMascote alerta mensagem="Não foi possível carregar o catálogo.">
                  <BotaoDeEstado onClick={catalogo.recarregar}>Tentar novamente</BotaoDeEstado>
                </EstadoComMascote>
              )}
              {!catalogo.carregando && !catalogo.erro && animesFiltrados.length === 0 && (
                <EstadoComMascote mensagem={`Nenhum anime encontrado para “${termoBusca.trim()}”.`} />
              )}
            </div>
            {!catalogo.carregando && !catalogo.erro && animesFiltrados.length > 0 && (
              <GradeDeCatalogo
                itens={animesFiltrados}
                tamanho="pequeno"
                comSombra={false}
                comAnimacao={false}
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
                Adicionar ao catálogo
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
                    Aperte Enter para buscar novos animes e adicionar ao catálogo.
                  </p>
                )}
                {termoBuscaSubmetido !== '' && resultadosDesatualizados && (
                  <p className="mt-[22px] text-sm text-ink-muted">
                    Aperte Enter para atualizar os resultados.
                  </p>
                )}
                {buscaBibliotecaAtiva && buscaBiblioteca.carregando && (
                  <p className="mt-[22px] text-sm text-ink-muted">Buscando animes…</p>
                )}
                {buscaBibliotecaAtiva && buscaBiblioteca.erro && (
                  <EstadoComMascote alerta compacto mensagem="Não foi possível buscar animes.">
                    <BotaoDeEstado onClick={buscaBiblioteca.recarregar}>
                      Tentar novamente
                    </BotaoDeEstado>
                  </EstadoComMascote>
                )}
                {buscaBibliotecaAtiva &&
                  !buscaBiblioteca.carregando &&
                  !buscaBiblioteca.erro &&
                  resultadosBiblioteca.length === 0 && (
                    <EstadoComMascote
                      mensagem={`Nenhum anime novo encontrado para “${termoBuscaSubmetido}”.`}
                    />
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
                    comAnimacao={false}
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
                <EstadoComMascote
                  alerta
                  compacto
                  mensagem="Não foi possível carregar os destaques da temporada."
                >
                  <BotaoDeEstado onClick={emAlta.recarregar}>Tentar novamente</BotaoDeEstado>
                </EstadoComMascote>
              </div>
            )}
            {erroMaterializacao && (
              <div role="alert" className="px-4 pb-8 sm:px-6 lg:px-8">
                <p className="text-sm text-red-400">{erroMaterializacao}</p>
              </div>
            )}
            {erroMarcarAssistido && (
              <div role="alert" className="px-4 pb-8 sm:px-6 lg:px-8">
                <p className="text-sm text-red-400">{erroMarcarAssistido}</p>
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
              // Sem `-mb-*` (2026-10-07, pedido do usuário): o carrossel ocupa a
              // tela inteira e nenhuma seção "espia" por baixo dele — antes um
              // `-mb-26` puxava a primeira fileira pra dentro do fade da base
              // do hero (padrão AnimeFire). O respiro até a primeira seção vem
              // do `pt-12` do <div> das fileiras abaixo.
              <section className="-mt-22">
                <CarrosselDestaques
                  itens={itensDoCarrossel}
                  rankingInicial={rankingInicialDoCarrossel}
                  aoMaterializar={materializarEIrPara}
                  materializando={chaveEmMaterializacao != null}
                  aoAbrirSinopse={setSinopseNaIlha}
                  sinopseAberta={sinopseNaIlha != null}
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
            {/* `pt-12`: respiro entre o fim do hero (tela cheia, sem peek da
                primeira seção) e o título grande da primeira seção. */}
            <div className="relative z-10 space-y-14 pb-20 pt-4">
              {fileirasDaHome.map((fileira) => fileira.node)}
            </div>

          </>
        )}
      </main>
    </>
  );
}

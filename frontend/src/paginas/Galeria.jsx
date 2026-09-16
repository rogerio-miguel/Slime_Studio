import { useCallback, useId, useMemo, useState } from 'react';
import { ErroDeApi } from '../api/cliente.js';
import { listarAnimes, removerAnime } from '../api/recursos.js';
import { useRecurso } from '../api/useRecurso.js';
import AnimeCard from '../components/AnimeCard.jsx';
import BarraDeNavegacao from '../components/BarraDeNavegacao.jsx';
import CartaoDeVideoLocal from '../components/CartaoDeVideoLocal.jsx';
import DialogoDeConfirmacao from '../components/DialogoDeConfirmacao.jsx';
import { useFocoAoMontar } from '../hooks/useFocoAoMontar.js';
import CartaoDeEstreia from '../inicio/CartaoDeEstreia.jsx';
import { agruparEmFranquias } from '../inicio/franquia.js';
import GradeDeCatalogo from '../inicio/GradeDeCatalogo.jsx';
import { PADDING_TITULO_GRADE } from '../inicio/tamanhoDeCard.js';
import { VIDEOS_LOCAIS } from '../videosLocais.js';

// Rótulos em `core/enums.py::StatusLancamento` (backend) — mesmos valores
// StrEnum, traduzidos aqui pra exibição no filtro de status. Cunhados aqui,
// sem rótulo pré-existente no frontend a reaproveitar.
const ROTULOS_STATUS_LANCAMENTO = {
  em_lancamento: 'Em lançamento',
  finalizado: 'Finalizado',
  nao_lancado: 'Não lançado',
  cancelado: 'Cancelado',
  hiato: 'Em hiato',
};

// Classe compartilhada pelos três <select> do filtro/ordenação — mesmo padrão
// visual de player/SeletorDePreset.jsx (único <select> já existente no app).
const CLASSE_SELECT =
  'rounded-md border border-border-chrome bg-[#222] px-3 py-1.5 text-sm text-white outline-none transition-colors hover:bg-[#2a2a2a] focus-visible:border-neon';
const CLASSE_LABEL_FILTRO = 'text-xs font-semibold uppercase tracking-wide text-ink-muted';

// Instante em ms de `proximo_ep_em`, ou `null` quando ausente/inválido —
// usado só pela ordenação "Próximo episódio" (empurra itens sem valor pro
// fim). `Number.isNaN` cobre string ISO malformada sem derrubar o sort.
function instanteDoProximoEpisodio(anime) {
  if (!anime.proximo_ep_em) return null;
  const instante = new Date(anime.proximo_ep_em).getTime();
  return Number.isNaN(instante) ? null : instante;
}

function compararPorProximoEpisodio(a, b) {
  const instanteA = instanteDoProximoEpisodio(a);
  const instanteB = instanteDoProximoEpisodio(b);
  if (instanteA == null && instanteB == null) return 0;
  if (instanteA == null) return 1; // sem valor sempre por último
  if (instanteB == null) return -1;
  return instanteA - instanteB; // mais próximo (menor instante) primeiro
}

// Nunca muta `lista` (mesma convenção de inicio/fileiras.js) — devolve
// sempre uma cópia nova, mesmo pra `criterio === 'titulo'`.
function ordenarAnimes(lista, criterio) {
  const copia = [...lista];
  if (criterio === 'proximo_episodio') return copia.sort(compararPorProximoEpisodio);
  return copia.sort((a, b) => a.titulo.localeCompare(b.titulo, 'pt-BR'));
}

// Rota "/animes" — catálogo completo. Sem cadastro manual aqui: o catálogo
// é populado materializando itens do feed de provedor externo na Home
// (`paginas/Inicio.jsx`, `POST /api/admin/animes`), não por um formulário
// nesta página.
//
// Busca é local: mesmo
// padrão de `termoBusca`/filtro em memória de `paginas/Inicio.jsx`, sem
// `?q=` na URL nem `aoSubmeterBusca` — esta página não busca em fontes
// externas, só filtra o catálogo já carregado (`GET /api/animes` não
// aceita query param de busca e a lista é pequena o bastante, uso pessoal,
// pra não justificar um endpoint novo).
//
// `<main>` sem padding horizontal e sem `max-w`: as duas grades
// (`inicio/GradeDeCatalogo.jsx`) já aplicam o gutter de 3.7% de cada lado
// (via `CLASSE_GUTTER`) medindo a viewport inteira, exatamente como as
// fileiras da Home (`inicio/FileiraDeCards.jsx`). Um `px` no `<main>`
// encolheria o container que o gutter mede e os cards sairiam mais
// estreitos que os da fileira "pequeno" da Home no mesmo viewport — o
// alinhamento título/card e o tamanho de card dependem de os dois medirem
// o mesmo container. Os títulos e os estados transitórios recuperam o
// alinhamento via `paddingInline: PADDING_TITULO_GRADE` (só o gutter — o
// slot da grade não tem padding próprio), não via `px` no `<main>`.
export default function Galeria() {
  const idMeuCatalogo = useId();
  const idVideosLocais = useId();
  const idFiltroStatus = useId();
  const idOrdenacao = useId();
  const [termoBusca, setTermoBusca] = useState('');
  const termoBuscaNormalizado = termoBusca.trim().toLowerCase();
  const focoTitulo = useFocoAoMontar();
  // `aquecer: true` — esta é a única página que dispara a carona fire-and-forget
  // do backend (sondagem da fonte real + aquecimento de `status_lancamento`); a
  // Home chama `listarAnimes()` sem a flag. `recarregar` do `useRecurso` segue
  // funcionando: reexecuta este mesmo `buscar`.
  // Chave 'animes' (invalidacao.js): recarrega sozinho quando `criarAnime`/
  // `removerAnime` resolve, mesmo se disparado por outra página.
  const { dados: animes, carregando, erro, recarregar } = useRecurso(
    () => listarAnimes({ aquecer: true }),
    [],
    'animes'
  );

  const [statusSelecionado, setStatusSelecionado] = useState('');
  const [ordenacao, setOrdenacao] = useState('titulo');

  // Opções construídas a partir do catálogo já carregado — nunca hardcoded:
  // um status que não aparece em nenhum anime não vira opção morta no
  // dropdown. Rótulo ordena as opções (não a chave crua).
  const statusDisponiveis = useMemo(() => {
    const encontrados = new Set();
    for (const anime of animes ?? []) {
      if (anime.status_lancamento) encontrados.add(anime.status_lancamento);
    }
    return [...encontrados].sort((a, b) =>
      (ROTULOS_STATUS_LANCAMENTO[a] ?? a).localeCompare(ROTULOS_STATUS_LANCAMENTO[b] ?? b, 'pt-BR')
    );
  }, [animes]);

  // Agrupamento por franquia (Fase 5): 1 card por `serie_ancora` (fallback slug),
  // representado pela última temporada, com badge/gêneros/status agregados de
  // todas as temporadas — ver `inicio/franquia.js`. Client-side: `GET /api/animes`
  // só ganhou `serie_ancora`/`numero_temporada`, a lista é pequena (uso pessoal).
  const franquias = useMemo(() => agruparEmFranquias(animes ?? []), [animes]);

  // Busca -> status -> ordenação, sempre client-side sobre as franquias já
  // agrupadas (sem chamada de API nova). Cada filtro bate se QUALQUER
  // temporada da franquia bate.
  const animesExibidos = useMemo(() => {
    let lista = franquias;
    if (termoBuscaNormalizado) {
      lista = lista.filter((franquia) =>
        franquia.titulosDaFranquia.some((titulo) =>
          titulo.toLowerCase().includes(termoBuscaNormalizado)
        )
      );
    }
    if (statusSelecionado) {
      lista = lista.filter((franquia) => franquia.statusDaFranquia.includes(statusSelecionado));
    }
    return ordenarAnimes(lista, ordenacao);
  }, [franquias, termoBuscaNormalizado, statusSelecionado, ordenacao]);

  const [animeParaRemover, setAnimeParaRemover] = useState(null);
  const [removendo, setRemovendo] = useState(false);
  const [erroRemocao, setErroRemocao] = useState(null);

  // Remove a franquia INTEIRA: um DELETE por temporada (`idsDaFranquia`). Falha
  // no meio (ex. temporada com captura em andamento) para o laço e deixa as já
  // removidas removidas — cada `removerAnime` bem-sucedido já invalida
  // 'animes' (invalidacao.js) e recarrega esta grade sozinho, refletindo o
  // estado real mesmo numa remoção parcial, sem precisar de um `recarregar()`
  // manual aqui.
  const confirmarRemocao = useCallback(async () => {
    if (!animeParaRemover) return;
    setRemovendo(true);
    setErroRemocao(null);
    const ids = animeParaRemover.idsDaFranquia ?? [animeParaRemover.id];
    try {
      for (const id of ids) {
        await removerAnime(id);
      }
      setAnimeParaRemover(null);
    } catch (erroCapturado) {
      if (erroCapturado instanceof ErroDeApi && erroCapturado.detail?.motivo === 'job_em_execucao') {
        setErroRemocao(
          'Há uma captura em andamento — aguarde terminar antes de remover.'
        );
      } else {
        console.error('falha ao remover anime do catálogo', erroCapturado);
        setErroRemocao('Não foi possível remover — tente novamente.');
      }
    } finally {
      setRemovendo(false);
    }
  }, [animeParaRemover]);

  // Fecha o dialog (cancelar, ou Esc/backdrop via DialogoDeConfirmacao) e
  // limpa `erroRemocao` junto — sem isto, um erro de uma tentativa anterior
  // "vazaria" pra próxima abertura do dialog.
  const fecharDialogoRemocao = useCallback(() => {
    setAnimeParaRemover(null);
    setErroRemocao(null);
  }, []);

  const contagemTemporadas = animeParaRemover?.contagemDeTemporadas ?? 1;
  const mensagemRemocao =
    contagemTemporadas > 1
      ? `Remover "${animeParaRemover?.titulo}" e suas ${contagemTemporadas} temporadas do catálogo? Todos os episódios e capturas da franquia serão apagados.`
      : `Remover "${animeParaRemover?.titulo}" do catálogo? Episódios e capturas associados serão apagados.`;

  return (
    <>
      <BarraDeNavegacao transparente termoBusca={termoBusca} aoMudarBusca={setTermoBusca} />
      {/* `bg-black` (não mais `bg-[#17171b]` de paginas/Inicio.jsx): a Galeria
          não leva mais a drop shadow dos cards (`comSombra={false}` nas duas
          `GradeDeCatalogo` abaixo — ela só fazia sentido sobre aquele
          cinza-quase-preto; num preto sólido ela sumia de qualquer jeito), e
          sem sombra pra sustentar não há motivo pra não usar o preto sólido
          do resto do app (`html{background:#000}`, index.css). `min-h-screen`
          evita o fundo não cobrir a viewport quando o catálogo é curto. */}
      <main className="min-h-screen bg-black pb-10 pt-24">
        <section aria-labelledby={idMeuCatalogo}>
          {/* Sem `mb`: o respiro até os cards vem do `pt-[22px]` interno de
              GradeDeCatalogo, igual às fileiras da Home. `paddingInline`
              (não `px` no <main>) alinha o texto com a borda do CARD —
              gutter 3.7% + os 10px do slot da grade. */}
          <h1
            ref={focoTitulo}
            tabIndex={-1}
            id={idMeuCatalogo}
            style={{ paddingInline: PADDING_TITULO_GRADE }}
            className="text-2xl font-semibold text-white outline-none"
          >
            Meu Catálogo
          </h1>

          {/* Estados transitórios (carregando / erro / catálogo vazio / sem
              resultado) + a barra de filtro/ordenação, no mesmo wrapper que só
              repõe o `paddingInline` que antes vinha do `px` do <main>; cada
              bloco leva o próprio `mt-[22px]` (mesmo respiro título->conteúdo
              da grade). Altura zero quando nada aparece. */}
          <div style={{ paddingInline: PADDING_TITULO_GRADE }}>
            {carregando && (
              <p className="mt-[22px] text-sm text-ink-muted">Carregando catálogo…</p>
            )}
            {erro && (
              <div
                role="alert"
                className="mt-[22px] rounded-md border border-red-500/40 bg-red-950/40 px-4 py-3 text-sm text-red-300"
              >
                Não foi possível carregar o catálogo.{' '}
                <button type="button" onClick={recarregar} className="underline">
                  Tentar novamente
                </button>
              </div>
            )}
            {!carregando && !erro && animes?.length === 0 && (
              <p className="mt-[22px] text-sm text-ink-muted">Nenhum anime cadastrado ainda.</p>
            )}

            {/* Filtro por status + ordenação — <select> nativo (mesmo padrão
                de player/SeletorDePreset.jsx), sem chamada de API nova: as
                derivações rodam em memória sobre `animes`. O <select> de
                status só renderiza se há pelo menos uma opção real (ver
                `statusDisponiveis` acima) — um dropdown com só "Todos" seria
                um controle morto. Ordenação sempre aparece: "Título (A-Z)"
                funciona mesmo sem nenhum dado extra. */}
            {!carregando && !erro && animes?.length > 0 && (
              <div className="mt-[22px] flex flex-wrap items-end gap-4">
                {statusDisponiveis.length > 0 && (
                  <div className="flex flex-col gap-1">
                    <label htmlFor={idFiltroStatus} className={CLASSE_LABEL_FILTRO}>
                      Status
                    </label>
                    <select
                      id={idFiltroStatus}
                      value={statusSelecionado}
                      onChange={(event) => setStatusSelecionado(event.target.value)}
                      className={CLASSE_SELECT}
                    >
                      <option value="">Todos os status</option>
                      {statusDisponiveis.map((status) => (
                        <option key={status} value={status}>
                          {ROTULOS_STATUS_LANCAMENTO[status] ?? status}
                        </option>
                      ))}
                    </select>
                  </div>
                )}
                <div className="flex flex-col gap-1">
                  <label htmlFor={idOrdenacao} className={CLASSE_LABEL_FILTRO}>
                    Ordenar por
                  </label>
                  <select
                    id={idOrdenacao}
                    value={ordenacao}
                    onChange={(event) => setOrdenacao(event.target.value)}
                    className={CLASSE_SELECT}
                  >
                    <option value="titulo">Título (A-Z)</option>
                    <option value="proximo_episodio">Próximo episódio</option>
                  </select>
                </div>
              </div>
            )}

            {!carregando && !erro && animes?.length > 0 && animesExibidos.length === 0 && (
              <p className="mt-[22px] text-sm text-ink-muted">
                {termoBusca.trim()
                  ? `Nenhum anime encontrado para “${termoBusca.trim()}”.`
                  : 'Nenhum anime encontrado com os filtros selecionados.'}
              </p>
            )}
          </div>

          {/* Card inerte de estreia (CartaoDeEstreia) SÓ quando o anime
              realmente ainda não estreou (`status_lancamento === 'nao_lancado'`)
              E não tem episódio capturado. Todo o resto — já com episódio, ou
              já lançado mas sem captura, ou com fonte pendente nas extratoras —
              usa AnimeCard navegável: um anime já lançado sem captura precisa
              chegar na PaginaDoAnime pra resolver fonte / enfileirar captura;
              só o bookmark de "Próximas estreias" é beco sem saída proposital. */}
          <GradeDeCatalogo
            itens={animesExibidos}
            tamanho="pequeno"
            comSombra={false}
            chaveDoItem={(anime) => anime.id}
            renderItem={(anime) =>
              !anime.tem_episodios && anime.status_lancamento === 'nao_lancado' ? (
                <CartaoDeEstreia item={anime} aoRemover={() => setAnimeParaRemover(anime)} />
              ) : (
                <AnimeCard anime={anime} aoRemover={() => setAnimeParaRemover(anime)} />
              )
            }
          />
        </section>

        {/* Vídeos locais (videosLocais.js) — arquivos já em disco (public/
            videos-locais/), fora do catálogo/backend por completo: card
            leva direto pro player (`/assistir-local/:slug`), sem passar
            por materialização/captura. Depois da grade principal — não é
            catálogo de verdade, é um apêndice de arquivos soltos. Guard
            `length > 0` aqui na <section> (não só na grade): sem ele a
            <section>/<h2> apareceriam com a grade vazia. */}
        {VIDEOS_LOCAIS.length > 0 && (
          <section aria-labelledby={idVideosLocais} className="mt-10">
            <h2
              id={idVideosLocais}
              style={{ paddingInline: PADDING_TITULO_GRADE }}
              className="text-2xl font-semibold text-white"
            >
              Vídeos locais
            </h2>
            <GradeDeCatalogo
              itens={VIDEOS_LOCAIS}
              tamanho="pequeno"
              comSombra={false}
              chaveDoItem={(video) => video.slug}
              renderItem={(video) => <CartaoDeVideoLocal video={video} />}
            />
          </section>
        )}

        <DialogoDeConfirmacao
          aberto={animeParaRemover != null}
          titulo="Remover do catálogo"
          mensagem={mensagemRemocao}
          erro={erroRemocao}
          aoConfirmar={confirmarRemocao}
          aoFechar={fecharDialogoRemocao}
          confirmando={removendo}
        />
      </main>
    </>
  );
}

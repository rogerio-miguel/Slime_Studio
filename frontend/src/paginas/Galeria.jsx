import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import { ErroDeApi } from '../api/cliente.js';
import { aquecimentoEmAndamento, listarAnimes, removerAnime } from '../api/recursos.js';
import { useRecurso } from '../api/useRecurso.js';
import AnimeCard from '../components/AnimeCard.jsx';
import BarraDeNavegacao from '../components/BarraDeNavegacao.jsx';
import CartaoDeVideoLocal from '../components/CartaoDeVideoLocal.jsx';
import DialogoDeConfirmacao from '../components/DialogoDeConfirmacao.jsx';
import SeletorEmMenu from '../components/SeletorEmMenu.jsx';
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

// Poll leve pós-carga (`listarAnimes({aquecer:true})`, abaixo): a sondagem da
// fonte real e o aquecimento de `status_lancamento` que `?aquecer=true`
// dispara são fire-and-forget — o resultado entra no banco só para a PRÓXIMA
// leitura do catálogo (`api/rotas/animes.py::listar_animes`), então sem isto
// as tags (status/dublado-legendado) e "Tn EP.n" só atualizavam num F5
// manual. Mesmo papel de `sondagem_em_andamento` em `paginas/Inicio.jsx` pra
// "Continuar assistindo", só que o sinal vem de um endpoint próprio
// (`aquecimentoEmAndamento`) em vez de vir junto da lista — `GET /api/animes`
// tem que continuar devolvendo array cru, é o mesmo contrato que a Home usa
// sem a flag. Cada tick só CHECA a flag; o catálogo só é recarregado UMA vez,
// no fim (quando a flag vira `false` ou o teto de tentativas é atingido) —
// pedido explícito do usuário pra os cards não ficarem trocando de tag/
// contagem repetidas vezes no meio do aquecimento.
const _INTERVALO_POLL_AQUECIMENTO_MS = 4000;
const _MAX_TENTATIVAS_POLL_AQUECIMENTO = 16;

// Ordem fixa da grade — sem dropdown de ordenação (removido a pedido do
// usuário: com filtro de status/assistido já cobrindo o caso de uso, o
// dropdown não agregava nada). Nunca muta `lista` (mesma convenção de
// inicio/fileiras.js) — devolve sempre uma cópia nova.
function ordenarPorTitulo(lista) {
  return [...lista].sort((a, b) => a.titulo.localeCompare(b.titulo, 'pt-BR'));
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
  const idFiltro = useId();
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

  // Checagem única, assim que a primeira carga termina: `disparouRef` evita
  // repetir esta checagem nos ciclos de `carregando` que o PRÓPRIO poll
  // abaixo produz (cada `recarregar()` alterna `carregando` true->false de
  // novo). Sem o guard, cada tick do poll re-perguntaria isto à toa.
  const [aquecendo, setAquecendo] = useState(false);
  const disparouChecagemDeAquecimentoRef = useRef(false);
  useEffect(() => {
    if (carregando || animes == null || disparouChecagemDeAquecimentoRef.current) return undefined;
    disparouChecagemDeAquecimentoRef.current = true;
    let cancelado = false;
    aquecimentoEmAndamento()
      .then(({ em_andamento }) => {
        if (!cancelado) setAquecendo(em_andamento);
      })
      .catch(() => {});
    return () => {
      cancelado = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [carregando]);

  // Enquanto `aquecendo`, só CHECA a flag a cada
  // `_INTERVALO_POLL_AQUECIMENTO_MS` (sem tocar no catálogo) — `recarregar()`
  // roda uma ÚNICA vez, no fim, quando a sondagem/aquecimento realmente
  // terminam (ou ao atingir o teto de tentativas). Pedido explícito do
  // usuário: os cards devem atualizar DEPOIS que a busca termina, não a cada
  // tick no meio dela (senão o catálogo troca de tag/contagem várias vezes
  // seguidas enquanto o usuário olha a tela). Dependência é `aquecendo` (não
  // `carregando`): isolar a checagem do próprio efeito colateral de
  // `recarregar()` evita reiniciar o contador de tentativas a cada tick.
  useEffect(() => {
    if (!aquecendo) return undefined;
    let cancelado = false;
    let tentativas = 0;
    const intervalo = setInterval(async () => {
      tentativas += 1;
      let emAndamento = false;
      try {
        ({ em_andamento: emAndamento } = await aquecimentoEmAndamento());
      } catch {
        emAndamento = true; // erro de rede: assume que ainda está em voo, tenta de novo
      }
      if (cancelado) return;
      if (!emAndamento || tentativas >= _MAX_TENTATIVAS_POLL_AQUECIMENTO) {
        setAquecendo(false);
        recarregar();
      }
    }, _INTERVALO_POLL_AQUECIMENTO_MS);
    return () => {
      cancelado = true;
      clearInterval(intervalo);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [aquecendo]);

  const [filtroSelecionado, setFiltroSelecionado] = useState('');

  // Opções construídas a partir do catálogo já carregado — nunca hardcoded:
  // um status que não aparece em nenhum anime não vira opção morta no
  // dropdown. Rótulo ordena as opções (não a chave crua). `finalizado`
  // excluído a pedido do usuário — maioria do catálogo cai nesse status, o
  // filtro quase não filtrava nada.
  const statusDisponiveis = useMemo(() => {
    const encontrados = new Set();
    for (const anime of animes ?? []) {
      if (anime.status_lancamento && anime.status_lancamento !== 'finalizado') {
        encontrados.add(anime.status_lancamento);
      }
    }
    return [...encontrados].sort((a, b) =>
      (ROTULOS_STATUS_LANCAMENTO[a] ?? a).localeCompare(ROTULOS_STATUS_LANCAMENTO[b] ?? b, 'pt-BR')
    );
  }, [animes]);

  // Opções do dropdown "Filtrar" (SeletorEmMenu) — um único dropdown pra dois
  // eixos diferentes (status_lancamento × assistido, pedido explícito do
  // usuário: queria os dois juntos, não dois dropdowns separados), por isso o
  // `valor` de cada opção carrega um prefixo (`status:`/`assistido:`) que
  // `animesExibidos` usa pra saber qual filtro aplicar — os dois eixos não se
  // combinam mais (selecionar um substitui o outro, mesmo dropdown).
  const opcoesFiltro = useMemo(
    () => [
      { valor: '', rotulo: 'Todos' },
      ...statusDisponiveis.map((status) => ({
        valor: `status:${status}`,
        rotulo: ROTULOS_STATUS_LANCAMENTO[status] ?? status,
      })),
      { valor: 'assistido:sim', rotulo: 'Assistidos' },
      { valor: 'assistido:nao', rotulo: 'Não assistidos' },
    ],
    [statusDisponiveis]
  );

  // Agrupamento por franquia (Fase 5): 1 card por `serie_ancora` (fallback slug),
  // representado pela última temporada, com badge/gêneros/status agregados de
  // todas as temporadas — ver `inicio/franquia.js`. Client-side: `GET /api/animes`
  // só ganhou `serie_ancora`/`numero_temporada`, a lista é pequena (uso pessoal).
  const franquias = useMemo(() => agruparEmFranquias(animes ?? []), [animes]);

  // Busca -> filtro -> ordem fixa por título, sempre client-side sobre as
  // franquias já agrupadas (sem chamada de API nova). `filtroSelecionado`
  // decide o eixo pelo prefixo (ver `opcoesFiltro` acima): status bate se
  // QUALQUER temporada da franquia bate; assistido usa o agregado da
  // franquia inteira (`franquia.assistido`, inicio/franquia.js).
  const animesExibidos = useMemo(() => {
    let lista = franquias;
    if (termoBuscaNormalizado) {
      lista = lista.filter((franquia) =>
        franquia.titulosDaFranquia.some((titulo) =>
          titulo.toLowerCase().includes(termoBuscaNormalizado)
        )
      );
    }
    if (filtroSelecionado.startsWith('status:')) {
      const status = filtroSelecionado.slice('status:'.length);
      lista = lista.filter((franquia) => franquia.statusDaFranquia.includes(status));
    } else if (filtroSelecionado.startsWith('assistido:')) {
      const assistido = filtroSelecionado.slice('assistido:'.length) === 'sim';
      lista = lista.filter((franquia) => franquia.assistido === assistido);
    }
    return ordenarPorTitulo(lista);
  }, [franquias, termoBuscaNormalizado, filtroSelecionado]);

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
              gutter 3.7% + os 10px do slot da grade. "Filtrar" (SeletorEmMenu
              — mesmo padrão de dropdown de components/SeletorDeTemporada.jsx)
              entra na MESMA linha do título, do outro lado do outro (`justify-between`
              + `items-center`) — pedido explícito do usuário. */}
          <div
            style={{ paddingInline: PADDING_TITULO_GRADE }}
            className="flex items-center gap-4"
          >
            <h1
              ref={focoTitulo}
              tabIndex={-1}
              id={idMeuCatalogo}
              className="text-2xl font-semibold text-white outline-none"
            >
              Meu Catálogo
            </h1>
            {!carregando && !erro && animes?.length > 0 && (
              <SeletorEmMenu
                id={idFiltro}
                opcoes={opcoesFiltro}
                valor={filtroSelecionado}
                aoMudar={setFiltroSelecionado}
                rotuloAcessivel="Filtrar"
                prefixo="FILTRAR"
              />
            )}
          </div>

          {/* Estados transitórios (carregando / erro / catálogo vazio / sem
              resultado), no mesmo wrapper que só repõe o `paddingInline` que
              antes vinha do `px` do <main>; cada bloco leva o próprio
              `mt-[22px]` (mesmo respiro título->conteúdo da grade). Altura
              zero quando nada aparece. */}
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
            comAnimacao={false}
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
              comAnimacao={false}
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

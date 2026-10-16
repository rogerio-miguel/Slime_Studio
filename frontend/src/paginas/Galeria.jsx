import { useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { ErroDeApi } from '../api/cliente.js';
import { listarAnimes, removerAnime } from '../api/recursos.js';
import { useRecurso } from '../api/useRecurso.js';
import AnimeCard from '../components/AnimeCard.jsx';
import BarraDeNavegacao from '../components/BarraDeNavegacao.jsx';
import CartaoDeVideoLocal from '../components/CartaoDeVideoLocal.jsx';
import { useAtualizacaoPeriodica } from '../hooks/useAtualizacaoPeriodica.js';
import { useFocoAoMontar } from '../hooks/useFocoAoMontar.js';
import { useStatusDeCapturaIlha } from '../hooks/useStatusDeCapturaIlha.js';
import CartaoDeEstreia from '../inicio/CartaoDeEstreia.jsx';
import { agruparEmFranquias } from '../inicio/franquia.js';
import {
  contarPorGenero,
  filtrarFranquias,
  agruparPorDiaDoFiltro,
  temOrdemFixa,
  OPCOES_DE_ORDEM,
  ORDEM_PADRAO,
  ordenarFranquias,
} from '../inicio/filtrosDeCatalogo.js';
import { traduzirGenero } from '../inicio/generos.js';
import GradeDeCatalogo from '../inicio/GradeDeCatalogo.jsx';
import SlotDoDiaDeEstreia from '../inicio/SlotDoDiaDeEstreia.jsx';
import { PADDING_TITULO_GRADE } from '../inicio/tamanhoDeCard.js';
import { usePreferencia } from '../player/hooks/usePreferencia.js';
import { VIDEOS_LOCAIS } from '../videosLocais.js';
import EstadoComMascote from '../components/mascote/EstadoComMascote.jsx';
import BotaoDeEstado from '../components/mascote/BotaoDeEstado.jsx';

// Rótulos em `core/enums.py::StatusLancamento` (backend) — mesmos valores
// StrEnum, traduzidos aqui pra exibição no filtro de status. Cunhados aqui,
// sem rótulo pré-existente no frontend a reaproveitar. `nao_lancado` aparece
// como "Próximas estreias" (mesmo nome da fileira da Home).
const ROTULOS_STATUS_LANCAMENTO = {
  em_lancamento: 'Em lançamento',
  finalizado: 'Finalizado',
  nao_lancado: 'Próximas estreias',
  cancelado: 'Cancelado',
  hiato: 'Em hiato',
};

// Valor especial de `filtroSelecionado` pra "Vídeos locais" (pedido do
// usuário, 2026-09-28) — não é um EIXO de filtro do catálogo de animes como
// os outros (sem prefixo `status:`/`assistido:`/`novos:`, `animesExibidos`
// nem processa isto): é um modo de visualização à parte que TROCA a grade
// principal pela grade de vídeos locais, mesmo padrão "substitui, não soma"
// dos demais itens do dropdown. Por isso a seção de vídeos locais deixou de
// ser sempre visível (era um apêndice fixo embaixo da grade) e passou a só
// aparecer quando este valor está selecionado.
const VALOR_FILTRO_VIDEOS_LOCAIS = 'videos-locais';
const CHAVE_DA_ORDEM = 'slime.galeria.ordem';
const CHAVE_DO_FILTRO = 'slime.galeria.filtro';
const CHAVE_DA_ORDEM_AVULSA = 'slime.galeria.ordemAvulsa';
const CHAVE_DOS_GENEROS = 'slime.galeria.generos';

// A verificação das fontes é do zelador (backend, `api/servicos/zelador.py`) e roda
// sem esta página aberta; ela só relê o catálogo de tempos em tempos (e ao voltar à
// aba) pra mostrar o que o zelador achou — tags, contagem "Tn EP.n", notificação.
const INTERVALO_ATUALIZACAO_CATALOGO_MS = 2 * 60 * 1000;

// Quanto tempo a notificação "novos episódios" da ilha dinâmica
// (BarraDeNavegacao.jsx) fica visível antes de sumir sozinha — pedido do
// usuário, 2026-09-27.
const DURACAO_NOTIFICACAO_NOVOS_EPS_MS = 5000;

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
// `jobsPorEpisodio` (App.jsx::Shell -> useEventosDeJobs.js, Map global do WS
// `episodio_id -> job`, TODOS os animes, não só os exibidos na grade
// filtrada) — alimenta só a notificação "episódio pronto" da ilha dinâmica
// (ver useEffect de diffing abaixo); a grade em si não cruza com jobs (isso é
// só feito em PaginaDoAnime.jsx, que mostra status de captura por episódio).
export default function Galeria({ jobsPorEpisodio, snapshotId }) {
  const {
    statusCapturaIlha,
    aoClicarStatusCapturaIlha,
    capturaProntaIlha,
    aoClicarCapturaProntaIlha,
    erroCapturaIlha,
    aoClicarErroCapturaIlha,
  } = useStatusDeCapturaIlha(jobsPorEpisodio, snapshotId);
  const idMeuCatalogo = useId();
  const idVideosLocais = useId();
  const [termoBusca, setTermoBusca] = useState('');
  const termoBuscaNormalizado = termoBusca.trim().toLowerCase();
  const focoTitulo = useFocoAoMontar();
  // Chave 'animes' (invalidacao.js): recarrega sozinho quando `criarAnime`/
  // `removerAnime` resolve, mesmo se disparado por outra página.
  const { dados: animes, carregando, erro, recarregar, atualizar } = useRecurso(
    listarAnimes,
    [],
    'animes'
  );
  useAtualizacaoPeriodica(atualizar, INTERVALO_ATUALIZACAO_CATALOGO_MS);

  // Filtro, ordem avulsa e gêneros do painel também ficam salvos no navegador e
  // voltam ao recarregar. O valor salvo pode ter perdido o sentido (status que
  // saiu do catálogo, gênero removido, vídeos locais zerados): `filtroSelecionado`
  // e `generosAtivos` abaixo descartam o que não existe mais, sem apagar o salvo.
  const [filtroSalvo, setFiltroSelecionado] = usePreferencia(CHAVE_DO_FILTRO, '');
  // A ordem escolhida só persiste em "Todos" — e persiste de verdade: fica salva
  // no navegador (`slime.galeria.ordem`) e volta ao reabrir a página. Em qualquer
  // outro filtro dá pra trocar, mas ela vale só enquanto aquele filtro está ativo
  // (`mudarFiltro` zera `ordemAvulsa`) e volta à de "Todos" ao sair. Valor salvo
  // que não existe mais nas opções cai no padrão.
  const [ordemSalva, setOrdemEmTodos] = usePreferencia(CHAVE_DA_ORDEM, ORDEM_PADRAO);
  const ordemEmTodos = OPCOES_DE_ORDEM.some((opcao) => opcao.valor === ordemSalva)
    ? ordemSalva
    : ORDEM_PADRAO;
  const [ordemAvulsaSalva, setOrdemAvulsa] = usePreferencia(CHAVE_DA_ORDEM_AVULSA, null);
  const ordemAvulsa = OPCOES_DE_ORDEM.some((opcao) => opcao.valor === ordemAvulsaSalva)
    ? ordemAvulsaSalva
    : null;
  const [generosSalvos, setGenerosSalvos] = usePreferencia(CHAVE_DOS_GENEROS, []);
  // Painel de filtros da ilha (BarraDeNavegacao.jsx): fica `true` até a animação
  // de volta terminar (`aoFechar`), não só até o pedido de fechar.
  const [painelAberto, setPainelAberto] = useState(false);

  // Último scrollY conhecido ANTES da troca de filtro. Não dá pra usar
  // `window.scrollY` dentro do `useLayoutEffect` abaixo pra decidir se o
  // navegador ia clampar — nesse ponto o layout novo (lista já filtrada) já
  // rodou, então se o clamp ia acontecer ele JÁ aconteceu e o valor "de
  // antes" já se perdeu. Listener passivo (mesmo padrão de scroll de
  // BarraDeNavegacao.jsx) mantém a referência sempre com o valor de antes do
  // clique, intocada até o próprio filtro mudar o layout.
  const ultimoScrollYRef = useRef(0);
  useEffect(() => {
    let quadroPendente = false;
    const atualizar = () => {
      ultimoScrollYRef.current = window.scrollY;
      quadroPendente = false;
    };
    const aoRolar = () => {
      if (quadroPendente) return;
      quadroPendente = true;
      requestAnimationFrame(atualizar);
    };
    ultimoScrollYRef.current = window.scrollY;
    window.addEventListener('scroll', aoRolar, { passive: true });
    return () => window.removeEventListener('scroll', aoRolar);
  }, []);

  // Bug reportado pelo usuário (2026-09-27): trocar o filtro enquanto rolado
  // (ilha dinâmica ativa) podia deixar a lista bem mais curta que antes —
  // o navegador então clampava o scroll pro novo `scrollHeight` menor,
  // "teletransportando" o usuário pra quase o fim da página. Correção
  // MÍNIMA (pedido explícito do usuário depois de testar um `scrollTo(0)`
  // incondicional a cada troca — ficava estranho ao lado do crossfade do
  // rótulo, ver SeletorEmMenu.jsx): só pula pro topo quando a troca
  // REALMENTE ia clampar (lista nova mais curta que a posição rolada);
  // senão fica parado onde estava, sem nenhum scroll forçado. `useLayoutEffect`
  // (não `useEffect`): mede `scrollHeight` depois do DOM já mutado mas ANTES
  // do paint, então se corrigir, o pulo não chega a ficar visível como dois
  // saltos (clamp do navegador + nosso `scrollTo`). Ignora a primeira
  // renderização (`useRef` em vez de checar `filtroSelecionado === ''`, que
  // também é o valor de "Todos" e dispararia isto de novo ao escolher
  // "Todos" outra vez).
  const primeiraRenderizacaoFiltroRef = useRef(true);
  useLayoutEffect(() => {
    if (primeiraRenderizacaoFiltroRef.current) {
      primeiraRenderizacaoFiltroRef.current = false;
      return;
    }
    const alturaMaximaScroll = document.documentElement.scrollHeight - window.innerHeight;
    if (ultimoScrollYRef.current > alturaMaximaScroll) {
      window.scrollTo(0, 0);
      ultimoScrollYRef.current = 0;
    }
  }, [filtroSalvo, generosSalvos, ordemEmTodos, ordemAvulsa]);

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

  // Filtro salvo só vale se ainda existe: com o catálogo carregado, um status
  // ausente (ou "Vídeos locais" sem vídeo nenhum) volta a "Todos" em vez de
  // esvaziar a grade sem opção visível pra desfazer. Antes de carregar, confia.
  const filtroSelecionado = useMemo(() => {
    if (filtroSalvo === VALOR_FILTRO_VIDEOS_LOCAIS) {
      return VIDEOS_LOCAIS.length > 0 ? filtroSalvo : '';
    }
    if (filtroSalvo.startsWith('status:') && animes != null) {
      return statusDisponiveis.includes(filtroSalvo.slice('status:'.length)) ? filtroSalvo : '';
    }
    return filtroSalvo;
  }, [filtroSalvo, animes, statusDisponiveis]);

  // Opções do dropdown "Filtrar" (SeletorEmMenu) — um único dropdown pra três
  // eixos diferentes (status_lancamento × assistido × novos episódios, pedido
  // explícito do usuário: queria tudo junto, não dropdowns separados), por
  // isso o `valor` de cada opção carrega um prefixo (`status:`/`assistido:`/
  // `novos:`) que `animesExibidos` usa pra saber qual filtro aplicar — os
  // eixos não se combinam entre si (selecionar um substitui o outro, mesmo
  // dropdown). "Novos episódios" bate no mesmo agregado que acende a
  // BadgeDeEpisodiosNovos no card (`franquia.episodios_novos > 0`,
  // inicio/franquia.js) — filtro e badge sempre concordam.
  const opcoesFiltro = useMemo(
    () => [
      { valor: '', rotulo: 'Todos' },
      { valor: 'novos:sim', rotulo: 'Novos episódios' },
      ...statusDisponiveis.map((status) => ({
        valor: `status:${status}`,
        rotulo: ROTULOS_STATUS_LANCAMENTO[status] ?? status,
      })),
      { valor: 'assistido:sim', rotulo: 'Assistidos' },
      // Último da lista: não é eixo do catálogo de animes, é o modo de
      // visualização à parte (ver comentário de `VALOR_FILTRO_VIDEOS_LOCAIS`
      // no topo do arquivo). Guard de `length` aqui também: sem vídeo local
      // nenhum, nem a opção aparece.
      ...(VIDEOS_LOCAIS.length > 0
        ? [{ valor: VALOR_FILTRO_VIDEOS_LOCAIS, rotulo: 'Vídeos locais' }]
        : []),
    ],
    [statusDisponiveis]
  );

  // Agrupamento por franquia (Fase 5): 1 card por `serie_ancora` (fallback slug),
  // representado pela última temporada, com badge/gêneros/status agregados de
  // todas as temporadas — ver `inicio/franquia.js`. Client-side: `GET /api/animes`
  // só ganhou `serie_ancora`/`numero_temporada`, a lista é pequena (uso pessoal).
  const franquias = useMemo(() => agruparEmFranquias(animes ?? []), [animes]);

  // Gêneros do catálogo (nunca hardcoded, como os status acima). A seleção que
  // sobrou de um gênero que saiu do catálogo (anime removido) é descartada aqui,
  // senão filtraria tudo sem nenhum botão visível pra desfazer.
  const listaDeGeneros = useMemo(
    () => [...new Set(franquias.flatMap((franquia) => franquia.generos))],
    [franquias],
  );
  const generosAtivos = useMemo(
    () => new Set(generosSalvos.filter((genero) => listaDeGeneros.includes(genero))),
    [generosSalvos, listaDeGeneros],
  );
  const alternarGenero = useCallback((genero) => {
    setGenerosSalvos((anterior) =>
      anterior.includes(genero) ? anterior.filter((g) => g !== genero) : [...anterior, genero],
    );
  }, [setGenerosSalvos]);

  const emVideosLocais = filtroSelecionado === VALOR_FILTRO_VIDEOS_LOCAIS;
  const emOrdemFixa = temOrdemFixa(filtroSelecionado);
  const ordemEfetiva =
    filtroSelecionado === '' ? ordemEmTodos : (ordemAvulsa ?? ORDEM_PADRAO);
  const selecaoAtiva = filtroSelecionado !== '' || generosAtivos.size > 0;
  const mudarOrdem = filtroSelecionado === '' ? setOrdemEmTodos : setOrdemAvulsa;
  const mudarFiltro = useCallback((valor) => {
    setFiltroSelecionado(valor);
    setOrdemAvulsa(null);
  }, [setFiltroSelecionado, setOrdemAvulsa]);
  const filtrosAtivos =
    (filtroSelecionado !== '' ? 1 : 0) +
    generosAtivos.size +
    (ordemEfetiva !== ORDEM_PADRAO ? 1 : 0);
  // Clique no link "Meu Catálogo", em degraus (BarraDeNavegacao.jsx): primeiro
  // limpa o filtro e os gêneros e guarda a ordem de "Todos" (preferência salva);
  // com isso limpo, o clique seguinte volta a ordem ao padrão; depois rola ao
  // topo. "Limpar tudo" do painel faz os dois primeiros passos de uma vez.
  const ordemSalvaAtiva = ordemEmTodos !== ORDEM_PADRAO;
  const limparSelecao = useCallback(() => {
    mudarFiltro('');
    setGenerosSalvos([]);
  }, [mudarFiltro, setGenerosSalvos]);
  const limparOrdem = useCallback(() => setOrdemEmTodos(ORDEM_PADRAO), [setOrdemEmTodos]);
  const limparFiltros = useCallback(() => {
    limparSelecao();
    limparOrdem();
  }, [limparSelecao, limparOrdem]);

  // Notificação "novos episódios" na ilha dinâmica (pedido do usuário,
  // 2026-09-27) — dispara quando uma releitura do catálogo (periódica, ver
  // acima) mostra uma franquia com MAIS episódios novos do que a leitura anterior,
  // ou seja, quando o zelador achou algo com a página aberta. A 1ª leitura só
  // fixa a referência (`episodiosNovosVistosRef`): dado que já estava ali não é
  // novidade. Franquia que aparece agora (id novo) também não notifica.
  const [notificacaoNovosEps, setNotificacaoNovosEps] = useState(false);
  const episodiosNovosVistosRef = useRef(null);
  useEffect(() => {
    if (carregando || animes == null) return;
    const atuais = new Map(franquias.map((franquia) => [franquia.id, franquia.episodios_novos]));
    const vistos = episodiosNovosVistosRef.current;
    episodiosNovosVistosRef.current = atuais;
    if (vistos === null) return;
    const cresceu = [...atuais].some(([id, novos]) => vistos.has(id) && novos > vistos.get(id));
    if (cresceu) setNotificacaoNovosEps(true);
  }, [franquias, carregando, animes]);

  // Escape hatch SÓ DEV pra testar a notificação sem precisar de um anime com
  // episódio novo de verdade — `import.meta.env.DEV` é substituído por `false` no build de
  // produção e o bloco inteiro é eliminado (dead code), não sobra no bundle
  // publicado. Uso no console do navegador, na rota /animes:
  //   __testarNotificacaoNovosEps()   -- força aparecer (some sozinha em 5s)
  useEffect(() => {
    if (!import.meta.env.DEV) return undefined;
    window.__testarNotificacaoNovosEps = () => setNotificacaoNovosEps(true);
    return () => {
      delete window.__testarNotificacaoNovosEps;
    };
  }, []);

  // Some sozinha 5s depois de aparecer (pedido do usuário) — continua
  // visível mesmo se a pessoa rolar a página nesse meio-tempo (o timer é
  // quem manda, não o scroll); só ao acabar o tempo é que
  // `capsulaExpandidaIlha` (BarraDeNavegacao.jsx) volta a decidir sozinha
  // se mostra o filtro (rolado) ou fecha (não rolado).
  useEffect(() => {
    if (!notificacaoNovosEps) return undefined;
    const tempo = setTimeout(() => setNotificacaoNovosEps(false), DURACAO_NOTIFICACAO_NOVOS_EPS_MS);
    return () => clearTimeout(tempo);
  }, [notificacaoNovosEps]);

  // Clicar na notificação (BarraDeNavegacao.jsx) já aplica o filtro "Novos
  // episódios" e dispensa a notificação na hora — não faz sentido as duas
  // coisas convivendo (a notificação anunciava exatamente o que o filtro
  // agora mostra).
  const aoClicarNotificacaoNovosEps = useCallback(() => {
    mudarFiltro('novos:sim');
    setNotificacaoNovosEps(false);
  }, [mudarFiltro]);

  // `statusCapturaIlha`/`capturaProntaIlha`/`erroCapturaIlha`: os três sinais
  // de captura da ilha, GLOBAL (qualquer anime do app) — hook compartilhado
  // com PaginaDoAnime.jsx (hooks/useStatusDeCapturaIlha.js), substitui os
  // toasts "concluído"/erro que existiam em components/Toasts.jsx (removido
  // por completo, 2026-09-27 — os dois migraram pra cá).

  // Busca -> filtro -> gêneros -> ordem, sempre client-side sobre as
  // franquias já agrupadas (sem chamada de API nova). Gêneros somam ao filtro
  // (precisa ter TODOS os marcados) e `filtroSelecionado`
  // decide o eixo pelo prefixo (ver `opcoesFiltro` acima): status bate se
  // QUALQUER temporada da franquia bate; assistido usa o agregado da
  // franquia inteira (`franquia.assistido`, inicio/franquia.js).
  const animesExibidos = useMemo(
    () =>
      ordenarFranquias(
        filtrarFranquias(franquias, {
          termo: termoBuscaNormalizado,
          filtro: filtroSelecionado,
          generos: generosAtivos,
        }),
        ordemEfetiva,
        filtroSelecionado,
      ),
    [franquias, termoBuscaNormalizado, filtroSelecionado, generosAtivos, ordemEfetiva],
  );

  // Filtros de ordem fixa ("Em lançamento": dia do próximo episódio; "Próximas
  // estreias": dia da estreia): cada card ganha a marca do dia acima (mesma
  // `SlotDoDiaDeEstreia` das "Próximas estreias" da Home); `primeiro`/
  // `ultimo` dizem a posição dele dentro do dia. Os grupos saem de
  // `animesExibidos`, já na ordem do próximo ep.
  const posicaoNoDia = useMemo(() => {
    if (!emOrdemFixa) return null;
    return new Map(
      agruparPorDiaDoFiltro(animesExibidos, filtroSelecionado).flatMap((grupo) =>
        grupo.itens.map((franquia, indice) => [
          franquia.id,
          { data: grupo.data, primeiro: indice === 0, ultimo: indice === grupo.itens.length - 1 },
        ]),
      ),
    );
  }, [emOrdemFixa, animesExibidos, filtroSelecionado]);

  // Painel de filtros da ilha (ilha/RegiaoDoPainelDeFiltros.jsx). Em "Vídeos
  // locais" não há ordem nem gênero (a grade é de arquivos, não do catálogo) e em
  // "Próximas estreias" e "Em lançamento" a ordem é fixa (temporada futura / próximo ep): a seção some.
  // O gênero mostra quantos animes sobrariam ao marcá-lo; contagem 0 apaga o botão.
  const contagemPorGenero = useMemo(
    () =>
      emVideosLocais
        ? null
        : contarPorGenero(
            franquias,
            { termo: termoBuscaNormalizado, filtro: filtroSelecionado, generos: generosAtivos },
            listaDeGeneros,
          ),
    [emVideosLocais, franquias, termoBuscaNormalizado, filtroSelecionado, generosAtivos, listaDeGeneros],
  );
  const opcoesGeneros = useMemo(
    () =>
      listaDeGeneros
        .map((genero) => ({
          valor: genero,
          rotulo: traduzirGenero(genero),
          contagem: contagemPorGenero?.get(genero) ?? 0,
        }))
        .sort((a, b) => a.rotulo.localeCompare(b.rotulo, 'pt-BR')),
    [listaDeGeneros, contagemPorGenero],
  );
  const resumoDoPainel = useMemo(() => {
    const rotuloDoFiltro = opcoesFiltro.find((opcao) => opcao.valor === filtroSelecionado)?.rotulo;
    const partes = [rotuloDoFiltro ?? 'Todos'];
    if (!emVideosLocais && !emOrdemFixa) {
      partes.push(OPCOES_DE_ORDEM.find((opcao) => opcao.valor === ordemEfetiva).curto);
    }
    if (!emVideosLocais && generosAtivos.size > 0) {
      partes.push(generosAtivos.size === 1 ? '1 gênero' : `${generosAtivos.size} gêneros`);
    }
    return partes.join(' · ');
  }, [opcoesFiltro, filtroSelecionado, emVideosLocais, emOrdemFixa, ordemEfetiva, generosAtivos]);
  const totalNoPainel = emVideosLocais ? VIDEOS_LOCAIS.length : animesExibidos.length;
  const rotuloDoTotal = emVideosLocais
    ? totalNoPainel === 1 ? 'vídeo' : 'vídeos'
    : totalNoPainel === 1 ? 'anime' : 'animes';

  // Modo de remoção (ilha dinâmica, BarraDeNavegacao.jsx; entra pelo "Remover" do
  // painel de filtros): seleção em lote do
  // catálogo e remoção com a confirmação dentro da própria ilha — substituiu o
  // botão de remover por card e o `DialogoDeConfirmacao`. Fases: 'inativo' →
  // 'selecionando' → 'confirmando' → 'removendo' → 'concluido' (sai sozinho do modo) ou 'erro' (fica até o usuário fechar). `selecionados` guarda
  // `anime.id` do REPRESENTANTE de cada franquia; só os que estão em
  // `animesExibidos` contam (um filtro que esconde um item selecionado o tira
  // da conta e do que é removido, sem surpresa).
  const [fase, setFase] = useState('inativo');
  const [selecionados, setSelecionados] = useState(() => new Set());
  const [resultado, setResultado] = useState(null);

  const itensSelecionados = useMemo(
    () => animesExibidos.filter((anime) => selecionados.has(anime.id)),
    [animesExibidos, selecionados],
  );
  const qtdSelecionados = itensSelecionados.length;

  const sairDoGerenciar = useCallback(() => {
    setFase('inativo');
    setSelecionados(new Set());
    setResultado(null);
  }, []);

  const alternarSelecao = useCallback(
    (anime) => {
      if (fase !== 'selecionando') return;
      setSelecionados((anterior) => {
        const novo = new Set(anterior);
        if (novo.has(anime.id)) novo.delete(anime.id);
        else novo.add(anime.id);
        return novo;
      });
    },
    [fase],
  );

  // Remove cada franquia selecionada INTEIRA: um DELETE por temporada
  // (`idsDaFranquia`), em série. Falha no meio (ex. temporada com captura em
  // andamento) para o laço e deixa as já removidas removidas — cada
  // `removerAnime` bem-sucedido já invalida 'animes' (invalidacao.js) e
  // recarrega esta grade sozinho, refletindo o estado real mesmo numa remoção
  // parcial, sem `recarregar()` manual. A seleção é limpa nos dois desfechos:
  // depois de uma remoção parcial os ids selecionados deixam de ser confiáveis.
  const confirmarRemocaoEmLote = useCallback(async () => {
    const alvos = itensSelecionados;
    if (alvos.length === 0) return;
    setFase('removendo');
    let removidos = 0;
    try {
      for (const anime of alvos) {
        for (const id of anime.idsDaFranquia ?? [anime.id]) {
          await removerAnime(id);
        }
        removidos += 1;
      }
      setResultado(removidos === 1 ? '1 anime removido' : `${removidos} animes removidos`);
      setFase('concluido');
    } catch (erroCapturado) {
      const parcial = removidos > 0 ? ` (${removidos} já removido${removidos > 1 ? 's' : ''})` : '';
      if (erroCapturado instanceof ErroDeApi && erroCapturado.detail?.motivo === 'job_em_execucao') {
        setResultado(`Há uma captura em andamento — aguarde terminar antes de remover${parcial}.`);
      } else {
        console.error('falha ao remover anime do catálogo', erroCapturado);
        setResultado(`Não foi possível remover — tente novamente${parcial}.`);
      }
      setFase('erro');
    } finally {
      setSelecionados(new Set());
    }
  }, [itensSelecionados]);

  // "Removido" some sozinho e sai do modo Gerenciar (ilha volta ao normal).
  useEffect(() => {
    if (fase !== 'concluido') return undefined;
    const timer = setTimeout(sairDoGerenciar, 3500);
    return () => clearTimeout(timer);
  }, [fase, sairDoGerenciar]);

  // Esc: volta da confirmação pra seleção; fora dela, sai do modo. Ignorado
  // enquanto remove (o laço não é cancelável).
  useEffect(() => {
    if (fase === 'inativo' || fase === 'removendo') return undefined;
    const aoTeclar = (evento) => {
      if (evento.key !== 'Escape') return;
      if (fase === 'confirmando') setFase('selecionando');
      else sairDoGerenciar();
    };
    window.addEventListener('keydown', aoTeclar);
    return () => window.removeEventListener('keydown', aoTeclar);
  }, [fase, sairDoGerenciar]);

  // Catálogo esvaziado (removeu tudo): não há mais o que gerenciar, e a ilha
  // deixa de receber `gerenciar` abaixo — sem isto o modo ficaria preso ligado.
  const catalogoVazio = !carregando && !erro && animes?.length === 0;
  useEffect(() => {
    if (catalogoVazio && fase !== 'inativo' && fase !== 'removendo') sairDoGerenciar();
  }, [catalogoVazio, fase, sairDoGerenciar]);

  const temporadasSelecionadas = itensSelecionados.reduce(
    (total, anime) => total + (anime.contagemDeTemporadas ?? 1),
    0,
  );
  const tituloCurto = (titulo) => (titulo.length > 28 ? `${titulo.slice(0, 27)}…` : titulo);
  const rotuloDoAlvo =
    qtdSelecionados === 1
      ? `"${tituloCurto(itensSelecionados[0].titulo)}"`
      : `${qtdSelecionados} animes`;
  const sufixoTemporadas = temporadasSelecionadas > qtdSelecionados ? ` (${temporadasSelecionadas} temporadas)` : '';
  const textoConfirmacao = `Remover ${rotuloDoAlvo}${sufixoTemporadas} e os episódios?`;

  return (
    <>
      {/* Ilha dinâmica (BarraDeNavegacao.jsx): ÚNICA via de filtro da página
          (o SeletorEmMenu da fileira "Meu Catálogo | Filtrar" foi removido,
          2026-09-27) e aberta já no scroll 0 (`ilhaAbertaNoTopo`). Só passa o
          painel de filtros e a remoção quando o catálogo está carregado e não vazio (mesma
          guarda do `<GradeDeCatalogo>` abaixo) — sem isso não há o que filtrar.
          Os sinais de captura vêm do WS global (hooks/useStatusDeCapturaIlha.js)
          e não dependem do catálogo. Ordem e espera das notificações:
          hooks/useFilaDaIlha.js. */}
      <BarraDeNavegacao
        transparente
        termoBusca={termoBusca}
        aoMudarBusca={setTermoBusca}
        opcoesFiltro={!carregando && !erro && animes?.length > 0 ? opcoesFiltro : undefined}
        ilhaAbertaNoTopo={!carregando && !erro && animes?.length > 0}
        filtroSelecionado={filtroSelecionado}
        aoMudarFiltro={mudarFiltro}
        notificacaoNovosEps={notificacaoNovosEps}
        aoClicarNotificacaoNovosEps={aoClicarNotificacaoNovosEps}
        statusCapturaIlha={statusCapturaIlha}
        aoClicarStatusCapturaIlha={aoClicarStatusCapturaIlha}
        capturaProntaIlha={capturaProntaIlha}
        aoClicarCapturaProntaIlha={aoClicarCapturaProntaIlha}
        erroCapturaIlha={erroCapturaIlha}
        aoClicarErroCapturaIlha={aoClicarErroCapturaIlha}
        painelDeFiltros={
          !carregando && !erro && animes?.length > 0
            ? {
                aberto: painelAberto,
                aoAbrir: () => setPainelAberto(true),
                aoFechar: () => setPainelAberto(false),
                resumo: resumoDoPainel,
                filtrosAtivos,
                aoLimpar: limparFiltros,
                selecaoAtiva,
                aoLimparSelecao: limparSelecao,
                ordemSalvaAtiva,
                aoLimparOrdem: limparOrdem,
                aoRemover: () => setFase('selecionando'),
                total: `${totalNoPainel} ${rotuloDoTotal}`,
                ordenacao:
                  emVideosLocais || emOrdemFixa
                    ? null
                    : { opcoes: OPCOES_DE_ORDEM, valor: ordemEfetiva, aoMudar: mudarOrdem },
                generos: emVideosLocais
                  ? null
                  : {
                      opcoes: opcoesGeneros,
                      selecionados: generosAtivos,
                      aoAlternar: alternarGenero,
                    },
              }
            : undefined
        }
        gerenciar={
          !carregando && !erro && animes?.length > 0
            ? {
                fase,
                qtdSelecionados,
                textoConfirmacao: qtdSelecionados > 0 ? textoConfirmacao : '',
                resultado,
                aoSelecionarTodos: () => setSelecionados(new Set(animesExibidos.map((anime) => anime.id))),
                aoPedirRemocao: () => setFase('confirmando'),
                aoCancelarRemocao: () => setFase('selecionando'),
                aoConfirmarRemocao: confirmarRemocaoEmLote,
                aoSair: sairDoGerenciar,
              }
            : undefined
        }
      />
      {/* `bg-black` (não mais `bg-[#17171b]` de paginas/Inicio.jsx): a Galeria
          não leva mais a drop shadow dos cards (`comSombra={false}` nas duas
          `GradeDeCatalogo` abaixo — ela só fazia sentido sobre aquele
          cinza-quase-preto; num preto sólido ela sumia de qualquer jeito), e
          sem sombra pra sustentar não há motivo pra não usar o preto sólido
          do resto do app (`html{background:#000}`, index.css). `min-h-screen`
          evita o fundo não cobrir a viewport quando o catálogo é curto. */}
      <main className="min-h-screen bg-black pb-10 pt-24">
        {/* Escondida quando o filtro está em "Vídeos locais" — esse valor
            TROCA a grade principal pela grade de vídeos locais (ver
            `VALOR_FILTRO_VIDEOS_LOCAIS` no topo do arquivo), mesmo padrão
            "substitui, não soma" dos outros itens do dropdown. O `<h1>`
            sr-only continua fora dessa guarda: o foco/anúncio de página
            (`useFocoAoMontar`) não deve depender de qual filtro está ativo. */}
        <h1 ref={focoTitulo} tabIndex={-1} id={idMeuCatalogo} className="sr-only">
          Meu Catálogo
        </h1>
        {filtroSelecionado !== VALOR_FILTRO_VIDEOS_LOCAIS && (
          <section aria-labelledby={idMeuCatalogo}>
            {/* Título "Meu Catálogo" e o filtro (SeletorEmMenu) removidos da
                tela (pedido do usuário, 2026-09-27): a ilha dinâmica da navbar
                (BarraDeNavegacao.jsx) já cobre os dois — rotula "Meu Catálogo"
                e traz o mesmo dropdown de filtro. Ciente do gap: no topo da
                página (scroll 0, antes de passar de `LIMIAR_ILHA_PX`) não há
                como filtrar — aceito, decisão explícita do usuário. `<h1>`
                agora mora fora desta `<section>` (ver comentário logo acima),
                já que a section some quando o filtro "Vídeos locais" está
                ativo mas o alvo de foco/anúncio de página não pode sumir
                junto. */}

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
                <EstadoComMascote alerta mensagem="Não foi possível carregar o catálogo.">
                  <BotaoDeEstado onClick={recarregar}>Tentar novamente</BotaoDeEstado>
                </EstadoComMascote>
              )}
              {!carregando && !erro && animes?.length === 0 && (
                <p className="mt-[22px] text-sm text-ink-muted">Nenhum anime cadastrado ainda.</p>
              )}

              {!carregando && !erro && animes?.length > 0 && animesExibidos.length === 0 && (
                <EstadoComMascote
                  mensagem={
                    termoBusca.trim()
                      ? `Nenhum anime encontrado para “${termoBusca.trim()}”.`
                      : 'Nenhum anime encontrado com os filtros selecionados.'
                  }
                />
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
              renderItem={(anime) => {
                const propsDeSelecao = {
                  modoSelecao: fase !== 'inativo',
                  selecionado: selecionados.has(anime.id),
                  aoAlternarSelecao: () => alternarSelecao(anime),
                };
                const card =
                  !anime.tem_episodios && anime.status_lancamento === 'nao_lancado' ? (
                    <CartaoDeEstreia
                      item={anime}
                      semTextoDeData={posicaoNoDia?.get(anime.id)?.data != null}
                      {...propsDeSelecao}
                    />
                  ) : (
                    <AnimeCard anime={anime} {...propsDeSelecao} />
                  );
                return posicaoNoDia ? (
                  <SlotDoDiaDeEstreia {...posicaoNoDia.get(anime.id)}>{card}</SlotDoDiaDeEstreia>
                ) : (
                  card
                );
              }}
            />
          </section>
        )}

        {/* Vídeos locais (videosLocais.js) — arquivos já em disco (public/
            videos-locais/), fora do catálogo/backend por completo: card
            leva direto pro player (`/assistir-local/:slug`), sem passar
            por materialização/captura. Era apêndice sempre visível embaixo
            da grade principal; virou modo de visualização exclusivo do
            filtro "Vídeos locais" (pedido do usuário, 2026-09-28) — guard
            de `filtroSelecionado` além do `length > 0` (sem vídeo local
            nenhum, a opção nem existe no dropdown pra selecionar). */}
        {VIDEOS_LOCAIS.length > 0 && filtroSelecionado === VALOR_FILTRO_VIDEOS_LOCAIS && (
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
      </main>
    </>
  );
}

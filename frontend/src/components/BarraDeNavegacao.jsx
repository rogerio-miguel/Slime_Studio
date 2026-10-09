import { useCallback, useEffect, useId, useRef, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { Home, LibraryBig, Tags } from 'lucide-react';
import { usePrefersReducedMotion } from '../inicio/usePrefersReducedMotion.js';
import { useFilaDaIlha } from '../hooks/useFilaDaIlha.js';
import { useLarguraMedida } from '../hooks/useLarguraMedida.js';
import { useCapsulaVisivel, useSinopseNaCapsula } from '../hooks/useSinopseNaCapsula.js';
import { ESTILO_FUNDO_INICIAL_TRANSPARENTE, useScrollDaNavbar } from '../hooks/useScrollDaNavbar.js';
import { useTrocaAntesDaIlha } from '../hooks/useTrocaAntesDaIlha.js';
import CampoDeBusca from './ilha/CampoDeBusca.jsx';
import ConteudoDaIlha from './ilha/ConteudoDaIlha.jsx';
import { ATRASO_APOS_TROCA_MS, DURACAO_ABRE_MS, estilosDaIlha } from './ilha/coreografiaDaIlha.js';
import RegiaoDaSinopse from './ilha/RegiaoDaSinopse.jsx';
import RegiaoDoPainelDeFiltros from './ilha/RegiaoDoPainelDeFiltros.jsx';
import LogoSlimeStudio from './LogoSlimeStudio';
import SeletorEmMenu from './SeletorEmMenu';
import SinopseNaIlha from './SinopseNaIlha.jsx';

// Navbar fixa (z-20, sempre acima do conteúdo) com a "ilha dinâmica": o link
// central vira uma cápsula que abre e hospeda, conforme a página, um filtro, uma
// navegação por seção, uma notificação, um modo (Gerenciar, "Trocar banner") ou
// a sinopse completa. As peças vivem em `components/ilha/` e `hooks/`.
//
// `transparente` (Início, Galeria, Página do Anime): sem fundo no topo, para o
// conteúdo full-bleed aparecer atrás; ao rolar ganha fundo escuro.
// Gêneros: desabilitado, mas visível (não existe gênero no modelo da navbar).
// Logo: decorativa; "Início" na lista é quem leva a `/`.
//
// Busca: `termoBusca`/`aoMudarBusca` controlados pelo pai; sem `aoMudarBusca` o
// campo nem renderiza (melhor omitir do que exibir um campo que não faz nada).

// ---------------------------------------------------------------------------
// O que a cápsula hospeda (props opcionais, cada página passa o seu)
// ---------------------------------------------------------------------------
// Filtro (`opcoesFiltro`/`filtroSelecionado`/`aoMudarFiltro`) — Galeria. Sem
// `painelDeFiltros` é um dropdown (`SeletorEmMenu`) dentro da cápsula; com ele,
// o filtro mora no painel (abaixo). `ilhaAbertaNoTopo` mantém a ilha aberta já
// no scroll 0 (por padrão ela só abre depois de ~96px de scroll).
//
// Seções (`opcoesSecoes`/`secaoSelecionada`/`aoMudarSecao`) — Início, scroll-spy.
// Mesmo contrato do filtro, mas SEPARADO porque muda qual link vira a cápsula
// (`capsulaNoInicio`): na Início é o "Início", nas demais é o "Meu Catálogo".
//
// Modos, que seguram a ilha aberta e tomam o lugar do seletor:
//   `gerenciar` — Galeria: seleção em lote para remover, ligada pelo "Remover"
//     do painel de filtros (contrato em ilha/ConteudoGerenciarIlha.jsx);
//   `modoDaIlha` — nó React, Página do Anime ("Trocar banner");
//   `sinopse` — Início e Página do Anime: `{ titulo, tituloSecundario, texto,
//     aoFechar }` enquanto aberta (`undefined` = página sem sinopse, `null` =
//     fechada). A ilha abre como no scroll (ou, já aberta, só troca o texto do
//     seletor para "Sinopse") e depois a cápsula cresce e vira o painel
//     (hooks/useSinopseNaCapsula.js; abaixo de `sm`, onde a
//     cápsula não existe, cai no <dialog> de SinopseNaIlha.jsx). A página mantém
//     o objeto até `aoFechar`, que só dispara depois da animação de volta.
//
// Notificações (`notificacaoNovosEps`, `verificandoNovosEps`, `statusCapturaIlha`,
// `capturaProntaIlha`, `erroCapturaIlha` + os `aoClicar*`): um só slot de texto,
// com fila e prioridade em hooks/useFilaDaIlha.js. Enquanto um menu da ilha está
// ativo (dropdown, modo, sinopse) elas esperam e entram depois, uma por vez.
//
// Painel de filtros (`painelDeFiltros`) — Galeria: o gatilho "Filtros" ocupa o
// lugar do dropdown e a cápsula cresce para baixo e vira o painel, como na sinopse
// (mesma mecânica, ilha/RegiaoDoPainelDeFiltros.jsx). Início e Gêneros somem
// enquanto está aberto e clicar fora só fecha (a cortina engole o clique).
// Contrato: ver ilha/RegiaoDoPainelDeFiltros.jsx (`aberto`, `aoAbrir` e `aoFechar`
// — que só dispara depois da animação de volta — e `resumo`, o texto do gatilho,
// são lidos aqui). O filtro do painel é o das props `opcoesFiltro`/
// `filtroSelecionado`/`aoMudarFiltro`.
//
// A cápsula mora no <ul> central, que some abaixo de `sm`: no celular não há
// ilha (o app é desktop-first).
// Sólido (a sinopse deixa a arte da página aparecer por baixo; os filtros não).
const FUNDO_DO_PAINEL_DE_FILTROS = '#0d0d0d';
const LARGURA_DO_PAINEL_DE_FILTROS_PX = 584;
const ROTULO_DO_PAINEL_ABERTO = 'Ordem e filtros';
// Cápsula fechada = link + `ml-2` do conteúdo + conteúdo + `px-3` dos dois lados.
const FOLGA_DA_CAPSULA_PX = 8 + 24;
// Topo da ilha na navbar (`h-20`, ilha de `h-10`): o painel — de filtros ou da
// sinopse — nasce nesse topo, alinhado com o logo e a busca, e cresce pra baixo.
const TOPO_DA_ILHA_PX = 20;

export default function BarraDeNavegacao({
  transparente = false,
  termoBusca,
  aoMudarBusca,
  aoSubmeterBusca,
  opcoesFiltro,
  filtroSelecionado,
  aoMudarFiltro,
  ilhaAbertaNoTopo = false,
  opcoesSecoes,
  secaoSelecionada,
  aoMudarSecao,
  gerenciar,
  painelDeFiltros,
  modoDaIlha = null,
  sinopse,
  notificacaoNovosEps = false,
  aoClicarNotificacaoNovosEps,
  verificandoNovosEps = false,
  statusCapturaIlha = null,
  aoClicarStatusCapturaIlha,
  capturaProntaIlha = null,
  aoClicarCapturaProntaIlha,
  erroCapturaIlha = null,
  aoClicarErroCapturaIlha,
  rotuloAcessivelIlha = 'Filtrar catálogo',
  rotuloAcessivelSecoes = 'Navegar por seção',
}) {
  const idFiltroIlha = useId();
  const { pathname } = useLocation();
  const movimentoReduzido = usePrefersReducedMotion();
  const emInicio = pathname === '/';
  const emAnimes = pathname.startsWith('/animes');
  const { navRef, logoColapsada, ilhaAtiva } = useScrollDaNavbar(transparente);

  // Abaixo de `sm` o <ul> some e vale o <dialog> da sinopse; o painel de filtros
  // não tem fallback (o app é desktop-first).
  const ilhaVisivel = useCapsulaVisivel();

  // --- O que a ilha hospeda nesta página ------------------------------------
  const temFiltroNaIlha = Boolean(aoMudarFiltro && opcoesFiltro?.length);
  const temSecoesNaIlha = Boolean(aoMudarSecao && opcoesSecoes?.length);
  const gerenciando = Boolean(gerenciar) && gerenciar.fase !== 'inativo';
  const temModoDaIlha = Boolean(modoDaIlha);
  const temSinopse = Boolean(sinopse);
  const temPainelDeFiltros = Boolean(painelDeFiltros?.aberto) && ilhaVisivel;
  // O painel de filtros NÃO é um modo da ilha: o cabeçalho (link + gatilho) segue
  // visível. Só segura a ilha aberta e as notificações (`menuAtivo`).
  const modoNaIlha = gerenciando || temModoDaIlha;
  // Gate de MONTAGEM do conteúdo da ilha: estável de propósito (presença dos
  // callbacks, não o valor de cada sinal) — o wrapper tem que nascer fechado
  // para ter transição de largura. Pelo mesmo motivo, `sinopse !== undefined`.
  const temConteudoNaIlha = Boolean(
    sinopse !== undefined ||
      gerenciar ||
      painelDeFiltros ||
      aoMudarFiltro ||
      aoMudarSecao ||
      aoClicarNotificacaoNovosEps ||
      aoClicarCapturaProntaIlha ||
      aoClicarStatusCapturaIlha ||
      aoClicarErroCapturaIlha,
  );
  // A cápsula (fundo, padding, seletor) envolve "Início" quando a página navega
  // por seção, e "Meu Catálogo" nas demais. O outro link renderiza puro.
  const capsulaNoInicio = temSecoesNaIlha;
  const opcoesDoSeletor = temSecoesNaIlha ? opcoesSecoes : opcoesFiltro;
  const valorDoSeletor = temSecoesNaIlha ? secaoSelecionada : filtroSelecionado;
  const aoMudarDoSeletor = temSecoesNaIlha ? aoMudarSecao : aoMudarFiltro;
  const rotuloDoSeletor = temSecoesNaIlha ? rotuloAcessivelSecoes : rotuloAcessivelIlha;

  // --- Nós e medidas da cápsula ---------------------------------------------
  // Com `modoDaIlha`, a roda sobre a cápsula não rola a página (a lista de
  // opções dela rola sozinha, ver SeletorDeBanner.jsx). Listener nativo porque
  // o `onWheel` do React é passivo e não cancela a rolagem.
  const travarRodaNaIlhaRef = useCallback(
    (no) => {
      if (!no || !temModoDaIlha) return undefined;
      const travar = (evento) => evento.preventDefault();
      no.addEventListener('wheel', travar, { passive: false });
      return () => no.removeEventListener('wheel', travar);
    },
    [temModoDaIlha],
  );
  const capsulaRef = useRef(null);
  // Ref por callback: a cápsula remonta ao trocar de posição (`linksTrocados`).
  const refDaCapsula = useCallback(
    (no) => {
      capsulaRef.current = no;
      const desfazerTrava = travarRodaNaIlhaRef(no);
      return () => {
        capsulaRef.current = null;
        desfazerTrava?.();
      };
    },
    [travarRodaNaIlhaRef],
  );
  const [larguraConteudoIlha, medidorConteudoIlhaRef] = useLarguraMedida();
  const [larguraDoLink, medidorDoLinkRef] = useLarguraMedida();

  // --- Quando a ilha abre ---------------------------------------------------
  const ilhaPedidaPorMenu =
    modoNaIlha ||
    temPainelDeFiltros ||
    ((temFiltroNaIlha || temSecoesNaIlha) && (ilhaAtiva || ilhaAbertaNoTopo));

  // Menu ativo = a ilha está ocupada com uma escolha do usuário: as
  // notificações esperam (hooks/useFilaDaIlha.js).
  const [dropdownAberto, setDropdownAberto] = useState(false);
  const menuAtivo = modoNaIlha || temSinopse || temPainelDeFiltros || dropdownAberto;
  const mensagemIlha = useFilaDaIlha({
    retida: menuAtivo,
    sinais: {
      erro: { texto: erroCapturaIlha, aoClicar: aoClicarErroCapturaIlha },
      pronto: { texto: capturaProntaIlha, aoClicar: aoClicarCapturaProntaIlha },
      novosEps: {
        texto: notificacaoNovosEps ? 'Novos episódios disponíveis' : null,
        aoClicar: aoClicarNotificacaoNovosEps,
      },
      status: { texto: statusCapturaIlha, aoClicar: aoClicarStatusCapturaIlha },
      verificando: { texto: verificandoNovosEps ? 'Verificando novos episódios…' : null },
    },
  });
  // A sinopse abre a ilha pelo mesmo caminho do scroll e das mensagens: só o texto
  // do seletor vira "Sinopse" (a cápsula cresce em painel depois, `atrasoAbrirMs`).
  const mensagemExibida = temSinopse ? { texto: 'Sinopse' } : mensagemIlha;
  const ilhaPedida = ilhaPedidaPorMenu || Boolean(mensagemExibida);

  const exigeTrocaAntes = emInicio && !logoColapsada;
  const { simulandoScroll, liberada } = useTrocaAntesDaIlha(exigeTrocaAntes, ilhaPedida);
  const capsulaExpandidaIlha = ilhaPedida && (!exigeTrocaAntes || liberada);
  const estilos = estilosDaIlha(capsulaExpandidaIlha);

  // Largura de destino da cápsula ao fechar o painel: tem que ser UM valor estável.
  // A medida viva (`larguraConteudoIlha`) anima junto do rótulo do gatilho, e um
  // destino que muda a cada quadro reinicia a transição de largura da cápsula (ela
  // fica parada e depois salta). Então parte da largura com o painel aberto — o
  // gatilho já mostra o rótulo aberto — trocando só o rótulo pelo de repouso, ambos
  // medidos na hora (SeletorEmMenu.jsx). Travado ao começar a recolher.
  const [rotulosDoGatilho, setRotulosDoGatilho] = useState(null);
  const [larguraAoFechar, setLarguraAoFechar] = useState(null);

  // "Remover" fecha o painel e SÓ DEPOIS liga o modo de remoção: ligado antes, a
  // barra de seleção crescia escondida dentro da cápsula travada e, ao voltar ao
  // fluxo, ela pulava para a largura da barra sem transição.
  const removerAoFecharRef = useRef(false);
  const aoTerminarDeFecharPainel = () => {
    painelDeFiltros.aoFechar();
    if (!removerAoFecharRef.current) return;
    removerAoFecharRef.current = false;
    painelDeFiltros.aoRemover();
  };

  const painel = useSinopseNaCapsula({
    // A cápsula só vira painel depois de terminar de abrir.
    ativa: (temSinopse || temPainelDeFiltros) && ilhaVisivel,
    // O painel de filtros nasce de um clique no gatilho, com a cápsula já aberta:
    // não há abertura pra esperar.
    // Sinopse: espera a troca dos links (Início) e a ilha terminar de abrir
    // mostrando "Sinopse".
    atrasoAbrirMs: temSinopse
      ? (exigeTrocaAntes ? ATRASO_APOS_TROCA_MS : 0) + DURACAO_ABRE_MS + 60
      : 0,
    topoFinalPx: TOPO_DA_ILHA_PX,
    capsulaRef,
    aoFechar: temPainelDeFiltros ? aoTerminarDeFecharPainel : sinopse?.aoFechar,
    movimentoReduzido,
    interativo: temPainelDeFiltros,
    manterPosicao: temPainelDeFiltros,
    travarRolagem: !temPainelDeFiltros,
    crescimentoDoCabecalhoPx: rotulosDoGatilho ? rotulosDoGatilho.aberto - rotulosDoGatilho.repouso : 0,
    fundoExpandido: temPainelDeFiltros ? FUNDO_DO_PAINEL_DE_FILTROS : undefined,
    larguraMaximaPx: temPainelDeFiltros ? LARGURA_DO_PAINEL_DE_FILTROS_PX : undefined,
    larguraAoFechar: temPainelDeFiltros ? larguraAoFechar : undefined,
  });
  const podeAtualizarLarguraAoFechar = temPainelDeFiltros && !painel.recolhendo;
  useEffect(() => {
    if (!podeAtualizarLarguraAoFechar || !rotulosDoGatilho) return;
    setLarguraAoFechar(
      larguraDoLink +
        larguraConteudoIlha +
        FOLGA_DA_CAPSULA_PX +
        rotulosDoGatilho.repouso -
        rotulosDoGatilho.aberto,
    );
  }, [podeAtualizarLarguraAoFechar, rotulosDoGatilho, larguraDoLink, larguraConteudoIlha]);
  // O gatilho diz "Ordem e filtros" (e a seta vira) enquanto o painel está
  // aberto; ao recolher, já volta ao resumo, pra cápsula animar até a largura
  // que vai ter de fato.
  const painelDeFiltrosEmUso = temPainelDeFiltros && painel.ancorada && !painel.recolhendo;

  // --- Links ----------------------------------------------------------------
  // Clique no link da cápsula na própria rota `/animes`, em degraus: limpa o
  // filtro (e os gêneros, com o painel de filtros); sem isso, volta a ordem salva
  // ao padrão; sem nada a limpar, rola ao topo ("clicar no item de nav já
  // ativo"). Fora dela é só a navegação do <Link>.
  const rolarAoTopo = () =>
    window.scrollTo({ top: 0, behavior: movimentoReduzido ? 'auto' : 'smooth' });
  const aoClicarLinkDaCapsula = () => {
    if (!emAnimes) return;
    if (painelDeFiltros) {
      if (painelDeFiltros.selecaoAtiva) painelDeFiltros.aoLimparSelecao();
      else if (painelDeFiltros.ordemSalvaAtiva) painelDeFiltros.aoLimparOrdem();
      else rolarAoTopo();
      return;
    }
    if (!opcoesFiltro?.length) return;
    const valorPadrao = opcoesFiltro[0].valor;
    if (filtroSelecionado === valorPadrao) {
      rolarAoTopo();
    } else {
      aoMudarFiltro?.(valorPadrao);
    }
  };
  // Já em `/`, o <Link to="/"> sozinho não faz nada visível; rola ao topo.
  const aoClicarLinkInicio = () => {
    if (!emInicio) return;
    rolarAoTopo();
  };
  // Início e Meu Catálogo trocam de POSIÇÃO ao rolar na Início (o Início assume
  // o slot do meio, onde a cápsula abre). Troca por ORDEM DE RENDER (não CSS
  // `order`) para a ordem de tab seguir a visual. Também troca com a ilha pedida
  // sem scroll (sinopse, captura...), simulando o scroll só nos links.
  const linksTrocados = emInicio && (logoColapsada || simulandoScroll);

  // Dropdown do filtro/seções — ou, na Galeria, o gatilho do painel de filtros.
  const gatilhoDoPainel = painelDeFiltros && {
    rotulo: painelDeFiltrosEmUso ? ROTULO_DO_PAINEL_ABERTO : painelDeFiltros.resumo,
    aberto: painelDeFiltrosEmUso,
    aoClicar: temPainelDeFiltros ? painel.fechar : painelDeFiltros.aoAbrir,
    rotuloAberto: ROTULO_DO_PAINEL_ABERTO,
    rotuloRepouso: painelDeFiltros.resumo,
    aoMedirRotulos: setRotulosDoGatilho,
  };
  const seletor = (
    <SeletorEmMenu
      id={idFiltroIlha}
      opcoes={opcoesDoSeletor}
      valor={valorDoSeletor}
      aoMudar={aoMudarDoSeletor}
      rotuloAcessivel={rotuloDoSeletor}
      mensagemSobreposta={mensagemExibida?.texto}
      aoClicarMensagem={mensagemExibida?.aoClicar}
      tomMensagem={mensagemExibida?.tom}
      ilhaAberta={capsulaExpandidaIlha}
      aoMudarAberto={setDropdownAberto}
      comoGatilho={gatilhoDoPainel}
      // O menu ocupa a largura da CÁPSULA inteira (do link ao chevron).
      ocuparLarguraDoPai
    />
  );

  // Na sinopse o cabeçalho (link + rótulo) colapsa a 0 e o texto toma o lugar; nos
  // filtros ele fica, no topo do painel.
  const recolheCabecalho = painel.expandida && !temPainelDeFiltros;
  const renderLinkComCapsula = ({ chave, to, ativo, Icone, rotulo, onClick }) => (
    <li key={chave} style={painel.estiloItem} className="pointer-events-auto">
      <div
        ref={refDaCapsula}
        style={{ ...estilos.forma, ...painel.estiloCapsula }}
        // `relative`: âncora do menu do dropdown (`ocuparLarguraDoPai`).
        className={`relative flex flex-col rounded-full transition-[background-color,padding] motion-reduce:transition-none ${
          capsulaExpandidaIlha || painel.ancorada ? 'bg-[#0d0d0d] px-3 py-1' : 'px-0 py-0'
        }`}
      >
        {/* Cabeçalho (link + conteúdo da ilha) numa grade de uma linha só, para
            colapsar a altura a 0 quando a cápsula vira o painel da sinopse. Em
            repouso é uma passagem direta. `overflow-hidden` só com a sinopse
            ancorada: em repouso o menu (`absolute`, ancorado na cápsula) não
            pode ser cortado. */}
        <div
          className="grid"
          style={{
            gridTemplateRows: recolheCabecalho ? '0fr' : '1fr',
            opacity: recolheCabecalho ? 0 : 1,
            transition: `${painel.estiloGrade.transition}, opacity 200ms ease`,
          }}
          inert={(painel.ancorada && !temPainelDeFiltros) || undefined}
        >
          <div
            style={painel.estiloCabecalho}
            className={`flex min-h-0 items-center ${painel.ancorada ? 'overflow-hidden' : ''}`}
          >
            <Link
              ref={medidorDoLinkRef}
              to={to}
              aria-current={ativo ? 'page' : undefined}
              onClick={onClick}
              className={`flex items-center gap-2 whitespace-nowrap outline-none transition-colors font-bold ${
                ativo ? 'text-neon' : 'hover:text-white/80 focus-visible:text-white'
              }`}
            >
              <Icone aria-hidden="true" strokeWidth={2.5} className="h-5 w-5" />
              {rotulo}
            </Link>
            {temConteudoNaIlha && (
              <ConteudoDaIlha
                aberta={capsulaExpandidaIlha}
                estilo={estilos.conteudo}
                largura={larguraConteudoIlha}
                medidorRef={medidorConteudoIlhaRef}
                seletor={seletor}
                gerenciar={gerenciar}
                gerenciando={gerenciando}
                modoDaIlha={modoDaIlha}
                modoNaIlha={modoNaIlha}
                larguraSegueOConteudo={painel.ancorada && temPainelDeFiltros}
              />
            )}
          </div>
        </div>
        {painel.ancorada &&
          (temPainelDeFiltros ? (
            <RegiaoDoPainelDeFiltros
              painel={painel}
              painelDeFiltros={{
                ...painelDeFiltros,
                // O painel cobre os cards: pra selecionar o que remover ele tem
                // que sair da frente.
                aoRemover: () => {
                  removerAoFecharRef.current = true;
                  painel.fechar();
                },
              }}
              filtro={{ opcoes: opcoesFiltro, valor: filtroSelecionado, aoMudar: aoMudarFiltro }}
            />
          ) : (
            <RegiaoDaSinopse painel={painel} sinopse={sinopse} />
          ))}
      </div>
    </li>
  );

  // O link que NÃO é a cápsula nesta página: só ícone + texto, idêntico ao
  // estado fechado da cápsula.
  const renderLinkPuro = ({ chave, to, ativo, Icone, rotulo, onClick }) => (
    <li key={chave} inert={painel.ancorada || undefined}>
      <Link
        to={to}
        aria-current={ativo ? 'page' : undefined}
        onClick={onClick}
        className={`flex items-center gap-2 outline-none transition-colors font-bold ${
          ativo ? 'text-neon' : 'hover:text-white/80 focus-visible:text-white'
        }`}
      >
        <Icone aria-hidden="true" strokeWidth={2.5} className="h-5 w-5" />
        {rotulo}
      </Link>
    </li>
  );

  // Destaque (`text-neon`) por ROTA, independente de qual link é a cápsula e de
  // qual slot cada um ocupa.
  const dadosInicio = {
    chave: 'inicio',
    to: '/',
    ativo: emInicio,
    Icone: Home,
    rotulo: 'Início',
    onClick: aoClicarLinkInicio,
  };
  const dadosCatalogo = {
    chave: 'catalogo',
    to: '/animes',
    ativo: emAnimes,
    Icone: LibraryBig,
    rotulo: 'Meu Catálogo',
    onClick: aoClicarLinkDaCapsula,
  };
  const linkInicio = capsulaNoInicio ? renderLinkComCapsula(dadosInicio) : renderLinkPuro(dadosInicio);
  const linkCatalogo = capsulaNoInicio
    ? renderLinkPuro({ ...dadosCatalogo, onClick: undefined })
    : renderLinkComCapsula(dadosCatalogo);

  return (
    <>
      <nav
        ref={navRef}
        aria-label="Principal"
        style={transparente ? ESTILO_FUNDO_INICIAL_TRANSPARENTE : undefined}
        className={`fixed inset-x-0 top-0 z-20 flex h-20 items-center justify-between gap-6 px-6 md:px-10 ${
          transparente ? '' : 'bg-surface/40 backdrop-blur-sm'
        }`}
      >
        {/* Cortina do painel (sinopse ou filtros): clicar fora só fecha, o clique
            não chega aos cards. */}
        {painel.ancorada && (
          <div aria-hidden="true" onClick={painel.fechar} className="sinopse-ilha-cortina" />
        )}
        <LogoSlimeStudio colapsada={logoColapsada} />
        {/* `absolute left-1/2 -translate-x-1/2`: centraliza em relação à navbar
            inteira, não ao espaço entre logo e busca (que varia por página:
            PaginaDoAnime não tem busca). */}
        <ul
          className={`absolute left-1/2 hidden -translate-x-1/2 items-center gap-8 text-lg text-ink-muted sm:flex sm:text-lg ${
            // Com o painel ancorado o <ul> sobe acima da cortina e os links
            // vizinhos somem (senão vazam pelos 6% de transparência do painel) e
            // deixam de receber clique: só a cápsula (`pointer-events-auto`) recebe.
            painel.ancorada ? 'pointer-events-none z-10 [&>li]:opacity-0' : ''
          } [&>li]:transition-opacity`}
        >
          {!linksTrocados && linkInicio}
          {linkCatalogo}
          {linksTrocados && linkInicio}
          <li key="generos" inert={painel.ancorada || undefined}>
            <button
              type="button"
              disabled
              aria-disabled="true"
              title="Em breve"
              className="flex items-center gap-2 cursor-not-allowed opacity-50 font-bold"
            >
              <Tags aria-hidden="true" strokeWidth={2.5} className="h-5 w-5" />
              Gêneros
            </button>
          </li>
        </ul>
        {aoMudarBusca && (
          <CampoDeBusca termo={termoBusca} aoMudar={aoMudarBusca} aoSubmeter={aoSubmeterBusca} />
        )}
      </nav>
      {/* Fallback abaixo de `sm`, onde o <ul> da cápsula some. Fora do <nav> para
          não herdar o fundo. */}
      {sinopse !== undefined && !ilhaVisivel && (
        <SinopseNaIlha
          aberta={temSinopse}
          titulo={sinopse?.titulo ?? ''}
          tituloSecundario={sinopse?.tituloSecundario}
          sinopse={sinopse?.texto}
          aoFechar={sinopse?.aoFechar}
        />
      )}
    </>
  );
}

import { useCallback, useEffect, useId, useRef, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { Home, LibraryBig, Search, Tags, X } from 'lucide-react';
import { usePrefersReducedMotion } from '../inicio/usePrefersReducedMotion.js';
import LogoSlimeStudio from './LogoSlimeStudio';
import SeletorEmMenu from './SeletorEmMenu';
import SinopseNaIlha, { ConteudoDaSinopse } from './SinopseNaIlha.jsx';
import { useCapsulaVisivel, useSinopseNaCapsula } from '../hooks/useSinopseNaCapsula.js';

// Navbar fixa (z-20, sempre acima do conteúdo).
//
// Gêneros: decisão do usuário sobre dado faltante — não existe gênero no
// modelo hoje, então fica visível mas desabilitado (`disabled` +
// `aria-disabled` + `title`), nunca escondido. Favoritos saiu da navbar:
// agora é filtro dentro de paginas/Galeria.jsx.
//
// Logo: puramente decorativa (sem `<Link>`/navegação) — "Início" na lista
// de links é quem leva pra `/`.
//
// Busca: `termoBusca`/`aoMudarBusca` controlados pelo pai (`paginas/Inicio.jsx`
// e `paginas/Galeria.jsx`, cada um filtrando sua própria lista). Filtro local
// ao vivo, sem submit: digitar já dispara `aoMudarBusca` via `onChange`.
// Enter (`onSubmit`, `preventDefault` evita reload de página) dispara
// `aoSubmeterBusca`, opcional — hoje aciona a busca em fontes externas.
// `aoMudarBusca` inteiro é opcional: `paginas/PaginaDoAnime.jsx` não tem uma
// lista pra filtrar, então o formulário de busca nem renderiza ali — melhor
// omitir a caixa do que exibir um campo que não faz nada ao digitar.
//
// `transparente`: usado por Início, Galeria e Página do Anime. Sem fundo
// enquanto a página está no topo (o conteúdo full-bleed do topo — faixa
// panorâmica, carrossel — aparece atrás da navbar); ao rolar, ganha um fundo
// mais escuro que o `<main>` (#17171b) pra manter contraste com o conteúdo
// que passa por baixo.
//
// Busca: campo pill sempre aberto (`w-96`, borda neon), sem animação de
// expandir/colapsar — a versão colapsável (botão-ícone circular que virava
// pill no foco/texto, escolhida num canvas de 5 variantes em 2026-09-21)
// foi removida a pedido do usuário (2026-09-23). Borda: `border-neon` em
// repouso, `hover:border-white/80` (mesmo tom usado no hover dos links da
// navbar) e `focus-visible:border-white` — precisa das DUAS variantes
// porque a borda neon fica fixa agora, então sem elas nem hover nem foco
// dariam feedback visual (nunca cortar isso, mesmo campo sempre aberto).
// Botão de limpar (`X`) só com texto; `onMouseDown` com
// `preventDefault` evita que o clique nele dispare `blur` do input antes do
// `onClick`. Cancelador nativo do `type="search"` (Chrome/Edge) escondido
// via `[&::-webkit-search-cancel-button]:hidden` — duplicaria o nosso `X`.
//
// Dropdown "ilha dinâmica" (`opcoesFiltro`/`filtroSelecionado`/`aoMudarFiltro`,
// opcionais, mesmo padrão de `aoMudarBusca`): só `paginas/Galeria.jsx` passa
// os três, pro filtro de catálogo. Sem esses props (`paginas/Inicio.jsx` e
// `paginas/PaginaDoAnime.jsx`), o link da cápsula renderiza sem dropdown,
// puro. Reaproveita `SeletorEmMenu` (já testado, já acessível — menu com
// teclado/clique-fora/Esc) dentro da cápsula em vez de listar os chips
// soltos (versão testada e revertida a pedido do usuário, 2026-09-26: com
// `opcoesFiltro` dinâmico — status varia por catálogo — os chips sempre
// expandidos passavam de 500px e precisavam de scroll horizontal próprio; o
// dropdown resolve isso sem esse artifício). Gatilho é só SCROLL (ver
// `capsulaExpandidaIlha` abaixo) — sem clique pra ativar. ÚNICA via de
// filtro da Galeria desde 2026-09-27: o seletor que ficava solto na página
// foi removido (redundante com este) — com isso, no topo da página
// (scroll 0) não há nenhum jeito de filtrar até rolar além do limiar de
// abertura da cápsula, gap aceito pelo usuário.
//
// Navegação por seção na Início — histórico, mesmo dia (2026-09-28), até
// chegar na versão atual: Tentativa 1 — a cápsula trocava de LINK (Início ↔
// Meu Catálogo) ao cruzar um limiar de scroll: confuso, revertido.
// Tentativa 2 — o SLOT central passava a ser ocupado por "Início" quando
// `emInicio` (troca estática por rota, não por scroll): resolvia a
// centralização mas quebrava a convenção de "Início" sempre na ponta
// esquerda — revertido. Uma quarta ideia (barra sticky separada abaixo da
// navbar) foi proposta e recusada antes de qualquer código. A versão que
// ficou combina duas peças independentes, pedidas em dois passos pelo
// usuário: (a) `linksTrocados` — Início e Meu Catálogo trocam de POSIÇÃO
// (não de link/texto) ao rolar, Início assume o slot do meio — e (b) a
// "terceira ideia" do histórico original (cápsula própria pra "Início"),
// implementada como generalização da mesma cápsula que já existia só em
// "Meu Catálogo": `capsulaNoInicio`/`temSecoesNaIlha` abaixo decidem qual
// dos dois links leva fundo+dropdown, com o dropdown mostrando SEÇÕES da
// Início (scroll-spy, `paginas/Inicio.jsx`) em vez do filtro de catálogo.
//
// `notificacaoNovosEps`/`aoClicarNotificacaoNovosEps`/`verificandoNovosEps`
// (opcionais — só Galeria.jsx passa) e `statusCapturaIlha`/`capturaProntaIlha`/
// `erroCapturaIlha` (opcionais — Inicio.jsx, Galeria.jsx e PaginaDoAnime.jsx
// passam os três, mesmo hook global `hooks/useStatusDeCapturaIlha.js`):
// gatilhos da cápsula independentes do scroll — ver comentário de
// `capsulaExpandidaIlha` abaixo pra coreografia e prioridade entre os cinco.

// Gerenciar (`gerenciar`, opcional — só `paginas/Galeria.jsx` passa): botão
// sem fundo dentro da ilha, depois do dropdown de filtro e de um divisor (só
// aparece com a ilha aberta, ou seja, rolado — mesma regra do filtro), que
// liga o modo de seleção do catálogo. Com o modo ligado a ilha
// abre e troca o conteúdo do dropdown por uma barra de gerenciamento
// (`ConteudoGerenciarIlha`): contagem, selecionar todos, remover em lote com a
// confirmação dentro da própria ilha, e o resultado/erro da remoção. Enquanto
// `gerenciar.fase !== 'inativo'` ele tem prioridade sobre qualquer mensagem da
// ilha (captura/novos episódios): o dropdown e as mensagens não são
// renderizados; os sinais contínuos voltam sozinhos ao sair, mas um
// transitório (pronto/erro de captura) pode expirar escondido nesse intervalo
// — perda aceita, mesmo trade-off da fila de um slot só descrita em
// `mensagemIlha`. A ilha mora no `<ul>` central, que some abaixo de `sm`: em
// tela de celular o modo não tem controles (o app é desktop-first).
// Contrato de `gerenciar`: { fase: 'inativo' | 'selecionando' | 'confirmando'
// | 'removendo' | 'concluido' | 'erro', qtdSelecionados, textoConfirmacao,
// resultado, aoAlternar, aoSelecionarTodos, aoPedirRemocao,
// aoCancelarRemocao, aoConfirmarRemocao, aoSair }.
// Mesmo padrão tipográfico do gatilho do `SeletorEmMenu` (18px semibold,
// `ink-muted` → branco no hover, sem fundo), separado dos vizinhos pelo mesmo
// divisor `h-4 w-px bg-white/15` da cápsula.
export function DivisorDaIlha() {
  return <span aria-hidden="true" className="h-4 w-px shrink-0 bg-white/15" />;
}

export function BotaoDaIlha({ children, perigo = false, ...props }) {
  return (
    <button
      type="button"
      className={`inline-flex h-8 shrink-0 cursor-pointer items-center whitespace-nowrap text-[18px] font-semibold outline-none transition-colors disabled:cursor-not-allowed disabled:opacity-40 motion-reduce:transition-none ${
        perigo
          ? 'text-red-400 hover:text-red-300 focus-visible:text-red-300'
          : 'text-ink-muted hover:text-white focus-visible:text-white'
      }`}
      {...props}
    >
      {children}
    </button>
  );
}

function ConteudoGerenciarIlha({ gerenciar }) {
  const { fase, qtdSelecionados, textoConfirmacao, resultado } = gerenciar;
  const plural = qtdSelecionados === 1 ? 'selecionado' : 'selecionados';
  const classeTexto = 'whitespace-nowrap text-[18px] font-semibold';
  if (fase === 'confirmando') {
    return (
      <>
        <span role="alert" className={`${classeTexto} text-white`}>
          {textoConfirmacao}
        </span>
        <DivisorDaIlha />
        <BotaoDaIlha perigo onClick={gerenciar.aoConfirmarRemocao}>
          Remover
        </BotaoDaIlha>
        <DivisorDaIlha />
        <BotaoDaIlha onClick={gerenciar.aoCancelarRemocao}>Cancelar</BotaoDaIlha>
      </>
    );
  }
  if (fase === 'removendo') {
    return (
      <span role="status" className={`${classeTexto} text-ink-muted`}>
        Removendo…
      </span>
    );
  }
  if (fase === 'concluido' || fase === 'erro') {
    return (
      <>
        <span
          role={fase === 'erro' ? 'alert' : 'status'}
          className={`${classeTexto} ${fase === 'erro' ? 'text-amber-300' : 'text-white'}`}
        >
          {resultado}
        </span>
        {fase === 'erro' && (
          <>
            <DivisorDaIlha />
            <BotaoDaIlha onClick={gerenciar.aoSair}>Fechar</BotaoDaIlha>
          </>
        )}
      </>
    );
  }
  return (
    <>
      <span role="status" className={`${classeTexto} text-white`}>
        {qtdSelecionados} <span className="text-ink-muted">{plural}</span>
      </span>
      <DivisorDaIlha />
      <BotaoDaIlha onClick={gerenciar.aoSelecionarTodos}>Selecionar todos</BotaoDaIlha>
      <DivisorDaIlha />
      <BotaoDaIlha perigo disabled={qtdSelecionados === 0} onClick={gerenciar.aoPedirRemocao}>
        {qtdSelecionados > 0 ? `Remover (${qtdSelecionados})` : 'Remover'}
      </BotaoDaIlha>
      <DivisorDaIlha />
      <BotaoDaIlha onClick={gerenciar.aoSair}>Cancelar</BotaoDaIlha>
    </>
  );
}

export default function BarraDeNavegacao({
  transparente = false,
  termoBusca,
  aoMudarBusca,
  aoSubmeterBusca,
  opcoesFiltro,
  filtroSelecionado,
  aoMudarFiltro,
  // `opcoesSecoes`/`secaoSelecionada`/`aoMudarSecao` (opcionais, mesmo
  // contrato de `opcoesFiltro`/`filtroSelecionado`/`aoMudarFiltro` — só
  // `paginas/Inicio.jsx` passa os três, pra navegar por seção da própria
  // página em vez de filtrar catálogo): mutuamente exclusivos com o trio de
  // filtro na prática (nenhuma página passa os dois), mas mantidos
  // SEPARADOS (não um único prop genérico renomeado) porque a cápsula que
  // cada um ativa é uma diferente — ver `capsulaNoInicio`/`temSecoesNaIlha`
  // abaixo, e o histórico de duas tentativas revertidas de navegação por
  // seção no comentário logo acima do componente.
  opcoesSecoes,
  secaoSelecionada,
  aoMudarSecao,
  gerenciar,
  // `modoDaIlha` (nó React ou null — só `paginas/PaginaDoAnime.jsx`, no modo "Trocar
  // banner"): quando presente, a ilha abre e mostra esse conteúdo no lugar do
  // dropdown/mensagens, igual ao `gerenciar` mas sem contrato próprio — quem usa monta
  // os botões com `BotaoDaIlha`/`DivisorDaIlha`.
  modoDaIlha = null,
  // `sinopse` (opcional — só `paginas/Inicio.jsx` e `paginas/PaginaDoAnime.jsx`
  // passam; `undefined` = a página não tem sinopse, `null` = tem e está
  // fechada): `{ titulo, tituloSecundario, texto, aoFechar }` enquanto a sinopse
  // completa está aberta. A cápsula abre sozinha mostrando "Sinopse" e, quando
  // termina de abrir, ELA MESMA cresce na vertical e vira o painel
  // (hooks/useSinopseNaCapsula.js; abaixo de `sm`, onde a cápsula não existe,
  // cai no <dialog> de SinopseNaIlha.jsx). A página mantém o objeto até
  // `aoFechar`, que só dispara depois da animação de volta — é isso que fecha a
  // cápsula, na ordem inversa da abertura. Fica de fora da fila de
  // `mensagemIlha`: o painel é modal e cobre as mensagens.
  sinopse,
  notificacaoNovosEps = false,
  aoClicarNotificacaoNovosEps,
  verificandoNovosEps = false,
  // `statusCapturaIlha` (string|null): rótulo ao vivo tipo "Anime — episódio
  // 5: Baixando", enquanto QUALQUER episódio do app está em pipeline
  // (`hooks/useStatusDeCapturaIlha.js`, cruzado com `jobsPorEpisodio` do WS)
  // — contínuo, clicável (`aoClicarStatusCapturaIlha` leva pra página
  // DAQUELE anime, exceto se você já estiver nela). `capturaProntaIlha`
  // (string|null): "Anime — episódio N pronto" — transitório (some sozinho,
  // timer no próprio hook), clicável (`aoClicarCapturaProntaIlha` vai direto
  // pro player) quando um único episódio concluiu, mesmo espírito de
  // `notificacaoNovosEps`.
  statusCapturaIlha = null,
  aoClicarStatusCapturaIlha,
  capturaProntaIlha = null,
  aoClicarCapturaProntaIlha,
  // `erroCapturaIlha` (string|null): "Anime — episódio N: Falhou na
  // extração" — transitório (some sozinho, timer no próprio hook), clicável
  // (`aoClicarErroCapturaIlha` leva pra página do anime, sempre dispensa).
  // Migrado de `components/Toasts.jsx` (pedido do usuário, 2026-09-27) — ver
  // `hooks/useStatusDeCapturaIlha.js` pro porquê da PRIORIDADE MÁXIMA que
  // este sinal recebe na fila de `mensagemIlha` abaixo.
  erroCapturaIlha = null,
  aoClicarErroCapturaIlha,
  // `rotuloAcessivelIlha` (opcional): rótulo ARIA do dropdown da cápsula —
  // só a Galeria passa `opcoesFiltro`/`filtroSelecionado`/`aoMudarFiltro`
  // hoje, então o default já cobre o único caso real.
  rotuloAcessivelIlha = 'Filtrar catálogo',
  rotuloAcessivelSecoes = 'Navegar por seção',
}) {
  const idBusca = useId();
  const idFiltroIlha = useId();
  const temFiltroNaIlha = Boolean(aoMudarFiltro && opcoesFiltro?.length);
  const temSecoesNaIlha = Boolean(aoMudarSecao && opcoesSecoes?.length);
  // Gatilho de MONTAGEM do wrapper de conteúdo da ilha (mais abaixo,
  // `temConteudoNaIlha &&`) — deliberadamente ESTÁVEL (presença dos
  // callbacks, não o valor transiente de cada sinal) — ver bug corrigido no
  // comentário do próprio wrapper mais abaixo.
  const gerenciando = Boolean(gerenciar) && gerenciar.fase !== 'inativo';
  const temModoDaIlha = Boolean(modoDaIlha);
  const temSinopse = Boolean(sinopse);
  const modoNaIlha = gerenciando || temModoDaIlha || temSinopse;
  // Com `modoDaIlha`, a roda sobre a cápsula não rola a página (a lista de opções
  // dela rola sozinha, ver `components/SeletorDeBanner.jsx`). Ref por callback pelo
  // mesmo motivo de `medidorConteudoIlhaRef`: a cápsula remonta ao trocar de posição.
  // Listener nativo, porque o `onWheel` do React é passivo e não cancela a rolagem.
  const travarRodaNaIlhaRef = useCallback(
    (no) => {
      if (!no || !temModoDaIlha) return undefined;
      const travar = (evento) => evento.preventDefault();
      no.addEventListener('wheel', travar, { passive: false });
      return () => no.removeEventListener('wheel', travar);
    },
    [temModoDaIlha],
  );
  // `sinopse !== undefined` (e não `temSinopse`): o gate de montagem tem que ser
  // estável, senão o wrapper nasceria já aberto e sem transição de largura.
  // Nó da cápsula: o hook da sinopse mede o retângulo dela pra ancorar a
  // transformação em painel.
  const capsulaRef = useRef(null);
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
  const temConteudoNaIlha = Boolean(
    sinopse !== undefined ||
      gerenciar ||
      aoMudarFiltro ||
      aoMudarSecao ||
      aoClicarNotificacaoNovosEps ||
      aoClicarCapturaProntaIlha ||
      aoClicarStatusCapturaIlha ||
      aoClicarErroCapturaIlha
  );
  const inputBuscaRef = useRef(null);
  // Largura NATURAL do conteúdo da ilha (divisor + filtro/gerenciar), medida
  // por ResizeObserver. A cápsula anima `width` até esse valor em vez de um
  // `max-width` fixo: com teto genérico (460/580/680px) o crescimento visível
  // acabava assim que o teto passava da largura real, e o resto da duração
  // ficava parado (a "trepidação"); e trocar filtro↔gerenciar pulava de uma
  // largura pra outra sem transição, porque max-width não muda com o conteúdo.
  const [larguraConteudoIlha, setLarguraConteudoIlha] = useState(0);
  const observadorConteudoIlhaRef = useRef(null);
  // Ref por CALLBACK (não `useRef` + efeito): a cápsula é desmontada e
  // remontada quando Início/Catálogo trocam de posição (`linksTrocados`: são
  // slots diferentes, `key` não vale fora de array). Um efeito amarrado ao
  // primeiro nó ficaria observando um elemento morto e a largura congelaria
  // num valor velho — o seletor de seções da Início sumia/cortava.
  const medidorConteudoIlhaRef = useCallback((no) => {
    observadorConteudoIlhaRef.current?.disconnect();
    observadorConteudoIlhaRef.current = null;
    if (!no) return;
    const medir = () => setLarguraConteudoIlha(Math.ceil(no.getBoundingClientRect().width));
    medir();
    const observador = new ResizeObserver(medir);
    observador.observe(no);
    observadorConteudoIlhaRef.current = observador;
  }, []);
  const { pathname } = useLocation();
  const movimentoReduzido = usePrefersReducedMotion();
  const emInicio = pathname === '/';
  const emAnimes = pathname.startsWith('/animes');
  // Fundo ligado direto ao pixel rolado (0 a 1), não a um booleano com
  // `transition` no CSS correndo atrás dele — alternar classe + CSS
  // transition deixava a troca com uma sensação de atraso/brusca, porque a
  // curva do `transition` não acompanha 1:1 a velocidade real do scroll do
  // usuário. Com opacidade calculada a cada evento de scroll, a "animação"
  // é o próprio scroll (2026-09-23, referência: animefire.one, que na
  // real nem anima — troca instantânea; aqui preferimos o fade contínuo).
  //
  // 140px (primeira tentativa) ainda parecia brusco: era curto demais perto
  // da altura do hero da Início (`min-h-screen`, ~85-100vh) — um scroll
  // normal cobria a distância toda de uma vez, então o fade acontecia
  // "dentro" do mesmo gesto e não dava tempo do olho perceber gradiente.
  // 700px (tentativa seguinte) resolveu a ida, mas a volta (fundo
  // reaparecendo transparente) continuou parecendo brusca mesmo mais devagar
  // — sintoma de que o problema não era só distância: alpha LINEAR não
  // corresponde a percepção linear de contraste (olho humano é mais
  // sensível a mudança perto dos extremos 0/1 do que no meio), então a
  // borda de "quase transparente" e "quase opaco" sempre vai parecer mais
  // repentina que o miolo do fade, em qualquer direção. `suavizar()`
  // (smoothstep) desacelera a curva perto dos dois extremos em vez de
  // andar num ritmo constante — resolve a assimetria sem precisar
  // distinguir subindo/descendo. Com isso, 420px (valor pedido de volta
  // pelo usuário, 2026-09-23) já fica suave o bastante de novo.
  // `requestAnimationFrame` no listener evita também que o evento nativo
  // `scroll` (que alguns navegadores/trackpads disparam em lotes, não a
  // cada pixel) deixe a atualização com passos visíveis em vez de contínua.
  const LIMIAR_FUNDO_PX = 420;
  const suavizar = (t) => t * t * (3 - 2 * t);
  // Mutação direta de `style` via ref (não `useState`), pedido do usuário
  // depois de perceber a abertura da ilha dinâmica (`capsulaExpandidaIlha`
  // abaixo) mais truncada/com overshoot mais fraco quando disparada por
  // SCROLL do que quando disparada por uma mensagem (status/notificação),
  // 2026-09-2x. Causa raiz: `progressoScroll` mudava a cada frame de scroll
  // (`useState` + `setProgressoScroll`), e cada mudança de estado primitivo
  // DIFERENTE força o React a re-renderizar `BarraDeNavegacao` inteira — ou
  // seja, rolando a página o componente re-renderizava a ~60fps ENQUANTO a
  // transição CSS da cápsula (`max-width`/`padding`, ambas disparam layout,
  // não são compositor-only) também tentava rodar seus 450ms, competindo
  // pela mesma main thread. Sem scroll (mensagem chegando com a página
  // parada), nada mais re-renderiza durante a transição — daí a diferença
  // percebida. `navRef` deixa o fade do fundo (só ele mudava todo frame)
  // fora do ciclo de render do React: grava direto no DOM, sem tocar
  // `setState`. `logoColapsada`/`ilhaAtiva` CONTINUAM em `useState` — são
  // booleanos que só mudam UMA vez ao cruzar o limiar (React já não
  // re-renderiza sozinho quando o valor não muda), não competem com nada.
  const navRef = useRef(null);
  // Logo: booleano simples (rolou/não rolou um pouco), não um progresso
  // contínuo — referência anthropic.com (pedido do usuário, 2026-09-23):
  // lá o wordmark do header troca de uma vez com uma `transition` CSS
  // curta ao passar de um limiar pequeno, sem acompanhar o pixel do
  // scroll como o fundo acima. LogoSlimeStudio.jsx aplica a
  // `transition-all` nas classes; aqui só decide QUANDO virou.
  const LIMIAR_LOGO_PX = 24;
  const [logoColapsada, setLogoColapsada] = useState(false);

  // Limiar de abertura da cápsula por scroll (binário + transição CSS,
  // mesma técnica de `logoColapsada` acima) — usado pelo dropdown de filtro
  // da Galeria (`capsulaExpandidaIlha` abaixo: só abre depois de rolar além
  // deste ponto). 96px == a distância de `pt-24` do `<main>` de
  // `paginas/Galeria.jsx` até o topo — não é ciência exata de pixel, só a
  // estimativa mais simples de "a fileira original já sumiu, ativa a ilha".
  const LIMIAR_ILHA_PX = 96;
  const [ilhaAtiva, setIlhaAtiva] = useState(false);

  // Gatilhos da cápsula independentes do scroll (pedido do usuário,
  // 2026-09-27/28, estendido 2026-09-XX pros de captura, que desde então são
  // GLOBAIS — hooks/useStatusDeCapturaIlha.js, não mais escopados a um
  // anime — e por isso podem conviver DE VERDADE com os dois de novos
  // episódios na mesma página, Galeria.jsx: uma sondagem de aquecimento e uma
  // captura em andamento não têm relação nenhuma entre si, então rodar as
  // duas ao mesmo tempo é caso real, não só teórico): `verificandoNovosEps`
  // (true enquanto `aquecendo` em paginas/Galeria.jsx), `notificacaoNovosEps`
  // (dispara DEPOIS que essa verificação termina, se achou algo),
  // `statusCapturaIlha` (contínuo, enquanto QUALQUER job do app está em
  // progresso), `capturaProntaIlha` (transitório, quando um job conclui) e
  // `erroCapturaIlha` (transitório, quando um job falha — migrado de
  // components/Toasts.jsx, 2026-09-27, removido) forçam a cápsula a abrir
  // mesmo com `ilhaAtiva` false, e PRIORIZAM a mensagem sobre o dropdown de
  // filtro enquanto qualquer um estiver ativo. Cada um some sozinho
  // (verificando: sondagem acaba; notificação, captura-pronta e erro: timer
  // no pai; status de captura: nenhum job mais em progresso) e só então volta
  // a mostrar o filtro (se ainda rolado) ou fecha (se não).
  // `capsulaExpandidaIlha` substitui `ilhaAtiva` cru em toda a coreografia
  // abaixo (forma + conteúdo): os dois usam exatamente a mesma
  // abertura/fechamento que o filtro já usava, só troca o que aparece DENTRO.
  const ilhaPedida =
    modoNaIlha ||
    ((temFiltroNaIlha || temSecoesNaIlha) && ilhaAtiva) ||
    notificacaoNovosEps ||
    verificandoNovosEps ||
    Boolean(capturaProntaIlha) ||
    Boolean(statusCapturaIlha) ||
    Boolean(erroCapturaIlha);

  // Na Início, a ilha só abre DEPOIS da troca de posição dos links — a mesma
  // ordem do scroll, onde isso acontece aos 24px (`LIMIAR_LOGO_PX`) com a
  // cápsula ainda fechada e ela só abre aos 96px (`LIMIAR_ILHA_PX`). Quando um
  // gatilho que não é scroll (sinopse, captura, notificação) pede a ilha no topo
  // da página, `ilhaSimulandoScroll` faz a troca primeiro e
  // `ilhaLiberadaTrasTroca` abre a cápsula `ATRASO_ILHA_APOS_TROCA_MS` depois; ao
  // fechar, a cápsula fecha primeiro e só então os links voltam (a ordem inversa
  // do scroll de volta ao topo). A logo NÃO entra na simulação: ela só anima com
  // scroll de verdade (pedido do usuário, 2026-10-05).
  // Abrir tudo junto remontava a cápsula (o slot do link muda) já aberta: ela
  // aparecia de uma vez, sem a animação de abertura. Já rolado (`logoColapsada`)
  // ou fora da Início não há o que simular e nada muda.
  const exigeTrocaAntes = emInicio && !logoColapsada;
  const [ilhaSimulandoScroll, setIlhaSimulandoScroll] = useState(false);
  const [ilhaLiberadaTrasTroca, setIlhaLiberadaTrasTroca] = useState(false);
  const capsulaExpandidaIlha = ilhaPedida && (!exigeTrocaAntes || ilhaLiberadaTrasTroca);

  // Qual dropdown ocupa o conteúdo da ilha — mutuamente exclusivo na prática
  // (nenhuma página passa os dois trios), `temSecoesNaIlha` decide porque só
  // ele muda TAMBÉM qual link vira cápsula (ver `capsulaNoInicio` abaixo).
  const opcoesDropdownIlha = temSecoesNaIlha ? opcoesSecoes : opcoesFiltro;
  const valorDropdownIlha = temSecoesNaIlha ? secaoSelecionada : filtroSelecionado;
  const aoMudarDropdownIlha = temSecoesNaIlha ? aoMudarSecao : aoMudarFiltro;
  const rotuloAcessivelDropdownIlha = temSecoesNaIlha ? rotuloAcessivelSecoes : rotuloAcessivelIlha;
  // A cápsula (fundo/padding + dropdown) muda de LINK conforme a página: na
  // Início (`temSecoesNaIlha`) ela envolve "Início" — contextualmente é a
  // seção da própria página que está sendo navegada, não o catálogo — nas
  // demais (Galeria/PaginaDoAnime) continua em "Meu Catálogo", como sempre
  // foi. O link que NÃO leva a cápsula nessa página renderiza puro (só
  // ícone+texto, sem fundo/dropdown) — mesma aparência de antes de existir
  // qualquer ilha.
  const capsulaNoInicio = temSecoesNaIlha;

  // Prioridade de qual mensagem ocupa a cápsula quando mais de um gatilho
  // está ativo — só cabe UMA por vez (é um texto só, não uma lista). Eixo
  // usado pra ordenar: TRANSITÓRIO (tem timer próprio, alguns segundos)
  // sempre antes de CONTÍNUO (fica aberto enquanto durar). O motivo não é
  // "mais importante" — é que perder a janela de um transitório é
  // definitivo (o timer roda escondido atrás do contínuo e expira sem nunca
  // ter sido visto), enquanto um contínuo só fica visível de novo assim que
  // o transitório sair — nada se perde nesse sentido. Dentro de cada eixo, o
  // mais ESPECÍFICO (fala de um episódio/anime certo) vence o mais genérico
  // (fala do catálogo como um todo). EXCEÇÃO ao eixo transitório/contínuo:
  // `erroCapturaIlha` vai pro TOPO absoluto, na frente até de outro
  // transitório — falha não se autorresolve como um "pronto" (o card do
  // episódio já guarda o alerta permanentemente, ver
  // `hooks/useStatusDeCapturaIlha.js`), então é o único sinal que vale
  // interromper a vez de outro pra ser visto:
  //   1. `erroCapturaIlha` — transitório, aponta um episódio/anime
  //      específico, PRIORIDADE MÁXIMA (migrado de `components/Toasts.jsx`).
  //   2. `capturaProntaIlha` — transitório, aponta um episódio específico.
  //   3. `notificacaoNovosEps` — transitório, mas genérico ("o catálogo tem
  //      novidade", sem dizer qual anime).
  //   4. `statusCapturaIlha` — contínuo, aponta um episódio específico.
  //   5. `verificandoNovosEps` — contínuo e genérico (só "estou checando").
  // Só a Galeria hoje consegue ter os cinco ativos ao mesmo tempo (é a
  // única página com `notificacaoNovosEps`/`verificandoNovosEps`) — nesse
  // caso, cada um ainda tem sua vez assim que os de prioridade mais alta
  // saem (nenhum é descartado, só adiado), EXCETO se o próprio timer de um
  // transitório expirar enquanto ele está tapado por outro de prioridade
  // maior — perda aceita, mesmo trade-off de qualquer fila de notificação
  // com um único slot de exibição.
  let mensagemIlha;
  let aoClicarMensagemIlha;
  let tomMensagemIlha;
  if (erroCapturaIlha) {
    mensagemIlha = erroCapturaIlha;
    aoClicarMensagemIlha = aoClicarErroCapturaIlha;
    tomMensagemIlha = 'alerta';
  } else if (capturaProntaIlha) {
    mensagemIlha = capturaProntaIlha;
    aoClicarMensagemIlha = aoClicarCapturaProntaIlha;
  } else if (notificacaoNovosEps) {
    mensagemIlha = 'Novos episódios disponíveis';
    aoClicarMensagemIlha = aoClicarNotificacaoNovosEps;
  } else if (statusCapturaIlha) {
    mensagemIlha = statusCapturaIlha;
    aoClicarMensagemIlha = aoClicarStatusCapturaIlha;
  } else if (verificandoNovosEps) {
    mensagemIlha = 'Verificando novos episódios…';
  }

  // Coreografia da ilha em duas curvas, não uma só (a diferença que faltava
  // pra parecer a Dynamic Island de verdade, pedido do usuário 2026-09-26):
  // FORMA (bg/padding da cápsula + max-width do conteúdo) usa uma curva com
  // leve overshoot — estica um pouco além do tamanho final antes de
  // assentar, a "mola" que a curva Material (`cubic-bezier(0.4,0,0.2,1)`,
  // puramente desacelerada) não tem. CONTEÚDO (opacity do divisor+
  // SeletorEmMenu) fica na curva Material mesmo — overshoot em opacidade não
  // existe de verdade (o navegador clampa em [0,1]), e some/aparece com
  // ATRASO em relação à forma: no iPhone a cápsula abre primeiro, o
  // conteúdo só cruza-funde depois que já há espaço pra ele, e no
  // fechamento o conteúdo desaparece rápido enquanto a forma ainda está
  // recolhendo. Overshoot pequeno (1.15, não o 1.56 clássico de easeOutBack)
  // porque testado num elemento deste tamanho (~220px), overshoot forte lia
  // como tremulação, não elasticidade.
  //
  // Tentativa revertida (2026-09-26): mover o overshoot pra um
  // `transform: scale()` na cápsula inteira, deixando bg/padding/max-width
  // na curva Material. Descartada — o `scale` reduz visualmente também o
  // texto do link "Meu Catálogo" no estado fechado (fonte ficava menor no
  // repouso, non-negociável pro usuário), e a combinação
  // transform+padding+background transicionando junto ficou mais
  // pesada/travada que a versão só com overshoot na forma.
  //
  // Durações (450/400ms): copiadas direto do próprio wordmark
  // (LogoSlimeStudio.jsx — `duration-[450ms]`/`duration-[400ms]` dos spans
  // de STUDIO/ícone) — usuário apontou que a primeira versão (380/280ms)
  // "ainda estava rápida" mesmo com a mola; comparado à referência que ele
  // já aprovou, o ganho de fluidez estava na DURAÇÃO mais longa, não só na
  // curva. Atraso do conteúdo escala junto (mesma proporção ~38% do total).
  //
  // Bug real medido (pedido do usuário, 2026-09-2x, mais perceptível na
  // PaginaDoAnime — lá `capsulaExpandidaIlha` fecha de VERDADE quando a
  // notificação/status some, sem filtro nenhum segurando aberto; na Galeria,
  // rolada, o filtro geralmente mantém a cápsula aberta e o fechamento
  // completo é raro de ver): a forma usava uma curva com overshoot (mola,
  // `y1=1.15 > 1`) tanto pra ABRIR quanto pra FECHAR. `y1 > 1` faz o
  // PROGRESSO da transição ultrapassar 1 antes de assentar — em quem abre
  // (0 → alvo) isso lê como elástico (estica um pouco além do tamanho final).
  // Em quem fecha (alvo → 0) o MESMO overshoot de progresso ultrapassa o
  // alvo NA OUTRA PONTA, ou seja, tenta deixar `max-width`/`padding`
  // negativos — o navegador clampa em 0 antes da curva terminar de verdade,
  // então a forma parece "chegar" no fechado bem antes do fim real da
  // `transition-duration` e passa o resto do tempo parada (o "travada"
  // reportado) — e como o movimento visível acaba mais cedo que os 400ms
  // configurados, a sensação também é de rápido demais. Fechar não tem
  // elasticidade nenhuma no design original (só abrir "estica"), então o
  // fechamento da FORMA passa a usar `EASE_ILHA_CONTEUDO` (a curva Material,
  // sem overshoot) — mesma curva que o conteúdo (opacity) já usava nos dois
  // sentidos, sem essa armadilha.
  //
  // Bug real reportado pelo usuário (2026-09-27): a mola na ABERTURA do
  // padding/max-width da cápsula fazia a borda (região logo depois do ícone
  // da seta do dropdown) crescer um pouco além do tamanho final antes de
  // assentar — visível bem no fim da transição, já que uma curva com
  // overshoot sempre corrige de volta pro valor exato só no último instante
  // (é assim que qualquer "mola" funciona: passa um pouco e volta). Fix:
  // abertura do FORM (bg/padding/max-width) usa a mesma curva sem overshoot
  // que o fechamento já usava — a mola em si foi removida de toda a cápsula.
  const EASE_ILHA_CONTEUDO = 'cubic-bezier(0.4, 0, 0.2, 1)';
  const EASE_ILHA_FORMA_FECHA = EASE_ILHA_CONTEUDO;
  const DURACAO_ILHA_ABRE_MS = 450;
  const DURACAO_ILHA_FECHA_MS = 400;
  const ATRASO_CONTEUDO_ILHA_ABRE_MS = 170;
  // Folga entre a troca dos links e a abertura da cápsula: o que o usuário leva
  // rolando dos 24px aos 96px.
  const ATRASO_ILHA_APOS_TROCA_MS = 200;
  useEffect(() => {
    if (!exigeTrocaAntes) return undefined;
    if (ilhaPedida) {
      setIlhaSimulandoScroll(true);
      const temporizador = setTimeout(() => setIlhaLiberadaTrasTroca(true), ATRASO_ILHA_APOS_TROCA_MS);
      return () => clearTimeout(temporizador);
    }
    setIlhaLiberadaTrasTroca(false);
    const temporizador = setTimeout(() => setIlhaSimulandoScroll(false), DURACAO_ILHA_FECHA_MS);
    return () => clearTimeout(temporizador);
  }, [exigeTrocaAntes, ilhaPedida]);
  const easeFormaAtual = EASE_ILHA_FORMA_FECHA;
  // A cápsula só vira painel depois de terminar de abrir (+ folga do fade do
  // conteúdo). `ilhaVisivel`: abaixo de `sm` o <ul> some e vale o <dialog>.
  const ilhaVisivel = useCapsulaVisivel();
  const painel = useSinopseNaCapsula({
    ativa: temSinopse && ilhaVisivel,
    atrasoAbrirMs: (exigeTrocaAntes ? ATRASO_ILHA_APOS_TROCA_MS : 0) + DURACAO_ILHA_ABRE_MS + 60,
    capsulaRef,
    aoFechar: sinopse?.aoFechar,
    movimentoReduzido,
  });
  // `contain: 'layout style'` isola o reflow da transição de
  // `padding`/`background-color` deste `<div>` a esta subárvore (a própria
  // cápsula) — o resto da página (incluindo o scroll em si) não entra na
  // conta do navegador pra validar o layout. Não muda nada visual: o
  // tamanho da PRÓPRIA cápsula ainda conta normalmente pro layout do `<ul>`
  // por fora (containment não isola a CAIXA em si, só o que está DENTRO
  // dela).
  const estiloFormaIlha = {
    transitionDuration: `${capsulaExpandidaIlha ? DURACAO_ILHA_ABRE_MS : DURACAO_ILHA_FECHA_MS}ms`,
    transitionTimingFunction: easeFormaAtual,
    contain: 'layout style',
  };
  const estiloConteudoIlha = {
    transitionDuration: `${capsulaExpandidaIlha ? DURACAO_ILHA_ABRE_MS : DURACAO_ILHA_FECHA_MS}ms, ${
      capsulaExpandidaIlha ? 280 : 200
    }ms`,
    transitionTimingFunction: `${easeFormaAtual}, ${EASE_ILHA_CONTEUDO}`,
    transitionDelay: `0ms, ${capsulaExpandidaIlha ? ATRASO_CONTEUDO_ILHA_ABRE_MS : 0}ms`,
  };

  // Clique no link "Meu Catálogo" quando ELE é a cápsula (Galeria/
  // PaginaDoAnime, `!capsulaNoInicio`): reseta a navegação/filtro
  // (`opcoesFiltro`/`aoMudarFiltro`) pro primeiro item; se já é o primeiro,
  // rola pro topo — mesmo padrão de "clicar no item de nav já ativo" de
  // outros apps. Só faz sentido na PRÓPRIA rota (`/animes`) — fora dela
  // (fallback da Início/PaginaDoAnime) o clique é só a navegação normal do
  // `<Link>`.
  const aoClicarLinkDaCapsula = () => {
    if (!emAnimes || !opcoesFiltro?.length) return;
    const valorPadrao = opcoesFiltro[0].valor;
    if (filtroSelecionado === valorPadrao) {
      window.scrollTo({ top: 0, behavior: movimentoReduzido ? 'auto' : 'smooth' });
    } else {
      aoMudarFiltro?.(valorPadrao);
    }
  };

  // Clique em "Início" (pedido do usuário, 2026-09-28): já estando na rota
  // "/", o `<Link to="/">` sozinho não faz nada visível (mesma rota, sem
  // remount) — sem isto, clicar em "Início" rolado (seção no meio, dropdown
  // de seções ativo) parecia morto. Rola pro topo, mesmo padrão de
  // `aoClicarLinkDaCapsula` pro ramo "já é o item ativo". Sem reset de
  // seção equivalente ao reset de filtro: não há "seção padrão" pra voltar,
  // o scroll-spy só reflete onde a página já está — rolar pro topo já
  // resolve isso sozinho (a 1ª seção passa a ser a "atual" de novo).
  const aoClicarLinkInicio = () => {
    if (!emInicio) return;
    window.scrollTo({ top: 0, behavior: movimentoReduzido ? 'auto' : 'smooth' });
  };

  // Ativo (destaque `text-neon`) por ROTA, independente de qual link leva a
  // cápsula (`capsulaNoInicio`) ou de qual slot cada um ocupa no momento
  // (`linksTrocados`, mais abaixo) — os dois eixos são independentes.
  const ativoLateral = emInicio;
  const ativoCapsula = emAnimes;

  // `linksTrocados`: só na Início (`emInicio`), ao passar do mesmo limiar
  // que colapsa a logo (`logoColapsada`) — Início e Meu Catálogo trocam de
  // posição (Início assume o slot do meio, Catálogo vai pra ponta esquerda).
  // Pedido do usuário 2026-09-28, depois de DUAS tentativas de navegação por
  // seção na Início reverdidas no mesmo dia (ver comentário no topo do
  // arquivo) — esta é mais simples que as duas: nenhum link muda de texto/
  // destino, só a posição dos dois troca. Troca via ORDEM DE RENDER (não CSS
  // `order`), pra manter a ordem de tab igual à ordem visual; `key` em cada
  // `<li>` evita que o React desmonte/remonte o dropdown da cápsula ao
  // trocar de posição.
  //
  // Também troca com a ilha pedida sem scroll (sinopse, captura, notificação),
  // simulando o scroll só nos links (`ilhaSimulandoScroll`, ver `ilhaPedida`) — pedido
  // do usuário, 2026-10-05: o "Início" é a cápsula na Início e tem que abrir no
  // meio da navbar, onde o painel da sinopse cresce, igual a quando se rola.
  const linksTrocados = emInicio && (logoColapsada || ilhaSimulandoScroll);

  // Fábrica de `<li>` compartilhada pelos dois links que podem virar
  // "a cápsula" (fundo + dropdown da ilha) — extraída pra não duplicar essa
  // JSX pra Início E Catálogo, já que agora qualquer um dos dois pode ser a
  // vez (`capsulaNoInicio` acima). Fecha sobre as variáveis da ilha já
  // calculadas acima (`estiloFormaIlha`, `capsulaExpandidaIlha`,
  // `temConteudoNaIlha`, `estiloConteudoIlha`, `opcoesDropdownIlha` etc.) —
  // redefinida a cada render, sem custo real (só JSX, sem trabalho pesado).
  const renderLinkComCapsula = ({ chave, to, ativo, Icone, rotulo, onClick }) => (
    <li key={chave} style={painel.estiloItem}>
      <div
        ref={refDaCapsula}
        style={{ ...estiloFormaIlha, ...painel.estiloCapsula }}
        // `relative`: âncora de posicionamento do dropdown (`ocuparLarguraDoPai`
        // no `SeletorEmMenu`, sempre `true` aqui, pedido do usuário,
        // 2026-09-28) — o menu passa a ocupar a largura da CÁPSULA INTEIRA
        // (do ícone/link até o chevron do dropdown), não só a do próprio
        // botão gatilho. Vale pros dois usos da cápsula (seções na Início,
        // filtro na Galeria) — é o padrão agora, não uma exceção da Início.
        className={`relative flex flex-col rounded-full transition-[background-color,padding] motion-reduce:transition-none ${
          capsulaExpandidaIlha ? 'bg-white/5 px-3 py-1' : 'px-0 py-0'
        }`}
      >
        {/* Cabeçalho (link + conteúdo da ilha): numa grade de uma linha só pra
            poder colapsar a altura a 0 quando a cápsula vira o painel da sinopse
            (`painel.expandida`), junto com a região abaixo crescer. Em repouso é
            uma passagem direta, sem mudar a medida de nada. `overflow-hidden` só
            com a sinopse ancorada: em repouso o menu do dropdown (`absolute`,
            ancorado na cápsula) não pode ser cortado — e ele não é, porque o
            ancestral posicionado dele está FORA deste wrapper. */}
        <div
          className="grid"
          style={{
            gridTemplateRows: painel.expandida ? '0fr' : '1fr',
            opacity: painel.expandida ? 0 : 1,
            transition: `${painel.estiloGrade.transition}, opacity 200ms ease`,
          }}
          inert={painel.ancorada || undefined}
        >
          <div className={`flex min-h-0 items-center ${painel.ancorada ? 'overflow-hidden' : ''}`}>
        <Link
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
          <div
            // Ver comentário completo desta coreografia (gate de montagem
            // estável, `inert`) na versão original deste wrapper — inalterado,
            // só generalizado pro link que for a cápsula em cada página.
            // `overflow-hidden` sempre: o menu do dropdown é `absolute` com
            // ancestral posicionado na cápsula (fora deste wrapper), então o
            // clip não o corta.
            inert={!capsulaExpandidaIlha || undefined}
            style={{
              ...estiloConteudoIlha,
              width: capsulaExpandidaIlha ? larguraConteudoIlha : 0,
            }}
            className={`overflow-hidden transition-[width,opacity,margin-left] motion-reduce:transition-none ${
              capsulaExpandidaIlha ? 'ml-2 opacity-100' : 'ml-0 opacity-0'
            }`}
          >
            <div ref={medidorConteudoIlhaRef} className="flex w-max items-center gap-2">
              <DivisorDaIlha />
              {/* Os dois painéis ficam montados: o SeletorEmMenu guarda estado
                  (largura do rótulo, aberto) que um desmonte jogaria fora.
                  `hidden` tira o inativo do layout, então o medidor acima só
                  conta o painel visível; sair de `display:none` reinicia o
                  fade de entrada (`animate-ilha-conteudo`). */}
              <div
                className={`flex items-center gap-2 animate-ilha-conteudo motion-reduce:animate-none ${
                  modoNaIlha ? 'hidden' : ''
                }`}
              >
                <SeletorEmMenu
                  id={idFiltroIlha}
                  opcoes={opcoesDropdownIlha}
                  valor={valorDropdownIlha}
                  aoMudar={aoMudarDropdownIlha}
                  rotuloAcessivel={rotuloAcessivelDropdownIlha}
                  mensagemSobreposta={mensagemIlha}
                  aoClicarMensagem={aoClicarMensagemIlha}
                  tomMensagem={tomMensagemIlha}
                  // Sempre `true` aqui: é o padrão pra QUALQUER dropdown hospedado
                  // pela cápsula (pedido do usuário, 2026-09-28 — antes só o
                  // seletor de seções da Início tinha isso, o filtro da Galeria
                  // ficou de fora por engano na primeira leva). Ver comentário de
                  // `ocuparLarguraDoPai` em `SeletorEmMenu.jsx`.
                  ocuparLarguraDoPai
                />
                {/* Some enquanto há notificação/status na cápsula (`mensagemIlha`):
                    o texto sobreposto já ocupa o lugar do filtro. */}
                {gerenciar && !mensagemIlha && (
                  <>
                    <DivisorDaIlha />
                    <button
                      type="button"
                      onClick={gerenciar.aoAlternar}
                      className="inline-flex h-8 shrink-0 cursor-pointer items-center whitespace-nowrap text-[18px] font-semibold text-ink-muted outline-none transition-colors hover:text-white focus-visible:text-white motion-reduce:transition-none"
                    >
                      Gerenciar
                    </button>
                  </>
                )}
              </div>
              {gerenciando && (
                // `key={fase}`: cada fase troca o conteúdo (contagem →
                // confirmação → removendo → resultado) e reentra com fade
                // enquanto a largura anima pro novo tamanho.
                <div
                  key={gerenciar.fase}
                  className="flex items-center gap-2 animate-ilha-conteudo motion-reduce:animate-none"
                >
                  <ConteudoGerenciarIlha gerenciar={gerenciar} />
                </div>
              )}
              {!gerenciando && !modoDaIlha && temSinopse && (
                <div className="flex items-center gap-2 animate-ilha-conteudo motion-reduce:animate-none">
                  {/* `h-9`: mesma altura do dropdown que volta ao sair do modo — senão a
                      cápsula dá um tranco de altura no fim do fechamento. */}
                  <span className="inline-flex h-9 items-center whitespace-nowrap text-[18px] font-semibold text-white">
                    Sinopse
                  </span>
                </div>
              )}
              {!gerenciando && modoDaIlha && (
                <div className="flex items-center gap-2 animate-ilha-conteudo motion-reduce:animate-none">
                  {modoDaIlha}
                </div>
              )}
            </div>
          </div>
        )}
          </div>
        </div>
        {painel.ancorada && (
          <div
            className="grid"
            style={{
              gridTemplateRows: painel.expandida ? '1fr' : '0fr',
              ...painel.estiloGrade,
            }}
          >
            {/* `role="dialog"` à mão (sem <dialog> nativo): o hook cuida de foco,
                Esc e Tab. Qualquer clique fecha, menos com texto selecionado
                (senão copiar um trecho fecharia o painel). */}
            <div
              ref={painel.regiaoRef}
              role="dialog"
              aria-modal="true"
              aria-labelledby="titulo-sinopse-ilha"
              tabIndex={-1}
              data-visivel={painel.expandida ? '' : undefined}
              data-rolavel={painel.rolavel ? '' : undefined}
              onClick={() => {
                if (window.getSelection()?.toString() === '') painel.fechar();
              }}
              style={{ maxHeight: 'calc(100dvh - 3rem)' }}
              className="sinopse-ilha-conteudo cursor-pointer text-left text-white outline-none"
            >
              {/* Com barra de rolagem o texto ocupa a largura que sobra (a barra come
                  uma fatia); sem ela, largura fixa pra não reflowar no crescimento. */}
              <div style={{ width: painel.rolavel ? undefined : painel.larguraConteudo }}>
                <ConteudoDaSinopse
                  titulo={sinopse?.titulo ?? ''}
                  tituloSecundario={sinopse?.tituloSecundario}
                  sinopse={sinopse?.texto}
                />
              </div>
            </div>
          </div>
        )}
      </div>
    </li>
  );

  // Link puro (ícone + texto), sem fundo/dropdown — o link que NÃO é a
  // cápsula nesta página usa esta forma, idêntica visualmente ao estado
  // fechado da cápsula.
  const renderLinkPuro = ({ chave, to, ativo, Icone, rotulo, onClick }) => (
    <li key={chave}>
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

  const linkInicio = capsulaNoInicio
    ? renderLinkComCapsula({
        chave: 'inicio',
        to: '/',
        ativo: ativoLateral,
        Icone: Home,
        rotulo: 'Início',
        onClick: aoClicarLinkInicio,
      })
    : renderLinkPuro({
        chave: 'inicio',
        to: '/',
        ativo: ativoLateral,
        Icone: Home,
        rotulo: 'Início',
        onClick: aoClicarLinkInicio,
      });

  const catalogoLi = capsulaNoInicio
    ? renderLinkPuro({ chave: 'catalogo', to: '/animes', ativo: ativoCapsula, Icone: LibraryBig, rotulo: 'Meu Catálogo' })
    : renderLinkComCapsula({
        chave: 'catalogo',
        to: '/animes',
        ativo: ativoCapsula,
        Icone: LibraryBig,
        rotulo: 'Meu Catálogo',
        onClick: aoClicarLinkDaCapsula,
      });

  useEffect(() => {
    if (!transparente) return undefined;
    let quadroPendente = false;
    const atualizar = () => {
      const t = Math.min(window.scrollY / LIMIAR_FUNDO_PX, 1);
      if (navRef.current) {
        navRef.current.style.backgroundColor = `rgba(0, 0, 0, ${suavizar(t)})`;
      }
      setLogoColapsada(window.scrollY > LIMIAR_LOGO_PX);
      setIlhaAtiva(window.scrollY > LIMIAR_ILHA_PX);
      quadroPendente = false;
    };
    const aoRolar = () => {
      if (quadroPendente) return;
      quadroPendente = true;
      requestAnimationFrame(atualizar);
    };
    atualizar();
    window.addEventListener('scroll', aoRolar, { passive: true });
    return () => window.removeEventListener('scroll', aoRolar);
  }, [transparente]);

  const fundoClasse = transparente ? '' : 'bg-surface/40 backdrop-blur-sm';
  // Valor inicial só (0 = topo da página, transparente) — depois disto o
  // efeito acima assume e escreve direto no elemento via `navRef`, nunca
  // mais por aqui.
  const estiloFundoInicial = transparente ? { backgroundColor: 'rgba(0, 0, 0, 0)' } : undefined;

  return (
    <>
    <nav
      ref={navRef}
      aria-label="Principal"
      style={estiloFundoInicial}
      className={`fixed inset-x-0 top-0 z-20 flex h-20 items-center justify-between gap-6 px-6 md:px-10 ${fundoClasse}`}
    >
      {/* Decorativa: não navega. Wordmark em texto (não SVG/imagem) —
          tamanho vem das classes text-* dentro de LogoSlimeStudio.jsx, não
          de uma altura fixa aqui. `colapsada` troca STUDIO pelo ícone de
          play assim que `scrollY` passa de `LIMIAR_LOGO_PX` — binário,
          independente do fade contínuo do fundo (via `navRef` acima). */}
      {painel.ancorada && (
        <div
          aria-hidden="true"
          onClick={painel.fechar}
          className="sinopse-ilha-cortina"
        />
      )}
      <LogoSlimeStudio colapsada={logoColapsada} />
      {/* `absolute left-1/2 -translate-x-1/2`: centraliza em relação à
          navbar inteira (que já é `fixed`, então já é containing block pra
          isso), não em relação ao espaço sobrando entre logo e busca — se
          centralizasse via flex normal, a posição dependeria de quanto a
          logo e a busca pesam de cada lado (varia por página: PaginaDoAnime
          não tem busca, então o `justify-between` sozinho puxaria os links
          pro centro errado ali). */}
      <ul
        className={`absolute left-1/2 hidden -translate-x-1/2 items-center gap-8 text-lg text-ink-muted sm:flex sm:text-lg ${
          // Com a sinopse ancorada, o <ul> sobe acima da cortina e os links
          // vizinhos da cápsula somem (senão vazam pelos 6% de transparência
          // do painel); o <li> da cápsula força `opacity: 1` inline.
          painel.ancorada ? 'z-10 [&>li]:opacity-0' : ''
        } [&>li]:transition-opacity`}
      >
        {/* `linksTrocados`: Início entra ANTES do Catálogo (posição normal,
            esquerda) quando false, e DEPOIS (posição do meio) quando true —
            ver `linksTrocados` acima. `linkInicio`/`catalogoLi` já vêm
            resolvidos (puro ou com cápsula, ver `capsulaNoInicio` acima) —
            só a ORDEM de render muda aqui, pra manter tab igual ao visual. */}
        {!linksTrocados && linkInicio}
        {catalogoLi}
        {linksTrocados && linkInicio}
        <li key="generos">
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
        <form
          onSubmit={(event) => {
            event.preventDefault();
            aoSubmeterBusca?.();
          }}
          role="search"
          className="mr-8 flex items-center"
        >
          <label htmlFor={idBusca} className="sr-only">
            Buscar animes
          </label>
          <div className="relative flex items-center">
            <span
              aria-hidden="true"
              className="pointer-events-none absolute inset-y-0 left-3.5 flex items-center text-ink-muted"
            >
              <Search strokeWidth={4} className="h-4 w-4" />
            </span>
            <input
              ref={inputBuscaRef}
              id={idBusca}
              type="search"
              value={termoBusca}
              onChange={(event) => aoMudarBusca(event.target.value)}
              placeholder="Buscar animes"
              className="h-10 w-86 rounded-full bg-surface/80 pl-10 pr-9 text-sm font-bold text-white outline-none transition-colors [&::-webkit-search-cancel-button]:hidden"
            />
            {termoBusca && (
              <button
                type="button"
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => {
                  aoMudarBusca('');
                  inputBuscaRef.current?.focus();
                }}
                aria-label="Limpar busca"
                className="absolute right-2 flex h-6 w-6 items-center justify-center rounded-full text-ink-muted outline-none transition-colors hover:text-white cursor-pointer"
              >
                <X strokeWidth={4} className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
        </form>
      )}
    </nav>
    {/* Fallback abaixo de `sm`, onde o <ul> da cápsula some. Fora do <nav>
        pra não herdar nada do `fundoClasse`. */}
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

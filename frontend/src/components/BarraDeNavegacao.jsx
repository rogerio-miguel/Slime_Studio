import { useEffect, useId, useRef, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { Home, LibraryBig, Search, Tags, X } from 'lucide-react';
import { usePrefersReducedMotion } from '../inicio/usePrefersReducedMotion.js';
import LogoSlimeStudio from './LogoSlimeStudio';
import SeletorEmMenu from './SeletorEmMenu';

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
  const temConteudoNaIlha = Boolean(
    aoMudarFiltro ||
      aoMudarSecao ||
      aoClicarNotificacaoNovosEps ||
      aoClicarCapturaProntaIlha ||
      aoClicarStatusCapturaIlha ||
      aoClicarErroCapturaIlha
  );
  const inputBuscaRef = useRef(null);
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
  const capsulaExpandidaIlha =
    ((temFiltroNaIlha || temSecoesNaIlha) && ilhaAtiva) ||
    notificacaoNovosEps ||
    verificandoNovosEps ||
    Boolean(capturaProntaIlha) ||
    Boolean(statusCapturaIlha) ||
    Boolean(erroCapturaIlha);

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
  const easeFormaAtual = EASE_ILHA_FORMA_FECHA;
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
  const linksTrocados = emInicio && logoColapsada;

  // Fábrica de `<li>` compartilhada pelos dois links que podem virar
  // "a cápsula" (fundo + dropdown da ilha) — extraída pra não duplicar essa
  // JSX pra Início E Catálogo, já que agora qualquer um dos dois pode ser a
  // vez (`capsulaNoInicio` acima). Fecha sobre as variáveis da ilha já
  // calculadas acima (`estiloFormaIlha`, `capsulaExpandidaIlha`,
  // `temConteudoNaIlha`, `estiloConteudoIlha`, `opcoesDropdownIlha` etc.) —
  // redefinida a cada render, sem custo real (só JSX, sem trabalho pesado).
  const renderLinkComCapsula = ({ chave, to, ativo, Icone, rotulo, onClick }) => (
    <li key={chave}>
      <div
        style={estiloFormaIlha}
        // `relative`: âncora de posicionamento do dropdown (`ocuparLarguraDoPai`
        // no `SeletorEmMenu`, sempre `true` aqui, pedido do usuário,
        // 2026-09-28) — o menu passa a ocupar a largura da CÁPSULA INTEIRA
        // (do ícone/link até o chevron do dropdown), não só a do próprio
        // botão gatilho. Vale pros dois usos da cápsula (seções na Início,
        // filtro na Galeria) — é o padrão agora, não uma exceção da Início.
        className={`relative flex items-center rounded-full transition-[background-color,padding] motion-reduce:transition-none ${
          capsulaExpandidaIlha ? 'bg-white/5 px-3 py-1' : 'px-0 py-0'
        }`}
      >
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
            // estável, `inert`, teto de largura) na versão original deste
            // wrapper — inalterado, só generalizado pro link que for a
            // cápsula em cada página.
            inert={!capsulaExpandidaIlha || undefined}
            style={estiloConteudoIlha}
            className={`flex items-center gap-2 transition-[max-width,opacity,margin-left] motion-reduce:transition-none ${
              capsulaExpandidaIlha
                ? 'ml-2 max-w-[460px] overflow-visible opacity-100'
                : 'ml-0 max-w-0 overflow-hidden opacity-0'
            }`}
          >
            <span aria-hidden="true" className="h-4 w-px shrink-0 bg-white/15" />
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
      <LogoSlimeStudio colapsada={logoColapsada} />
      {/* `absolute left-1/2 -translate-x-1/2`: centraliza em relação à
          navbar inteira (que já é `fixed`, então já é containing block pra
          isso), não em relação ao espaço sobrando entre logo e busca — se
          centralizasse via flex normal, a posição dependeria de quanto a
          logo e a busca pesam de cada lado (varia por página: PaginaDoAnime
          não tem busca, então o `justify-between` sozinho puxaria os links
          pro centro errado ali). */}
      <ul className="absolute left-1/2 hidden -translate-x-1/2 items-center gap-8 text-lg text-ink-muted sm:flex sm:text-lg">
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
          className="flex items-center mr-8"
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
  );
}

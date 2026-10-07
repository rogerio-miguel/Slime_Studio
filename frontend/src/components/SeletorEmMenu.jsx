import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { ChevronDown } from 'lucide-react';
import { usePrefersReducedMotion } from '../inicio/usePrefersReducedMotion.js';

const DURACAO_CROSSFADE_ROTULO_MS = 220;
const EASE_LARGURA_ROTULO = 'cubic-bezier(0.4, 0, 0.2, 1)';

// Dropdown de valor único genérico — mesmo padrão de acessibilidade de
// `SeletorDeTemporada.jsx` (gatilho com chevron que gira + `role="menu"`/
// `role="menuitem"`, Esc fecha e devolve o foco ao gatilho, ↑/↓ andam pelos
// itens, Home/End vão pras pontas, clique fora fecha), generalizado pra
// `valor`/`aoMudar` em vez de navegação de rota — usado pelo filtro de
// `paginas/Galeria.jsx`, que antes usava `<select>` nativo e passou a seguir
// esta mesma linguagem visual (pedido do usuário). `opcoes`: [{valor, rotulo}].
// Histórico do menu do seletor de seções de `paginas/Inicio.jsx` (~14
// opções, 4 principais + fileiras temáticas), tudo no mesmo dia
// (2026-09-28): um divisor visual entre grupos de opções (`grupo` por opção)
// foi tentado e removido (ficou feio); um teto de altura com scroll interno
// (`max-h-[198px] overflow-y-auto`, calibrado pra mostrar 5 opções inteiras
// + um pedaço da 6ª) também foi tentado e removido — a versão atual usa
// `ocuparLarguraDoPai` (abaixo) pra ganhar largura em vez de altura, sem
// scroll nenhum, todas as opções sempre visíveis.
//
// `ocuparLarguraDoPai` (opcional, default `false`): o menu passa a ocupar a
// largura do ANCESTRAL POSICIONADO mais próximo (`inset-x-0`, este
// componente abre mão do próprio `relative` — ver `containerRef` abaixo) em
// vez da largura do PRÓPRIO botão gatilho (`min-w-full`, comportamento
// default). `BarraDeNavegacao.jsx` passa sempre `true` nos dois usos da
// cápsula (seletor de seções da Início E filtro da Galeria, pedido do
// usuário 2026-09-28: "é o padrão") — esse ancestral é a cápsula inteira
// (ícone/link + divisor + gatilho), então o menu passa a "pegar o início e o
// fim da ilha", não só do gatilho. `false` (default) fica só pra um
// `SeletorEmMenu` usado FORA de uma cápsula, sem ancestral posicionado
// nenhum pra herdar largura. Opções ganham `whitespace-normal` (quebra de
// linha) no modo `true`: a largura agora é FIXA (não cresce pra caber o
// texto mais longo como o `min-w-full` default faz), então rótulos longos
// precisam poder quebrar em vez de vazar pra fora da cápsula.
//
// `prefixo` (opcional): igual ao gatilho de `SeletorDeTemporada.jsx`, o texto
// do botão É o rótulo — sem `<label>` externo separado. Quando passado,
// renderiza "PREFIXO | opção" (ex. "FILTRAR | Assistidos") em vez de só a
// opção; pedido explícito do usuário pra reduzir a pilha label-em-cima
// botão-embaixo de antes pra uma linha só.
//
// `mensagemSobreposta`/`aoClicarMensagem` (opcionais, usados só pela
// notificação "novos episódios" da ilha dinâmica em BarraDeNavegacao.jsx):
// pedido explícito do usuário, 2026-09-27, pra notificação ficar IGUAL ao
// filtro — mesma fonte/cor/tamanho e MESMO crossfade que já roda pra trocar
// de rótulo, em vez de um elemento à parte com estilo próprio. Por isso a
// mensagem não é um componente irmão: é só outro valor possível de
// `textoAlvo` abaixo, o crossfade nem sabe a diferença. Enquanto presente,
// clique chama `aoClicarMensagem` no lugar de abrir o menu (a notificação
// não é um dropdown).
//
// `tomMensagem` (opcional, só faz sentido junto de `mensagemSobreposta`):
// 'alerta' pinta o texto em âmbar (`text-amber-300`, mesmo tom de
// `LinhaDeEpisodio.jsx::OverlayDeStatus`/`AnimeCard.jsx` pra falha/atenção)
// em vez do cinza neutro das outras mensagens — migrado de
// `components/Toasts.jsx` (que usava vermelho num toast à parte); aqui
// reaproveita o âmbar já estabelecido como "isto precisa de atenção" em vez
// de introduzir uma terceira cor de alerta no app.
export default function SeletorEmMenu({
  id,
  // Default `[]`: chamadores só-mensagem (status/notificação de captura da
  // ilha dinâmica em `paginas/PaginaDoAnime.jsx`) nunca têm opções de
  // dropdown de verdade — sem o default, `opcoes.findIndex` abaixo quebraria
  // com `opcoes` undefined. Inofensivo (o ramo de dropdown real nunca abre
  // sem `mensagemSobreposta`, que estes chamadores sempre passam).
  opcoes = [],
  valor,
  aoMudar,
  rotuloAcessivel,
  prefixo,
  mensagemSobreposta,
  aoClicarMensagem,
  tomMensagem,
  ocuparLarguraDoPai = false,
}) {
  const [aberto, setAberto] = useState(false);
  const [indiceAtivo, setIndiceAtivo] = useState(0);
  const idMenu = useId();
  const containerRef = useRef(null);
  const gatilhoRef = useRef(null);
  const itensRef = useRef([]);

  const indiceSelecionado = Math.max(
    0,
    opcoes.findIndex((opcao) => opcao.valor === valor)
  );
  const opcaoSelecionada = opcoes[indiceSelecionado];
  const movimentoReduzido = usePrefersReducedMotion();

  // `textoAlvo`: mensagem sobreposta tem prioridade sobre o rótulo da opção
  // — o crossfade abaixo reage a QUALQUER mudança deste valor, seja troca de
  // filtro ou a notificação aparecendo/sumindo, sem precisar saber a causa.
  const textoAlvo = mensagemSobreposta ?? (prefixo ? `${prefixo} | ${opcaoSelecionada?.rotulo}` : opcaoSelecionada?.rotulo);

  // Crossfade no texto do botão quando `textoAlvo` muda (pedido do usuário,
  // 2026-09-27) — sem isto a troca era instantânea. `textoExibido` só
  // atualiza no MEIO do fade: o toggle de `desvanecendo` (true na mudança,
  // false 150ms depois, junto com o texto novo) dispara as duas metades —
  // fade-out seguido de fade-in — com uma única classe `transition-opacity`.
  // Ignora a primeira renderização (senão o texto inicial já entraria
  // desvanecendo). Sob `prefers-reduced-motion`, pula o fade inteiro
  // (atualiza na hora): só neutralizar a duração via CSS deixaria o texto em
  // branco parado pelos 150ms sem nenhum motivo funcional, pior que não
  // animar.
  const [textoExibido, setTextoExibido] = useState(textoAlvo);
  const [desvanecendo, setDesvanecendo] = useState(false);
  const primeiraRenderizacaoRotuloRef = useRef(true);
  useEffect(() => {
    if (primeiraRenderizacaoRotuloRef.current) {
      primeiraRenderizacaoRotuloRef.current = false;
      return undefined;
    }
    if (movimentoReduzido) {
      setTextoExibido(textoAlvo);
      return undefined;
    }
    setDesvanecendo(true);
    const tempo = setTimeout(() => {
      setTextoExibido(textoAlvo);
      setDesvanecendo(false);
    }, DURACAO_CROSSFADE_ROTULO_MS);
    return () => clearTimeout(tempo);
  }, [textoAlvo, movimentoReduzido]);

  // Bug medido ao vivo (2026-09-27, ver conversa): sem isto, o `<span>` do
  // rótulo tinha largura AUTOMÁTICA (auto-encolhe/estica pro texto que
  // estiver dentro) — quando `textoExibido` trocava pra um texto de
  // comprimento bem diferente (ex. filtro curto "Todos" ↔ notificação longa
  // "Novos episódios disponíveis"), a largura pulava instantaneamente no
  // meio do crossfade (opacidade em 0, mas o LAYOUT saltava igual). Como a
  // `<ul>` inteira da navbar é centralizada via `left-1/2`+`-translate-x-1/2`
  // (BarraDeNavegacao.jsx), esse salto de largura arrastava a navbar inteira
  // pro lado num frame só — medido ~91px de deslocamento no caso da
  // notificação. Fix: mede a largura do texto ALVO (não o exibido) num
  // `<span>` invisível fora do fluxo (`medidorRef`), e anima a largura do
  // `<span>` visível até esse valor — a mudança de tamanho vira uma transição
  // suave em vez de um salto, sincronizada com o próprio crossfade (mesma
  // duração, metade "encolhe/estica" enquanto o texto está invisível,
  // metade final já no tamanho certo quando o texto some/aparece).
  const medidorRef = useRef(null);
  const [larguraRotulo, setLarguraRotulo] = useState(null);
  // `ResizeObserver` + descarte de largura 0: o pai pode esconder este
  // componente com `display:none` (a ilha esconde o filtro no modo Gerenciar,
  // BarraDeNavegacao.jsx) — medir nesse estado dava 0 e o rótulo voltava com
  // largura zero (só a seta aparecia). Ao reaparecer, o observer re-mede.
  useLayoutEffect(() => {
    const medidor = medidorRef.current;
    if (!medidor) return undefined;
    const medir = () => {
      if (medidor.offsetWidth > 0) setLarguraRotulo(medidor.offsetWidth);
    };
    medir();
    const observador = new ResizeObserver(medir);
    observador.observe(medidor);
    return () => observador.disconnect();
  }, [textoAlvo]);

  useEffect(() => {
    if (!aberto) return undefined;
    const aoApontarFora = (evento) => {
      if (!containerRef.current?.contains(evento.target)) setAberto(false);
    };
    document.addEventListener('pointerdown', aoApontarFora);
    return () => document.removeEventListener('pointerdown', aoApontarFora);
  }, [aberto]);

  useEffect(() => {
    if (!aberto) return;
    setIndiceAtivo(indiceSelecionado);
    itensRef.current[indiceSelecionado]?.focus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [aberto]);

  const fechar = (devolverFoco = true) => {
    setAberto(false);
    if (devolverFoco) gatilhoRef.current?.focus();
  };

  // Sempre chama `aoMudar`, mesmo pra opção já selecionada — a navegação por
  // seção da Início (paginas/Inicio.jsx, mesmo dropdown reaproveitado) precisa
  // disso: clicar na seção que o scroll-spy já marca como "atual" ainda deve
  // rolar até o topo exato dela (o usuário pode estar no MEIO da seção, não
  // necessariamente no topo). Pra filtro (Galeria) é inofensivo: reaplicar o
  // mesmo valor é um no-op equivalente.
  const escolher = (opcao) => {
    fechar(false);
    aoMudar(opcao.valor);
  };

  const aoTeclarNoMenu = (evento) => {
    if (evento.key === 'Escape') {
      evento.preventDefault();
      fechar();
    } else if (evento.key === 'ArrowDown') {
      evento.preventDefault();
      const proximo = (indiceAtivo + 1) % opcoes.length;
      setIndiceAtivo(proximo);
      itensRef.current[proximo]?.focus();
    } else if (evento.key === 'ArrowUp') {
      evento.preventDefault();
      const anterior = (indiceAtivo - 1 + opcoes.length) % opcoes.length;
      setIndiceAtivo(anterior);
      itensRef.current[anterior]?.focus();
    } else if (evento.key === 'Home') {
      evento.preventDefault();
      setIndiceAtivo(0);
      itensRef.current[0]?.focus();
    } else if (evento.key === 'End') {
      evento.preventDefault();
      const ultimo = opcoes.length - 1;
      setIndiceAtivo(ultimo);
      itensRef.current[ultimo]?.focus();
    }
  };

  return (
    // `inline-block` (não `relative` puro): o pai em paginas/Galeria.jsx é um
    // <div> de bloco cheio, e sem isto este container herdava a largura
    // inteira dele — aí o `min-w-full` do menu abaixo esticava pra cobrir a
    // área dos cards em vez de só acompanhar a largura do botão. Sem
    // `relative` quando `ocuparLarguraDoPai`: de propósito — o menu abaixo
    // precisa "escapar" pro ancestral posicionado mais próximo (a cápsula em
    // `BarraDeNavegacao.jsx`, ver comentário de `ocuparLarguraDoPai` no topo
    // do arquivo), não ficar preso a ESTE container.
    <div ref={containerRef} className={`inline-block ${ocuparLarguraDoPai ? '' : 'relative'}`}>
      <button
        id={id}
        ref={gatilhoRef}
        type="button"
        aria-haspopup={mensagemSobreposta ? undefined : 'menu'}
        aria-expanded={mensagemSobreposta ? undefined : aberto}
        aria-controls={aberto && !mensagemSobreposta ? idMenu : undefined}
        onClick={() => {
          if (mensagemSobreposta) {
            aoClicarMensagem?.();
            return;
          }
          setAberto((estava) => !estava);
        }}
        onKeyDown={(evento) => {
          if (evento.key === 'ArrowDown' && !aberto && !mensagemSobreposta) {
            evento.preventDefault();
            setAberto(true);
          }
        }}
        className={`inline-flex items-center gap-2 h-8 text-[18px] font-semibold outline-none transition-colors hover:border-neon cursor-pointer ${
          mensagemSobreposta && tomMensagem === 'alerta'
            ? 'text-amber-300 hover:text-amber-200'
            : 'text-ink-muted hover:text-white'
        }`}
      >
        <span
          style={{
            width: larguraRotulo != null ? `${larguraRotulo}px` : undefined,
            transitionDuration: `${DURACAO_CROSSFADE_ROTULO_MS}ms, ${DURACAO_CROSSFADE_ROTULO_MS}ms`,
            transitionTimingFunction: `linear, ${EASE_LARGURA_ROTULO}`,
          }}
          className={`inline-block overflow-hidden whitespace-nowrap transition-[opacity,width] motion-reduce:transition-none ${
            desvanecendo ? 'opacity-0' : 'opacity-100'
          }`}
        >
          {textoExibido}
        </span>
        {/* Medidor invisível: mede a largura do texto ALVO (não o exibido,
            ver comentário de `larguraRotulo` acima) fora do fluxo normal —
            `absolute` garante que ele não empurra o layout do botão. */}
        <span
          ref={medidorRef}
          aria-hidden="true"
          className="pointer-events-none invisible absolute whitespace-nowrap"
        >
          {textoAlvo}
        </span>
        {/* Sem chevron com mensagem sobreposta (pedido do usuário,
            2026-09-27) — não é um dropdown nesse estado, a seta sugeriria
            que dá pra abrir algo. */}
        {!mensagemSobreposta && (
          <ChevronDown
            width={14}
            height={14}
            aria-hidden="true"
            strokeWidth="4"
            className={`shrink-0 transition-transform ${aberto ? 'rotate-180' : ''}`}
          />
        )}
      </button>

      {aberto && !mensagemSobreposta && (
        <div
          id={idMenu}
          role="menu"
          aria-label={rotuloAcessivel}
          onKeyDown={aoTeclarNoMenu}
          // Sem teto de altura/scroll (removido a pedido do usuário,
          // 2026-09-28 — ver histórico no topo do arquivo): todas as opções
          // sempre visíveis, altura cresce com o conteúdo. Largura:
          // `inset-x-0` (ancestral posicionado, a cápsula inteira) quando
          // `ocuparLarguraDoPai`, senão `left-0 min-w-full` (o próprio
          // botão gatilho, comportamento default/Galeria) — ver comentário
          // de `ocuparLarguraDoPai` no topo do arquivo.
          // `overflow-hidden`: o fundo de hover/foco da 1ª e da última opção é um
          // retângulo e, sem o recorte, ficava sobrando para fora dos cantos
          // arredondados do menu.
          className={`absolute top-full z-20 mt-1 overflow-hidden border border-border-chrome rounded-2xl bg-[#0f0f10] shadow-xl shadow-black/50 ${
            ocuparLarguraDoPai ? 'inset-x-0' : 'left-0 min-w-full'
          }`}
        >
          {opcoes.map((opcao, indice) => {
            const atual = opcao.valor === valor;
            return (
              <button
                key={opcao.valor}
                ref={(no) => {
                  itensRef.current[indice] = no;
                }}
                type="button"
                role="menuitem"
                aria-current={atual ? 'true' : undefined}
                tabIndex={indice === indiceAtivo ? 0 : -1}
                onClick={() => escolher(opcao)}
                className={`block w-full px-4 py-2 text-left text-sm font-semibold outline-none transition-colors hover:bg-white/5 focus-visible:bg-white/10 cursor-pointer ${
                  ocuparLarguraDoPai ? '' : 'whitespace-nowrap'
                } ${atual ? 'text-white' : 'text-ink-muted hover:text-white'}`}
              >
                {opcao.rotulo}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

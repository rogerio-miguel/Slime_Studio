import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import {
  ATRASO_POR_INDICE_MS,
  COLUNAS_GRID,
  DURACAO_ENTRADA_MS,
  estiloLarguraMaxCard,
  RESERVA_TOPO,
  SlotDeCard,
} from './GradeDeCards.jsx';
import { usePrefersReducedMotion } from './usePrefersReducedMotion.js';

// Pontos de quebra espelhando exatamente as classes Tailwind do grid abaixo
// (`sm`/`md`/`lg`/`xl` default do framework: 640/768/1024/1280px) — o número
// de colunas em JS precisa bater com o que o CSS realmente renderiza,
// senão o tamanho do lote (colunas * 2) fica errado e sobra/falta card na
// última linha.
const _PONTOS_DE_QUEBRA = [
  { consulta: '(min-width: 1280px)', colunas: 7 },
  { consulta: '(min-width: 1024px)', colunas: 6 },
  { consulta: '(min-width: 768px)', colunas: 5 },
  { consulta: '(min-width: 640px)', colunas: 4 },
];
const _COLUNAS_BASE = 2;

function _colunasAtuais() {
  const ponto = _PONTOS_DE_QUEBRA.find((p) => window.matchMedia(p.consulta).matches);
  return ponto ? ponto.colunas : _COLUNAS_BASE;
}

// Quantidade de colunas do grid na largura atual — via `matchMedia` (mesma
// família de mecanismo de `usePrefersReducedMotion`), não `ResizeObserver`:
// o grid é full-width (não tem container próprio pra observar), é a
// viewport que decide o breakpoint.
function useColunasResponsivas() {
  const [colunas, setColunas] = useState(_colunasAtuais);

  useEffect(() => {
    const consultas = _PONTOS_DE_QUEBRA.map((p) => window.matchMedia(p.consulta));
    const recalcular = () => setColunas(_colunasAtuais());
    consultas.forEach((c) => c.addEventListener('change', recalcular));
    return () => consultas.forEach((c) => c.removeEventListener('change', recalcular));
  }, []);

  return colunas;
}

// Grade full-bleed de 2 linhas fixas, encaixada entre a navbar e o fim da
// viewport (sem rolar), cujo conteúdo roda por tempo (substitui o carrossel
// horizontal de FaixaDeAnimes/FaixaDeDestaques, Fase 4 — pivot de produto,
// ver plano). Quem chama não entrega cards prontos (`children`, padrão
// antigo): entrega o pool inteiro (`itens`) + uma função de render por item
// (`renderItem`), porque agora o componente precisa conhecer os itens
// individualmente pra sortear/paginar o lote visível. Pode expandir sob
// demanda (botão "Mostrar todos", estado `expandido` abaixo) pra trocar o
// recorte rotativo pelo pool inteiro — nesse modo a seção deixa de estar
// presa a 1 viewport e cresce com a página normalmente.
//
// `ativa` só faz o gate de quando o timer PODE começar (ex.: a fase
// "revelado" de useIntroPorVideo) — opacidade/visibilidade da seção como um
// todo já vem do fade-in de <main> em paginas/Inicio.jsx, este componente
// não duplica isso.
//
// A seção ocupa exatamente 1 viewport (`minHeight: calc(100vh - RESERVA_TOPO)`
// abaixo) enquanto está no modo rotativo — é a premissa de "2 linhas sempre
// visíveis, sem precisar rolar". Ao expandir, esse limite é removido (ver
// `estilo.minHeight` abaixo).
export default function GradeRotativa({
  titulo,
  itens = [],
  renderItem,
  ativa,
  intervaloMs = 600000, // 10min
}) {
  const idTitulo = useId();
  const idGrade = useId();
  const colunas = useColunasResponsivas();
  const movimentoReduzido = usePrefersReducedMotion();
  const tamanhoLote = colunas * 2;
  const rotaciona = itens.length > tamanhoLote;

  const [expandido, setExpandido] = useState(false);

  const estilo = {
    // Sem limite quando expandido: a grade passa a mostrar o pool inteiro e
    // a seção precisa crescer com a página normalmente, em vez de ficar
    // espremida em 1 viewport.
    minHeight: expandido ? undefined : `calc(100vh - ${RESERVA_TOPO})`,
    ...estiloLarguraMaxCard,
  };

  const [indiceInicio, setIndiceInicio] = useState(0);
  const [geracao, setGeracao] = useState(0);
  const pausadoRef = useRef(false);

  // Índice de rotação volta pro início se o pool encolher (ex. feed
  // recarregou com menos itens) — sem isto, um `indiceInicio` alto de uma
  // rodada anterior podia ficar fora do alcance do novo pool.
  useEffect(() => {
    setIndiceInicio(0);
    setGeracao(0);
  }, [itens.length]);

  useEffect(() => {
    // `expandido` entra no early-return: com o pool inteiro já visível não
    // faz sentido manter o timer de rotação rodando por baixo — ele só
    // reassume quando o usuário volta pro modo recortado.
    if (!ativa || movimentoReduzido || !rotaciona || expandido) return undefined;

    const id = setInterval(() => {
      if (pausadoRef.current) return;
      setIndiceInicio((atual) => (atual + tamanhoLote) % itens.length);
      setGeracao((atual) => atual + 1);
    }, intervaloMs);

    return () => clearInterval(id);
  }, [ativa, movimentoReduzido, rotaciona, expandido, tamanhoLote, itens.length, intervaloMs]);

  // Mesma fórmula de rotação pros dois modos, só o comprimento muda: expandir
  // não troca a ORDEM dos itens já visíveis (evitaria o "pulo" de recomeçar
  // do índice 0 da lista original) — as primeiras `tamanhoLote` posições
  // continuam batendo com o que já estava na tela, e o restante do pool
  // aparece encadeado a partir da 3ª linha, como continuação da rotação.
  const lote = useMemo(() => {
    if (!rotaciona) return itens;
    const tamanho = expandido ? itens.length : tamanhoLote;
    return Array.from({ length: tamanho }, (_, i) => itens[(indiceInicio + i) % itens.length]);
  }, [itens, rotaciona, expandido, tamanhoLote, indiceInicio]);

  // Gate de exibição do botão "Mostrar todos": só liga depois que a última
  // posição da leva atual termina a própria animação de entrada (SlotDeCard
  // acima) — sem isto o botão "furava a fila" e ficava clicável antes dos
  // cards que ele resume estarem todos na tela. `movimentoReduzido` pula a
  // espera (cards já aparecem sem transição nesse caso, ver motion-reduce
  // em SlotDeCard); `geracao` reseta o gate a cada rotação, já que a leva
  // inteira re-anima nesse momento (mesma key `${geracao}-${posicao}` do
  // grid abaixo). Usa `tamanhoLote`, não `lote.length`: o botão só é
  // regatado no modo recortado — expandir não deve escondê-lo de novo, é
  // uma ação direta sobre ele mesmo.
  const [botaoVisivel, setBotaoVisivel] = useState(false);
  useEffect(() => {
    if (!ativa) {
      setBotaoVisivel(false);
      return undefined;
    }
    if (movimentoReduzido) {
      setBotaoVisivel(true);
      return undefined;
    }
    setBotaoVisivel(false);
    const atraso = (tamanhoLote - 1) * ATRASO_POR_INDICE_MS + DURACAO_ENTRADA_MS;
    const id = setTimeout(() => setBotaoVisivel(true), atraso);
    return () => clearTimeout(id);
  }, [ativa, movimentoReduzido, geracao, tamanhoLote]);

  const pausar = useCallback(() => {
    pausadoRef.current = true;
  }, []);
  const retomar = useCallback(() => {
    pausadoRef.current = false;
  }, []);

  if (lote.length === 0) return null;

  return (
    <section
      aria-labelledby={idTitulo}
      style={estilo}
      // `px-6 md:px-10`: mesmo padding horizontal da navbar
      // (components/BarraDeNavegacao.jsx) — sem isto, o início do título
      // "Destaques da temporada" (e a borda esquerda da grade, agora
      // alinhada a ele via `justify-start` em GradeDeCards.jsx) não batia
      // com o início de "Slime Studio" na navbar, nem a borda direita da
      // grade batia com o fim do campo de busca.
      className="flex flex-col justify-center-safe px-6 pb-2 md:px-10"
    >
      <h2 id={idTitulo} className="mb-4 text-2xl font-semibold text-white">
        {titulo}
      </h2>

      {/* Pausa a rotação com o cursor ou o foco dentro da grade — sem isto,
          um card podia sumir debaixo do cursor/foco no meio de uma
          interação. `onFocus`/`onBlur` do React usam focusin/focusout por
          baixo (bubbla), então se comportam como `:focus-within` mas
          conseguem pausar o timer em JS (CSS puro não alcança o `setInterval`).

          Ver GradeDeCards.jsx pro racional de COLUNAS_GRID (por que a track
          não é `1fr` e por que `justify-start`, não `justify-center`). */}
      <div
        id={idGrade}
        onMouseEnter={pausar}
        onMouseLeave={retomar}
        onFocus={pausar}
        onBlur={retomar}
        className={`grid gap-6 ${COLUNAS_GRID}`}
      >
        {lote.map((item, posicao) => (
          // SEM `expandido` na key, de propósito: `lote` usa a mesma fórmula
          // de rotação nos dois modos (ver acima), então as posições
          // 0..tamanhoLote-1 apontam pro MESMO item antes/depois de expandir
          // — manter a key estável nelas evita remontar/reanimar as 2
          // primeiras linhas só porque o modo mudou. Só as posições novas
          // (a partir da 3ª linha) são, de fato, nós novos — e entram com a
          // animação de entrada normal do SlotDeCard.
          <SlotDeCard key={`${geracao}-${posicao}`} indice={posicao} ativa={ativa}>
            {renderItem(item)}
          </SlotDeCard>
        ))}
      </div>

      {/* Só existe quando há mais itens do que o lote fixo mostra
          (`rotaciona`) — sem excedente, "Mostrar todos" não teria nada a
          mais pra exibir. `self-center`: a seção é `flex-col`, então sem
          isto o botão herdava o `align-items: stretch` padrão e esticava
          pra largura inteira da seção — `self-center` tira do stretch,
          encolhe pro tamanho do conteúdo e centraliza no eixo cruzado. */}
      {rotaciona && (
        // Wrapper controla a entrada (opacity/scale, gate `botaoVisivel`
        // acima) sem herdar a duração de 700ms pro hover do botão em si —
        // mesma separação de responsabilidade que SlotDeCard usa pros
        // cards. `disabled` no botão some com o foco/clique enquanto
        // invisível, sem precisar de mais um atributo pra isso.
        <div
          className={`mt-6 self-center transition-[opacity,scale] duration-700 ease-out motion-reduce:opacity-100 motion-reduce:scale-100 motion-reduce:transition-none ${
            botaoVisivel ? 'scale-100 opacity-100' : 'scale-[0.8] opacity-0'
          }`}
        >
          <button
            type="button"
            onClick={() => setExpandido((atual) => !atual)}
            aria-expanded={expandido}
            aria-controls={idGrade}
            disabled={!botaoVisivel}
            className="rounded-md border border-neon-soft bg-surface px-4 py-2 text-sm font-semibold text-neon outline-none transition-colors hover:border-neon focus-visible:ring-2 focus-visible:ring-neon"
          >
            {expandido ? 'Mostrar menos' : `Mostrar todos (${itens.length})`}
          </button>
        </div>
      )}
    </section>
  );
}

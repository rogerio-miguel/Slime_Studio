import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
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

// A grade (2 linhas fixas) precisa caber inteira entre a navbar fixa e o fim
// da viewport, sem rolar, com respiro visível abaixo da navbar (mt-20 do h2
// da própria seção, somado ao pt-24 de <main>).
const _RESERVA_TOPO = '6rem'; // pt-24 de <main> (paginas/Inicio.jsx)
// mt-20 do h2 (5rem, respiro visível abaixo da navbar) + h2 text-2xl
// line-height (1.75rem) + mb-4 (1rem) + gap-6 entre as 2 linhas do grid
// (0.5rem, espelha o gap-6 do grid abaixo) + folga de respiro (0.25rem) +
// reserva de topo (6rem).
const _RESERVA_TOTAL = '14.5rem';

// Track não pode ser `1fr` (padrão do grid em fluxo normal) — se a coluna
// ficar mais larga que o teto do card (--largura-max-card), o card sobra
// menor que ela e centralizado dentro (`mx-auto` em SlotDeCard), abrindo um
// respiro DENTRO de cada coluna que se soma ao `gap` e aparece como
// distância extra entre os cards de uma mesma linha — não só entre colunas.
// Track do tamanho do próprio teto colapsa essa folga nas bordas do bloco
// inteiro (`justify-center`) em vez de espalhar entre cada par de cards.
// Contagem de colunas por breakpoint espelha `_PONTOS_DE_QUEBRA`.
const _COLUNAS_GRID =
  'grid-cols-[repeat(2,minmax(0,var(--largura-max-card)))] justify-center ' +
  'sm:grid-cols-[repeat(4,minmax(0,var(--largura-max-card)))] ' +
  'md:grid-cols-[repeat(5,minmax(0,var(--largura-max-card)))] ' +
  'lg:grid-cols-[repeat(6,minmax(0,var(--largura-max-card)))] ' +
  'xl:grid-cols-[repeat(7,minmax(0,var(--largura-max-card)))]';

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

// Slot de um card do grid — dono da transição de entrada (opacity-0
// scale-95 → opacity-100 scale-100, "surge do meio", linguagem visual já
// validada com o usuário na rodada anterior). Monta escondido e no próximo
// frame revela: é o mesmo truque de duas fases que antes vinha de
// `useEntradaNaViewport` (visível vira `true` depois do mount), só que agora
// local a cada slot em vez de global à seção — GradeRotativa força um
// componente novo por posição a cada troca de lote (key inclui a geração),
// então o mount por si só já dispara a transição de novo, sem orquestração
// extra no componente pai.
function SlotDeCard({ indice, children }) {
  const [visivel, setVisivel] = useState(false);

  useEffect(() => {
    const quadro = requestAnimationFrame(() => setVisivel(true));
    return () => cancelAnimationFrame(quadro);
  }, []);

  return (
    <div
      // maxWidth (não maxHeight): o card usa aspect-[2/3], que resolve a
      // largura primeiro — um teto de altura entraria em conflito com o
      // aspect-ratio e quebraria a proporção 2:3. `--largura-max-card` vem
      // do estilo inline de GradeRotativa (herdado via custom property CSS),
      // sempre presente enquanto este componente só existir dentro dela.
      style={{ transitionDelay: `${Math.min(indice, 7) * 60}ms`, maxWidth: 'var(--largura-max-card)' }}
      className={`mx-auto w-full transition-[opacity,transform] duration-500 ease-out motion-reduce:opacity-100 motion-reduce:scale-100 motion-reduce:transition-none ${
        visivel ? 'scale-100 opacity-100' : 'scale-95 opacity-0'
      }`}
    >
      {children}
    </div>
  );
}

// Grade full-bleed de 2 linhas fixas, encaixada entre a navbar e o fim da
// viewport (sem rolar), cujo conteúdo roda por tempo (substitui o carrossel
// horizontal de FaixaDeAnimes/FaixaDeDestaques, Fase 4 — pivot de produto,
// ver plano). Quem chama não entrega cards prontos (`children`, padrão
// antigo): entrega o pool inteiro (`itens`) + uma função de render por item
// (`renderItem`), porque agora o componente precisa conhecer os itens
// individualmente pra sortear/paginar o lote visível.
//
// `ativa` só faz o gate de quando o timer PODE começar (ex.: a fase
// "revelado" de useScrubDeVideo) — opacidade/visibilidade da seção como um
// todo já vem do fade-in de <main> em paginas/Inicio.jsx, este componente
// não duplica isso.
export default function GradeRotativa({
  titulo,
  itens = [],
  renderItem,
  ativa,
  intervaloMs = 1800000, // 30min
}) {
  const idTitulo = useId();
  const colunas = useColunasResponsivas();
  const movimentoReduzido = usePrefersReducedMotion();
  const tamanhoLote = colunas * 2;
  const rotaciona = itens.length > tamanhoLote;

  // Teto de largura do card (--largura-max-card, consumido em SlotDeCard)
  // vem de altura_max_card = (100vh - RESERVA_TOTAL) / 2 linhas; como o card
  // usa aspect-[2/3], largura = altura * 2/3 — daí a divisão final por 3.
  const estilo = {
    minHeight: `calc(100vh - ${_RESERVA_TOPO})`,
    '--largura-max-card': `calc((100vh - ${_RESERVA_TOTAL}) / 3)`,
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
    if (!ativa || movimentoReduzido || !rotaciona) return undefined;

    const id = setInterval(() => {
      if (pausadoRef.current) return;
      setIndiceInicio((atual) => (atual + tamanhoLote) % itens.length);
      setGeracao((atual) => atual + 1);
    }, intervaloMs);

    return () => clearInterval(id);
  }, [ativa, movimentoReduzido, rotaciona, tamanhoLote, itens.length, intervaloMs]);

  const lote = useMemo(() => {
    if (!rotaciona) return itens;
    return Array.from({ length: tamanhoLote }, (_, i) => itens[(indiceInicio + i) % itens.length]);
  }, [itens, rotaciona, tamanhoLote, indiceInicio]);

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
      className="flex flex-col justify-center-safe px-4 sm:px-6 lg:px-8"
    >
      <h2 id={idTitulo} className="mb-4 mt-20 text-2xl font-semibold text-white">
        {titulo}
      </h2>

      {/* Pausa a rotação com o cursor ou o foco dentro da grade — sem isto,
          um card podia sumir debaixo do cursor/foco no meio de uma
          interação. `onFocus`/`onBlur` do React usam focusin/focusout por
          baixo (bubbla), então se comportam como `:focus-within` mas
          conseguem pausar o timer em JS (CSS puro não alcança o `setInterval`). */}
      <div
        onMouseEnter={pausar}
        onMouseLeave={retomar}
        onFocus={pausar}
        onBlur={retomar}
        className={`grid gap-6 ${_COLUNAS_GRID}`}
      >
        {lote.map((item, posicao) => (
          <SlotDeCard key={`${geracao}-${posicao}`} indice={posicao}>
            {renderItem(item)}
          </SlotDeCard>
        ))}
      </div>
    </section>
  );
}

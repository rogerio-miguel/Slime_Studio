import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import { COLUNAS_GRID, estiloLarguraMaxCard, RESERVA_TOPO, SlotDeCard } from './GradeDeCards.jsx';
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

  const estilo = {
    minHeight: `calc(100vh - ${RESERVA_TOPO})`,
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
      // `px-6 md:px-10`: mesmo padding horizontal da navbar
      // (components/BarraDeNavegacao.jsx) — sem isto, o início do título
      // "Destaques da temporada" (e a borda esquerda da grade, agora
      // alinhada a ele via `justify-start` em GradeDeCards.jsx) não batia
      // com o início de "Slime Studio" na navbar, nem a borda direita da
      // grade batia com o fim do campo de busca.
      className="flex flex-col justify-center-safe px-6 md:px-10"
    >
      <h2 id={idTitulo} className="mb-4 mt-20 text-2xl font-semibold text-white">
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
        onMouseEnter={pausar}
        onMouseLeave={retomar}
        onFocus={pausar}
        onBlur={retomar}
        className={`grid gap-6 ${COLUNAS_GRID}`}
      >
        {lote.map((item, posicao) => (
          <SlotDeCard key={`${geracao}-${posicao}`} indice={posicao} ativa={ativa}>
            {renderItem(item)}
          </SlotDeCard>
        ))}
      </div>
    </section>
  );
}

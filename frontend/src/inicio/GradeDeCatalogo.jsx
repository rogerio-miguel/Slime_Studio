import { SOMBRA_SLIDE_ATIVO } from './CarrosselDestaques.jsx';
import {
  CLASSE_GUTTER,
  CLASSE_RESPIRO_POSTER,
  CLASSES_POR_PAGINA,
  FLEX_BASIS_SLOT_COM_RESPIRO,
} from './tamanhoDeCard.js';
import { SlotDeCard } from './GradeDeCards.jsx';

// Grade de catálogo: irmã de FileiraDeCards.jsx que QUEBRA LINHA (`flex-wrap`)
// em vez de rolar. Compartilha o vocabulário de tamanho de ./tamanhoDeCard.js
// (mesmo `--por-pagina` por breakpoint via `CLASSES_POR_PAGINA`, mesmo
// `CLASSE_GUTTER`, mesmo `FLEX_BASIS_SLOT_COM_RESPIRO`), então o card sai com a MESMA
// largura de slot que a fileira por construção — desde que as duas passem o
// MESMO `tamanho`: as fileiras de pôster da Home (Próximas estreias, Top 10)
// e as duas grades daqui passam `tamanho="pequeno"` explicitamente (pedido
// explícito do usuário, 2026-09-15 — antes as fileiras caíam no default
// "grande" do componente e saíam maiores que a Galeria; ver ./tamanhoDeCard.js
// pro vocabulário completo). `<li>` sem padding — pedido explícito do usuário
// pra não sobrar respiro nenhum entre cards, maximizando o pôster mantendo
// `--por-pagina` intacto (6 por linha no xl, tamanho "pequeno").
// FileiraDeCards.jsx usava `p-[10px]` no slot antes; depois (2026-09-15) o
// usuário removeu de lá também, então hoje as duas telas têm o MESMO
// tratamento de padding também. `isolate` + `[&:has(li:hover)>li:not(:hover)]:z-1`
// na `<ul>`: o glow do hover (components/AnimeCard.jsx, `-z-10`, vaza ~14px pra
// fora do pôster) precisa ficar ATRÁS dos pôsteres vizinhos, que são
// contíguos — sem isso o slot em hover (ou o stacking context do `SlotDeCard`
// animado) pintaria o brilho por cima do vizinho. Mesma regra em FileiraDeCards.jsx.
//
// Sem setas / `onScroll` / `medirLimites` / `useRef`: não há trilha rolável
// pra medir. Nada aqui recorta o overflow (não há `overflow-x-auto` como na
// fileira).
//
// Cada card leva a MESMA drop shadow do slide ativo do billboard
// (`SOMBRA_SLIDE_ATIVO`, de CarrosselDestaques.jsx — fonte única): histórico,
// pedido do usuário quando ainda fazia sentido visualmente. Ela mora num
// wrapper só-da-sombra DENTRO do `SlotDeCard`, então entra/some junto com a
// animação de entrada escalonada — mesmo comportamento da fileira.
// `comSombra = false` (usado por paginas/Galeria.jsx E paginas/Inicio.jsx —
// hoje TODO chamador passa `false`, `true` só segue default por
// retrocompatibilidade caso algum uso futuro volte a querer sombra) desliga
// esse wrapper. Motivo duplo — (1) a sombra só tem contraste visível sobre um
// cinza tipo `#17171b`; sobre o preto sólido que as duas páginas usam hoje
// (`html{background:#000}`, index.css) ela praticamente some de qualquer
// jeito; (2) com o card do catálogo agora em duas partes (pôster + legenda
// abaixo, sem caixa própria — ver components/AnimeCard.jsx), um wrapper
// `rounded-xl` de sombra abraçando as DUAS partes lançava um halo escuro
// atrás do bloco de texto, que não tem caixa nenhuma pra justificá-lo — lia
// como um "fundo" indevido ali.
//
// O respiro entre LINHAS quebradas vem do `gap-y-[34px]` da `<ul>` (row-gap:
// só o eixo cross, não afeta o cálculo de `flex-basis` no eixo principal),
// NÃO do `pb-[44px]` da fileira — aqui há várias linhas e a sombra de uma
// (desce ~46px abaixo da borda do card) não pode invadir a linha de baixo.
// `pb-[24px]` dá a folga da última linha; `pt-[22px]` o respiro título->cards.
//
// `comAnimacao = false` (paginas/Galeria.jsx, pedido explícito do usuário,
// 2026-09-17) desliga a animação de entrada "surge do meio" repassando
// `animada` pro SlotDeCard — cards do catálogo nascem já visíveis. Default
// `true` preserva o comportamento das duas grades de paginas/Inicio.jsx.
//
// API espelha FileiraDeCards: `itens` + `renderItem(item, indice)` +
// `chaveDoItem(item)` + `tamanho`. O guard de lista vazia mora aqui (retorna
// `null`), o chamador não repete. NÃO leva `aria-labelledby` — o
// `<section aria-labelledby>` do chamador (paginas/Galeria.jsx) já rotula.
// `role="list"` explícito porque o Preflight do Tailwind v4 zera `list-style`
// e o VoiceOver larga a semântica de lista junto.
export default function GradeDeCatalogo({
  itens,
  renderItem,
  chaveDoItem,
  tamanho = 'grande',
  comSombra = true,
  comAnimacao = true,
}) {
  const lista = itens ?? [];
  if (lista.length === 0) return null;

  return (
    <ul
      role="list"
      className={`isolate flex flex-wrap [&:has(li:hover)>li:not(:hover)]:z-1 ${CLASSE_GUTTER} ${CLASSE_RESPIRO_POSTER} gap-y-[36px] pt-[22px] pb-[24px] ${
        CLASSES_POR_PAGINA[tamanho] ?? CLASSES_POR_PAGINA.grande
      }`}
    >
      {lista.map((item, indice) => (
        <li
          key={chaveDoItem(item)}
          className="relative shrink-0 grow-0"
          style={{ flexBasis: FLEX_BASIS_SLOT_COM_RESPIRO }}
        >
          {/* Wrapper só da sombra, mesmo markup de FileiraDeCards.jsx: traça o
              retângulo `rounded-xl` (raio do AnimeCard) na borda do card. Fica
              DENTRO do SlotDeCard pra a sombra acompanhar a animação de entrada.
              `style` inline pelo mesmo motivo de CarrosselDestaques.jsx: o
              Tailwind v4 não gera sombra de 2 camadas começando pela cor de
              forma confiável. `comSombra=false` pula esse wrapper por completo
              (ver bloco de comentário acima). */}
          <SlotDeCard indice={indice} animada={comAnimacao}>
            {comSombra ? (
              <div className="rounded-xl" style={{ boxShadow: SOMBRA_SLIDE_ATIVO }}>
                {renderItem(item, indice)}
              </div>
            ) : (
              renderItem(item, indice)
            )}
          </SlotDeCard>
        </li>
      ))}
    </ul>
  );
}

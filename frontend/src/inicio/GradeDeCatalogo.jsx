import { SOMBRA_SLIDE_ATIVO } from './CarrosselDestaques.jsx';
import { CLASSE_GUTTER, CLASSES_POR_PAGINA, FLEX_BASIS_SLOT } from './tamanhoDeCard.js';
import { SlotDeCard } from './GradeDeCards.jsx';

// Grade de catálogo: irmã de FileiraDeCards.jsx que QUEBRA LINHA (`flex-wrap`)
// em vez de rolar. Compartilha o vocabulário de tamanho de ./tamanhoDeCard.js
// (mesmo `--por-pagina` por breakpoint via `CLASSES_POR_PAGINA`, mesmo
// `CLASSE_GUTTER`, mesmo `FLEX_BASIS_SLOT`, mesmo `p-[10px]` no slot), então o
// card sai com largura IDÊNTICA à da fileira por construção, não por
// coincidência aritmética.
//
// Sem setas / `onScroll` / `medirLimites` / `useRef`: não há trilha rolável
// pra medir. Nada aqui recorta o overflow (não há `overflow-x-auto` como na
// fileira) — o `scale-105` do card no hover transborda livre.
//
// Cada card leva a MESMA drop shadow do slide ativo do billboard
// (`SOMBRA_SLIDE_ATIVO`, de CarrosselDestaques.jsx — fonte única), igual às
// fileiras da Home: o usuário pediu a sombra em todos os cards. Ela mora num
// wrapper só-da-sombra DENTRO do `SlotDeCard`, então entra/some junto com a
// animação de entrada escalonada e fica ESTÁTICA no hover (o `scale-105` mora
// mais fundo, no wrapper do próprio AnimeCard/CartaoDeEstreia) — mesmo
// comportamento da fileira. Só aparece de fato sobre o fundo `#17171b` do
// container (o `<main>` de paginas/Galeria.jsx e o de paginas/Inicio.jsx).
//
// O respiro entre LINHAS quebradas vem do `gap-y-[34px]` da `<ul>` (row-gap:
// só o eixo cross, não afeta o cálculo de `flex-basis` no eixo principal),
// NÃO do `pb-[44px]` da fileira — aqui há várias linhas e a sombra de uma
// (desce ~46px abaixo da borda do card) não pode invadir a linha de baixo.
// `pb-[24px]` dá a folga da última linha; `pt-[22px]` o respiro título->cards.
//
// API espelha FileiraDeCards: `itens` + `renderItem(item, indice)` +
// `chaveDoItem(item)` + `tamanho`. O guard de lista vazia mora aqui (retorna
// `null`), o chamador não repete. NÃO leva `aria-labelledby` — o
// `<section aria-labelledby>` do chamador (paginas/Galeria.jsx) já rotula.
// `role="list"` explícito porque o Preflight do Tailwind v4 zera `list-style`
// e o VoiceOver larga a semântica de lista junto.
export default function GradeDeCatalogo({ itens, renderItem, chaveDoItem, tamanho = 'grande' }) {
  const lista = itens ?? [];
  if (lista.length === 0) return null;

  return (
    <ul
      role="list"
      className={`flex flex-wrap ${CLASSE_GUTTER} gap-y-[34px] pt-[22px] pb-[24px] ${
        CLASSES_POR_PAGINA[tamanho] ?? CLASSES_POR_PAGINA.grande
      }`}
    >
      {lista.map((item, indice) => (
        // `hover:z-10 focus-within:z-10` no `<li>`: numa grade justa (sem `gap`
        // horizontal, respiro só do `p-[10px]`) o card ampliado no hover
        // ficaria coberto pela borda do vizinho seguinte sem o z-index aqui — o
        // z-index do próprio AnimeCard fica preso em ancestrais transformados.
        <li
          key={chaveDoItem(item)}
          className="relative shrink-0 grow-0 p-[10px] hover:z-10 focus-within:z-10"
          style={{ flexBasis: FLEX_BASIS_SLOT }}
        >
          {/* Wrapper só da sombra, mesmo markup de FileiraDeCards.jsx: traça o
              retângulo `rounded-xl` (raio do AnimeCard) na borda do card. Fica
              DENTRO do SlotDeCard pra a sombra acompanhar a animação de entrada
              e ficar estática no hover (o `scale-105` mora mais fundo). `style`
              inline pelo mesmo motivo de CarrosselDestaques.jsx: o Tailwind v4
              não gera sombra de 2 camadas começando pela cor de forma
              confiável. */}
          <SlotDeCard indice={indice}>
            <div className="rounded-xl" style={{ boxShadow: SOMBRA_SLIDE_ATIVO }}>
              {renderItem(item, indice)}
            </div>
          </SlotDeCard>
        </li>
      ))}
    </ul>
  );
}

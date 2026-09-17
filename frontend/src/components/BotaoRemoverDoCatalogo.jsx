// Botão de remover do catálogo — compartilhado por components/AnimeCard.jsx e
// inicio/CartaoDeEstreia.jsx. `position: absolute` puro (`right-2 top-2`), sem
// opinião sobre onde é montado — quem chama decide o pai, e esse pai PRECISA
// ser a própria div da capa (`relative`, idealmente `overflow-hidden`), não um
// wrapper mais externo: um wrapper tipo `p-3 -m-3` (efeito de hover) entre este
// botão e a capa desalinha a posição (a margem negativa vertical colapsa com o
// pai — só cancela no eixo horizontal —, então o `top-2` fica alto demais e o
// ícone nasce boa parte fora da imagem). `CartaoDeEstreia.jsx` ancora aqui
// dentro da própria div da capa (card inerte, sem Link/button — nesting
// válido de cara). `AnimeCard.jsx` ancora no mesmo lugar apesar de ter
// Link/button: lá a navegação virou uma camada invisível `absolute inset-0`
// IRMÃ do conteúdo (não mais pai dele), então este botão nunca fica aninhado
// dentro de `<a>`/`<button>` — ver rationale completo em components/AnimeCard.jsx.
// `preventDefault` + `stopPropagation` evitam ativar o Link/button por baixo
// quando ele existir. A opacidade some por padrão e só aparece no hover do
// card (`group-hover/card:` — exige um ancestral com `group/card`, que ambos
// os cards têm no wrapper) ou no foco do próprio botão (`focus-visible:`) —
// nunca via `hidden`/DOM removido, senão ficaria inalcançável por Tab.
//
import { CircleMinus } from 'lucide-react';

// Ícone e posição copiados do botão "Remover" do Disney+ (seção "Continue
// Assistindo", inspecionado ao vivo em 2026-09-13): círculo-menos SEM chip de
// fundo (só o ícone, branco), ancorado no canto superior direito da capa. O
// `drop-shadow` é acréscimo nosso — o card lá tem um scrim que já dá contraste
// e o nosso não. `CircleMinus` (lucide-react, trocado a pedido do usuário,
// 2026-09-17, no lugar do SVG desenhado à mão que reproduzia o mesmo
// círculo-menos — Escada de Minimalismo, CLAUDE.md §4: a lib já tem o glifo
// pronto). `h-8 w-8` + `strokeWidth={2.5}` (mesmo tamanho/espessura do ícone
// de `inicio/CartaoDeEstreia.jsx::IconeSalvar` — pedido explícito do usuário
// pros dois botões saírem do mesmo tamanho). SEM `p-1` ao redor: o svg já
// mede 32px, igual ao `h-8` do `badgeAssistido` de `AnimeCard.jsx` — qualquer
// padding aqui infla a caixa além dos 32px e desalinha o centro vertical dos
// dois (badge exatamente `h-8`, botão viraria `h-8` + `p-1` dobrado = 40px),
// mesmo os dois começando do mesmo `top-2`.
export default function BotaoRemoverDoCatalogo({ titulo, aoRemover }) {
  return (
    <button
      type="button"
      onClick={(evento) => {
        evento.preventDefault();
        evento.stopPropagation();
        aoRemover();
      }}
      aria-label={`Remover ${titulo} do catálogo`}
      className="absolute right-2 top-2 z-10 rounded-full text-white opacity-0 outline-none drop-shadow-[0_1px_3px_rgba(0,0,0,0.9)] transition-colors duration-200 hover:text-white/80 focus-visible:opacity-100 group-hover/card:opacity-100 cursor-pointer"
    >
      <CircleMinus aria-hidden="true" focusable="false" strokeWidth={2.5} className="h-8 w-8" />
    </button>
  );
}

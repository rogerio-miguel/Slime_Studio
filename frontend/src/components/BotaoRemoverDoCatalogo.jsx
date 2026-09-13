// Botão de remover do catálogo — compartilhado por components/AnimeCard.jsx e
// inicio/CartaoDeEstreia.jsx. `position: absolute` puro (`right-2 top-2`), sem
// opinião sobre onde é montado — quem chama decide o pai, e esse pai PRECISA
// ser a própria div da capa (`relative`, idealmente `overflow-hidden`), não um
// wrapper mais externo: um wrapper tipo `p-3 -m-3` (efeito de hover) entre este
// botão e a capa desalinha a posição (a margem negativa vertical colapsa com o
// pai — só cancela no eixo horizontal —, então o `top-2` fica alto demais e o
// ícone nasce boa parte fora da imagem). `CartaoDeEstreia.jsx` já ancora aqui
// dentro da própria div da capa (card inerte, sem Link/button — nesting
// válido). `AnimeCard.jsx` ainda ancora como IRMÃO do Link/button (button
// dentro de `<a>` é inválido, não dá pra aninhar) — mesmo risco de
// desalinhamento vertical ali, não corrigido nesta passada por exigir
// reestruturar esse card sem quebrar a regra de nesting.
// `preventDefault` + `stopPropagation` evitam ativar o Link/button por baixo
// quando ele existir. A opacidade some por padrão e só aparece no hover do
// card (`group-hover/card:` — exige um ancestral com `group/card`, que ambos
// os cards têm no wrapper) ou no foco do próprio botão (`focus-visible:`) —
// nunca via `hidden`/DOM removido, senão ficaria inalcançável por Tab.
//
// Ícone e posição copiados do botão "Remover" do Disney+ (seção "Continue
// Assistindo", inspecionado ao vivo em 2026-09-13): círculo-menos SEM chip de
// fundo (só o ícone, branco), ancorado no canto superior direito da capa. O
// `drop-shadow` é acréscimo nosso — o card lá tem um scrim que já dá contraste
// e o nosso não. `h-6 w-6` + `strokeWidth="2.5"` (mesmo tamanho/espessura do
// ícone de `inicio/CartaoDeEstreia.jsx::IconeSalvar` — pedido explícito do
// usuário pros dois botões saírem do mesmo tamanho): `p-1` ao redor preserva
// uma caixa de 32px (referência de altura pro `badgeAssistido` de
// `AnimeCard.jsx`, que usa `h-8`), mesmo sem fundo visível.
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
      className="absolute right-2 top-2 z-10 rounded-full p-1 text-white opacity-0 outline-none drop-shadow-[0_1px_3px_rgba(0,0,0,0.9)] transition-colors duration-200 hover:text-red-400 focus-visible:opacity-100 group-hover/card:opacity-100"
    >
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" className="h-6 w-6">
        <circle cx="12" cy="12" r="9" />
        <line x1="8" y1="12" x2="16" y2="12" strokeLinecap="round" />
      </svg>
    </button>
  );
}

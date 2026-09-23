import { IconePlay } from '../player/Icones.jsx';

// Wordmark "SLIME STUDIO" construído do zero (não é mais uma recriação do
// PNG antigo em assets/logo4.png, nem o "ANIME STUDIO" que veio depois —
// trocado pro nome oficial do projeto, o mesmo do mascote em
// assets/logo2.png). Fonte padrão do projeto (nenhuma importada: Tailwind
// cai no stack sans default), caixa alta, "SLIME" maior que "STUDIO". Sem
// o selo do mascote (`assets/icone-Slime_Studio2.png`) do lado — removido
// a pedido do usuário durante os testes desta animação; só o wordmark em
// texto ficou.
//
// SLIME fica sempre por extenso. STUDIO troca pro ícone sólido de play
// (`IconePlay`, mesmo componente da barra de controles do player,
// `player/Icones.jsx`) quando `colapsada` vira true — referência
// anthropic.com (pedido do usuário, 2026-09-23): lá o wordmark do header
// ("ANTHROPIC"→"A\") troca de uma vez com uma `transition` CSS curta ao
// passar de um limiar pequeno de scroll, não acompanhando o pixel like um
// progresso contínuo. Testamos antes um dissolve letra-a-letra (S/T/U/I/O
// sumindo em janelas próprias, D virando ícone) — tinha mais
// "personalidade", mas o usuário pediu pra trocar pelo binário mais limpo
// da referência.
//
// `max-width` + `opacity` em vez de só opacity: precisa recolher a
// LARGURA reservada também, senão sobra um vão vazio no lugar de STUDIO
// (mesmo problema que o dissolve letra-a-letra teve antes com `width`
// fixo != largura real do conteúdo — aqui os dois lados (texto e ícone)
// declaram seu PRÓPRIO max-width generoso o bastante pro conteúdo real,
// nunca um valor arbitrário menor). `overflow-hidden` em cada um evita
// que o conteúdo vaze durante a transição. O max-width do ícone é em PX
// fixo (`40px`), não `em` — esse `<span>` não herda `text-3xl` (só o
// STUDIO tem), então um `em` ali resolvia contra os 16px padrão do
// documento e cortava o ícone bem antes do tamanho real pedido nas props
// do `IconePlay`.
//
// `IconePlay` já nasce `aria-hidden` via `propsBase` de Icones.jsx, então
// o texto "STUDIO" continua a única coisa lida por leitor de tela, mesmo
// com opacity 0 depois de rolar.
export default function LogoSlimeStudio({ className = '', colapsada = false }) {
  return (
    <div className={`flex items-center gap-0.5 uppercase leading-none ${className}`}>
      <span className="font-extrabold tracking-tight text-white text-3xl">SLIME</span>
      <span
        className={`overflow-hidden whitespace-nowrap font-bold tracking-wide text-neon text-3xl transition-all duration-[400ms] ease-[cubic-bezier(0.4,0,0.2,1)] motion-reduce:transition-none ${
          colapsada ? 'max-w-0 opacity-0' : 'max-w-[8em] opacity-100'
        }`}
      >
        STUDIO
      </span>
      <span
        className={`flex items-center overflow-hidden transition-all duration-[400ms] ease-[cubic-bezier(0.4,0,0.2,1)] motion-reduce:transition-none ${
          colapsada ? 'max-w-[40px] opacity-100' : 'max-w-0 opacity-0'
        }`}
      >
        <IconePlay fill="currentColor" stroke="none" width={32} height={32} />
      </span>
    </div>
  );
}

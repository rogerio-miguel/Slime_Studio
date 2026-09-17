// Adapter fino sobre lucide-react (Escada de Minimalismo, CLAUDE.md §4: uma
// dependência já instalada/adotada resolve, não vale a pena manter SVG
// desenhado à mão) — mantém os MESMOS nomes/API de antes (IconePlay,
// IconeVolume com `nivel`, IconeSkip10 com `direcao`, etc.) para que
// BarraDeControles/MenuDeConfiguracoes/LinhaDeEpisodio não precisem mudar
// nenhuma chamada, só a implementação por trás muda. Continua exportando
// componentes aria-hidden/focusable=false por padrão: o texto acessível vem
// do aria-label do <button> que os envolve.
import { Play, Pause, Headphones, Maximize, RotateCcw, RotateCw, Settings } from 'lucide-react';

const propsBase = {
  width: 18,
  height: 18,
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 2,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
  'aria-hidden': 'true',
  focusable: 'false',
};

export function IconePlay(props) {
  return <Play {...propsBase} {...props} />;
}

export function IconePausa(props) {
  return <Pause {...propsBase} {...props} />;
}

// Exceção deliberada ao adapter de lucide (Escada de Minimalismo, CLAUDE.md
// §4, passo 6: nada pronto resolve) — a lib não tem um glifo que MORPHA
// entre mudo/baixo/alto, só 3 ícones estáticos (Volume2/Volume1/VolumeX)
// trocados por inteiro, o que descartava a transição suave pedida (igual ao
// ícone de volume do YouTube ao arrastar a barra). Volta ao desenho à mão:
// um <svg> só, corpo do alto-falante fixo, e os 2 arcos + o X entram/saem
// via opacity+scale — CSS anima a MUDANÇA de estado (não o valor contínuo
// do volume), o que já basta pra sensação de morph do YouTube porque
// `nivel` (3 estados) muda a cada vez que o arrasto cruza um limiar.
const classeArco = 'origin-center transition-[opacity,transform] duration-150 ease-out motion-reduce:transition-none';

export function IconeVolume({ nivel = 'alto', ...props }) {
  return (
    <svg viewBox="0 0 24 24" {...propsBase} {...props}>
      <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" />
      <path
        d="M15.54 8.46a5 5 0 0 1 0 7.07"
        className={classeArco}
        style={{ opacity: nivel === 'mudo' ? 0 : 1, transform: nivel === 'mudo' ? 'scale(0.6)' : 'scale(1)' }}
      />
      <path
        d="M19.07 4.93a10 10 0 0 1 0 14.14"
        className={classeArco}
        style={{ opacity: nivel === 'alto' ? 1 : 0, transform: nivel === 'alto' ? 'scale(1)' : 'scale(0.6)' }}
      />
      <g
        className={classeArco}
        style={{ opacity: nivel === 'mudo' ? 1 : 0, transform: nivel === 'mudo' ? 'scale(1)' : 'scale(0.6)' }}
      >
        <line x1="23" y1="9" x2="17" y2="15" />
        <line x1="17" y1="9" x2="23" y2="15" />
      </g>
    </svg>
  );
}

export function IconeFones(props) {
  return <Headphones {...propsBase} {...props} />;
}

export function IconeTelaCheia(props) {
  return <Maximize {...propsBase} {...props} />;
}

export function IconeEngrenagem(props) {
  return <Settings {...propsBase} {...props} />;
}

// Seta circular (RotateCcw/RotateCw) com o "10" composto DENTRO do círculo
// — não mais um <span> empilhado abaixo do ícone (removido a pedido do
// usuário, 2026-09-17: primeiro pro trio virar o glifo de player só
// SkipBack/SkipForward, depois revertido pro par de seta circular original,
// mas com o número sobreposto ao próprio glifo, tipo o "replay 10"/
// "forward 10" do YouTube). `<span>` wrapper (não <svg> — o número é texto,
// não caminho vetorial) do tamanho exato de `width`/`height`, com o ícone e
// o texto empilhados via `absolute inset-0` um sobre o outro; o vão vazio no
// centro do traço do RotateCcw/RotateCw (a seta só ocupa o anel externo)
// sobra espaço de sobra pro número sem colidir com o traço.
export function IconeSkip10({ direcao = 'frente', width = 18, height = 18, ...props }) {
  const Icone = direcao === 'tras' ? RotateCcw : RotateCw;
  return (
    <span
      aria-hidden="true"
      style={{ width, height }}
      className="relative inline-flex shrink-0 items-center justify-center"
    >
      <Icone {...propsBase} width={width} height={height} {...props} />
      <span
        style={{ fontSize: Math.round(Number(width) * 0.34) }}
        className="absolute inset-0 flex items-center justify-center pt-px font-bold leading-none text-white"
      >
        10
      </span>
    </span>
  );
}

// Mesmo triângulo do botão de play (IconePlay, mesmo componente `Play` da
// lib) pro botão "Avançar 1m30" (BarraDeControles.jsx, grupo secundário —
// HUD/config/tela cheia) — pedido explícito do usuário, 2026-09-17, no
// lugar do glifo SkipForward de antes. `fill="currentColor"`: mesmo
// triângulo maciço do play, não outline.
export function IconeAvancarPlayer(props) {
  return <Play {...propsBase} fill="currentColor" {...props} />;
}

// Adapter fino sobre lucide-react (Escada de Minimalismo, CLAUDE.md §4: uma
// dependência já instalada/adotada resolve, não vale a pena manter SVG
// desenhado à mão) — mantém os MESMOS nomes/API de antes (IconePlay,
// IconeVolume com `nivel`, IconeSkip10 com `direcao`, etc.) para que
// BarraDeControles/MenuDeConfiguracoes/LinhaDeEpisodio não precisem mudar
// nenhuma chamada, só a implementação por trás muda. Continua exportando
// componentes aria-hidden/focusable=false por padrão: o texto acessível vem
// do aria-label do <button> que os envolve.
import { Play, Pause, Headphones, Maximize, Settings } from 'lucide-react';

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

// `d` dos dois <path> que compõem RotateCcw/RotateCw no lucide-react (arco +
// seta são SEPARADOS) — copiados à mão (mesma exceção deliberada de
// IconeVolume acima: Escada de Minimalismo, CLAUDE.md §4 passo 6, nada
// pronto resolve "pintar" só uma parte de um ícone de terceiro) pra poder
// desenhar uma segunda cópia em neon por cima, com stroke-dasharray.
const CAMINHOS_SKIP = {
  tras: { arco: 'M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8', seta: 'M3 3v5h5' },
  frente: { arco: 'M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8', seta: 'M21 3v5h-5' },
};

// Proporção do traço TOTAL (arco + seta) que pertence só ao arco — calculada
// geometricamente uma vez a partir do `d` acima (arco: ~270° de raio 9 +
// ~44° de raio 9,75 + um segmento reto ≈53 unidades; seta: dois segmentos de
// 5 ≈10 unidades; total ≈63 → 53/63), não medida em runtime via
// getTotalLength(): a geometria dos dois ícones é fixa entre renders, medir
// de novo a cada montagem seria trabalho sem benefício. É o que faz o
// "pintar" andar na mesma velocidade ao longo do arco e da seta, mesmo os
// dois sendo <path> separados com pathLength normalizado por igual.
const FRACAO_ARCO_SKIP = 53 / 63;

// Seta circular (RotateCcw/RotateCw) com o "10"/"90" compostos DENTRO do
// círculo — não mais um <span> empilhado abaixo do ícone (removido a pedido
// do usuário, 2026-09-17). `<span>` wrapper (não <svg> — o número é texto,
// não caminho vetorial) do tamanho exato de `width`/`height`, com o ícone(s)
// e o texto empilhados via `absolute inset-0` um sobre o outro.
//
// `progresso` (0-1, de useSegurarParaPular.js) substitui o anel fino que
// existia ao redor do botão (AnelDeSegurar, removido de BarraDeControles.jsx,
// pedido do usuário 2026-09-24): uma SEGUNDA cópia do próprio ícone, em neon,
// sobreposta à branca, com o traço "pintado" progressivamente do início do
// arco até a ponta da seta via strokeDasharray/strokeDashoffset.
// `pathLength="1"` normaliza cada <path> (arco e seta têm comprimento real
// bem diferente) pra que o dasharray de 0 a 1 funcione igual nos dois; só a
// PROPORÇÃO do progresso entre eles (FRACAO_ARCO_SKIP) precisa vir de fora.
// O "10"→"90" faz crossfade contínuo (opacity+scale) junto — mesma técnica
// de IconeVolume acima, só que ligada a um valor contínuo em vez de um
// estado de 3 níveis.
export function IconeSkip10({ direcao = 'frente', width = 18, height = 18, progresso = 0, ...props }) {
  const { arco, seta } = CAMINHOS_SKIP[direcao];
  const progressoArco = Math.min(1, progresso / FRACAO_ARCO_SKIP);
  const progressoSeta = Math.min(1, Math.max(0, (progresso - FRACAO_ARCO_SKIP) / (1 - FRACAO_ARCO_SKIP)));
  return (
    <span
      aria-hidden="true"
      style={{ width, height }}
      className="relative inline-flex shrink-0 items-center justify-center"
    >
      <svg viewBox="0 0 24 24" {...propsBase} width={width} height={height} {...props}>
        <path d={arco} />
        <path d={seta} />
      </svg>
      {progresso > 0 && (
        <svg viewBox="0 0 24 24" {...propsBase} width={width} height={height} {...props} className="absolute inset-0 text-neon">
          <path d={arco} pathLength="1" strokeDasharray="1" strokeDashoffset={1 - progressoArco} />
          <path d={seta} pathLength="1" strokeDasharray="1" strokeDashoffset={1 - progressoSeta} />
        </svg>
      )}
      <span
        style={{ fontSize: Math.round(Number(width) * 0.34) }}
        className="absolute inset-0 font-bold leading-none text-white"
      >
        <span
          style={{ opacity: 1 - progresso, transform: `scale(${0.7 + 0.3 * (1 - progresso)})` }}
          className="absolute inset-0 flex items-center justify-center pt-px"
        >
          10
        </span>
        <span
          style={{ opacity: progresso, transform: `scale(${0.7 + 0.3 * progresso})` }}
          className="absolute inset-0 flex items-center justify-center pt-px"
        >
          90
        </span>
      </span>
    </span>
  );
}

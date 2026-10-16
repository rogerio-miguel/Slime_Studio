import { usePrefersReducedMotion } from '../../inicio/usePrefersReducedMotion';
import {
  QUADRO_AGACHADO,
  QUADRO_ESTICADO,
  QUADRO_ESPALHADO,
  QUADRO_ESPALHADO_DE_OLHOS_FECHADOS,
  QUADRO_MURCHO,
  QUADRO_OLHOS_FECHADOS,
  QUADRO_REPOUSO,
} from './quadros';
import { usePiscar } from './usePiscar';

export function QuadroDoSlime({ partes, className, atraso }) {
  return (
    <g className={className} style={atraso}>
      {partes.map(({ letra, classe, d }) => (
        <path key={letra} d={d} className={classe} />
      ))}
    </g>
  );
}

// Poses do mascote fora da navbar (estados vazios, erro, carregando). Sempre na
// cor neon (pedido do usuário, 2026-10-15): `text-neon` mora aqui e não há prop
// de cor. A entrada com queda do logo fica em `LogoSlimeStudio.jsx`.
//
//  - `repouso`: parado, pisca de tempos em tempos.
//  - `vazio`: espalhado numa poça, sem os fones, de olhos baixos; pisca de tempos
//    em tempos (estado vazio).
//  - `murcho`: baixo e de olhos inclinados, parado (erro).
//  - `pulando`: pulinho em laço (carregando/espera longa).
//
// `tamanho` em px: múltiplos de 16 dão células inteiras (64 = 4px por célula).
// O pulo sai da grade 16×16 pra cima e a poça do `vazio` passa dela pelos lados
// (4 células); o SVG tem `overflow: visible` pra isso: reserve folga no layout
// de quem usa.
const POSES = ['repouso', 'vazio', 'murcho', 'pulando'];

const CLASSE_PULO = {
  repouso: 'animate-[slime-pulo-repouso_1000ms_step-end_infinite]',
  agachado: 'animate-[slime-pulo-agachado_1000ms_step-end_infinite]',
  esticado: 'animate-[slime-pulo-esticado_1000ms_step-end_infinite]',
};

function Repouso({ animar }) {
  const piscando = usePiscar(animar);
  return <QuadroDoSlime partes={piscando ? QUADRO_OLHOS_FECHADOS : QUADRO_REPOUSO} />;
}

// Os três quadros ficam montados e o CSS alterna a opacidade de cada um, igual à
// entrada do logo. Sem animação (movimento reduzido) sobra só o repouso, e os
// outros nascem invisíveis (`opacity-0`).
function Vazio({ animar }) {
  const piscando = usePiscar(animar);
  return (
    <QuadroDoSlime
      partes={piscando ? QUADRO_ESPALHADO_DE_OLHOS_FECHADOS : QUADRO_ESPALHADO}
    />
  );
}

function Pulando({ animar }) {
  const classe = (chave, base = '') => `${base} ${animar ? CLASSE_PULO[chave] : ''}`;
  return (
    <>
      <QuadroDoSlime partes={QUADRO_REPOUSO} className={classe('repouso')} />
      <QuadroDoSlime partes={QUADRO_AGACHADO} className={classe('agachado', 'opacity-0')} />
      <QuadroDoSlime partes={QUADRO_ESTICADO} className={classe('esticado', 'opacity-0')} />
    </>
  );
}

export default function MascoteSlime({ pose = 'repouso', tamanho = 64, rotulo, className = '' }) {
  const movimentoReduzido = usePrefersReducedMotion();
  const animar = !movimentoReduzido;
  if (!POSES.includes(pose)) throw new Error(`MascoteSlime: pose desconhecida "${pose}"`);
  return (
    <svg
      viewBox="0 0 16 16"
      width={tamanho}
      height={tamanho}
      fill="currentColor"
      shapeRendering="crispEdges"
      style={{ overflow: 'visible' }}
      className={`text-neon ${className}`}
      // Decorativo por padrão: quem usa põe o texto do estado ao lado.
      {...(rotulo ? { role: 'img', 'aria-label': rotulo } : { 'aria-hidden': true, focusable: false })}
    >
      {pose === 'repouso' && <Repouso animar={animar} />}
      {pose === 'vazio' && <Vazio animar={animar} />}
      {pose === 'murcho' && <QuadroDoSlime partes={QUADRO_MURCHO} />}
      {pose === 'pulando' && <Pulando animar={animar} />}
    </svg>
  );
}

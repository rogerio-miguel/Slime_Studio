import { useRef } from 'react';
import useTransicaoParaIcone from './useTransicaoParaIcone';
import { USA_ESTICAR_FUSAO } from './variantesMorphLogo';

// Letra que VIAJA de verdade (posição + forma) até virar a peça do ícone —
// ver `useTransicaoParaIcone.js` pro porquê do FLIP manual em vez de CSS
// transition simples. Tamanho fixo 32×32 (mesmo do `IconeClaquete`) e
// viewBox `0 0 24 24` igual: o `transform` (aplicado pelo hook) é quem faz
// o elemento PARECER do tamanho/posição da letra durante a fase "texto" —
// o box em si nunca muda de tamanho real, só sua transformação.
export default function LetraViajante({
  origemRef,
  slimeRef,
  letra,
  dLetra,
  dIcone,
  bboxLetra,
  ativo,
  visivel,
  atrasoMs,
  instantaneo,
}) {
  const overlayRef = useRef(null);
  const esticoRef = useRef(null);
  const pathRef = useRef(null);

  useTransicaoParaIcone({
    origemRef,
    slimeRef,
    overlayRef,
    esticoRef,
    pathRef,
    letra,
    dLetra,
    dIcone,
    bboxLetra,
    ativo,
    visivel,
    atrasoMs,
    instantaneo,
  });

  return (
    <div
      ref={overlayRef}
      className="text-neon"
      style={{ position: 'fixed', width: 32, height: 32, transformOrigin: '0 0', willChange: 'transform' }}
      aria-hidden="true"
    >
      {/* `esticoRef`: camada separada do FLIP de posição/tamanho (overlay
          acima) — carrega só o squash-and-stretch da técnica 'esticar-fusao'
          (`variantesMorphLogo.js`; gosma esticando na direção do trajeto),
          atualizado por frame no mesmo rAF que já desenha o morph de forma
          (`useTransicaoParaIcone.js`). Fica inerte (transform 'none') em
          qualquer outra técnica ativa. `transformOrigin: 50% 50%` (centro),
          diferente do `0 0` do overlay: o FLIP precisa de origem no canto
          pra combinar com a matemática de translate; o esticar precisa de
          origem no centro pra "puxar" a letra pros dois lados, não empurrar
          ela pro canto. */}
      <div ref={esticoRef} style={{ width: '100%', height: '100%', transformOrigin: '50% 50%' }}>
        <svg
          viewBox="0 0 24 24"
          width="32"
          height="32"
          style={{
            overflow: 'visible',
            // `lighten` é a "fusão visual" da técnica 'esticar-fusao' —
            // letras que convergem pro mesmo destino somam brilho em vez de
            // uma tampar a outra. Sem efeito em qualquer outra técnica.
            mixBlendMode: USA_ESTICAR_FUSAO ? 'lighten' : 'normal',
          }}
          focusable="false"
        >
          <path ref={pathRef} d={ativo ? dIcone : dLetra} fill="currentColor" />
        </svg>
      </div>
    </div>
  );
}

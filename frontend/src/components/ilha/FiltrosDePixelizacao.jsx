// Filtros SVG que `pixelarTroca` anima: A pixeliza o nó que sai, B o que entra.
// Célula de 2px é o estado neutro. `margem` (% do nó) alarga a região do filtro
// pra o que passa da caixa — a lâmina aberta da claquete — não ser cortado.
export default function FiltrosDePixelizacao({ svgRef, sufixo, margem = 0 }) {
  return (
    <svg
      ref={svgRef}
      width="0"
      height="0"
      aria-hidden="true"
      focusable="false"
      className="pointer-events-none absolute"
    >
      {['A', 'B'].map((letra) => (
        <filter
          key={letra}
          id={`pix${letra}-${sufixo}`}
          x={`${-margem}%`}
          y={`${-margem}%`}
          width={`${100 + 2 * margem}%`}
          height={`${100 + 2 * margem}%`}
        >
          <feFlood data-p="flood" x="0" y="0" width="2" height="2" />
          <feComposite data-p="comp" width="2" height="2" />
          <feTile result="celulas" />
          <feComposite in="SourceGraphic" in2="celulas" operator="in" />
          <feMorphology data-p="morph" operator="dilate" radius="1" />
        </filter>
      ))}
    </svg>
  );
}

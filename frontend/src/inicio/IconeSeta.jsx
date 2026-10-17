// Chevron de navegação — MESMO modelo do AnimeFire (glyph lucide
// `chevron-left`/`right`, sem fundo nem círculo, só o traço). SEM a animação de
// "empurrão" do chevron que o AnimeFire faz no hover: aqui só o modelo; a troca
// de cor no hover fica na classe do <button> que envolve o ícone.
//
// Compartilhado pelo hero (CarrosselDestaques.jsx) e pelas fileiras
// horizontais (FileiraDeCards.jsx) — as duas setas do bloco `src/inicio/`.
// `w-[4.1vw]` com teto/piso: acompanha a viewport como no AnimeFire, sem
// virar minúsculo no mobile nem gigante no ultrawide.
export default function IconeSeta({ direcao }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      className="w-[4.1vw] min-w-8 max-w-16"
    >
      <path d={direcao === 'esquerda' ? 'm15 18-6-6 6-6' : 'm9 18 6-6-6-6'} />
    </svg>
  );
}

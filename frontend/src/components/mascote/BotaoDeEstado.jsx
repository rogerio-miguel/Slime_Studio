// Botão de ação do `EstadoComMascote` e do "Mostrar mais" da Home: pílula
// branca do CTA do hero (`CLASSE_BOTAO_HERO`), no tamanho de `h-12` — o hero
// escala até `lg:h-14`, grande demais pra um estado vazio.
export default function BotaoDeEstado({ onClick, children, ...resto }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="inline-flex h-12 cursor-pointer items-center gap-2 rounded-xl bg-white px-8 font-bold text-[#17171b] outline-none transition hover:brightness-90 focus-visible:ring-2 focus-visible:ring-neon focus-visible:ring-offset-2 focus-visible:ring-offset-black motion-reduce:transition-none"
      {...resto}
    >
      {children}
    </button>
  );
}

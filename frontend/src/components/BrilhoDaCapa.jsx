// Glow ambiente do hover dos cards de pôster (AnimeCard, CartaoDeEstreia): uma
// segunda `<img>` da própria capa, borrada e saturada, `-z-10` atrás do pôster.
// IRMÃ do pôster, não filha: o pôster tem `overflow-hidden` e cortaria o brilho
// que precisa vazar. Maior que o pôster (`scale-[1.12]`, senão ele a cobre
// inteira e sobram ~10px de borrão) e levemente deslocada pra baixo
// (`translate-y-[3%]`). A fileira da Home recorta no eixo Y (`overflow-x-auto`
// vira auto nos dois eixos): por isso a trilha de FileiraDeCards.jsx tem
// padding grande compensado por margem negativa, pra o glow vazar da seção.
// `invisible` fora do hover pra o navegador não compor dezenas de imagens
// borradas à toa; `transition-[opacity,visibility]` mantém o fade-out visível
// até o fim. Reage a `group-hover/card` — o pai precisa ser o `group/card` — e
// só fica ATRÁS dos vizinhos por causa do `isolate` + regra `:has(li:hover)` da
// `<ul>` de FileiraDeCards/GradeDeCatalogo.
// `classeAspecto`: proporção do pôster que o glow acompanha (2:3 por padrão;
// miniatura de episódio passa `aspect-video`). Literal no call site, pro Tailwind extrair.
export default function BrilhoDaCapa({ capa, classeAspecto = 'aspect-[2/3]' }) {
  return (
    <img
      src={capa}
      alt=""
      aria-hidden="true"
      loading="lazy"
      className={`pointer-events-none invisible absolute inset-x-0 top-0 -z-10 ${classeAspecto} w-full scale-[1.12] translate-y-[3%] rounded-2xl object-cover opacity-0 blur-xl brightness-[1.15] saturate-[1.8] transition-[opacity,visibility] duration-300 ease-out group-hover/card:visible group-hover/card:opacity-100 motion-reduce:transition-none`}
    />
  );
}

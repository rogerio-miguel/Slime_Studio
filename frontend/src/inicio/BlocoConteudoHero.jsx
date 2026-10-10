import { useEffect, useRef, useState } from 'react';
import { PADDING_TITULO } from './tamanhoDeCard.js';

// Esqueleto do bloco de conteúdo do hero (pills → título/subtítulo → sinopse →
// meta → CTA opcional) — extraído de inicio/CarrosselDestaques.jsx e
// paginas/PaginaDoAnime.jsx, que montavam o MESMO empilhamento em paralelo
// (comentário histórico dos dois arquivos já dizia "espelha o carrossel").
// Cada chamador continua dono do PRÓPRIO conteúdo (nível de heading, ref de
// foco, Link de navegação, pills, CTA) — este componente só garante que a
// ordem e a geometria comum (gap, padding lateral) não divirjam de novo.
// `className`: classes de POSICIONAMENTO específicas do contexto (o carrossel
// é `absolute` dentro do slide + `max-w`/`pb` responsivos; a página do anime é
// `relative` — precisa pintar acima da arte/gradiente `absolute` do header,
// ver comentário em PaginaDoAnime.jsx — + `pb-8 pt-24`). `paddingInline` vai
// sempre aqui (mesmo gutter percentual de Home/Galeria, ./tamanhoDeCard.js).
// `acaoSinopse`: nó (botão "ler sinopse completa") renderizado logo abaixo da
// sinopse SÓ quando o `line-clamp` realmente cortou texto — sem isso, uma
// sinopse curta ganharia um botão que não leva a nada. Mede com
// `ResizeObserver` (o corte muda com a largura da janela).
export default function BlocoConteudoHero({
  className,
  pills,
  titulo,
  tituloSecundario,
  extraTitulo,
  sinopse,
  acaoSinopse,
  ocultarSinopseNoMobile = false,
  meta,
  metaExtra,
  cta,
  // `compacto`: menos espaço entre as seções do bloco (Top 10).
  compacto = false,
  // Handlers do contêiner (ex. `onMouseEnter`/`onMouseLeave` do carrossel, que
  // pausa o auto-avanço só com o mouse em cima do bloco).
  ...propsDoContainer
}) {
  const sinopseRef = useRef(null);
  const [sinopseCortada, setSinopseCortada] = useState(false);

  useEffect(() => {
    const elemento = sinopseRef.current;
    if (!elemento) return undefined;
    // O observer dispara uma vez ao `observe`, então não há medição avulsa aqui.
    const observador = new ResizeObserver(() => {
      setSinopseCortada(elemento.scrollHeight > elemento.clientHeight + 1);
    });
    observador.observe(elemento);
    return () => observador.disconnect();
  }, [sinopse]);

  return (
    <div
      className={`flex flex-col items-start ${compacto ? 'gap-1.5' : 'gap-4'} ${className ?? ''}`}
      style={{ paddingInline: PADDING_TITULO }}
      {...propsDoContainer}
    >
      {pills && pills.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">{pills}</div>
      )}

      <div>
        {titulo}
        {tituloSecundario}
        {extraTitulo}
      </div>

      {sinopse && (
        <div className={ocultarSinopseNoMobile ? 'hidden sm:block' : undefined}>
          <p ref={sinopseRef} className="line-clamp-2 max-w-2xl text-sm font-bold text-ink-muted sm:text-base">
            {sinopse}
          </p>
          {sinopseCortada && acaoSinopse}
        </div>
      )}

      {(meta || metaExtra) && (
        <div className="flex flex-col items-start gap-1">
          {meta && <p className="text-xs text-ink-muted sm:text-sm">{meta}</p>}
          {metaExtra}
        </div>
      )}

      {cta}
    </div>
  );
}

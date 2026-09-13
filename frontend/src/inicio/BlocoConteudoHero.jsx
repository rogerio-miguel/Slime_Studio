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
export default function BlocoConteudoHero({
  className,
  pills,
  titulo,
  tituloSecundario,
  extraTitulo,
  sinopse,
  ocultarSinopseNoMobile = false,
  meta,
  metaExtra,
  cta,
}) {
  return (
    <div
      className={`flex flex-col items-start gap-4 ${className ?? ''}`}
      style={{ paddingInline: PADDING_TITULO }}
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
          <p className="line-clamp-3 max-w-2xl text-sm text-ink-muted sm:text-base">{sinopse}</p>
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

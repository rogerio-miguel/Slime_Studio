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
// `ResizeObserver` (o corte muda com a largura da janela). Pode ser uma função
// `(caracteresLidos) => nó`: recebe quantos caracteres da sinopse o clamp deixou
// visíveis, pro painel da sinopse completa marcar onde o leitor parou.

const ESPACO = /\s/;

// Quantos caracteres do texto cabem no `line-clamp` do elemento. As linhas
// cortadas continuam no layout (só o `overflow` as esconde), então dá pra
// perguntar ao navegador onde cada caractere caiu e achar a fronteira por busca
// binária. Espaço de quebra de linha não tem retângulo próprio — usa o último
// caractere visível antes dele. Recua até o fim de palavra: o "…" do clamp
// come as últimas letras da última linha.
function caracteresVisiveis(elemento) {
  const no = elemento.firstChild;
  if (no?.nodeType !== Node.TEXT_NODE) return null;
  const texto = no.data;
  const limite = elemento.getBoundingClientRect().bottom + 1;
  const intervalo = document.createRange();

  const fundoDe = (indice) => {
    let i = indice;
    while (i > 0 && ESPACO.test(texto[i])) i -= 1;
    intervalo.setStart(no, i);
    intervalo.setEnd(no, i + 1);
    const retangulos = intervalo.getClientRects();
    return retangulos.length > 0 ? retangulos[retangulos.length - 1].bottom : 0;
  };

  let baixo = 0;
  let alto = texto.length;
  while (baixo < alto) {
    const meio = Math.ceil((baixo + alto) / 2);
    if (fundoDe(meio - 1) <= limite) baixo = meio;
    else alto = meio - 1;
  }
  if (baixo >= texto.length) return null;
  const fimDePalavra = texto.lastIndexOf(' ', baixo - 1);
  return fimDePalavra > 0 ? fimDePalavra : null;
}

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
  const [caracteresLidos, setCaracteresLidos] = useState(null);

  useEffect(() => {
    const elemento = sinopseRef.current;
    if (!elemento) return undefined;
    // O observer dispara uma vez ao `observe`, então não há medição avulsa aqui.
    const observador = new ResizeObserver(() => {
      const cortada = elemento.scrollHeight > elemento.clientHeight + 1;
      setSinopseCortada(cortada);
      setCaracteresLidos(cortada ? caracteresVisiveis(elemento) : null);
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
          {sinopseCortada &&
            (typeof acaoSinopse === 'function' ? acaoSinopse(caracteresLidos) : acaoSinopse)}
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

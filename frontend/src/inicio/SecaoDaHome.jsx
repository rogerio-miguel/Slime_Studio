import { useId } from 'react';
import { PADDING_TITULO } from './tamanhoDeCard.js';

// Cabeçalho das seções PRINCIPAIS da Home (continuar, Top 10, lançamentos,
// estreias): título grande + linha de apoio, no mesmo gutter de 3.7% das
// fileiras. As fileiras temáticas seguem com o título pequeno de
// `FileiraDeCards` — a diferença de escala é de propósito, marca o que é
// seção-âncora e o que é descoberta.
// `cabecalhoOculto`: some só visualmente (`sr-only`) — o `<section>` segue nomeado
// pelo h2 pra leitor de tela, e a seção não perde o landmark. Sem cabeçalho também
// não há o `pt-8` de respiro do título; o espaçamento fica com quem usa.
export default function SecaoDaHome({ titulo, descricao, cabecalhoOculto = false, children }) {
  const idTitulo = useId();
  return (
    // `pt-8`: respiro extra entre seções principais (some ao `space-y-14` do
    // contêiner em `paginas/Inicio.jsx`) — com o título grande, só o `space-y`
    // deixava uma seção colada na anterior, em especial depois do coverflow do Top 10.
    <section aria-labelledby={idTitulo} className={cabecalhoOculto ? undefined : 'pt-8'}>
      <header
        style={{ paddingInline: PADDING_TITULO }}
        className={cabecalhoOculto ? 'sr-only' : 'mb-6'}
      >
        <h2
          id={idTitulo}
          className="text-2xl font-extrabold tracking-tight text-white sm:text-3xl lg:text-4xl"
        >
          {titulo}
        </h2>
        {descricao && <p className="mt-2 text-sm font-bold text-ink-muted sm:text-base">{descricao}</p>}
      </header>
      {children}
    </section>
  );
}

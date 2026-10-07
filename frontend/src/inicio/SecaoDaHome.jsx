import { useId } from 'react';
import { PADDING_TITULO } from './tamanhoDeCard.js';

// Cabeçalho das seções PRINCIPAIS da Home (continuar, Top 10, lançamentos,
// estreias): título grande + linha de apoio, no mesmo gutter de 3.7% das
// fileiras. As fileiras temáticas seguem com o título pequeno de
// `FileiraDeCards` — a diferença de escala é de propósito, marca o que é
// seção-âncora e o que é descoberta.
export default function SecaoDaHome({ titulo, descricao, children }) {
  const idTitulo = useId();
  return (
    // `pt-8`: respiro extra entre seções principais (some ao `space-y-14` do
    // contêiner em `paginas/Inicio.jsx`) — com o título grande, só o `space-y`
    // deixava uma seção colada na anterior, em especial depois do palco do Top 10.
    <section aria-labelledby={idTitulo} className="pt-8">
      <header style={{ paddingInline: PADDING_TITULO }} className="mb-6">
        <h2
          id={idTitulo}
          className="text-3xl font-extrabold tracking-tight text-white sm:text-4xl lg:text-5xl"
        >
          {titulo}
        </h2>
        {descricao && <p className="mt-2 text-sm font-bold text-ink-muted sm:text-base">{descricao}</p>}
      </header>
      {children}
    </section>
  );
}

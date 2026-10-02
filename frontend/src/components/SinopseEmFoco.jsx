import { useEffect, useMemo, useRef } from 'react';

// Sinopse completa em "modo foco": `<dialog>` nativo em tela cheia (mesmo idioma
// de DialogoDeConfirmacao.jsx — foco preso, Esc e `inert` do resto de graça),
// com o `::backdrop` borrando a página inteira (regra em index.css) e as
// frases entrando uma a uma. Sentença como unidade do atraso (e não linha ou
// palavra) porque dá o ritmo de leitura sem medir layout nem depender da
// largura da tela.
//
// Fechar: Esc ou um clique em qualquer lugar (sem botão X — pedido do usuário).
// O clique é ignorado quando há texto selecionado, senão selecionar um trecho
// pra copiar fecharia o modo foco. Sem botão, o clique é também a única saída
// em tela de toque; o teclado tem o Esc nativo do <dialog>.
//
// `sinopse` é texto de provedor externo (AniList/TMDB): renderizado como texto
// do React, nunca como HTML (CLAUDE.md §5).
const REGEX_FRASE = /[^.!?]+[.!?]*["')\]”’]*\s*/g;

function dividirEmFrases(texto) {
  return texto.match(REGEX_FRASE) ?? [texto];
}

export default function SinopseEmFoco({ aberta, titulo, tituloSecundario, sinopse, aoFechar }) {
  const dialogRef = useRef(null);
  const frases = useMemo(() => dividirEmFrases(sinopse ?? ''), [sinopse]);

  useEffect(() => {
    const dialogo = dialogRef.current;
    if (!dialogo) return;
    if (aberta && !dialogo.open) dialogo.showModal();
    if (!aberta && dialogo.open) dialogo.close();
  }, [aberta]);

  return (
    <dialog
      ref={dialogRef}
      onClose={aoFechar}
      onClick={() => {
        if (window.getSelection()?.toString() === '') aoFechar();
      }}
      aria-labelledby="titulo-sinopse-foco"
      // `open:flex` (não `flex` puro): display próprio num <dialog> fechado
      // sobrescreveria o `display: none` do navegador e ele ficaria visível.
      className="sinopse-foco fixed inset-0 m-0 h-dvh max-h-none w-dvw max-w-none items-center bg-transparent p-0 text-white open:flex"
    >
      <div className="mx-auto max-h-full w-full max-w-3xl overflow-y-auto px-6 py-28">
        <p className="mb-3 text-xs font-bold uppercase tracking-[0.14em] text-ink-muted">Sinopse</p>
        <h2
          id="titulo-sinopse-foco"
          className={`text-2xl font-extrabold sm:text-4xl ${tituloSecundario ? 'mb-2' : 'mb-6'}`}
        >
          {titulo}
        </h2>
        {tituloSecundario && (
          <p className="mb-6 text-lg font-bold text-ink-muted sm:text-xl">{tituloSecundario}</p>
        )}
        {/* Mesmo peso e cor da sinopse do hero (`font-bold text-ink-muted`,
            inicio/BlocoConteudoHero.jsx e inicio/DestaqueGrande.jsx), só em
            tamanho de leitura — pedido do usuário, 2026-10-02. */}
        <p className="text-lg font-bold leading-relaxed text-ink-muted sm:text-xl sm:leading-[1.75]">
          {frases.map((frase, indice) => (
            <span key={indice} className="sinopse-foco-frase" style={{ '--i': indice }}>
              {frase}
            </span>
          ))}
        </p>
      </div>
    </dialog>
  );
}

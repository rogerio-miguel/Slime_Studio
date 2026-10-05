import { useCallback, useEffect, useMemo, useRef } from 'react';

import { useTravaDeRolagem } from '../hooks/useTravaDeRolagem.js';
import { usePrefersReducedMotion } from '../inicio/usePrefersReducedMotion.js';

// Sinopse completa em tela estreita (< `sm`), onde a cápsula da ilha não existe:
// um `<dialog>` nativo (`showModal` — foco preso, Esc e `inert` do resto da
// página de graça) que nasce no topo-centro, como uma pílula, e cresce na
// vertical até o texto caber. Em tela larga a sinopse é a PRÓPRIA cápsula
// virando painel (hooks/useSinopseNaCapsula.js + BarraDeNavegacao.jsx); este
// arquivo também exporta `ConteudoDaSinopse`, o miolo compartilhado pelos dois.
// As regras visuais do dialog estão em index.css (`dialog.sinopse-ilha`), com o
// `::backdrop` transparente (sem desfoque, pedido do usuário).
//
// Abrir/fechar são transições: `data-visivel` só entra depois de um reflow com
// o dialog já aberto (senão não há estado inicial pra animar) e, ao fechar, sai
// primeiro e o `close()` real espera a transição terminar — por isso Esc é
// interceptado (`onCancel`), senão o navegador fecharia seco. O `aoFechar` do
// pai só dispara no `close` do dialog, depois da animação e com o foco já
// devolvido ao botão que abriu.
//
// Fechar: Esc ou um clique em qualquer lugar (sem botão X — pedido do usuário).
// O clique é ignorado quando há texto selecionado, senão selecionar um trecho
// pra copiar fecharia o painel. Sem botão, o clique é também a única saída em
// tela de toque; o teclado tem o Esc.
//
// As frases entram uma a uma (sentença como unidade do atraso, e não linha ou
// palavra, porque dá o ritmo de leitura sem medir layout nem depender da
// largura da tela).
//
// `sinopse` é texto de provedor externo (AniList/TMDB): renderizado como texto
// do React, nunca como HTML (CLAUDE.md §5).
const REGEX_FRASE = /[^.!?]+[.!?]*["')\]”’]*\s*/g;
// Mesma duração de `transition` em `dialog.sinopse-ilha` (index.css).
const PAINEL_MS = 340;

function dividirEmFrases(texto) {
  return texto.match(REGEX_FRASE) ?? [texto];
}

// Miolo da sinopse (rótulo, títulos e frases entrando uma a uma), igual no
// dialog e dentro da cápsula.
export function ConteudoDaSinopse({ titulo, tituloSecundario, sinopse }) {
  const frases = useMemo(() => dividirEmFrases(sinopse ?? ''), [sinopse]);
  return (
    <div className="px-6 pb-8 pt-6 sm:px-9 sm:pb-10 sm:pt-8">
      <p className="mb-2 text-xs font-bold uppercase tracking-[0.14em] text-ink-muted">Sinopse</p>
      <h2
        id="titulo-sinopse-ilha"
        className={`text-xl font-extrabold sm:text-3xl ${tituloSecundario ? 'mb-1' : 'mb-5'}`}
      >
        {titulo}
      </h2>
      {tituloSecundario && (
        <p className="mb-5 text-base font-bold text-ink-muted sm:text-lg">{tituloSecundario}</p>
      )}
      {/* Mesmo peso e cor da sinopse do hero (`font-bold text-ink-muted`,
          inicio/BlocoConteudoHero.jsx e inicio/DestaqueGrande.jsx), só em
          tamanho de leitura — pedido do usuário, 2026-10-02. */}
      <p className="text-base font-bold leading-relaxed text-ink-muted sm:text-lg sm:leading-[1.75]">
        {frases.map((frase, indice) => (
          <span key={indice} className="sinopse-ilha-frase" style={{ '--i': indice }}>
            {frase}
          </span>
        ))}
      </p>
    </div>
  );
}

export default function SinopseNaIlha({ aberta, titulo, tituloSecundario, sinopse, aoFechar }) {
  const dialogRef = useRef(null);
  const conteudoRef = useRef(null);
  const temporizadorFecharRef = useRef(null);
  const temporizadorEstavelRef = useRef(null);
  const movimentoReduzido = usePrefersReducedMotion();
  // O dialog modal não trava a rolagem da página por trás sozinho.
  useTravaDeRolagem(aberta, conteudoRef);

  const fechar = useCallback(() => {
    const dialogo = dialogRef.current;
    if (!dialogo?.open || temporizadorFecharRef.current != null) return;
    delete dialogo.dataset.visivel;
    delete dialogo.dataset.rolavel;
    clearTimeout(temporizadorEstavelRef.current);
    temporizadorFecharRef.current = setTimeout(
      () => {
        temporizadorFecharRef.current = null;
        dialogo.close();
      },
      movimentoReduzido ? 0 : PAINEL_MS,
    );
  }, [movimentoReduzido]);

  useEffect(() => {
    const dialogo = dialogRef.current;
    if (!dialogo) return;
    if (!aberta) {
      fechar();
      return;
    }
    if (dialogo.open) return;
    dialogo.showModal();
    // Reflow com o estado "recolhido" já pintável: sem isto o navegador funde
    // `open` e `data-visivel` no mesmo estilo e não anima.
    void dialogo.offsetWidth;
    dialogo.dataset.visivel = '';
    // Só rola depois de assentar e se o texto não couber (ver
    // `.sinopse-ilha-conteudo` em index.css e useSinopseNaCapsula.js).
    temporizadorEstavelRef.current = setTimeout(
      () => {
        const conteudo = conteudoRef.current;
        if (conteudo && conteudo.scrollHeight > conteudo.clientHeight + 1) {
          dialogo.dataset.rolavel = '';
        }
      },
      PAINEL_MS + 120,
    );
  }, [aberta, fechar]);

  useEffect(
    () => () => {
      clearTimeout(temporizadorFecharRef.current);
      clearTimeout(temporizadorEstavelRef.current);
    },
    [],
  );

  return (
    <dialog
      ref={dialogRef}
      onClose={aoFechar}
      onCancel={(evento) => {
        evento.preventDefault();
        fechar();
      }}
      onClick={() => {
        if (window.getSelection()?.toString() === '') fechar();
      }}
      aria-labelledby="titulo-sinopse-ilha"
      className="sinopse-ilha"
    >
      <div ref={conteudoRef} className="sinopse-ilha-conteudo">
        <ConteudoDaSinopse titulo={titulo} tituloSecundario={tituloSecundario} sinopse={sinopse} />
      </div>
    </dialog>
  );
}

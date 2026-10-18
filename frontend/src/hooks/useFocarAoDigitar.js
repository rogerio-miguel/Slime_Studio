import { useEffect } from 'react';

const CAMPOS_DE_TEXTO = 'input, textarea, select, [contenteditable]:not([contenteditable="false"])';
// Dialog/menu abertos (sinopse, seletores, painel de fonte) têm foco e teclas
// próprios; roubar a letra deles quebraria o teclado dentro do overlay.
const OVERLAYS_ABERTOS = '[role="dialog"], [role="menu"], [role="listbox"]';

// Tecla imprimível solta (sem Ctrl/Meta/Alt) fora de campo de texto e de
// overlay. Espaço fica de fora: com um botão focado ele é "ativar", não texto.
function ehDigitacaoParaABusca(evento) {
  if (evento.isComposing || evento.ctrlKey || evento.metaKey || evento.altKey) return false;
  if (evento.key.length !== 1 || evento.key === ' ') return false;
  const alvo = document.activeElement;
  if (alvo?.closest(CAMPOS_DE_TEXTO)) return false;
  return !document.querySelector(OVERLAYS_ABERTOS);
}

// Digitar em qualquer ponto da página foca a busca. O `focus()` roda no
// `keydown` e o navegador entrega o caractere ao input recém-focado: sem
// `preventDefault` a 1ª letra não se perde e acento/IME seguem o fluxo nativo.
export function useFocarAoDigitar(ativo, inputRef) {
  useEffect(() => {
    if (!ativo) return undefined;
    const aoTeclar = (evento) => {
      if (ehDigitacaoParaABusca(evento)) inputRef.current?.focus();
    };
    window.addEventListener('keydown', aoTeclar);
    return () => window.removeEventListener('keydown', aoTeclar);
  }, [ativo, inputRef]);
}

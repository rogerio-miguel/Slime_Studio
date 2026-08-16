import { useCallback, useState } from 'react';

// Hook único pra preferências persistidas em localStorage (slime.preset,
// slime.cinemaAudio, slime.hudVisivel — mesmas chaves do protótipo, ver
// bench.js:277-291). try/catch em leitura E escrita: localStorage pode
// estar bloqueado (ex. modo anônimo) — nesse caso a preferência simplesmente
// não persiste, nunca quebra a UI. Valores são serializados via JSON (não o
// '1'/'0' cru que o protótipo usava só pra slime.cinemaAudio) pra um único
// hook servir string (preset) e boolean (cinemaAudio/hudVisivel) sem
// tratamento especial por chamador.
export function usePreferencia(chave, valorInicial) {
  const [valor, setValor] = useState(() => {
    try {
      const bruto = localStorage.getItem(chave);
      return bruto === null ? valorInicial : JSON.parse(bruto);
    } catch {
      return valorInicial; // localStorage bloqueado ou valor corrompido — não é erro fatal
    }
  });

  const definir = useCallback(
    (novoValor) => {
      setValor((atual) => {
        const resolvido = typeof novoValor === 'function' ? novoValor(atual) : novoValor;
        try {
          localStorage.setItem(chave, JSON.stringify(resolvido));
        } catch {
          // best-effort — falha de storage não pode quebrar quem chamou
        }
        return resolvido;
      });
    },
    [chave]
  );

  return [valor, definir];
}

import { useEffect, useState } from 'react';

// Estrutura de grid de cards compartilhada entre GradeRotativa.jsx (grade
// fixa de 2 linhas, "Destaques da temporada") e as seções de resultado de
// busca de paginas/Inicio.jsx (lista normal, rola com a página) — mesmas
// colunas por breakpoint, mesmo gap (gap-6, aplicado por quem usa isto,
// não aqui) e mesmo teto de largura de card (`--largura-max-card`), pra
// ficarem visualmente idênticas. O que diverge entre os dois usos é só o
// comportamento de altura do container: GradeRotativa trava a seção em
// exatamente 2 linhas sem rolar (`minHeight` calculado a partir da
// viewport); as seções de busca não têm esse teto e rolam normalmente com
// a página — mesmo assim reaproveitam a MESMA fórmula de
// `--largura-max-card` só pra os cards saírem do mesmo tamanho visual, não
// porque compartilham a restrição de "caber em 2 linhas".
//
// Pontos de quebra espelhando exatamente as classes Tailwind do grid
// abaixo (`sm`/`md`/`lg`/`xl` default do framework: 640/768/1024/1280px).
//
// Track não pode ser `1fr`: se a coluna ficasse mais larga que o teto do
// card (--largura-max-card), o card sobraria menor que ela e centralizado
// dentro (`mx-auto` em SlotDeCard), abrindo um respiro DENTRO de cada
// coluna que se soma ao `gap` e aparece como distância extra entre os
// cards de uma mesma linha, não só entre colunas — daí `minmax(0, ...)`
// travando a track no próprio teto. `justify-start` (não `justify-center`)
// colapsa a folga resultante na borda DIREITA do bloco inteiro (sem uso
// visual, mas sem distorcer o gap) em vez de espalhar entre cada par de
// cards ou centralizar o bloco — isso último desalinhava a grade em
// relação ao `<h2>` do título, que é sempre flush-left.
export const COLUNAS_GRID =
  'grid-cols-[repeat(2,minmax(0,var(--largura-max-card)))] justify-start ' +
  'sm:grid-cols-[repeat(4,minmax(0,var(--largura-max-card)))] ' +
  'md:grid-cols-[repeat(5,minmax(0,var(--largura-max-card)))] ' +
  'lg:grid-cols-[repeat(6,minmax(0,var(--largura-max-card)))] ' +
  'xl:grid-cols-[repeat(7,minmax(0,var(--largura-max-card)))]';

// pt-24 de <main> (paginas/Inicio.jsx) — reserva de topo usada por
// GradeRotativa pro cálculo de `minHeight` (não usado pelas seções de
// busca, que não travam altura).
export const RESERVA_TOPO = '6rem';

// Ver GradeRotativa.jsx pro detalhe completo do cálculo (mt-20 do h2 +
// line-height + mb-4 + gap-6 entre 2 linhas + folga + RESERVA_TOPO) — o
// valor em si é o que importa aqui: --largura-max-card = teto de largura
// que faz o card caber em 1/3 da altura de UMA linha dentro desse
// orçamento vertical (aspect-[2/3] do card resolve altura->largura).
const _RESERVA_TOTAL = '14.5rem';
export const estiloLarguraMaxCard = {
  '--largura-max-card': `calc((100vh - ${_RESERVA_TOTAL}) / 3)`,
};

// Atraso escalonado por posição do `transitionDelay` de SlotDeCard — sem
// teto: cada posição do grid dispara estritamente depois da anterior, "um
// card por vez" em vez de um bloco inteiro a partir de um certo índice.
// Exportado (junto com DURACAO_ENTRADA_MS abaixo): GradeRotativa.jsx usa os
// dois pra calcular quando a última posição da leva termina de aparecer,
// sem duplicar a fórmula.
export const ATRASO_POR_INDICE_MS = 60;

// Duração da transição de entrada de SlotDeCard — precisa bater com a
// classe `duration-700` do className abaixo (não dá pra interpolar isto na
// classe: quebraria a extração estática de classes do Tailwind).
export const DURACAO_ENTRADA_MS = 700;

// Slot de um card do grid — dono da transição de entrada/saída (opacity-0
// scale-[0.8] ↔ opacity-100 scale-100, "surge do meio"). Mesma dupla
// opacidade+escala partindo de 0.8 usada na logo do hero
// (inicio/useScrubDeVideo.js, `_LOGO_ESCALA_INICIO`) — card cresce a
// partir do próprio centro (transform-origin default) em vez do scale-95
// quase imperceptível de antes, ecoando o "emergir de dentro da cena" da
// logo. `indice` pode ser a posição no grid ou qualquer índice estável —
// quem chama decide via `key` se quer retrigger (key nova a cada troca) ou
// persistência (key estável por item, ex. id do anime).
//
// `ativa` (default true, pros usos fora de GradeRotativa — resultados de
// busca em paginas/Inicio.jsx, que só montam depois de `fase === 'revelado'`)
// controla a visibilidade NOS DOIS SENTIDOS, não só a entrada: quando volta
// a `false` (GradeRotativa.jsx repassa `fase === 'revelado'` — se o usuário
// rola de volta pra cima e sai da fase revelada antes de chegar na grade de
// novo) o card reverte na hora pro estado oculto, tocando a MESMA transição
// em reverso; quando `ativa` volta a `true` (rolou de volta pra baixo) ela
// toca de novo pra frente — sem depender de dar reload na página. Sem
// isto, `visivel` só ia de false→true uma vez (no primeiro `ativa=true`) e
// ficava presa em true pro resto da vida do componente.
export function SlotDeCard({ indice, ativa = true, children }) {
  const [visivel, setVisivel] = useState(false);

  useEffect(() => {
    if (!ativa) {
      setVisivel(false);
      return undefined;
    }
    const quadro = requestAnimationFrame(() => setVisivel(true));
    return () => cancelAnimationFrame(quadro);
  }, [ativa]);

  return (
    <div
      style={{
        transitionDelay: `${indice * ATRASO_POR_INDICE_MS}ms`,
        maxWidth: 'var(--largura-max-card)',
      }}
      className={`mx-auto w-full transition-[opacity,scale] duration-700 ease-out motion-reduce:opacity-100 motion-reduce:scale-100 motion-reduce:transition-none ${
        visivel ? 'scale-100 opacity-100' : 'scale-[0.8] opacity-0'
      }`}
    >
      {children}
    </div>
  );
}

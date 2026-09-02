import { useCallback, useEffect, useId, useRef, useState } from 'react';
import { SOMBRA_SLIDE_ATIVO } from './CarrosselDestaques.jsx';
import {
  CLASSE_GUTTER,
  CLASSES_POR_PAGINA,
  FLEX_BASIS_SLOT,
  PADDING_TITULO,
} from './tamanhoDeCard.js';
import { usePrefersReducedMotion } from './usePrefersReducedMotion.js';

// Fileira horizontal de cards no estilo "prateleira" do Disney+ (título +
// trilha rolável + setas nos gutters), reutilizável e alimentada por qualquer
// lista. Diferente dos outros dois blocos da home:
//   - CarrosselDestaques.jsx: billboard hero, 1 item grande, auto-avanço, loop.
//   - GradeRotativa.jsx: grade 2D fixa que gira o recorte por tempo.
// Aqui a rolagem é 100% do usuário — clicar numa seta rola UMA página cheia via
// `scrollBy` (sem CSS scroll-snap, sem auto-avanço, sem timer). Espelha a API
// de render-prop de GradeRotativa: quem chama passa o pool (`itens`) +
// `renderItem(item, indice)` e `chaveDoItem(item)`; o guard de lista vazia
// mora aqui (retorna `null`), o chamador não repete. A irmã que quebra linha
// em vez de rolar é GradeDeCatalogo.jsx.
//
// Vocabulário de tamanho de card (`CLASSES_POR_PAGINA`, `CLASSE_GUTTER`,
// `FLEX_BASIS_SLOT`, `PADDING_TITULO`) e a geometria medida no Disney+ moram
// em ./tamanhoDeCard.js — fonte única compartilhada com GradeDeCatalogo pra os
// cards saírem do mesmo tamanho. `--por-pagina` vem por breakpoint das classes
// de `CLASSES_POR_PAGINA[tamanho]`; o `flex-basis` correspondente vai no
// `style` inline (a `/` colide com o modificador de opacidade do Tailwind v4).
//
// Cada card leva a MESMA drop shadow do slide ativo do billboard
// (`SOMBRA_SLIDE_ATIVO`, importada de CarrosselDestaques.jsx — fonte única) —
// o usuário pediu a sombra do carrossel, não o "sem sombra" das prateleiras
// reais do Disney+. Ela mora num wrapper só-da-sombra dentro do slot, não no
// AnimeCard (compartilhado com a Galeria), e é ESTÁTICA: não acompanha o
// `scale` do hover, igual ao billboard. Só aparece de fato sobre o fundo
// `#17171b` do `<main>` (paginas/Inicio.jsx) — sobre um preto mais fechado
// some.

export default function FileiraDeCards({
  titulo,
  itens,
  renderItem,
  chaveDoItem,
  idRotulo,
  tamanho = 'grande',
}) {
  const idGerado = useId();
  const idTitulo = idRotulo ?? idGerado;
  const idTrilha = useId();
  const trilhaRef = useRef(null);
  const movimentoReduzido = usePrefersReducedMotion();

  const lista = itens ?? [];

  // Seta "morta" nos extremos: `disabled` (tira do tab/clique) + `opacity-0`
  // forçado (uma seta visível que não rola nada é pior que nenhuma seta).
  // Começa com as duas nos limites — o efeito de mount corrige assim que mede
  // a trilha; como as setas já são `opacity-0` em repouso, não há flash.
  const [limites, setLimites] = useState({ noInicio: true, noFim: true });

  const medirLimites = useCallback(() => {
    const trilha = trilhaRef.current;
    if (!trilha) return;
    const { scrollLeft, clientWidth, scrollWidth } = trilha;
    const noInicio = scrollLeft <= 1;
    // Tolerância de 1px: scrollLeft/scrollWidth podem ser fracionários e nunca
    // fechar a conta exata no fim da trilha.
    const noFim = scrollLeft + clientWidth >= scrollWidth - 1;
    setLimites((atual) =>
      atual.noInicio === noInicio && atual.noFim === noFim ? atual : { noInicio, noFim },
    );
  }, []);

  // Uma medição no mount e a cada mudança no tamanho da lista (feed pode
  // recarregar com mais/menos itens e mudar se há transbordo). Depois disso,
  // só o `onScroll` da trilha mantém os limites em dia.
  useEffect(() => {
    medirLimites();
  }, [medirLimites, lista.length]);

  // Rola uma página cheia. Passo = largura visível da trilha menos os dois
  // gutters de 3.7% (medido: ~1783px em 1920) — lido do estilo computado em
  // vez de repetir o "3.7%" aqui. `getComputedStyle` só é tocado dentro deste
  // handler, nunca no corpo do render e nunca antes do ref existir.
  const rolar = (direcao) => {
    const trilha = trilhaRef.current;
    if (!trilha) return;
    const paddingInline = Number.parseFloat(getComputedStyle(trilha).paddingInlineStart);
    const passo = trilha.clientWidth - 2 * paddingInline;
    if (!Number.isFinite(passo) || passo <= 0) return;
    trilha.scrollBy({
      left: direcao * passo,
      behavior: movimentoReduzido ? 'auto' : 'smooth',
    });
  };

  // Depois de acionar a seta por PONTEIRO (mouse/toque), tira o foco dela: sem
  // isto o gutter fica "com foco preso" e a seta visível até um clique fora.
  // `evento.detail === 0` = teclado (Enter/Espaço) — aí o foco fica, pra não
  // perder o lugar na navegação. Mesmo helper de CarrosselDestaques.jsx.
  const desfocarSePonteiro = (evento) => {
    if (evento.detail > 0) evento.currentTarget.blur();
  };

  if (lista.length === 0) return null;

  // Setas reveladas só no hover/foco do grupo — NUNCA `hidden`: continuam
  // alcançáveis por Tab mesmo invisíveis. No limite, as classes de revelar
  // não entram, então a seta fica `opacity-0` inclusive sob o cursor.
  const classesSeta =
    'absolute inset-y-0 z-10 flex w-[3.7%] items-center justify-center text-8xl ' +
    'text-white/70 outline-none transition-opacity duration-300 hover:text-white ' +
    'focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-neon ' +
    'motion-reduce:transition-none opacity-0';
  const classesRevelar = 'group-hover/fileira:opacity-100 focus-visible:opacity-100';

  return (
    <section aria-labelledby={idTitulo}>
      {/* Sem `margin-bottom`: o respiro até os cards vem do `pt` da trilha.
          `PADDING_TITULO` (./tamanhoDeCard.js) alinha o título com a borda do
          CARD interno (gutter de 3.7% + os 10px de padding do slot); vai no
          `style` pelo mesmo motivo do `flex-basis` abaixo. */}
      <h2
        id={idTitulo}
        style={{ paddingInline: PADDING_TITULO }}
        className="text-[22px] font-bold text-[#dbdcde]"
      >
        {titulo}
      </h2>

      {/* `group/fileira relative`: revela as setas no hover/foco e ancora o
          posicionamento absoluto delas. Grupo NOMEADO — os cards dentro têm
          `group/card` próprio; `group` puro nos dois faria o hover da trilha
          acender a borda de todos os cards de uma vez. */}
      <div className="group/fileira relative">
        {/* `pt-[22px] pb-[44px]` NÃO é cosmético: `overflow-x-auto` também
            recorta no eixo Y, e aqui há DUAS coisas transbordando pra baixo —
            o `scale-105` do card no hover (feito no AnimeCard) e, sobretudo, a
            drop shadow do billboard, que desce ~46px abaixo da borda do card
            (`0 26px 30px -10px`). O card fica 10px acima da borda do slot, daí
            `pb` >= ~36px pra sombra não ser cortada; 44px dá folga. O `pt`
            também é o respiro título -> cards (o h2 não tem `margin-bottom`).
            Mesma classe de armadilha do `py-16 -my-16` de CarrosselDestaques.jsx.
            Sem classe `gap-*`: o respiro entre cards vem do `p-[10px]` de cada
            `<li>`. Scrollbar escondida nos dois motores (Firefox / WebKit).
            `--por-pagina` (via `CLASSES_POR_PAGINA[tamanho]`) por breakpoint
            aqui, nunca como prop numérica. */}
        <ul
          ref={trilhaRef}
          id={idTrilha}
          onScroll={medirLimites}
          className={`flex overflow-x-auto ${CLASSE_GUTTER} pt-[22px] pb-[44px] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden ${
            CLASSES_POR_PAGINA[tamanho] ?? CLASSES_POR_PAGINA.grande
          }`}
        >
          {lista.map((item, indice) => (
            // `relative` + `hover:z-10 focus-within:z-10` no PRÓPRIO slot: o
            // `AnimeCard` também tem `hover:z-10` no wrapper dele, mas esse
            // z-index fica preso em ancestrais transformados e não escapa pro
            // contexto da fileira — numa trilha justa (sem `gap`) o card
            // ampliado no hover ficaria coberto pela borda do vizinho seguinte
            // sem o z-index aqui.
            <li
              key={chaveDoItem(item)}
              className="relative shrink-0 grow-0 p-[10px] hover:z-10 focus-within:z-10"
              style={{ flexBasis: FLEX_BASIS_SLOT }}
            >
              {/* Wrapper só da sombra: traça o retângulo `rounded-xl` (mesmo
                  raio do AnimeCard) exatamente na borda do card. Não pode
                  morar no `<li>` (que tem `p-[10px]`) senão a sombra sairia
                  destacada 10px do card. Não escala no hover — a sombra fica
                  estática enquanto o card cresce por cima, igual ao billboard.
                  `style` inline pelo mesmo motivo de CarrosselDestaques.jsx: o
                  parser de valor arbitrário do Tailwind v4 não gera de forma
                  confiável sombra de 2 camadas começando pela cor. */}
              <div className="rounded-xl" style={{ boxShadow: SOMBRA_SLIDE_ATIVO }}>
                {renderItem(item, indice)}
              </div>
            </li>
          ))}
        </ul>

        <button
          type="button"
          onClick={(evento) => {
            rolar(-1);
            desfocarSePonteiro(evento);
          }}
          disabled={limites.noInicio}
          aria-label={`Anterior: ${titulo}`}
          aria-controls={idTrilha}
          className={`left-0 ${classesSeta} ${limites.noInicio ? '' : classesRevelar}`}
        >
          <span aria-hidden="true">‹</span>
        </button>
        <button
          type="button"
          onClick={(evento) => {
            rolar(1);
            desfocarSePonteiro(evento);
          }}
          disabled={limites.noFim}
          aria-label={`Próximo: ${titulo}`}
          aria-controls={idTrilha}
          className={`right-0 ${classesSeta} ${limites.noFim ? '' : classesRevelar}`}
        >
          <span aria-hidden="true">›</span>
        </button>
      </div>
    </section>
  );
}

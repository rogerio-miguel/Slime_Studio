import { useCallback, useEffect, useId, useRef, useState } from 'react';
import { SOMBRA_SLIDE_ATIVO } from './CarrosselDestaques.jsx';
import IconeSeta from './IconeSeta.jsx';
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
// histórico, pedido do usuário quando ainda fazia sentido visualmente. Ela
// mora num wrapper só-da-sombra dentro do slot, não no AnimeCard
// (compartilhado com a Galeria), e é ESTÁTICA: não acompanha o `scale` do
// hover, igual ao billboard.
// `comSombra = false` (hoje TODO chamador — as 4 fileiras de
// paginas/Inicio.jsx — passa `false`; `true` só segue default por
// retrocompatibilidade): desliga esse wrapper — mesmo prop e mesmo motivo de
// inicio/GradeDeCatalogo.jsx (fonte única do rationale completo). A sombra só
// tinha contraste visível sobre o cinza `#17171b` que o `<main>` da Home usava
// (hoje `bg-black`, sólido, index.css), e com o card do catálogo em duas
// partes (pôster + legenda abaixo, sem caixa própria) o wrapper `rounded-xl`
// da sombra abraçando as DUAS partes lançava um halo escuro atrás do bloco de
// texto.

export default function FileiraDeCards({
  titulo,
  itens,
  renderItem,
  chaveDoItem,
  idRotulo,
  tamanho = 'grande',
  comSombra = true,
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
  // Mesma seta do hero (glyph chevron do IconeSeta, modelo AnimeFire): zona de
  // clique full-height no gutter, sem fundo, revelada no hover da fileira, cor
  // trocando no hover do próprio controle.
  const classesSeta =
    'absolute inset-y-0 z-10 flex w-[3.7%] items-center justify-center ' +
    'text-white/60 outline-none transition-opacity duration-300 hover:text-neon ' +
    'motion-reduce:transition-none opacity-0';
  const classesRevelar = 'group-hover/fileira:opacity-100 focus-visible:opacity-100';

  return (
    <section aria-labelledby={idTitulo}>
      {/* Sem `margin-bottom`: o respiro até os cards vem do `pt` da trilha.
          `PADDING_TITULO` (./tamanhoDeCard.js) alinha o título com a borda do
          CARD — hoje só o gutter de 3.7%, sem inset a mais: o slot não tem
          mais padding (removido a pedido do usuário, 2026-09-15), então a
          borda do card já coincide com a do gutter. Vai no `style` pelo mesmo
          motivo do `flex-basis` abaixo. */}
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
            recorta no eixo Y, e a drop shadow do billboard desce ~46px abaixo
            da borda do card (`0 26px 30px -10px`). O `pb-[44px]` foi calibrado
            de quando o slot ainda tinha `p-[10px]` (card 10px acima da borda
            do slot, `pb` só precisava cobrir ~36px) — hoje, sem esse padding
            (removido a pedido do usuário, 2026-09-15), a borda do card
            coincide com a do slot e o `pb` ideal seria ~46px; não ajustado
            porque `comSombra` é `false` em todo chamador hoje (ver bloco de
            comentário no topo do arquivo) — a sombra nem renderiza, então a
            folga de 2px não tem efeito visual algum na prática. Revisitar se
            `comSombra=true` voltar a ser usado. O `pt` também é o respiro
            título -> cards (o h2 não tem `margin-bottom`). Mesma classe de
            armadilha do `py-16 -my-16` de CarrosselDestaques.jsx. Sem classe
            `gap-*` e sem padding no `<li>`: cards colam borda a borda (mesmo
            tratamento de GradeDeCatalogo.jsx, ver comentário lá). Scrollbar
            escondida nos dois motores (Firefox / WebKit). `--por-pagina` (via
            `CLASSES_POR_PAGINA[tamanho]`) por breakpoint aqui, nunca como prop
            numérica. */}
        <ul
          ref={trilhaRef}
          id={idTrilha}
          onScroll={medirLimites}
          className={`flex overflow-x-auto ${CLASSE_GUTTER} pt-[22px] pb-[44px] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden ${
            CLASSES_POR_PAGINA[tamanho] ?? CLASSES_POR_PAGINA.grande
          }`}
        >
          {lista.map((item, indice) => (
            <li
              key={chaveDoItem(item)}
              className="relative shrink-0 grow-0"
              style={{ flexBasis: FLEX_BASIS_SLOT }}
            >
              {/* Wrapper só da sombra: traça o retângulo `rounded-xl` (mesmo
                  raio do AnimeCard) exatamente na borda do card — hoje a
                  borda do `<li>` já É a borda do card (slot sem padding, ver
                  comentário acima), então este wrapper não corrige inset
                  nenhum mais, só continua existindo como o lugar natural pra
                  aplicar a sombra caso `comSombra` volte a ser usado.
                  `style` inline pelo mesmo motivo de CarrosselDestaques.jsx: o
                  parser de valor arbitrário do Tailwind v4 não gera de forma
                  confiável sombra de 2 camadas começando pela cor.
                  `comSombra=false` pula esse wrapper por completo (ver bloco
                  de comentário acima). */}
              {comSombra ? (
                <div className="rounded-xl" style={{ boxShadow: SOMBRA_SLIDE_ATIVO }}>
                  {renderItem(item, indice)}
                </div>
              ) : (
                renderItem(item, indice)
              )}
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
          <IconeSeta direcao="esquerda" />
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
          <IconeSeta direcao="direita" />
        </button>
      </div>
    </section>
  );
}

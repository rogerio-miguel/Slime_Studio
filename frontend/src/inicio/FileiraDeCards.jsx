import { useCallback, useEffect, useId, useRef, useState } from 'react';
import { SOMBRA_SLIDE_ATIVO } from './CarrosselDestaques.jsx';
import IconeSeta from './IconeSeta.jsx';
import {
  CLASSE_GUTTER,
  CLASSE_RESPIRO_POSTER,
  CLASSES_POR_PAGINA,
  FLEX_BASIS_SLOT_COM_RESPIRO,
  PADDING_TITULO,
} from './tamanhoDeCard.js';
import { usePrefersReducedMotion } from './usePrefersReducedMotion.js';

// Mesmos 4 breakpoints padrão do Tailwind que `--por-pagina`
// (./tamanhoDeCard.js) usa por classe responsiva — `matchMedia`, não
// `ResizeObserver` (mesma escolha de `GradeRotativa.jsx::
// useColunasResponsivas`: a trilha é só o que decide o card por página, é a
// VIEWPORT que muda o breakpoint, não o elemento em si). Só dispara um
// recálculo (`medirLimites`) quando a faixa muda — sem guardar quantas
// colunas cada uma tem, isso já sai medindo a geometria real do DOM.
const _PONTOS_DE_QUEBRA = [
  '(min-width: 1280px)',
  '(min-width: 1024px)',
  '(min-width: 768px)',
  '(min-width: 640px)',
];

// Passo de rolagem = largura visível da trilha menos os dois gutters de
// 3.7% (medido em `getComputedStyle`, não repetindo "3.7%" aqui) — usado
// tanto pelas setas (`rolar`) quanto pela paginação em pílulas (`medirLimites`
// abaixo), por isso extraído: as duas precisam do MESMO valor pra as
// pílulas baterem com onde as setas realmente param.
function _passoDaTrilha(trilha) {
  const estilo = getComputedStyle(trilha);
  const paddingInline = Number.parseFloat(estilo.paddingInlineStart);
  // + 1 gap: a próxima página começa DEPOIS do respiro entre slots; sem somar,
  // cada página deslizava um gap a menos e o alinhamento derivava. `normal`
  // (sem gap) vira NaN → 0.
  const gap = Number.parseFloat(estilo.columnGap) || 0;
  return trilha.clientWidth - 2 * paddingInline + gap;
}

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
  // Paginação em pílulas (pedido do usuário, 2026-09-21) — decorativa, só
  // indicador (não navega, ver `PilulasDePaginacao` abaixo): `total` = quantas
  // "paradas" de `passo` cabem na trilha, `atual` = a mais próxima da posição
  // de rolagem corrente. `total: 1` (default, sem pílula nenhuma renderizada,
  // ver JSX) até a 1ª medição confirmar se há transbordo de verdade.
  const [paginacao, setPaginacao] = useState({ atual: 0, total: 1 });

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

    const passo = _passoDaTrilha(trilha);
    if (Number.isFinite(passo) && passo > 0) {
      // `Math.ceil`, não `Math.round`: a última "página" quase nunca fecha um
      // passo cheio (sobra menos da metade de um card), e `round` pra baixo
      // contava uma pílula a menos do que os passos que `rolar()` realmente
      // precisa pra chegar no fim — sobrava conteúdo atrás da última pílula.
      // Tolerância de 1px (mesma da checagem de `noFim` acima) só pra não
      // gerar pílula extra por ruído de ponto flutuante num passo exato.
      const total = Math.max(1, Math.ceil((scrollWidth - clientWidth - 1) / passo) + 1);
      // `scrollLeft` no fim de verdade raramente é múltiplo exato de `passo`
      // (última "página" quase sempre sobra/falta item vs. as demais) — daí
      // não dar pra confiar só no arredondamento de `scrollLeft / passo`:
      // ele pode fechar em `total - 2` mesmo com `noFim` true. Trava nos
      // limites já medidos acima (`noInicio`/`noFim`) antes de arredondar.
      const atual = noFim
        ? total - 1
        : noInicio
          ? 0
          : Math.min(Math.max(Math.round(scrollLeft / passo), 0), total - 1);
      setPaginacao((estado) =>
        estado.atual === atual && estado.total === total ? estado : { atual, total },
      );
    }
  }, []);

  // Uma medição no mount, a cada mudança no tamanho da lista (feed pode
  // recarregar com mais/menos itens e mudar se há transbordo) e a cada troca
  // de breakpoint (`--por-pagina` muda, então `passo`/`total` também mudam
  // mesmo sem a lista mudar — ver `_PONTOS_DE_QUEBRA` no topo do arquivo).
  // Depois disso, só o `onScroll` da trilha mantém os dois em dia.
  useEffect(() => {
    medirLimites();
  }, [medirLimites, lista.length]);

  useEffect(() => {
    const consultas = _PONTOS_DE_QUEBRA.map((consulta) => window.matchMedia(consulta));
    consultas.forEach((c) => c.addEventListener('change', medirLimites));
    return () => consultas.forEach((c) => c.removeEventListener('change', medirLimites));
  }, [medirLimites]);

  // Rola uma página cheia. `getComputedStyle` (dentro de `_passoDaTrilha`) só
  // é tocado dentro deste handler, nunca no corpo do render e nunca antes do
  // ref existir.
  const rolar = (direcao) => {
    const trilha = trilhaRef.current;
    if (!trilha) return;
    const passo = _passoDaTrilha(trilha);
    if (!Number.isFinite(passo) || passo <= 0) return;
    trilha.scrollBy({
      left: direcao * passo,
      behavior: movimentoReduzido ? 'auto' : 'smooth',
    });
  };

  // Pílula clicada = ir DIRETO pra página `indice` (não relativo, diferente
  // de `rolar`): posição absoluta `indice * passo`, `scrollTo` em vez de
  // `scrollBy`. Trava no `maximo` real da trilha (`scrollWidth - clientWidth`)
  // — a última página quase nunca é um múltiplo exato de `passo` (mesmo
  // motivo do `noFim` forçar `atual = total - 1` em `medirLimites`), então
  // `(total - 1) * passo` estouraria o scroll de verdade.
  const irParaPagina = (indice) => {
    const trilha = trilhaRef.current;
    if (!trilha) return;
    const passo = _passoDaTrilha(trilha);
    if (!Number.isFinite(passo) || passo <= 0) return;
    const maximo = trilha.scrollWidth - trilha.clientWidth;
    trilha.scrollTo({
      left: Math.min(indice * passo, maximo),
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
    'absolute inset-y-0 z-10 flex w-[3.7%] cursor-pointer items-center justify-center ' +
    'text-white/60 outline-none transition-opacity duration-300 hover:text-neon ' +
    'motion-reduce:transition-none opacity-0';
  const classesRevelar = 'group-hover/fileira:opacity-100 focus-visible:opacity-100';

  return (
    <section aria-labelledby={idTitulo}>
      {/* Sem `margin-bottom`: o respiro até os cards vem do `pt` da trilha.
          `PADDING_TITULO` (./tamanhoDeCard.js) alinha o título (e as pílulas,
          no extremo oposto da MESMA linha) com a borda do CARD — hoje só o
          gutter de 3.7%, sem inset a mais: o slot não tem mais padding
          (removido a pedido do usuário, 2026-09-15), então a borda do card já
          coincide com a do gutter. `tamanho="episodio"` continua alinhado com
          o MESMO `PADDING_TITULO` — o respiro entre cards daquele tamanho vem
          de um `gap-x` na trilha (ver comentário mais abaixo), não de padding
          no primeiro/último `<li>`, então as bordas de fora continuam
          coincidindo com o gutter/título como nos outros tamanhos. Vai no
          `style` pelo mesmo motivo do `flex-basis` abaixo. */}
      <div
        style={{ paddingInline: PADDING_TITULO }}
        className="flex items-center gap-4"
      >
        <h2 id={idTitulo} className="text-[22px] font-bold text-[#dbdcde]">
          {titulo}
        </h2>
        <PilulasDePaginacao
          atual={paginacao.atual}
          total={paginacao.total}
          titulo={titulo}
          aoClicar={irParaPagina}
        />
      </div>

      {/* `group/fileira relative`: revela as setas no hover/foco e ancora o
          posicionamento absoluto delas. Grupo NOMEADO — os cards dentro têm
          `group/card` próprio; `group` puro nos dois faria o hover da trilha
          acender a borda de todos os cards de uma vez. */}
      <div className="group/fileira relative flow-root">
        {/* GLOW VAZANDO DA SEÇÃO: a trilha (`overflow-x-auto`) recorta nos dois
            eixos, então o brilho do hover (`BrilhoDaCapa`: ~55px acima e ~80px
            abaixo do pôster, com o blur) só aparece se o box de rolagem for
            MAIOR que a fileira visível. Por isso `pt-[80px] pb-[88px]`
            compensados por `-mt-[58px] -mb-[44px]`: o espaçamento efetivo
            segue `22px` em cima / `44px` embaixo (o `flow-root` do wrapper
            impede a margem negativa de colapsar e mover o wrapper — as setas
            `inset-y-0` continuam na altura original), mas o recorte fica
            mais longe. A trilha passa a SOBREPOR o título e a seção de baixo
            com padding transparente: `pointer-events-none` nela e
            `pointer-events-auto` nos `<li>`, senão ela taparia as pílulas de
            paginação. Custo: rolar com o gesto horizontal sobre o gap/padding
            (fora de um card) não rola a fileira.
            `pt-[22px] pb-[44px]` (valores efetivos) NÃO é cosmético: `overflow-x-auto` também
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
            padding no `<li>`; o respiro entre pôsteres é `gap-x-4` na trilha
            (`CLASSE_RESPIRO_POSTER`, mesmo de GradeDeCatalogo.jsx) — inclusive
            em `tamanho="episodio"` ("Continuar assistindo"), que antes tinha
            `gap-x-[20px]` próprio porque as caixas 16:9 de cantos retos
            coladas não se distinguiam; hoje o card tem cantos `rounded-2xl` e
            glow como o `AnimeCard`, então segue o mesmo padrão. O respiro só
            fica ENTRE os slots — a borda de fora do primeiro/último card
            continua colada no gutter. Scrollbar escondida nos
            dois motores (Firefox / WebKit). `--por-pagina` (via
            `CLASSES_POR_PAGINA[tamanho]`) por breakpoint aqui, nunca como prop
            numérica. */}
        <ul
          ref={trilhaRef}
          id={idTrilha}
          onScroll={medirLimites}
          className={`isolate flex overflow-x-auto [&:has(li:hover)>li:not(:hover)]:z-1 ${CLASSE_GUTTER} pointer-events-none -mt-[58px] -mb-[44px] pt-[80px] pb-[88px] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden ${
            CLASSE_RESPIRO_POSTER
          } ${CLASSES_POR_PAGINA[tamanho] ?? CLASSES_POR_PAGINA.grande}`}
        >
          {lista.map((item, indice) => (
            <li
              key={chaveDoItem(item)}
              className="pointer-events-auto relative shrink-0 grow-0"
              style={{ flexBasis: FLEX_BASIS_SLOT_COM_RESPIRO }}
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

// Indicador de "página" da fileira, em pílulas — pedido explícito do usuário
// (2026-09-21): mesma altura pra todas, só a ATIVA muda de cor (não elonga,
// ver decisão do usuário sobre o estilo). Também clicável (pedido do mesmo
// dia): cada pílula é um `<button>` que chama `aoClicar(indice)` (=
// `irParaPagina` em FileiraDeCards) — por isso `aria-label` próprio por
// pílula em vez do `aria-hidden` de quando era só decorativo, e
// `aria-current` na ativa pro mesmo padrão de "página atual" de paginação.
// `total <= 1` (conteúdo cabe sem rolar) não renderiza nada, nunca uma
// pílula solitária sem sentido (e sem botão fantasma que não rola nada).
function PilulasDePaginacao({ atual, total, titulo, aoClicar }) {
  if (total <= 1) return null;
  return (
    <div className="flex shrink-0 items-center gap-1.5">
      {Array.from({ length: total }, (_, indice) => (
        <button
          key={indice}
          type="button"
          onClick={(evento) => {
            aoClicar(indice);
            if (evento.detail > 0) evento.currentTarget.blur();
          }}
          aria-label={`Página ${indice + 1} de ${total}: ${titulo}`}
          aria-current={indice === atual ? 'true' : undefined}
          className={`h-2 w-8 cursor-pointer rounded-full outline-none transition-colors duration-300 motion-reduce:transition-none focus-visible:ring-2 focus-visible:ring-neon ${
            indice === atual ? 'bg-neon' : 'bg-white/25 hover:bg-white/40'
          }`}
        />
      ))}
    </div>
  );
}

import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { usePrefersReducedMotion } from './usePrefersReducedMotion.js';
import { traduzirGenero } from './generos.js';

// Carrossel "billboard" da home (estilo Hulu/Disney+): um destaque grande por
// vez com espiada (peek) dos vizinhos, alimentado pelo feed
// `GET /api/animes/em-alta`. Substitui visualmente o DestaquePrincipal único
// (inicio/DestaquePrincipal.jsx, hoje não renderizado). Não há botão de CTA:
// o slide ativo inteiro é clicável — abre `/anime/:id` quando já catalogado,
// senão materializa o item do feed (`aoMaterializar`) e navega pro anime criado.
//
// O feed chega com até 50 itens; o carrossel mostra uma JANELA de 15 que
// desliza pelo pool a cada 10 min (e a cada reload, via relógio) — herda da
// antiga GradeRotativa o papel de não deixar a home presa nos mesmos
// destaques. Ver `TAMANHO_DA_JANELA` / `INTERVALO_ROTACAO_MS`.
//
// Geometria (ponto sensível): a máscara externa é `overflow-hidden`, NÃO
// scroll do usuário — rolagem manual dessincronizaria o índice. Ela leva
// `py-16 -my-16`: o padding afasta as bordas de clipe pra cima/baixo o
// bastante pra sombra do slide ativo (que projeta pra baixo) não ser cortada,
// e a margem negativa devolve esse espaço ao fluxo (largura e ritmo vertical
// intactos). O track é um flex; cada slide ocupa `--slide-w` (< 100%, e é daí
// que sai o peek, sem
// margin/padding negativo) e o track desliza `--slide-w + --slide-gap` por
// passo via `transform: translateX(calc(...))`, com meia-folga inicial pra
// centralizar o slide ativo. O gap vem de uma variável (`--slide-gap`), não
// de uma classe `gap-4`, pra não repetir o mesmo número dentro do `calc`
// (mesma armadilha documentada em inicio/GradeDeCards.jsx). As proporções e
// larguras seguem a medição do carrossel do Disney+ (card ~92,6% da largura,
// ~2,93:1 no desktop). A `<section>` NÃO tem `max-w`/`mx-auto`: ocupa toda a
// largura do `<main>` (full-bleed, como a área do carrossel do Disney+); o
// peek de ~3,7% de cada lado é o único respiro horizontal.
//
// Loop infinito (estilo Disney+): a lista base é renderizada 3x concatenada e
// `pos` — o índice de render do slide ativo dentro dessas cópias — começa na
// cópia do MEIO. Avançar/voltar mexe `pos` de 1 em 1 com transição; quando
// `pos` sai da faixa da cópia do meio `[n, 2n)`, depois que a animação assenta
// (`onTransitionEnd`) ele salta pro ponto equivalente da cópia do meio SEM
// transição (`semTransicao` tira a classe por 1 frame). Como as três cópias
// são idênticas, o salto é imperceptível — os dois peeks nunca ficam vazios e
// o wrap não "rebobina". Sem animação (movimento reduzido, ou clique rápido
// que empurra `pos` pros extremos das cópias) a normalização acontece direto
// num efeito, aceitando o corte da animação pra nunca renderizar slot vazio.
//
// A11y: perfil mínimo do padrão "carrossel" do WAI-ARIA APG. Só o slide
// central é interativo — todos os outros `<li>` (peeks e cópias) ficam `inert`
// (remove foco/tab/clique/árvore de a11y de uma vez), então os CTAs
// triplicados no DOM não entram no tab order. Setas e bolinhas têm rótulo e
// `focus-visible`; a navegação por seta do teclado fica presa à `<section>`
// (sem listener global). O track tem `aria-live` (silencioso enquanto o
// auto-avanço roda; `polite` quando parado por hover/foco/`prefers-reduced-
// motion`) e o auto-avanço reagenda um `setTimeout` por slide — gate por
// `ativa`, hover/foco e movimento reduzido.

// Quantos destaques o carrossel mostra de uma vez. O feed "em alta" chega com
// até 50 itens (`perPage: 50` na AniList); em vez de cortar nos 15 primeiros
// para sempre, essa é uma JANELA que desliza pelo pool inteiro ao longo do
// tempo (ver `blocoDaJanela` / `INTERVALO_ROTACAO_MS`), no lugar da rotação de
// lotes que a antiga GradeRotativa fazia.
const TAMANHO_DA_JANELA = 15;

// Janela do auto-avanço. `setTimeout` reagendado a cada slide (não
// `setInterval`): navegação manual muda `pos`, o efeito reexecuta e a
// contagem de 10s reinicia de graça.
const INTERVALO_MS = 10000;

// A cada 10 min (mesmo intervalo da antiga GradeRotativa) a janela avança um
// bloco pelo pool. O bloco inicial vem do relógio (`Date.now()`), não de 0:
// dois reloads dentro da mesma janela de 10 min mostram o mesmo recorte e não
// há "drift" entre abas.
const INTERVALO_ROTACAO_MS = 600000;

// Sombra do slide ativo — `box-shadow` computado medido ao vivo no billboard
// do Disney+. Via `style` inline, NÃO classe Tailwind: o parser de valor
// arbitrário do Tailwind v4 não gera de forma confiável uma sombra de 2
// camadas que começa pela cor, então `shadow-[#hex_0_26px...]` era emitida na
// classe mas sem regra CSS correspondente.
// Exportada: `inicio/FileiraDeCards.jsx` reusa o mesmo valor nos slots das
// fileiras (o usuário pediu a sombra do billboard nos cards, não o "sem
// sombra" do Disney+ real) — fonte única, se a sombra for retunada muda nos
// dois lugares de uma vez.
export const SOMBRA_SLIDE_ATIVO =
  'rgba(0,0,0,0.69) 0 26px 30px -10px, rgba(0,0,0,0.73) 0 16px 10px -10px';

// `numeric: 'auto'` dá "amanhã"/"hoje" em vez de "em 1 dia"/"em 0 dias".
// Instância única de módulo — recriar por render é caro.
const rtf = new Intl.RelativeTimeFormat('pt-BR', { numeric: 'auto' });

// Texto relativo em dias até `iso`. Só chamado com data futura (dias >= 0).
function relativo(iso) {
  const dias = Math.round((new Date(iso) - new Date()) / 86400000);
  return rtf.format(dias, 'day');
}

// Frase curta derivada do item do feed. Ordem importa — para no primeiro match.
// Nunca promete disponibilidade ("já disponível"): o item pode nem estar
// catalogado. Sem match → null e a linha da tagline não renderiza.
function taglineDoItem(item) {
  const epEm = item.proximo_ep_em;
  const futuro = Boolean(epEm) && new Date(epEm) > new Date();
  if (futuro && item.proximo_ep_numero != null) {
    return `Episódio ${item.proximo_ep_numero} ${relativo(epEm)}`;
  }
  if (futuro) return `Novo episódio ${relativo(epEm)}`;
  if (item.status_lancamento === 'em_lancamento') return 'Em lançamento';
  if (item.status_lancamento === 'finalizado') return 'Temporada completa';
  return null;
}

export default function CarrosselDestaques({ itens, ativa, aoMaterializar, materializando }) {
  const idTitulo = useId();
  const idSlides = useId();
  const trackRef = useRef(null);

  const pool = useMemo(() => itens ?? [], [itens]);

  // Deslocamento da janela, em BLOCOS de `TAMANHO_DA_JANELA`. Nasce do relógio
  // (não de 0) pra que o recorte também mude entre reloads, não só enquanto a
  // aba fica aberta.
  const [blocoDaJanela, setBlocoDaJanela] = useState(() =>
    Math.floor(Date.now() / INTERVALO_ROTACAO_MS),
  );

  // Recorte visível: `TAMANHO_DA_JANELA` itens a partir do bloco atual,
  // circulando pelo pool (`% pool.length`) — mesma fórmula de rotação da
  // GradeRotativa. `n` fica fixo em `TAMANHO_DA_JANELA` sempre que o pool é
  // grande o bastante, então as 3 cópias, as bolinhas e a normalização não
  // mudam de tamanho quando a janela gira.
  const base = useMemo(() => {
    const tamanho = Math.min(TAMANHO_DA_JANELA, pool.length);
    if (tamanho === 0) return [];
    const inicio = (blocoDaJanela * TAMANHO_DA_JANELA) % pool.length;
    return Array.from({ length: tamanho }, (_, i) => pool[(inicio + i) % pool.length]);
  }, [pool, blocoDaJanela]);
  const n = base.length;

  // `pos` é o índice DE RENDER do slide ativo dentro das 3 cópias. Já nasce na
  // cópia do meio (índice `n`): o feed sempre chega preenchido (o pai só monta
  // o carrossel com `itens.length > 0`), então não há varredura de
  // posicionamento no mount.
  const [pos, setPos] = useState(() => {
    const inicial = Math.min(TAMANHO_DA_JANELA, (itens ?? []).length);
    return inicial >= 2 ? inicial : 0;
  });
  // Pausa é `useState` (não `useRef` como em GradeRotativa): o valor entra no
  // gate `autoAvancando`, que também alimenta o `aria-live` do track no render.
  const [pausado, setPausado] = useState(false);
  // Liga por 1 frame no salto de normalização: sem a classe de transição o
  // track pula pra cópia do meio sem animar.
  const [semTransicao, setSemTransicao] = useState(false);
  const movimentoReduzido = usePrefersReducedMotion();

  // Índice lógico (0..n-1) do slide ativo, invariante às 3 cópias e a `pos`
  // fora de faixa. Alimenta bolinhas (`aria-current`), o rótulo "X de n" e o
  // alvo da normalização.
  const indiceLogico = n > 0 ? ((pos % n) + n) % n : 0;

  // Navegação por passo: move `pos` de 1 em 1 (forma funcional — não depende
  // de `pos`, `useCallback` estável). A normalização devolve `pos` pra faixa
  // da cópia do meio depois.
  const avancar = useCallback((delta) => {
    setPos((p) => p + delta);
  }, []);

  // Bolinha: vai pro `indiceLogico === i` pela cópia mais próxima de `pos`,
  // pra animar o caminho curto em vez de varrer a lista toda.
  const irParaLogico = useCallback(
    (i) => {
      setPos((p) =>
        [i, i + n, i + 2 * n].reduce((a, b) =>
          Math.abs(b - p) < Math.abs(a - p) ? b : a,
        ),
      );
    },
    [n],
  );

  // Normalização (snap back): traz `pos` pra dentro de `[n, 2n)` quando sai.
  // Só age direto quando não há animação a preservar — movimento reduzido,
  // logo após um salto (`semTransicao`) ou clique rápido que empurrou `pos`
  // pros extremos das cópias; o caminho animado normal espera
  // `onTransitionEnd`.
  useEffect(() => {
    if (n < 2) return;
    if (pos >= n && pos < 2 * n) return;
    const semAnimacao =
      movimentoReduzido || semTransicao || pos <= 1 || pos >= 3 * n - 2;
    if (semAnimacao) {
      setSemTransicao(true);
      setPos(indiceLogico + n);
    }
  }, [pos, n, movimentoReduzido, semTransicao, indiceLogico]);

  // Religa a transição no frame seguinte ao salto — o `transform` novo já está
  // pintado, então repor a classe não anima nada.
  useEffect(() => {
    if (!semTransicao) return undefined;
    const id = requestAnimationFrame(() => setSemTransicao(false));
    return () => cancelAnimationFrame(id);
  }, [semTransicao]);

  // Ref-espelho de `pausado`: o timer de rotação é longo (10 min) e não deve
  // ser recriado a cada hover/foco (recriar reiniciaria a contagem). Mesmo
  // truque do `pausadoRef` da antiga GradeRotativa.
  const pausadoRef = useRef(pausado);
  useEffect(() => {
    pausadoRef.current = pausado;
  }, [pausado]);

  // Rotação da janela: a cada `INTERVALO_ROTACAO_MS` avança um bloco pelo pool.
  // Gate por `ativa` (não gira atrás da introdução) e por haver mais itens que
  // a janela. Hover/foco só adiam o próximo avanço (via `pausadoRef`), não
  // reiniciam o timer.
  useEffect(() => {
    if (!ativa || pool.length <= TAMANHO_DA_JANELA) return undefined;
    const id = setInterval(() => {
      if (!pausadoRef.current) setBlocoDaJanela((b) => b + 1);
    }, INTERVALO_ROTACAO_MS);
    return () => clearInterval(id);
  }, [ativa, pool.length]);

  // Janela girou: o recorte inteiro trocou de conteúdo. Corta pro começo da
  // cópia do meio SEM animar (mesmo `semTransicao` da normalização) — um
  // "pulo" de um slide seria incoerente com 15 itens trocando de uma vez.
  // `montadoRef` pula o primeiro run (no mount `pos` já nasce em `n`).
  const montadoRef = useRef(false);
  useEffect(() => {
    if (!montadoRef.current) {
      montadoRef.current = true;
      return;
    }
    setSemTransicao(true);
    setPos(n);
  }, [blocoDaJanela, n]);

  // Gate único do auto-avanço, reusado no efeito e no `aria-live` do track:
  // intro revelada (`ativa`), sem preferência por menos movimento, sem pausa
  // por hover/foco e com mais de um destaque.
  const autoAvancando = ativa && !movimentoReduzido && !pausado && n > 1;

  // Cadeia de timeouts: cada disparo avança 1 slide; ao mudar `pos` (inclusive
  // por navegação manual) o efeito reexecuta e a janela de 7s reinicia. Fora
  // do gate não agenda nada.
  useEffect(() => {
    if (!autoAvancando) return undefined;
    const proximo = pos + 1;
    const id = setTimeout(() => setPos(proximo), INTERVALO_MS);
    return () => clearTimeout(id);
  }, [autoAvancando, pos]);

  if (n === 0) return null;

  const mostrarControles = n > 1;
  const loop = n >= 2;
  const slides = loop ? [...base, ...base, ...base] : base;
  const deslocamento = loop ? pos : 0;

  const aoTeclar = (evento) => {
    if (!mostrarControles) return;
    if (evento.key === 'ArrowLeft') {
      evento.preventDefault();
      avancar(-1);
    } else if (evento.key === 'ArrowRight') {
      evento.preventDefault();
      avancar(1);
    }
  };

  // Depois de acionar um controle por PONTEIRO (mouse/toque), tira o foco dele.
  // Sem isto a `<section>` fica "com foco dentro": o auto-avanço trava pausado
  // e a seta continua visível até um clique fora do carrossel. `evento.detail
  // === 0` = acionado por teclado (Enter/Espaço) — aí o foco fica, pra não
  // perder o lugar na navegação.
  const desfocarSePonteiro = (evento) => {
    if (evento.detail > 0) evento.currentTarget.blur();
  };

  // Depois que a varredura de 1 passo assenta: se `pos` caiu fora da cópia do
  // meio, salta pro ponto equivalente sem transição. Filtra o `transitionend`
  // do próprio track (a `transform`), ignorando o `box-shadow` dos `<li>`.
  const aoFimDaTransicao = (evento) => {
    if (!loop) return;
    if (evento.target !== trackRef.current || evento.propertyName !== 'transform') {
      return;
    }
    if (pos >= n && pos < 2 * n) return;
    setSemTransicao(true);
    setPos(indiceLogico + n);
  };

  return (
    <section
      aria-roledescription="carrossel"
      aria-labelledby={idTitulo}
      onKeyDown={aoTeclar}
      onMouseEnter={() => setPausado(true)}
      onMouseLeave={() => setPausado(false)}
      onFocus={() => setPausado(true)}
      onBlur={() => setPausado(false)}
    >
      <h2 id={idTitulo} className="sr-only">
        Destaques da temporada
      </h2>

      <div className="group relative">
        {/* `py-16 -my-16`: espaço de clipe pra sombra do slide ativo sem
            mexer no layout — ver bloco de geometria no topo do arquivo. */}
        <div className="overflow-hidden py-16 -my-16">
          <ul
            ref={trackRef}
            id={idSlides}
            aria-live={autoAvancando ? 'off' : 'polite'}
            onTransitionEnd={aoFimDaTransicao}
            style={{
              '--slide-gap': '1.5rem',
              gap: 'var(--slide-gap)',
              transform: `translateX(calc((100% - var(--slide-w)) / 2 - ${deslocamento} * (var(--slide-w) + var(--slide-gap))))`,
            }}
            className={`flex [--slide-w:88%] sm:[--slide-w:90%] lg:[--slide-w:92.6%] ${
              semTransicao
                ? ''
                : 'transition-transform duration-500 ease-out motion-reduce:transition-none'
            }`}
          >
            {slides.map((item, k) => {
              const ativo = loop ? k === pos : true;
              const titulo = item.titulo_romaji || item.titulo_ingles;
              // Sem arte horizontal: só temos o pôster retrato pra trabalhar.
              const semBanner = !item.banner_url && Boolean(item.capa_url);
              const fonteImagem = item.banner_url || item.capa_url || null;
              const primeiroDestaque = k % n === 0;

              const tag = taglineDoItem(item);
              const generosTraduzidos = (item.generos ?? [])
                .slice(0, 3)
                .map((g) => traduzirGenero(g));
              const meta = [item.ano_estreia, generosTraduzidos.join(', ')]
                .filter(Boolean)
                .join(' • ');

              return (
                <li
                  key={k}
                  role="group"
                  aria-roledescription="slide"
                  aria-label={`${(k % n) + 1} de ${n}: ${titulo}`}
                  inert={!ativo}
                  // `semBanner` + cor dominante da capa (AniList `coverImage.color`):
                  // a cor entra como fundo do slide, sob o blur da capa (ver o
                  // primeiro <img> abaixo). `bg-surface` continua de fallback
                  // quando `capa_cor` é null — item do Kitsu, ou `color: null`
                  // da própria AniList.
                  style={{
                    ...(ativo && { boxShadow: SOMBRA_SLIDE_ATIVO }),
                    ...(semBanner &&
                      item.capa_cor && { backgroundColor: item.capa_cor }),
                  }}
                  // `group/slide`: gatilho do hover da BORDA. Grupo NOMEADO no
                  // próprio `<li>` (não no `group` da máscara, que é full-bleed
                  // e ainda transborda 64px em Y) pra a borda só acender sobre a
                  // área do card ativo, não nos peeks/faixas vazias. Os `<li>`
                  // inertes não casam `:hover`, então pôr em todos é inofensivo.
                  className="group/slide relative aspect-[16/10] max-h-[40rem] shrink-0 grow-0 basis-[var(--slide-w)] overflow-hidden rounded-[18px] bg-surface transition-shadow duration-300 sm:aspect-[7/3] lg:aspect-[1783/608]"
                >
                  {fonteImagem && (
                    <img
                      src={fonteImagem}
                      alt=""
                      loading={primeiroDestaque ? undefined : 'lazy'}
                      decoding={primeiroDestaque ? undefined : 'async'}
                      className={
                        semBanner
                          ? // a capa borrada/escurecida é só textura por cima da
                            // cor dominante — em TODOS os breakpoints, não mais
                            // a arte recortada nítida abaixo de `lg`. `opacity-70`
                            // deixa a cor de fundo do <li> aparecer atrás.
                            'absolute inset-0 h-full w-full object-cover scale-125 blur-lg brightness-[0.5] opacity-70'
                          : 'absolute inset-0 h-full w-full object-cover'
                      }
                    />
                  )}

                  {/* Sem banner (`semBanner`): o fundo do slide é a cor
                      dominante da capa (`item.capa_cor`, via `style` no `<li>`
                      acima), com a própria capa borrada por cima como textura
                      (o primeiro <img>). Só de `lg` pra cima o pôster também
                      entra NÍTIDO como card na lateral direita (oposta ao
                      texto) — abaixo disso não há largura pro pôster ao lado do
                      texto: fica só cor + capa borrada + gradiente + título.
                      Mesma URL do fundo, então sem download extra. */}
                  {semBanner && (
                    <img
                      src={item.capa_url}
                      alt=""
                      loading={primeiroDestaque ? undefined : 'lazy'}
                      decoding={primeiroDestaque ? undefined : 'async'}
                      className="absolute right-14 top-1/2 hidden aspect-[2/3] h-[82%] -translate-y-1/2 rounded-xl object-cover shadow-2xl shadow-black/60 ring-1 ring-white/10 lg:block"
                    />
                  )}

                  <div
                    className={
                      semBanner
                        ? 'pointer-events-none absolute inset-0 bg-gradient-to-r from-black/90 via-black/45 to-black/15 lg:to-transparent'
                        : 'pointer-events-none absolute inset-0 bg-gradient-to-r from-black/95 via-black/55 to-black/10'
                    }
                  />

                  {/* Slide ativo inteiro clicável (sem botão de CTA): navega
                      pro anime catalogado ou materializa o item do feed. Os
                      peeks/cópias não recebem clique — o `<li>` não-ativo é
                      `inert`. A camada de texto abaixo é `pointer-events-none`
                      pra não roubar o clique deste overlay. */}
                  {ativo &&
                    (item.anime_id != null ? (
                      <Link
                        to={`/anime/${item.anime_id}`}
                        aria-label={`${titulo} — ver episódios`}
                        className="absolute inset-0 z-10 rounded-[18px] outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-neon"
                      />
                    ) : (
                      <button
                        type="button"
                        onClick={() => aoMaterializar(item)}
                        disabled={materializando}
                        aria-label={`Adicionar ${titulo} ao catálogo`}
                        className="absolute inset-0 z-10 rounded-[18px] outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-neon disabled:cursor-progress"
                      />
                    ))}

                  <div className="pointer-events-none absolute inset-y-0 left-0 flex max-w-[min(90%,42rem)] flex-col items-start justify-center gap-2 px-6 md:px-10 lg:px-14">
                    <h3 className="line-clamp-3 text-2xl font-black uppercase tracking-tight text-white sm:text-4xl lg:text-5xl">
                      {titulo}
                    </h3>
                    <p className="text-sm font-semibold text-white/90 sm:text-base">
                      {item.anime_id != null
                        ? 'Anime já no catálogo'
                        : materializando
                          ? 'Adicionando…'
                          : ''}
                    </p>
                    {meta && <p className="text-xs text-ink-muted sm:text-sm">{meta}</p>}
                    {tag && <p className="text-xs text-white/70 sm:text-sm">{tag}</p>}
                  </div>
                  {/* Borda do slide ativo: overlay por CIMA da imagem/gradiente
                      (um `ring`/`border` no próprio `<li>` fica atrás dos filhos
                      `absolute inset-0` e aparece só nas frestas). `border-4
                      border-transparent` reserva a espessura; acende só no hover
                      do CARD ativo (`group/slide`, não a máscara full-bleed),
                      igual ao Disney+ (traço limpo, sem glow), na cor neon. */}
                  {ativo && (
                    <div
                      aria-hidden="true"
                      className="pointer-events-none absolute inset-0 rounded-[18px] border-4 border-transparent transition-colors duration-200 group-hover/slide:border-neon motion-reduce:transition-none"
                    />
                  )}
                </li>
              );
            })}
          </ul>
        </div>

        {mostrarControles && (
          <>
            <button
              type="button"
              onClick={(evento) => {
                avancar(-1);
                desfocarSePonteiro(evento);
              }}
              aria-label="Destaque anterior"
              aria-controls={idSlides}
              className="absolute inset-y-0 left-2 z-10 flex w-6 items-center justify-center rounded-lg text-8xl text-white/60 opacity-0 outline-none transition hover:text-white focus-visible:opacity-100 focus-visible:ring-2 focus-visible:ring-neon group-hover:opacity-100"
            >
              <span aria-hidden="true">‹</span>
            </button>
            <button
              type="button"
              onClick={(evento) => {
                avancar(1);
                desfocarSePonteiro(evento);
              }}
              aria-label="Próximo destaque"
              aria-controls={idSlides}
              className="absolute inset-y-0 right-2 z-10 flex w-6 items-center justify-center rounded-lg text-8xl text-white/60 opacity-0 outline-none transition hover:text-white focus-visible:opacity-100 focus-visible:ring-2 focus-visible:ring-neon group-hover:opacity-100"
            >
              <span aria-hidden="true">›</span>
            </button>
          </>
        )}
      </div>

      {mostrarControles && (
        // `relative z-10`: sem isto os cliques nas bolinhas não chegam. O
        // `<div className="group relative">` acima é posicionado e sua máscara
        // `overflow-hidden py-16 -my-16` transborda ~64px pra baixo, cobrindo
        // esta faixa; como elemento posicionado ele é pintado DEPOIS deste
        // container (estático) e intercepta o ponteiro. Posicionar o container
        // e elevá-lo devolve o clique.
        <div className="relative z-10 mt-6 flex flex-wrap justify-center gap-2">
          {base.map((item, i) => (
            <button
              key={item.anilist_id ?? item.titulo_romaji ?? i}
              type="button"
              onClick={(evento) => {
                irParaLogico(i);
                desfocarSePonteiro(evento);
              }}
              aria-label={`Ir para o destaque ${i + 1}`}
              aria-current={i === indiceLogico ? 'true' : undefined}
              className="group/dot flex h-6 w-6 items-center justify-center rounded-full outline-none focus-visible:ring-2 focus-visible:ring-neon"
            >
              <span
                aria-hidden="true"
                className={`block h-2 w-2 rounded-full transition motion-reduce:transition-none ${
                  i === indiceLogico
                    ? 'scale-125 bg-white'
                    : 'bg-white/40 group-hover/dot:bg-white/70'
                }`}
              />
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
// Re-exportado por components/LinhaDeEpisodio.jsx — `src/inicio/` não importa
// de `src/player/` direto (fronteira Clean Architecture, ver paginas/Inicio.jsx).
// Mesmo ícone do CTA "Assistir agora" que inicio/DestaqueGrande.jsx reusa.
import { IconePlay } from '../components/LinhaDeEpisodio.jsx';
import IconeSeta from './IconeSeta.jsx';
import {
  embaralharComSemente,
  INTERVALO_ROTACAO_MS,
  TAMANHO_DA_JANELA,
} from './janelaDeDestaques.js';
import { usePrefersReducedMotion } from './usePrefersReducedMotion.js';
import { traduzirGenero } from './generos.js';
import BlocoConteudoHero from './BlocoConteudoHero.jsx';
import SinopseEmFoco from '../components/SinopseEmFoco.jsx';

// Hero da home (estilo AnimeFire): banner full-width com imagem de fundo e
// gradiente escuro, um destaque por vez, alimentado pelo feed
// `GET /api/animes/em-alta`. Substitui visualmente o DestaquePrincipal único
// (inicio/DestaquePrincipal.jsx, hoje não renderizado) e o antigo layout de
// carrossel "billboard" com peek dos vizinhos (estilo Hulu/Disney+) — a
// imagem agora cobre 100% da largura da seção, sem card com bordas
// arredondadas nem sombra flutuando sobre o fundo da página; é a própria
// seção.
//
// Cada slide tem um bloco de conteúdo ancorado embaixo-esquerda: pill de
// ranking (`#N em alta`, posição do item no feed já ordenado), título (link
// pra `/anime/:id` quando catalogado), título alternativo e UM botão primário
// de CTA. O slide NÃO é mais clicável inteiro — o botão é o único alvo de
// navegação/materialização (mais o link do título quando catalogado): `<Link>`
// "Assistir agora" pro anime já catalogado, `<button>` "Adicionar ao Catálogo"
// (`aoMaterializar`) pro item do feed ainda não catalogado.
//
// O feed chega com até 50 itens; o carrossel mostra 15 deles, sorteados do
// pool por um embaralhamento com semente no relógio (ver `embaralharComSemente`
// / `blocoDaJanela`) — ordem aparentemente aleatória, não a ordem de ranking do
// feed. A cada 10 min (e a cada reload) a semente muda: novo recorte e nova
// ordem — herda da antiga GradeRotativa o papel de não deixar a home presa nos
// mesmos destaques. `TAMANHO_DA_JANELA` / `INTERVALO_ROTACAO_MS` /
// `embaralharComSemente` vêm de ./janelaDeDestaques.js (fonte única —
// paginas/Inicio.jsx reproduz este recorte pra excluí-lo dos destaques
// grandes).
//
// Geometria: a máscara externa é `overflow-hidden`, NÃO scroll do usuário —
// rolagem manual dessincronizaria o índice. Os slides ficam todos empilhados
// (`absolute inset-0`) sobre a mesma área — a troca é um CROSSFADE de opacity
// (não mais slide lateral por `translateX`, trocado a pedido do usuário,
// 2026-09-20: o movimento lateral em si não agradava, independente de
// velocidade). A `<section>` NÃO tem `max-w`/`mx-auto`: ocupa toda a largura
// do `<main>` (full-bleed). As bolinhas de paginação ficam SOBREPOSTAS na
// imagem, dentro do hero (`absolute bottom-*`), não numa faixa abaixo dele.
//
// Loop: com crossfade não existe "rebobinar" pra disfarçar (isso só era
// problema pra slide lateral) — `indiceAtivo` é só `0..n-1` e avança/volta
// com módulo (`(i + delta + n) % n`), sem cópias triplicadas da lista nem
// normalização de posição. Bem mais simples que o mecanismo antigo.
//
// A11y: perfil mínimo do padrão "carrossel" do WAI-ARIA APG. Só o slide
// ativo é interativo — todos os outros `<li>` ficam `inert` (remove foco/tab/
// clique/árvore de a11y de uma vez, inclusive hit-testing do crossfade
// empilhado), então o botão de CTA e o link do título dos slides invisíveis
// não entram no tab order. Setas e bolinhas têm rótulo e `focus-visible`; a
// navegação por seta do teclado fica presa à `<section>` (sem listener
// global). O contêiner de slides tem `aria-live` (silencioso enquanto o
// auto-avanço roda; `polite` quando parado por hover/foco/
// `prefers-reduced-motion`) e o auto-avanço reagenda um `setTimeout` por slide
// — gate por hover/foco e movimento reduzido.

// `TAMANHO_DA_JANELA` (destaques por vez) e `INTERVALO_ROTACAO_MS` (de quanto
// em quanto a janela desliza pelo pool), junto com `embaralharComSemente`,
// moram em ./janelaDeDestaques.js — fonte única, porque paginas/Inicio.jsx
// reproduz o mesmo recorte pra excluí-lo dos "destaques grandes".

// Janela do auto-avanço. `setTimeout` reagendado a cada slide (não
// `setInterval`): navegação manual muda `indiceAtivo`, o efeito reexecuta e a
// contagem de 10s reinicia de graça.
const INTERVALO_MS = 10000;

// Sombra "flutuante" usada pelos cards da Galeria/fileiras
// (GradeDeCatalogo.jsx, FileiraDeCards.jsx, DestaqueGrande.jsx) e pela capa no
// header de PaginaDoAnime.jsx — `box-shadow` computado medido ao vivo no
// antigo billboard do Disney+, via `style` inline (não classe Tailwind: o
// parser de valor arbitrário do Tailwind v4 não gera de forma confiável uma
// sombra de 2 camadas que começa pela cor). Este arquivo não usa mais
// localmente — o hero agora é um banner full-bleed, sem card flutuando sobre
// o fundo — mas o export segue como fonte única pra quem ainda precisa dela.
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

// Texto do próximo episódio a partir de `proximo_ep_em`/`proximo_ep_numero`.
// Sem data (ausente, ou já no passado/dado inválido — ex. `status_lancamento
// === 'finalizado'`) retorna null e a linha simplesmente não renderiza, nunca
// "Invalid Date"/"NaN dias". `relativo`/`rtf` acima continuam locais.
export function textoProximoEpisodio(item) {
  const epEm = item.proximo_ep_em;
  if (!epEm) return null;
  const data = new Date(epEm);
  if (Number.isNaN(data.getTime()) || data <= new Date()) return null;
  const quando = relativo(epEm);
  return item.proximo_ep_numero != null
    ? `Ep.${item.proximo_ep_numero} ${quando}`
    : `Novo episódio ${quando}`;
}

// Backdrops do TMDB chegam do feed em `w1280` (ver backend/integrations/tmdb.py
// `_TAMANHO_BACKDROP`). O hero é full-bleed (>=1920px): w1280 sob `object-cover`
// é upscale visível. Os tamanhos de backdrop do TMDB são w300/w780/w1280/original
// — nada entre w1280 e original —, então pro hero sobe direto pra `original`.
// URL de outra origem (banner da AniList, capa) passa intacta. Exportada —
// fonte única: o hero de paginas/PaginaDoAnime.jsx usa a mesma normalização
// pro `banner_path` do anime catalogado.
export function imagemEmAltaResolucao(url) {
  if (!url) return url;
  return url.replace(
    /^(https:\/\/image\.tmdb\.org\/t\/p\/)w\d+(\/)/,
    '$1original$2',
  );
}

// Gradiente do hero — pseudo-::before empilhado no AnimeFire: 3 camadas na
// cor EXATA do fundo da página, pra base do hero se dissolver nela sem
// emenda. Função, não mais constante: `paginas/Inicio.jsx` e
// `paginas/PaginaDoAnime.jsx` compartilhavam UM `#17171b` fixo até este
// dissolver ficar hardcoded — hoje a Home é `bg-black` sólido
// (paginas/Inicio.jsx) e a página do anime ainda é `#17171b`
// (paginas/PaginaDoAnime.jsx), então cada hero passa a PRÓPRIA cor de fundo
// em vez de uma compartilhada. Inline no `style` (não a função em si, o
// gradiente que ela devolve): o parser de multi-gradiente de valor arbitrário
// do Tailwind v4 não é confiável (mesmo motivo de `SOMBRA_SLIDE_ATIVO`).
// Exportada — fonte única, o hero de paginas/PaginaDoAnime.jsx chama a mesma
// função com a própria cor. Stops em 60/55/70% (subiram de 45/40/60%) —
// pedido explícito do usuário: o preto sólido precisa aparecer mais cedo,
// sobrando mais área atrás do bloco de texto em vez de ainda estar sobre a
// arte quando o texto começa.
export function gradienteHero(cor) {
  return `linear-gradient(to top, ${cor}, transparent 60%), linear-gradient(to top, ${cor}, transparent 55%), linear-gradient(77deg, ${cor}, transparent 70%)`;
}
// Sem arte horizontal (`semBanner`): só o pôster retrato borrado atrás do
// texto — uma camada extra à esquerda mantém o texto legível sobre ele.
// Também exportada (mesmo fallback no hero de paginas/PaginaDoAnime.jsx).
export function gradienteHeroSemBanner(cor) {
  return `linear-gradient(to right, ${cor}, transparent 60%), ${gradienteHero(cor)}`;
}

// `#rgb`/`#rrggbb` → `[r, g, b]`. Só pra montar `rgba()` abaixo — os
// chamadores de `gradienteHero*` sempre passam hex ('#000', '#17171b'),
// nunca `rgb()`/nome de cor.
function hexParaRgb(hex) {
  const digitos = hex.replace('#', '');
  const seisDigitos = digitos.length === 3 ? digitos.split('').map((c) => c + c).join('') : digitos;
  const inteiro = parseInt(seisDigitos, 16);
  return [(inteiro >> 16) & 255, (inteiro >> 8) & 255, inteiro & 255];
}

// Curva de alfa aproximando um "ease-out" (técnica easing-gradients,
// larsenwork.com/easing-gradients): um `linear-gradient(cor, transparent)`
// de 2 stops varia a OPACIDADE de forma linear, mas o olho não percebe
// opacidade de forma linear — a queda perto da ponta opaca salta à vista
// muito menos do que a matemática sugere, então o trecho inicial parece uma
// "prateleira" sólida antes de qualquer coisa acontecer, seguido de uma
// queda que parece repentina em comparação. Os stops abaixo (alfa explícito
// via `rgba`, não `color-mix` — a 1ª tentativa usava `color-mix` e não dava
// pra confirmar render em todo navegador) compensam isso. Tentativa anterior
// empilhando várias camadas de 2 stops cada (`transparent P%` em paralelo)
// parecia que ia suavizar, mas multiplicar várias curvas LINEARES perto do
// zero (`1 - ∏(1-αᵢ)`) cria exatamente essa prateleira plana antes de cair —
// pior que uma única camada. Só uma camada com os alfas certos em cada stop
// resolve. Pares [posição 0..1 ao longo do alcance do fade, alfa 0..1].
const ESTAGIOS_ALFA_SUAVE = [
  [0, 1],
  [0.19, 0.85],
  [0.34, 0.65],
  [0.47, 0.47],
  [0.565, 0.32],
  [0.65, 0.2],
  [0.73, 0.11],
  [0.803, 0.05],
  [0.87, 0.02],
  [0.925, 0.005],
  [1, 0],
];

// Gradiente linear na `direcao` dada, com a curva suave acima em vez de
// 2 stops crus — `alcance` é até onde (em %) o fade termina transparente.
// Exportada — inicio/DestaqueGrande.jsx reusa pro próprio overlay (2 stops
// crus caíam de forma linear, o que o olho percebe como corte brusco perto da
// ponta opaca; ver ESTAGIOS_ALFA_SUAVE acima).
export function gradienteSuave(direcao, cor, alcance) {
  const [r, g, b] = hexParaRgb(cor);
  const stops = ESTAGIOS_ALFA_SUAVE.map(
    ([posicao, alfa]) => `rgba(${r}, ${g}, ${b}, ${alfa}) ${(posicao * alcance).toFixed(1)}%`
  ).join(', ');
  return `linear-gradient(${direcao}, ${stops})`;
}

// Variante pra banners que ficam ENTRE outras fileiras da Home
// (inicio/DestaqueGrande.jsx) — ao contrário do carrossel (topo da página,
// só precisa dissolver embaixo), aqui a fileira anterior encosta direto na
// borda de CIMA do banner, então a imagem precisa dissolver na cor de fundo
// nas duas pontas. Pedido explícito do usuário, 2026-09-20: "tornar igual ao
// do carrossel só que o efeito de se misturar com a cor do fundo ficaria em
// cima e embaixo". Reusa `gradienteHero` (base, já aprovada e calibrada —
// não mexer) e soma uma 4ª camada no topo, mesmo alcance (60%) mas com a
// curva suave acima — duas tentativas anteriores (1 camada crua, depois
// várias camadas empilhadas) ficaram "brusca"/"ainda não suave" (feedback
// explícito do usuário, 2026-09-20).
export function gradienteHeroTopoEBase(cor) {
  return `${gradienteSuave('to bottom', cor, 60)}, ${gradienteHero(cor)}`;
}

// Botão primário do hero (pílula clara, texto escuro, ícone play) — geometria
// medida ao vivo no AnimeFire. Compartilhado entre o `<Link>` (anime já
// catalogado) e o `<button>` de materialização (item do feed), e reusado por
// inicio/DestaqueGrande.jsx pro CTA do mesmo painel de info.
export const CLASSE_BOTAO_HERO =
  'inline-flex h-11 w-fit cursor-pointer items-center gap-3 rounded-xl bg-white px-6 font-bold text-[#17171b] outline-none transition hover:brightness-90 motion-reduce:transition-none disabled:cursor-progress sm:h-12 lg:h-14 lg:text-xl';

// Pill do hero — usada pela tag de ranking ("#N em alta") e pela de estado
// ("Anime no Catálogo"), lado a lado. Mesmo visual pras duas.
export const CLASSE_PILL_HERO =
  'inline-flex items-center gap-2 rounded-xl bg-white/10 px-4 py-2 text-sm font-bold text-white backdrop-blur-sm';

// Ícone "em alta" (chama) da pill de ranking — inline, sem dependência nova
// (Escada de Minimalismo, CLAUDE.md §4); mesmo estilo stroke 24×24 de
// player/Icones.jsx. Decorativo: o texto "#N em alta" já carrega o sentido.
export function IconeEmAlta(props) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={16}
      height={16}
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...props}
    >
      <path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.07-2.14-.22-4.05 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.15.43-2.29 1-3a2.5 2.5 0 0 0 2.5 2.5z" />
    </svg>
  );
}

export default function CarrosselDestaques({ itens, aoMaterializar, materializando }) {
  const idTitulo = useId();
  const idSlides = useId();

  // Filtra "Hentai" do gênero (nome exato da AniList, ./generos.js) fora do
  // pool de sorteio — pedido explícito do usuário, 2026-09-23. `_QUERY_EM_
  // ALTA` (backend/integrations/anilist.py) não tem `isAdult: false` como as
  // queries de fileira temática têm, então o filtro entra aqui, no consumo do
  // feed "em alta". `rank` (abaixo) usa `itens` cru, não `pool`, pra manter a
  // posição de ranking igual à do feed original mesmo com itens excluídos.
  const pool = useMemo(
    () => (itens ?? []).filter((item) => !(item.generos ?? []).includes('Hentai')),
    [itens]
  );

  // Deslocamento da janela, em BLOCOS de `TAMANHO_DA_JANELA`. Nasce do relógio
  // (não de 0) pra que o recorte também mude entre reloads, não só enquanto a
  // aba fica aberta.
  const [blocoDaJanela, setBlocoDaJanela] = useState(() =>
    Math.floor(Date.now() / INTERVALO_ROTACAO_MS),
  );

  // Recorte visível: o pool inteiro embaralhado com semente no `blocoDaJanela`,
  // cortado em `TAMANHO_DA_JANELA`. Cada rotação de janela re-embaralha (nova
  // semente) — troca o recorte E a ordem, sem ficar preso nos mesmos destaques
  // nem exibi-los em ordem de ranking. `n` fica fixo em `TAMANHO_DA_JANELA`
  // sempre que o pool é grande o bastante, então as bolinhas não mudam de
  // quantidade quando a janela gira.
  const base = useMemo(() => {
    const tamanho = Math.min(TAMANHO_DA_JANELA, pool.length);
    if (tamanho === 0) return [];
    return embaralharComSemente(pool, blocoDaJanela).slice(0, tamanho);
  }, [pool, blocoDaJanela]);
  const n = base.length;

  // Índice do slide ativo (0..n-1) — sem cópias, sem posição de render
  // separada da lógica: com crossfade não há "trilha" pra deslizar.
  const [indiceAtivo, setIndiceAtivo] = useState(0);
  // Pausa é `useState` (não `useRef` como em GradeRotativa): o valor entra no
  // gate `autoAvancando`, que também alimenta o `aria-live` do contêiner no
  // render.
  const [pausado, setPausado] = useState(false);
  // Modo foco da sinopse (components/SinopseEmFoco.jsx): guarda os textos do
  // slide que abriu (`{ titulo, tituloSecundario, sinopse }`) — um dialog só pro
  // carrossel inteiro, e o conteúdo não depende de qual slide está ativo
  // depois. Aberto, congela o auto-avanço e a rotação da janela, senão o slide
  // trocaria por baixo de quem está lendo.
  const [sinopseEmFoco, setSinopseEmFoco] = useState(null);
  const abertaPorPonteiroRef = useRef(false);
  const emPausa = pausado || sinopseEmFoco != null;
  const movimentoReduzido = usePrefersReducedMotion();

  // Navegação por passo, com wrap por módulo — sem cópias, o wrap não precisa
  // de nenhum truque visual (o crossfade já cobre a troca de qualquer índice
  // pra qualquer outro).
  const avancar = useCallback(
    (delta) => {
      if (n === 0) return;
      setIndiceAtivo((i) => ((i + delta) % n + n) % n);
    },
    [n],
  );

  const irParaIndice = useCallback((i) => {
    setIndiceAtivo(i);
  }, []);

  // Ref-espelho de `pausado`: o timer de rotação é longo (10 min) e não deve
  // ser recriado a cada hover/foco (recriar reiniciaria a contagem). Mesmo
  // truque do `pausadoRef` da antiga GradeRotativa.
  const pausadoRef = useRef(emPausa);
  useEffect(() => {
    pausadoRef.current = emPausa;
  }, [emPausa]);

  // Rotação da janela: a cada `INTERVALO_ROTACAO_MS` avança um bloco pelo pool.
  // Gate por haver mais itens que a janela. Hover/foco só adiam o próximo
  // avanço (via `pausadoRef`), não reiniciam o timer.
  useEffect(() => {
    if (pool.length <= TAMANHO_DA_JANELA) return undefined;
    const id = setInterval(() => {
      if (!pausadoRef.current) setBlocoDaJanela((b) => b + 1);
    }, INTERVALO_ROTACAO_MS);
    return () => clearInterval(id);
  }, [pool.length]);

  // Janela girou: o recorte inteiro trocou de conteúdo — volta pro primeiro
  // slide. `montadoRef` pula o primeiro run (no mount `indiceAtivo` já nasce
  // em 0).
  const montadoRef = useRef(false);
  useEffect(() => {
    if (!montadoRef.current) {
      montadoRef.current = true;
      return;
    }
    setIndiceAtivo(0);
  }, [blocoDaJanela]);

  // Gate único do auto-avanço, reusado no efeito e no `aria-live` do
  // contêiner: sem preferência por menos movimento, sem pausa por hover/foco
  // e com mais de um destaque.
  const autoAvancando = !movimentoReduzido && !emPausa && n > 1;

  // Contagem regressiva sobrevive à pausa (pedido explícito do usuário,
  // 2026-09-20): ao pausar por hover/foco, o tempo já decorrido fica
  // guardado e o retomar continua dali — não reinicia os 10s inteiros do
  // zero. `duracaoRestanteRef` guarda quanto falta (ms) pro próximo avanço;
  // `inicioTrechoRef` marca quando o trecho ATUAL (rodando) começou, pra dar
  // pra calcular o decorrido no cleanup do efeito abaixo.
  const duracaoRestanteRef = useRef(INTERVALO_MS);
  const inicioTrechoRef = useRef(0);

  // Slide mudou (manual ou automático): o countdown do PRÓXIMO slide sempre
  // começa cheio. Declarado ANTES do efeito de timeout logo abaixo — React
  // roda todas as limpezas de um commit antes de todos os efeitos novos, na
  // ordem de declaração dos hooks, então este reset entra em vigor antes do
  // efeito seguinte reler `duracaoRestanteRef` quando `indiceAtivo` muda.
  useEffect(() => {
    duracaoRestanteRef.current = INTERVALO_MS;
  }, [indiceAtivo]);

  // Cadeia de timeouts: agenda só o tempo QUE FALTA (`duracaoRestanteRef`),
  // não sempre `INTERVALO_MS` inteiro — pausar (autoAvancando vira `false`
  // sem mexer em `indiceAtivo`) não dispara o efeito de reset acima, então o
  // cleanup abaixo só desconta do restante o que já rodou desde o último
  // início, sem zerar. Ao disparar de fato, avança 1 slide (com wrap); o
  // efeito de reset acima cuida de repor o restante cheio pro próximo trecho.
  useEffect(() => {
    if (!autoAvancando) return undefined;
    inicioTrechoRef.current = Date.now();
    const duracao = duracaoRestanteRef.current;
    const id = setTimeout(() => setIndiceAtivo((i) => (i + 1) % n), duracao);
    return () => {
      clearTimeout(id);
      const decorrido = Date.now() - inicioTrechoRef.current;
      duracaoRestanteRef.current = Math.max(0, duracaoRestanteRef.current - decorrido);
    };
  }, [autoAvancando, indiceAtivo, n]);

  if (n === 0) return null;

  const mostrarControles = n > 1;

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

  return (
    <>
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

      <div className="group relative h-svh min-h-[480px] overflow-hidden">
        <ul id={idSlides} aria-live={autoAvancando ? 'off' : 'polite'} className="absolute inset-0">
          {base.map((item, i) => {
            const ativo = i === indiceAtivo;
            const titulo = item.titulo_romaji || item.titulo_ingles;
            // Título alternativo (o outro idioma) pro subtítulo nativo — só
            // aparece se existir E divergir do exibido.
            const tituloAlternativo =
              titulo === item.titulo_romaji ? item.titulo_ingles : item.titulo_romaji;
            const mostrarAlternativo =
              Boolean(tituloAlternativo) && tituloAlternativo !== titulo;
            const catalogado = item.anime_id != null;
            // Posição no ranking do feed `em-alta` (já vem ordenado). Usa
            // `itens` (o array cru da prop), não `pool` (filtrado sem
            // Hentai) — a numeração exibida ("#N em alta") reflete a posição
            // real no feed, não a posição pós-filtro. O item aqui é a MESMA
            // referência de objeto (a janela não clona item), então
            // `indexOf` casa. -1 (não deve acontecer) → sem pill.
            const rank = (itens ?? []).indexOf(item) + 1;
            // Sem arte horizontal: só temos o pôster retrato pra trabalhar.
            const semBanner = !item.banner_url && Boolean(item.capa_url);
            const fonteImagem = item.banner_url || item.capa_url || null;
            const primeiroDestaque = i === 0;

            const proximoEpisodio = textoProximoEpisodio(item);
            const generosTraduzidos = (item.generos ?? [])
              .slice(0, 3)
              .map((g) => traduzirGenero(g));
            // Fatos rotulados (Ano/Gêneros/Próximo episódio) — MESMO formato
            // Rótulo/Valor do painel de fatos de paginas/PaginaDoAnime.jsx
            // (pedido explícito do usuário: alinhar o design do carrossel
            // com o novo header da página do anime). Substitui a antiga linha
            // `meta` de texto corrido ("ano • gêneros").
            const fatos = [
              item.ano_estreia != null ? { rotulo: 'Ano', valor: String(item.ano_estreia) } : null,
              generosTraduzidos.length > 0
                ? { rotulo: 'Gêneros', valor: generosTraduzidos.join(', ') }
                : null,
              proximoEpisodio ? { rotulo: 'Próximo episódio', valor: proximoEpisodio } : null,
            ].filter(Boolean);

            return (
              <li
                key={item.anilist_id ?? item.titulo_romaji ?? i}
                role="group"
                aria-roledescription="slide"
                aria-label={`${i + 1} de ${n}: ${titulo}`}
                inert={!ativo}
                // `semBanner` + cor dominante da capa (AniList `coverImage.color`):
                // a cor entra como fundo do slide, sob o blur da capa (ver o
                // primeiro <img> abaixo). `bg-surface` continua de fallback
                // quando `capa_cor` é null — item do Kitsu, ou `color: null`
                // da própria AniList.
                style={semBanner && item.capa_cor ? { backgroundColor: item.capa_cor } : undefined}
                // Crossfade: todos os slides empilhados na mesma área
                // (`absolute inset-0`, herdada do `h-svh` do wrapper — ver
                // acima), só a opacity muda. `pointer-events-none` no inativo
                // é redundante com `inert` (que já tira do hit-test), mas
                // documenta a intenção de forma explícita no próprio className.
                className={`absolute inset-0 overflow-hidden bg-surface transition-opacity duration-700 ease-in-out motion-reduce:transition-none ${
                  ativo ? 'opacity-100' : 'pointer-events-none opacity-0'
                }`}
              >
                {fonteImagem && (
                  <img
                    // Só o banner horizontal (caso COM banner) sobe pra
                    // `original`: no `semBanner` a fonte é a capa da AniList
                    // (`item.capa_url`, sem variantes de tamanho) e o regex
                    // não casaria — não vale chamar o helper nesse caminho.
                    src={semBanner ? fonteImagem : imagemEmAltaResolucao(fonteImagem)}
                    alt=""
                    loading={primeiroDestaque ? undefined : 'lazy'}
                    decoding={primeiroDestaque ? undefined : 'async'}
                    className={
                      semBanner
                        ? // a capa borrada/escurecida é só textura por cima da
                          // cor dominante — em TODOS os breakpoints, não mais
                          // a arte recortada nítida abaixo de `lg`. `opacity-70`
                          // deixa a cor de fundo do <li> aparecer atrás.
                          'absolute inset-0 h-full w-full object-cover object-top scale-125 blur-lg brightness-[0.5] opacity-70'
                        : // `object-top`: ancora a imagem pelo topo (medido no
                          // AnimeFire) — a essa altura (`h-svh`) o `object-cover`
                          // centralizado cortaria rosto/cabeça dos personagens
                          // no banner.
                          'absolute inset-0 h-full w-full object-cover object-top'
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

                {/* Gradiente empilhado (::before do AnimeFire) — 3 camadas
                    inline (multi-gradiente arbitrário não é confiável no
                    Tailwind v4). Sem banner, uma 4ª camada à esquerda pro
                    texto continuar legível sobre o pôster borrado. Substitui
                    o card com bordas/sombra flutuante do layout anterior —
                    aqui a imagem+gradiente É a seção. */}
                <div
                  className="pointer-events-none absolute inset-0"
                  style={{
                    // `#000`: cor do `<main>` da Home (paginas/Inicio.jsx,
                    // `bg-black`) — o hero dissolve nela, não mais no antigo
                    // `#17171b` (ver rationale em gradienteHero acima).
                    background: semBanner ? gradienteHeroSemBanner('#000') : gradienteHero('#000'),
                  }}
                />

                {/* Bloco de conteúdo — esqueleto compartilhado com o header de
                    paginas/PaginaDoAnime.jsx (./BlocoConteudoHero.jsx: pills →
                    título/subtítulo → sinopse → meta → CTA). Aqui só o
                    posicionamento é próprio do slide: ancorado embaixo-
                    esquerda, largura limitada a `45vw` no desktop, texto
                    empurrado pro rodapé do hero (geometria medida ao vivo no
                    AnimeFire). Sem `pointer-events-none`: tem botão/link
                    dentro; os textos puros não roubam clique de nada (não há
                    mais overlay de slide). */}
                <BlocoConteudoHero
                  className="absolute inset-x-0 bottom-0 max-w-[90%] pb-10 sm:max-w-[70%] sm:pb-14 lg:max-w-[45vw] lg:pb-[18vh] xl:pb-[20vh]"
                  pills={[
                    rank > 0 && (
                      <span key="rank" className={CLASSE_PILL_HERO}>
                        <IconeEmAlta />
                        {`#${rank} em alta`}
                      </span>
                    ),
                    catalogado && (
                      <span key="catalogado" className={CLASSE_PILL_HERO}>
                        Anime no Catálogo
                      </span>
                    ),
                  ].filter(Boolean)}
                  titulo={
                    <h3 className="mb-1 line-clamp-2 text-2xl font-extrabold text-white sm:text-4xl lg:text-5xl lg:leading-[1.2]">
                      {catalogado ? (
                        <Link
                          to={`/anime/${item.anime_id}`}
                          className="rounded-sm outline-none"
                        >
                          {titulo}
                        </Link>
                      ) : (
                        titulo
                      )}
                    </h3>
                  }
                  tituloSecundario={
                    mostrarAlternativo && (
                      <p className="line-clamp-1 text-lg font-bold text-ink-muted sm:text-xl xl:text-2xl">
                        {tituloAlternativo}
                      </p>
                    )
                  }
                  // Só o feed "em alta" traz sinopse (`AnimeEmAltaSaida.sinopse`).
                  // Escondida abaixo de `sm` porque no mobile o slide é curto
                  // demais e a sinopse empurraria o CTA pra fora (a página do
                  // anime não tem esse limite — o hero dela cresce).
                  sinopse={item.sinopse}
                  ocultarSinopseNoMobile
                  // O botão só aparece se o `line-clamp` cortou texto (decisão
                  // do `BlocoConteudoHero`); só o slide ativo é focável
                  // (`inert` nos demais).
                  acaoSinopse={
                    <button
                      type="button"
                      onClick={(evento) => {
                        abertaPorPonteiroRef.current = evento.detail > 0;
                        setSinopseEmFoco({
                          titulo,
                          tituloSecundario: mostrarAlternativo ? tituloAlternativo : null,
                          sinopse: item.sinopse,
                        });
                      }}
                      aria-haspopup="dialog"
                      className="-mt-0.5 inline-flex min-h-9 items-center text-sm font-bold text-neon outline-none transition-colors hover:text-white focus-visible:underline"
                    >
                      Ler sinopse completa
                    </button>
                  }
                  // Fatos rotulados (Ano/Gêneros/Próximo episódio) ACIMA do
                  // botão — o AnimeFire não mostra essa linha no hero, mas o
                  // usuário quis mantê-la e vê-la nesta posição. MESMO
                  // formato Rótulo/Valor do painel de fatos de
                  // paginas/PaginaDoAnime.jsx (pedido explícito do usuário).
                  metaExtra={
                    fatos.length > 0 && (
                      <div className="flex flex-wrap gap-6">
                        {fatos.map((fato) => (
                          <div key={fato.rotulo} className="flex flex-col gap-0.5">
                            <span className="text-[11px] font-bold uppercase tracking-wide text-ink-muted">
                              {fato.rotulo}
                            </span>
                            <span className="text-sm font-bold text-white sm:text-base">
                              {fato.valor}
                            </span>
                          </div>
                        ))}
                      </div>
                    )
                  }
                  cta={
                    catalogado ? (
                      <Link
                        to={`/anime/${item.anime_id}`}
                        aria-label={`${titulo} — assistir agora`}
                        // `mt-2` extra (além do `gap-4` do esqueleto entre
                        // seções) só aqui — pedido explícito do usuário pra
                        // afastar o CTA dos fatos logo acima. Direto no
                        // elemento, não em `CLASSE_BOTAO_HERO`, pra não afetar
                        // os outros usos da constante.
                        className={`${CLASSE_BOTAO_HERO} mt-8`}
                      >
                        <IconePlay width={20} height={20} fill="currentColor" />
                        Assistir agora
                      </Link>
                    ) : (
                      <button
                        type="button"
                        onClick={() => aoMaterializar(item)}
                        disabled={materializando}
                        aria-label={materializando ? undefined : `Adicionar ${titulo} ao catálogo`}
                        className={`${CLASSE_BOTAO_HERO} mt-8`}
                      >
                        <IconePlay width={20} height={20} fill="currentColor" />
                        {materializando ? 'Adicionando…' : 'Adicionar ao Catálogo'}
                      </button>
                    )
                  }
                />
              </li>
            );
          })}
        </ul>

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
              className="absolute inset-y-0 left-0 z-10 flex w-[3.8vw] min-w-10 cursor-pointer items-center justify-center text-white/60 opacity-0 outline-none transition-opacity hover:text-neon focus-visible:opacity-100 group-hover:opacity-100 motion-reduce:transition-none"
            >
              <IconeSeta direcao="esquerda" />
            </button>
            <button
              type="button"
              onClick={(evento) => {
                avancar(1);
                desfocarSePonteiro(evento);
              }}
              aria-label="Próximo destaque"
              aria-controls={idSlides}
              className="absolute inset-y-0 right-0 z-10 flex w-[3.8vw] min-w-10 cursor-pointer items-center justify-center text-white/60 opacity-0 outline-none transition-opacity hover:text-neon focus-visible:opacity-100 group-hover:opacity-100 motion-reduce:transition-none"
            >
              <IconeSeta direcao="direita" />
            </button>

            {/* Paginação SOBREPOSTA na imagem, dentro do hero (`bottom-[14.3vh]`
                no desktop, medido no AnimeFire; mais baixo no mobile, onde o
                bloco de conteúdo fica colado no rodapé e ocuparia essa faixa).
                Bullet ativo vira uma barrinha de PROGRESSO enquanto o
                auto-avanço está rodando — mostra quanto falta pra trocar de
                slide (`@keyframes preencher-progresso-dot` em index.css,
                duração casada com `INTERVALO_MS`, anima `transform: scaleX`
                — NÃO `width`: `width` força recálculo de layout a cada frame
                durante os 10s inteiros e travava o resto da página, incluindo
                a troca de slide por seta; `scaleX` só mexe em compositing).
                Pausar por hover/foco CONGELA a barra onde está (`animation-
                play-state: paused`, ver comentário no span da barra) — não
                salta pra cheia nem reinicia do zero ao retomar, pedido
                explícito do usuário (2026-09-20). Só `prefers-reduced-motion`
                tira a animação de vez (barra assenta em `scale-x-100`, cheia
                e parada — respeita a preferência em vez de só pausar).
                Wrappers `<button>` de 32px
                (`w-8`, subiu de `w-6` pra caber a barra) mantêm o alvo de
                clique e o rótulo, uniforme pra todas as bolinhas (sem pulo de
                layout quando uma vira a ativa). */}
            <div className="absolute bottom-6 left-1/2 z-20 flex -translate-x-1/2 gap-2 lg:bottom-[14.3vh]">
              {base.map((item, i) => {
                const ehAtiva = i === indiceAtivo;
                return (
                  <button
                    key={item.anilist_id ?? item.titulo_romaji ?? i}
                    type="button"
                    onClick={(evento) => {
                      irParaIndice(i);
                      desfocarSePonteiro(evento);
                    }}
                    aria-label={`Ir para o destaque ${i + 1}`}
                    aria-current={ehAtiva ? 'true' : undefined}
                    className="group/dot flex h-6 w-8 cursor-pointer items-center justify-center rounded-full outline-none"
                  >
                    {/* Track — UMA estrutura única pra bolinha ativa, sem
                        trocar de árvore JSX quando `autoAvancando` liga/desliga
                        (hover/foco pausa e retoma): só a barra de preenchimento
                        (span filho) entra/sai, sempre no mesmo lugar. */}
                    <span
                      aria-hidden="true"
                      className={`relative block h-2 overflow-hidden rounded-full bg-white/25 transition-all duration-300 ease-out motion-reduce:transition-none ${
                        ehAtiva ? 'w-8' : 'w-2 group-hover/dot:bg-white/50'
                      }`}
                    >
                      {ehAtiva && (
                        <span
                          aria-hidden="true"
                          // PAUSA de verdade (pedido explícito do usuário,
                          // 2026-09-20), não substituição de estado: a
                          // animação fica montada o tempo todo (enquanto não
                          // é `movimentoReduzido`) e só ganha `animation-
                          // play-state: paused` ao pausar — o navegador
                          // congela exatamente onde estava e retoma dali, sem
                          // saltar pra cheia nem reiniciar do zero (mesmo
                          // espírito do `duracaoRestanteRef` que já faz isso
                          // pro avanço de verdade, no efeito acima). Sem
                          // `movimentoReduzido` a barra some de vez, e a
                          // pílula fica só no `scale-x-100` de repouso —
                          // respeita a preferência por menos movimento em vez
                          // de só pausar.
                          className={`absolute inset-y-0 left-0 block w-full origin-left scale-x-100 rounded-full bg-neon ${
                            movimentoReduzido
                              ? ''
                              : `animate-[preencher-progresso-dot_10000ms_linear_forwards] ${
                                  emPausa ? '[animation-play-state:paused]' : ''
                                }`
                          }`}
                        />
                      )}
                    </span>
                  </button>
                );
              })}
            </div>
          </>
        )}
      </div>
    </section>

    {/* Fora da <section>: o `aoTeclar` dela (setas trocam o slide) e o
        pause por hover/foco não devem ver os eventos de dentro do dialog. */}
    <SinopseEmFoco
      aberta={sinopseEmFoco != null}
      titulo={sinopseEmFoco?.titulo ?? ''}
      tituloSecundario={sinopseEmFoco?.tituloSecundario}
      sinopse={sinopseEmFoco?.sinopse}
      aoFechar={() => {
        setSinopseEmFoco(null);
        // O dialog devolve o foco ao botão que o abriu; aberto por mouse/toque,
        // isso deixaria a <section> "com foco dentro" (ver `desfocarSePonteiro`).
        if (abertaPorPonteiroRef.current) document.activeElement?.blur();
      }}
    />
    </>
  );
}

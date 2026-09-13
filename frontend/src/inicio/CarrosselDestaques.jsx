import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
// Re-exportado por components/LinhaDeEpisodio.jsx — `src/inicio/` não importa
// de `src/player/` direto (fronteira Clean Architecture, ver paginas/Inicio.jsx).
// Mesmo ícone do CTA "Assistir agora" que inicio/DestaqueGrande.jsx já reusa.
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
// rolagem manual dessincronizaria o índice. Cada slide ocupa 100% da largura
// do track (`w-full shrink-0`, sem peek) e o track desliza um slide inteiro
// por passo via `transform: translateX(-N * 100%)`. A `<section>` NÃO tem
// `max-w`/`mx-auto`: ocupa toda a largura do `<main>` (full-bleed). As
// bolinhas de paginação ficam SOBREPOSTAS na imagem, dentro do hero
// (`absolute bottom-*`), não numa faixa abaixo dele.
//
// Loop infinito (estilo Disney+, mantido do layout anterior): a lista base é
// renderizada 3x concatenada e `pos` — o índice de render do slide ativo
// dentro dessas cópias — começa na cópia do MEIO. Avançar/voltar mexe `pos`
// de 1 em 1 com transição; quando `pos` sai da faixa da cópia do meio
// `[n, 2n)`, depois que a animação assenta (`onTransitionEnd`) ele salta pro
// ponto equivalente da cópia do meio SEM transição (`semTransicao` tira a
// classe por 1 frame). Como as três cópias são idênticas, o salto é
// imperceptível — os dois peeks nunca ficam vazios (não que haja peek visual
// aqui, mas o mecanismo evita o "rebobinar" do wrap) e o wrap não
// "rebobina". Sem animação (movimento reduzido, ou clique rápido que empurra
// `pos` pros extremos das cópias) a normalização acontece direto num efeito,
// aceitando o corte da animação pra nunca renderizar slot vazio.
//
// A11y: perfil mínimo do padrão "carrossel" do WAI-ARIA APG. Só o slide
// central é interativo — todos os outros `<li>` (cópias) ficam `inert` (remove
// foco/tab/clique/árvore de a11y de uma vez), então o botão de CTA e o link do
// título triplicados no DOM não entram no tab order. Setas e bolinhas têm
// rótulo e `focus-visible`; a navegação por seta do teclado fica presa à
// `<section>` (sem listener global). O track tem `aria-live` (silencioso
// enquanto o auto-avanço roda; `polite` quando parado por hover/foco/
// `prefers-reduced-motion`) e o auto-avanço reagenda um `setTimeout` por slide
// — gate por `ativa`, hover/foco e movimento reduzido.

// `TAMANHO_DA_JANELA` (destaques por vez) e `INTERVALO_ROTACAO_MS` (de quanto
// em quanto a janela desliza pelo pool), junto com `embaralharComSemente`,
// moram em ./janelaDeDestaques.js — fonte única, porque paginas/Inicio.jsx
// reproduz o mesmo recorte pra excluí-lo dos "destaques grandes".

// Janela do auto-avanço. `setTimeout` reagendado a cada slide (não
// `setInterval`): navegação manual muda `pos`, o efeito reexecuta e a
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
// "Invalid Date"/"NaN dias". Compartilhado com inicio/DestaqueGrande.jsx
// (mesmo painel de info); `relativo`/`rtf` acima continuam locais.
export function textoProximoEpisodio(item) {
  const epEm = item.proximo_ep_em;
  if (!epEm) return null;
  const data = new Date(epEm);
  if (Number.isNaN(data.getTime()) || data <= new Date()) return null;
  const quando = relativo(epEm);
  return item.proximo_ep_numero != null
    ? `Episódio ${item.proximo_ep_numero} ${quando}`
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
// função com a própria cor.
export function gradienteHero(cor) {
  return `linear-gradient(to top, ${cor}, transparent 45%), linear-gradient(to top, ${cor}, transparent 40%), linear-gradient(77deg, ${cor}, transparent 60%)`;
}
// Sem arte horizontal (`semBanner`): só o pôster retrato borrado atrás do
// texto — uma camada extra à esquerda mantém o texto legível sobre ele.
// Também exportada (mesmo fallback no hero de paginas/PaginaDoAnime.jsx).
export function gradienteHeroSemBanner(cor) {
  return `linear-gradient(to right, ${cor}, transparent 60%), ${gradienteHero(cor)}`;
}

// Botão primário do hero (pílula clara, texto escuro, ícone play) — geometria
// medida ao vivo no AnimeFire. Compartilhado entre o `<Link>` (anime já
// catalogado) e o `<button>` de materialização (item do feed), e reusado por
// inicio/DestaqueGrande.jsx pro CTA do mesmo painel de info.
export const CLASSE_BOTAO_HERO =
  'inline-flex h-11 w-fit items-center gap-3 rounded-xl bg-white px-6 font-bold text-[#17171b] outline-none transition hover:brightness-90 focus-visible:ring-2 focus-visible:ring-neon motion-reduce:transition-none disabled:cursor-progress sm:h-12 lg:h-14 lg:text-xl';

// Pill do hero — usada pela tag de ranking ("#N em alta") e pela de estado
// ("Anime no Catálogo"), lado a lado. Mesmo visual pras duas. Compartilhada
// com inicio/DestaqueGrande.jsx.
export const CLASSE_PILL_HERO =
  'inline-flex items-center gap-2 rounded-xl bg-white/10 px-4 py-2 text-sm font-bold text-white backdrop-blur-sm';

// Ícone "em alta" (chama) da pill de ranking — inline, sem dependência nova
// (Escada de Minimalismo, CLAUDE.md §4); mesmo estilo stroke 24×24 de
// player/Icones.jsx. Decorativo: o texto "#N em alta" já carrega o sentido.
// Compartilhado com inicio/DestaqueGrande.jsx.
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

  // Recorte visível: o pool inteiro embaralhado com semente no `blocoDaJanela`,
  // cortado em `TAMANHO_DA_JANELA`. Cada rotação de janela re-embaralha (nova
  // semente) — troca o recorte E a ordem, sem ficar preso nos mesmos destaques
  // nem exibi-los em ordem de ranking. `n` fica fixo em `TAMANHO_DA_JANELA`
  // sempre que o pool é grande o bastante, então as 3 cópias, as bolinhas e a
  // normalização não mudam de tamanho quando a janela gira.
  const base = useMemo(() => {
    const tamanho = Math.min(TAMANHO_DA_JANELA, pool.length);
    if (tamanho === 0) return [];
    return embaralharComSemente(pool, blocoDaJanela).slice(0, tamanho);
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
  // do próprio track (a `transform`), ignorando qualquer transição interna dos
  // `<li>`.
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

      <div className="group relative overflow-hidden">
        <ul
          ref={trackRef}
          id={idSlides}
          aria-live={autoAvancando ? 'off' : 'polite'}
          onTransitionEnd={aoFimDaTransicao}
          style={{ transform: `translateX(-${deslocamento * 100}%)` }}
          className={`flex ${
            semTransicao
              ? ''
              : 'transition-transform duration-500 ease-out motion-reduce:transition-none'
          }`}
        >
          {slides.map((item, k) => {
            const ativo = loop ? k === pos : true;
            const titulo = item.titulo_romaji || item.titulo_ingles;
            // Título alternativo (o outro idioma) pro subtítulo nativo — só
            // aparece se existir E divergir do exibido.
            const tituloAlternativo =
              titulo === item.titulo_romaji ? item.titulo_ingles : item.titulo_romaji;
            const mostrarAlternativo =
              Boolean(tituloAlternativo) && tituloAlternativo !== titulo;
            const catalogado = item.anime_id != null;
            // Posição no ranking do feed `em-alta` (já vem ordenado). `pool` é
            // o array `itens` original e o item aqui é a MESMA referência de
            // objeto (janela e cópias não clonam item), então `indexOf` casa.
            // -1 (não deve acontecer) → sem pill.
            const rank = pool.indexOf(item) + 1;
            // Sem arte horizontal: só temos o pôster retrato pra trabalhar.
            const semBanner = !item.banner_url && Boolean(item.capa_url);
            const fonteImagem = item.banner_url || item.capa_url || null;
            const primeiroDestaque = k % n === 0;

            const proximoEpisodio = textoProximoEpisodio(item);
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
                style={semBanner && item.capa_cor ? { backgroundColor: item.capa_cor } : undefined}
                // Altura = viewport pequena (`h-svh`, medido ao vivo no
                // AnimeFire: a `<section>` hero deles usa `svh`) — não mais uma
                // fração dela nem `100vh` (que conta a barra de UI do mobile).
                // `min-h` só pra não achatar demais em viewports muito baixos.
                className="relative h-svh min-h-[480px] w-full shrink-0 grow-0 overflow-hidden bg-surface"
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
                          className="rounded-sm outline-none focus-visible:ring-2 focus-visible:ring-neon"
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
                  // Meta (ano • gêneros) + data do próximo episódio ACIMA do
                  // botão — o AnimeFire não mostra essas linhas no hero, mas o
                  // usuário quis mantê-las e vê-las nesta posição.
                  meta={meta}
                  metaExtra={
                    proximoEpisodio && (
                      <p className="text-xs text-white/70 sm:text-sm">{proximoEpisodio}</p>
                    )
                  }
                  cta={
                    catalogado ? (
                      <Link
                        to={`/anime/${item.anime_id}`}
                        aria-label={`${titulo} — assistir agora`}
                        className={CLASSE_BOTAO_HERO}
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
                        className={CLASSE_BOTAO_HERO}
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
              className="absolute inset-y-0 left-0 z-10 flex w-[3.8vw] min-w-10 items-center justify-center text-white/60 opacity-0 outline-none transition-opacity hover:text-neon focus-visible:opacity-100 focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-neon group-hover:opacity-100 motion-reduce:transition-none"
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
              className="absolute inset-y-0 right-0 z-10 flex w-[3.8vw] min-w-10 items-center justify-center text-white/60 opacity-0 outline-none transition-opacity hover:text-neon focus-visible:opacity-100 focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-neon group-hover:opacity-100 motion-reduce:transition-none"
            >
              <IconeSeta direcao="direita" />
            </button>

            {/* Paginação SOBREPOSTA na imagem, dentro do hero (`bottom-[14.3vh]`
                no desktop, medido no AnimeFire; mais baixo no mobile, onde o
                bloco de conteúdo fica colado no rodapé e ocuparia essa faixa).
                Bullet ativo vira PÍLULA por largura (`w-4` + `transition-all`),
                não por `scale`. Wrappers `<button>` de 24px mantêm o alvo de
                clique e o rótulo. */}
            <div className="absolute bottom-6 left-1/2 z-20 flex -translate-x-1/2 gap-2 lg:bottom-[14.3vh]">
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
                    className={`block h-2 rounded-full transition-all motion-reduce:transition-none ${
                      i === indiceLogico
                        ? 'w-4 bg-white'
                        : 'w-2 bg-white/25 group-hover/dot:bg-white/50'
                    }`}
                  />
                </button>
              ))}
            </div>
          </>
        )}
      </div>
    </section>
  );
}

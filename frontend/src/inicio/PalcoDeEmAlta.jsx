import { useState } from 'react';
import AtivadorDeAnime from './AtivadorDeAnime.jsx';
import {
  ConteudoDeDestaque,
  gradienteDeDestaque,
  imagemEmAltaResolucao,
} from './CarrosselDestaques.jsx';
import { traduzirGenero } from './generos.js';
import { PADDING_TITULO } from './tamanhoDeCard.js';
import { useHoverAposFechar } from './useHoverAposFechar.js';
import { usePrefersReducedMotion } from './usePrefersReducedMotion.js';

// Quanto cada título fica no palco antes de passar pro próximo.
const DURACAO_AUTOMATICA_MS = 7000;

// Top 10 em "palco + lista": à esquerda o título selecionado (banner + o MESMO
// bloco de conteúdo do carrossel hero, em versão compacta, com sombra só atrás
// dele); à direita os dez em linhas. Passar o mouse ou focar uma linha
// troca o palco; clicar nela abre o anime. Em toque não há hover: o palco fica
// no 1º e a linha abre o anime direto — o CTA do palco continua levando ao
// selecionado.
//
// Troca sozinho a cada `DURACAO_AUTOMATICA_MS`, em ciclo. O relógio é a própria
// animação da barra de progresso da linha ativa (`preencher-progresso-dot`,
// index.css): `onAnimationEnd` avança, e pausar é só congelar a animação — o
// tempo restante nunca dessincroniza do preenchimento (uma película clara
// que varre a linha ativa da esquerda pra direita POR CIMA do conteúdo, recortada no
// raio dela). Mouse em cima do bloco todo
// (palco + lista), foco dentro dele ou a sinopse aberta na ilha pausam, pra dar tempo de ler a sinopse e
// clicar; `prefers-reduced-motion` desliga a troca automática por completo (sem
// animação não há barra nem relógio).
//
// Todas as artes ficam empilhadas no palco e só a opacidade muda, o mesmo
// crossfade do carrossel: sem isso cada troca esperaria a imagem baixar. Item
// sem `banner_url` cai no mesmo fallback do carrossel (`semBanner`): cor
// dominante da capa + o pôster como card à direita (só de `lg` pra cima) — a
// capa retrato nunca é esticada como fundo.
export default function PalcoDeEmAlta({
  itens,
  chaveDoItem,
  aoAtivar,
  desabilitado,
  aoAbrirSinopse,
  // Sinopse completa aberta na ilha: a troca automática congela até fechar, senão
  // o palco trocaria de título por trás do texto que o usuário está lendo.
  sinopseAberta = false,
}) {
  const [selecionado, setSelecionado] = useState(0);
  const [mouseEmCima, setMouseEmCima] = useState(false);
  const [focoDentro, setFocoDentro] = useState(false);
  const movimentoReduzido = usePrefersReducedMotion();
  useHoverAposFechar(sinopseAberta, setMouseEmCima);
  if (itens.length === 0) return null;

  // Os feeds podem encolher entre renders (refetch); sem o clamp o índice
  // ficaria apontando pra fora da lista.
  const indiceAtual = Math.min(selecionado, itens.length - 1);
  const atual = itens[indiceAtual];
  const rotacaoAutomatica = !movimentoReduzido && itens.length > 1;
  const pausada = mouseEmCima || focoDentro || sinopseAberta;

  return (
    <div
      style={{ paddingInline: PADDING_TITULO }}
      className="flex flex-wrap items-stretch gap-5"
      onMouseEnter={() => setMouseEmCima(true)}
      onMouseLeave={() => setMouseEmCima(false)}
      data-pausa-por-mouse=""
      onFocus={() => setFocoDentro(true)}
      onBlur={(evento) => {
        if (!evento.currentTarget.contains(evento.relatedTarget)) setFocoDentro(false);
      }}
    >
      <article className="relative flex min-h-[28rem] min-w-0 basis-[40rem] grow-[4] flex-col justify-end rounded-[2rem] sm:min-h-[44rem]">
        {itens.map((item, indice) => {
          const semBanner = !item.banner_url;
          return (
            <div
              key={chaveDoItem(item)}
              aria-hidden="true"
              style={semBanner && item.capa_cor ? { backgroundColor: item.capa_cor } : undefined}
              className={`absolute inset-0 transition-opacity duration-500 motion-reduce:transition-none ${
                indice === indiceAtual ? 'opacity-100' : 'opacity-0'
              }`}
            >
              {semBanner ? (
                item.capa_url && (
                  <img
                    src={item.capa_url}
                    alt=""
                    loading={indice === 0 ? undefined : 'lazy'}
                    className="absolute right-10 top-1/2 hidden aspect-[2/3] h-[70%] -translate-y-1/2 rounded-xl object-cover shadow-2xl shadow-black/60 ring-1 ring-white/10 lg:block"
                  />
                )
              ) : (
                <img
                  src={imagemEmAltaResolucao(item.banner_url)}
                  alt=""
                  loading={indice === 0 ? undefined : 'lazy'}
                  className="absolute inset-0 h-full w-full object-cover object-[100%_0%]"
                />
              )}
            </div>
          );
        })}

        {/* Sombra da base e da lateral esquerda, onde fica o texto: fade de toda
            a largura embaixo (a versão radial anterior terminava antes da borda
            direita e deixava um corte visível) e um escurecimento à esquerda. A
            parte de cima e a da direita do banner ficam sem escurecer. Inline: o
            parser de gradiente arbitrário do Tailwind v4 não é confiável (mesmo
            motivo de `SOMBRA_SLIDE_ATIVO`). */}
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-0"
          style={{
            background: gradienteDeDestaque(),
          }}
        />

        <ConteudoDeDestaque
          compacto
          item={atual}
          className="relative max-w-full pb-8 sm:pb-10 lg:max-w-[80%]"
          aoAbrirSinopse={aoAbrirSinopse}
          aoMaterializar={aoAtivar}
          materializando={desabilitado}
        />

        {/* Anel preto por FORA do palco no lugar do `overflow-hidden`: recortar
            as camadas (arte + sombra) no raio deixava uma linha clara nos
            cantos de baixo — cada camada é suavizada à parte e a arte vaza por
            baixo da sombra. Aqui nada é recortado; o anel (sombra sem desfoque,
            16px, na cor da página) cobre os cantos em cima da arte já
            composta, então a suavização só mistura com preto. Validado no
            navegador. O anel invade só o vão de 20px entre palco e lista. */}
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 rounded-[2rem] shadow-[0_0_0_16px_#000]"
        />
      </article>

      <ol className="flex min-w-0 basis-[19rem] grow flex-col gap-1">
        {itens.map((item, indice) => {
          const ativo = indice === indiceAtual;
          return (
            <li key={chaveDoItem(item)}>
              <AtivadorDeAnime
                item={item}
                aoAtivar={() => aoAtivar(item)}
                desabilitado={desabilitado}
                onMouseEnter={() => setSelecionado(indice)}
                onFocus={() => setSelecionado(indice)}
                aria-current={ativo ? 'true' : undefined}
                className={`relative flex min-h-16 w-full items-center gap-3 rounded-2xl py-1.5 pl-2 pr-3 transition-colors ${
                  ativo ? 'bg-surface' : 'hover:bg-surface'
                }`}
              >
                <span
                  aria-hidden="true"
                  className={`w-9 shrink-0 text-center text-3xl font-extrabold tabular-nums ${
                    ativo ? 'text-neon' : 'text-[#6b7178]'
                  }`}
                >
                  {indice + 1}
                </span>
                {item.capa_url && (
                  <img
                    src={item.capa_url}
                    alt=""
                    loading="lazy"
                    className="h-14 w-10 shrink-0 rounded-md bg-black object-cover"
                  />
                )}
                <span className="flex min-w-0 flex-col gap-0.5">
                  <span className="line-clamp-2 text-base font-bold text-white">
                    {item.titulo_romaji}
                  </span>
                  <span className="text-xs text-ink-muted">
                    {(item.generos ?? []).slice(0, 2).map(traduzirGenero).join(' · ')}
                  </span>
                </span>
                {ativo && rotacaoAutomatica && (
                  <span
                    aria-hidden="true"
                    className="pointer-events-none absolute inset-0 overflow-hidden rounded-2xl"
                  >
                    <span
                      key={indiceAtual}
                      onAnimationEnd={() => setSelecionado((indiceAtual + 1) % itens.length)}
                      style={{ animationDuration: `${DURACAO_AUTOMATICA_MS}ms` }}
                      className={`absolute inset-0 origin-left animate-[preencher-progresso-dot_linear_forwards] bg-white/15 ${
                        pausada ? '[animation-play-state:paused]' : ''
                      }`}
                    />
                  </span>
                )}
              </AtivadorDeAnime>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

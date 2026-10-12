import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { IconePlay } from '../components/LinhaDeEpisodio.jsx';
import {
  CLASSE_BOTAO_HERO,
  CLASSE_PILL_HERO,
  IconeEmAlta,
  imagemEmAltaResolucao,
  textoProximoEpisodio,
} from './CarrosselDestaques.jsx';
import { traduzirGenero } from './generos.js';
import { PADDING_TITULO } from './tamanhoDeCard.js';

// Banner promocional da Home (`paginas/Inicio.jsx::fileirasDaHome`), entre
// fileiras — direção "I · Bento", escolhida em 2026-10-02 entre 11 propostas de
// design. Três blocos arredondados numa grade: à esquerda a arte horizontal
// INTEIRA (16:9, `aspect-video`) com ranking e título por cima; à direita, em
// coluna, um bloco com pôster + sinopse e outro com os fatos + CTA.
//
// Histórico do que NÃO funcionou (não repetir): arte transbordando por trás das
// fileiras vizinhas (fade longo); faixa baixa de 340px com a arte recortada
// ("Faixa cinema" — cortava demais a imagem); pôster + fundo borrado ("D", não
// agradou). Aqui a arte nunca é recortada além do ajuste 16:9 → 16:9 do próprio
// backdrop, e não há gradiente tentando se fundir com o fundo: cada bloco tem
// borda própria sobre o preto da página.
//
// Geometria: a altura da linha vem do bloco da esquerda (16:9 da largura); a
// coluna da direita NÃO contribui pra altura em `lg` (absolute inset-0 dentro do
// wrapper) — só preenche o que sobra, senão uma sinopse longa esticaria a linha
// e deformaria o 16:9. Abaixo de `lg` empilha e cada bloco usa a altura natural.
// O bloco de fatos tem a altura do próprio conteúdo (`flex-none`) e o da sinopse
// leva todo o resto (`flex-1`) — com os dois `flex-1` sobrava um vazio entre os
// fatos e o botão. A sinopse ocupa TODA a altura do bloco (a mesma do pôster, que
// estica junto) e corta só quando acaba o espaço: `SinopseAjustavel` mede a
// caixa e calcula o `line-clamp` (CSS puro não corta por altura disponível; a
// primeira versão fixava as linhas por faixa de largura e cortava com espaço
// sobrando).
// Tipografia, cores e pills seguem o PADRÃO DO CARROSSEL (CarrosselDestaques.jsx
// / BlocoConteudoHero.jsx) — pedido explícito do usuário, 2026-10-02: título
// `text-2xl sm:text-4xl lg:text-5xl`, sinopse `font-bold text-ink-muted`, fatos
// com rótulo `text-[11px]` caixa-alta e valor `text-sm sm:text-base` branco, e
// a mesma pill de ranking (`CLASSE_PILL_HERO`: "#N em alta").
//
// `rank`: posição do item no feed `em-alta` (1-based), calculada por quem
// renderiza (`paginas/Inicio.jsx`) — o item sozinho não carrega isso. 0 =
// desconhecido: some a pill de ranking.
//
// Fonte da arte: `item.banner_url` — já passa pelo overlay TMDB do backend
// (`integrations/servico.py::_sobrepor_arte_em_lote`) antes de chegar aqui, e
// `imagemEmAltaResolucao` sobe um backdrop TMDB de `w1280` pra `original`. Sem
// `banner_url`, não renderiza. O pôster (`capa_url`) é opcional: sem ele o
// bloco da sinopse só perde a capa.
// Sinopse que enche a altura disponível: `ResizeObserver` na caixa (flex-1,
// `min-h-0`, `overflow-hidden` — a altura vem do bloco, não do texto) e
// `line-clamp` = linhas inteiras que cabem (`floor`, nunca corta a última no
// meio). Abaixo de `lg` os blocos empilham e a caixa cresce com o texto — sem
// altura fixa pra medir —, então lá o teto é `LINHAS_EMPILHADO`.
const LINHAS_EMPILHADO = 5;
function SinopseAjustavel({ texto }) {
  const caixaRef = useRef(null);
  const textoRef = useRef(null);
  const [linhas, setLinhas] = useState(null);

  useEffect(() => {
    const caixa = caixaRef.current;
    const paragrafo = textoRef.current;
    if (!caixa || !paragrafo) return undefined;
    const medir = () => {
      const estilo = getComputedStyle(paragrafo);
      const alturaLinha = parseFloat(estilo.lineHeight) || parseFloat(estilo.fontSize) * 1.5;
      const cabem = Math.max(1, Math.floor(caixa.clientHeight / alturaLinha));
      const empilhado = !window.matchMedia('(min-width: 1024px)').matches;
      setLinhas(empilhado ? Math.min(cabem, LINHAS_EMPILHADO) : cabem);
    };
    const observador = new ResizeObserver(medir);
    observador.observe(caixa);
    return () => observador.disconnect();
  }, [texto]);

  return (
    <div ref={caixaRef} className="min-h-0 flex-1 overflow-hidden">
      <p
        ref={textoRef}
        className="text-sm font-bold text-ink-muted sm:text-base"
        style={
          linhas
            ? {
                display: '-webkit-box',
                WebkitBoxOrient: 'vertical',
                WebkitLineClamp: linhas,
                overflow: 'hidden',
              }
            : undefined
        }
      >
        {texto}
      </p>
    </div>
  );
}

const CLASSE_BLOCO = 'rounded-2xl border border-white/10 bg-[#111114]';
const CLASSE_ROTULO = 'text-[11px] font-bold uppercase tracking-wide text-ink-muted';

export default function DestaqueGrande({ item, aoAtivar, desabilitado, rank = 0 }) {
  if (!item.banner_url) return null;

  const titulo = item.titulo_romaji || item.titulo_ingles;
  const catalogado = item.anime_id != null;
  const proximoEpisodio = textoProximoEpisodio(item);

  const fatos = [
    item.ano_estreia != null ? { rotulo: 'Ano', valor: String(item.ano_estreia) } : null,
    (item.generos ?? []).length > 0
      ? { rotulo: 'Gêneros', valor: item.generos.slice(0, 3).map(traduzirGenero).join(', ') }
      : null,
    proximoEpisodio ? { rotulo: 'Próximo episódio', valor: proximoEpisodio } : null,
  ].filter(Boolean);

  return (
    <section
      aria-label={titulo}
      className="grid gap-4 py-5 lg:grid-cols-[11fr_7fr]"
      style={{ paddingInline: PADDING_TITULO }}
    >
      <div className="relative aspect-video overflow-hidden rounded-2xl bg-surface">
        <img
          src={imagemEmAltaResolucao(item.banner_url)}
          alt=""
          loading="lazy"
          className="absolute inset-0 h-full w-full object-cover"
        />
        {/* Só o que o texto precisa pra ler sobre a arte (topo p/ a pill, base
            p/ o título) — não é fade pra fundir com o fundo da página. */}
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-0"
          style={{
            background:
              'linear-gradient(180deg, rgba(0,0,0,0.3) 0%, rgba(0,0,0,0) 30%, rgba(0,0,0,0.85) 100%)',
          }}
        />
        {rank > 0 && (
          <div className="absolute left-4 top-4 flex flex-wrap items-center gap-2 sm:left-5 sm:top-5">
            <span className={CLASSE_PILL_HERO}>
              <IconeEmAlta />
              {`#${rank} em alta`}
            </span>
          </div>
        )}
        <h3 className="absolute inset-x-5 bottom-4 line-clamp-2 text-2xl font-extrabold text-white sm:inset-x-7 sm:bottom-6 sm:text-4xl lg:text-5xl lg:leading-[1.2]">
          {catalogado ? (
            <Link to={`/anime/${item.anime_id}`} className="rounded-sm outline-none">
              {titulo}
            </Link>
          ) : (
            titulo
          )}
        </h3>
      </div>

      <div className="relative">
        <div className="flex flex-col gap-4 lg:absolute lg:inset-0">
          <div className={`${CLASSE_BLOCO} flex min-h-[160px] flex-1 gap-4 overflow-hidden p-4`}>
            {item.capa_url && (
              <div className="relative aspect-[2/3] flex-none self-stretch overflow-hidden rounded-2xl bg-surface">
                <img
                  src={item.capa_url}
                  alt=""
                  loading="lazy"
                  className="absolute inset-0 h-full w-full object-cover"
                />
              </div>
            )}
            <div className="flex min-w-0 flex-col gap-2 overflow-hidden">
              <span className={CLASSE_ROTULO}>Sinopse</span>
              <SinopseAjustavel texto={item.sinopse || 'Sinopse ainda não disponível.'} />
            </div>
          </div>

          <div className={`${CLASSE_BLOCO} flex flex-none flex-col gap-4 p-5`}>
            {fatos.length > 0 && (
              <div className="flex flex-wrap gap-x-6 gap-y-3">
                {fatos.map((fato) => (
                  <div key={fato.rotulo} className="flex flex-col gap-0.5">
                    <span className={CLASSE_ROTULO}>{fato.rotulo}</span>
                    <span className="text-sm font-bold text-white sm:text-base">{fato.valor}</span>
                  </div>
                ))}
              </div>
            )}

            {catalogado ? (
              <Link
                to={`/anime/${item.anime_id}`}
                aria-label={`${titulo} — assistir agora`}
                className={`${CLASSE_BOTAO_HERO} w-full! justify-center`}
              >
                <IconePlay width={20} height={20} fill="currentColor" />
                Assistir agora
              </Link>
            ) : (
              <button
                type="button"
                onClick={() => aoAtivar(item)}
                disabled={desabilitado}
                aria-label={desabilitado ? undefined : `Adicionar ${titulo} ao catálogo`}
                className={`${CLASSE_BOTAO_HERO} w-full! justify-center`}
              >
                <IconePlay width={20} height={20} fill="currentColor" />
                {desabilitado ? 'Adicionando…' : 'Adicionar ao Catálogo'}
              </button>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}

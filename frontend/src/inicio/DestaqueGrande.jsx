import { Link } from 'react-router-dom';
import { IconePlay } from '../components/LinhaDeEpisodio.jsx';
import BlocoConteudoHero from './BlocoConteudoHero.jsx';
import {
  CLASSE_BOTAO_HERO,
  CLASSE_PILL_HERO,
  gradienteHeroTopoEBase,
  IconeEmAlta,
  imagemEmAltaResolucao,
  textoProximoEpisodio,
} from './CarrosselDestaques.jsx';
import { traduzirGenero } from './generos.js';

// Banner promocional único da Home, logo após "Top 10 em alta"
// (`paginas/Inicio.jsx::fileirasDaHome`). Era só a imagem, sem nenhum texto
// (estilo "feed-banner" da Crunchyroll) — pedido explícito do usuário
// (2026-09-20) trouxe de volta o MESMO bloco de conteúdo do hero
// (`./BlocoConteudoHero.jsx`, compartilhado com `CarrosselDestaques.jsx` e o
// header de `paginas/PaginaDoAnime.jsx`) sobreposto à imagem, ancorado à
// esquerda. Não tem rotação/paginação (é sempre o mesmo item) — por isso não
// leva setas nem bolinhas, únicas diferenças estruturais pro carrossel.
//
// Geometria: 3ª rodada de "igual ao carrossel" (pedido explícito do usuário,
// 2026-09-20 — desta vez posição/tamanho/estrutura IDÊNTICOS, "pedaço dos
// cards aparecendo" incluso, só sem a animação de rotação). 1ª rodada tentou
// uma caixa mais baixa e própria (`aspect-[67/30] sm:aspect-[3/1]`, medida ao
// vivo no Crunchyroll) com fade só embaixo; 2ª rodada (fade nas DUAS pontas,
// `gradienteHeroTopoEBase` — necessário porque este banner fica ENTRE
// fileiras, não no topo da página) aumentou a caixa pra `aspect-[4/3] sm:
// aspect-[16/6]` pra sobrar imagem nítida entre os dois fades. Essa 3ª
// rodada abandona a proporção própria de vez: `h-svh` (idêntico ao
// carrossel) + o MESMO `pb-10 sm:pb-14 lg:pb-[18vh] xl:pb-[20vh]` do
// `BlocoConteudoHero` de lá. A `<section>` externa não leva `paddingInline`
// próprio — full-bleed, igual à do carrossel; o gutter do texto vem de
// dentro de `BlocoConteudoHero`.
//
// Peek do "pedaço dos cards": o carrossel puxa a fileira SEGUINTE pra dentro
// do próprio fade (`-mb-28` na `<section>` de `CarrosselDestaques.jsx` em
// `paginas/Inicio.jsx`) — só precisa disso porque é o 1º elemento da página,
// sem nada ANTES pra espiar por cima. Este banner fica NO MEIO da lista de
// fileiras (`fileirasDaHome`), com fade nas duas pontas, então replica o
// mesmo `-mb-28` embaixo e espelha com `-mt-28` em cima, os dois na própria
// `<section>` — sobrepõe tanto a fileira anterior quanto a seguinte (Tailwind
// `space-y-10` usa `:where()` com especificidade zero pro `margin-top`
// injetado entre irmãos, então uma margem negativa aqui, direto na classe,
// sobrepõe sem conflito). A caixa da imagem (`h-svh` abaixo) leva `-z-10`
// (mesmo `<div className="relative z-10">` de `paginas/Inicio.jsx` que
// envolve todas as fileiras) pra ficar atrás de QUALQUER vizinha — sem isso a
// fileira ANTERIOR (ex. "Top 10", que vem antes no DOM) pintaria ATRÁS deste
// banner (irmão mais tarde pinta por cima por padrão), escondendo o "pedaço
// dos cards" em vez de deixá-lo visível por cima do fade.
//
// Título/CTA por cima de QUALQUER vizinha: `BlocoConteudoHero` NÃO fica
// dentro da caixa `-z-10` acima — é irmão dela, direto dentro da `<section>`
// (que por isso ganhou `relative`, só pra ancorar o `absolute inset-x-0
// bottom-0` do bloco, sem `z-index` próprio pra não criar um contexto de
// empilhamento que prendesse o `z-10` do bloco lá dentro). `z-10` explícito
// no bloco garante que título/CTA ficam clicáveis por cima da fileira de
// cima E da de baixo, mesmo se uma ponta ou outra invadir a área do texto.
//
// `pointer-events-none` na `<section>` inteira (2026-09-21, corrige bug
// reportado pelo usuário no mesmo dia): a `<section>` É `position: relative`
// (necessário pra ancorar os filhos acima) — isso sozinho já coloca a caixa
// INTEIRA (h-svh, vazia ou não) num nível de empilhamento acima de QUALQUER
// fileira vizinha sem `position` própria, independente de DOM/`-z-10`/`z-10`
// dos filhos (confirmado com `elementFromPoint` no navegador: o alvo do
// clique era a própria `<section>`, não o `BlocoConteudoHero`). Antes de
// pills coladas no título (pedido do usuário, também 2026-09-21), a fileira
// seguinte só tinha as pílulas de paginação longe do título (`justify-
// between`), fora da faixa de 45vw do bloco de conteúdo — por isso o roubo
// de clique nunca tinha sido percebido. `pointer-events-none` aqui deixa
// clique atravessar por padrão; título e CTA reativam `pointer-events-auto`
// neles mesmos (únicos alvos de clique deste banner — a imagem é decorativa,
// `alt=""`).
//
// Fonte da imagem: `item.banner_url` — já passa pelo overlay TMDB do backend
// (`integrations/servico.py::_sobrepor_arte_em_lote`) antes de chegar aqui, e
// `imagemEmAltaResolucao` sobe um backdrop TMDB de `w1280` pra `original`
// (mesmo upscale do carrossel). Sem `banner_url`, não renderiza nada
// (`null`). `object-cover`: testamos `object-fill` (esticar sem cortar) e
// `object-contain` (sem cortar/esticar, mas sobra barra vazia quando a
// proporção do banner não bate exata com a da caixa) e o usuário preferiu o
// corte normal.
//
// `rank` (posição no feed `em-alta`, 1-based): calculado por quem chama
// (`paginas/Inicio.jsx`, mesmo `pool.indexOf(item) + 1` do carrossel) — este
// componente só recebe o `item` isolado, não o feed inteiro.
export default function DestaqueGrande({ item, rank, aoAtivar, desabilitado }) {
  if (!item.banner_url) return null;

  const titulo = item.titulo_romaji || item.titulo_ingles;
  const tituloAlternativo =
    titulo === item.titulo_romaji ? item.titulo_ingles : item.titulo_romaji;
  const mostrarAlternativo = Boolean(tituloAlternativo) && tituloAlternativo !== titulo;
  const catalogado = item.anime_id != null;

  const proximoEpisodio = textoProximoEpisodio(item);
  const generosTraduzidos = (item.generos ?? []).slice(0, 3).map((g) => traduzirGenero(g));
  // Mesmo formato Rótulo/Valor do carrossel/página do anime.
  const fatos = [
    item.ano_estreia != null ? { rotulo: 'Ano', valor: String(item.ano_estreia) } : null,
    generosTraduzidos.length > 0
      ? { rotulo: 'Gêneros', valor: generosTraduzidos.join(', ') }
      : null,
    proximoEpisodio ? { rotulo: 'Próximo episódio', valor: proximoEpisodio } : null,
  ].filter(Boolean);

  return (
    // `-mt-28 -mb-28`: puxa a fileira anterior E a seguinte pra dentro dos
    // fades desta caixa (mesma técnica/valor do `-mb-28` do carrossel, só
    // espelhada nos dois lados) — ver comentário "Peek do..." no topo do
    // arquivo. Substitui o antigo `mb-10 lg:mb-16` (respiro extra, pedido de
    // uma rodada de design anterior) — a rodada atual quer o pedaço da
    // fileira vizinha visível, não respiro.
    <section className="relative -mt-28 -mb-28 pointer-events-none">
      {/* `-z-10`: fica atrás de QUALQUER fileira vizinha sem z-index próprio
          (mesmo `<div className="relative z-10">` de `paginas/Inicio.jsx`
          que envolve todas elas) — sem isso a fileira ANTERIOR (que vem
          antes no DOM) pintaria atrás deste banner na área de sobreposição,
          escondendo o "pedaço dos cards" em vez de deixá-lo por cima do
          fade. Ver comentário "Peek do..." no topo do arquivo. */}
      <div className="relative -z-10 h-svh min-h-[480px] w-full overflow-hidden bg-surface">
        <img
          src={imagemEmAltaResolucao(item.banner_url)}
          alt=""
          loading="lazy"
          className="absolute inset-0 h-full w-full object-cover"
        />

        {/* Variante do gradiente do carrossel/header da página do anime com
            dissolução nas DUAS pontas (topo e base) — cor do `<main>` da Home
            (`bg-black`, paginas/Inicio.jsx). Ver comentário no topo do
            arquivo. */}
        <div
          className="pointer-events-none absolute inset-0"
          style={{ background: gradienteHeroTopoEBase('#000') }}
        />
      </div>

      {/* Irmão da caixa `-z-10` acima, não filho — ver comentário "Título/CTA
          por cima de..." no topo do arquivo. */}
      <BlocoConteudoHero
        className="absolute inset-x-0 bottom-0 z-10 max-w-[90%] pb-10 sm:max-w-[70%] sm:pb-14 lg:max-w-[45vw] lg:pb-[18vh] xl:pb-[20vh]"
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
                className="pointer-events-auto rounded-sm outline-none"
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
        metaExtra={
          fatos.length > 0 && (
            <div className="flex flex-wrap gap-6">
              {fatos.map((fato) => (
                <div key={fato.rotulo} className="flex flex-col gap-0.5">
                  <span className="text-[11px] font-bold uppercase tracking-wide text-ink-muted">
                    {fato.rotulo}
                  </span>
                  <span className="text-sm font-bold text-white sm:text-base">{fato.valor}</span>
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
              className={`${CLASSE_BOTAO_HERO} pointer-events-auto`}
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
              className={`${CLASSE_BOTAO_HERO} pointer-events-auto`}
            >
              <IconePlay width={20} height={20} fill="currentColor" />
              {desabilitado ? 'Adicionando…' : 'Adicionar ao Catálogo'}
            </button>
          )
        }
      />
    </section>
  );
}

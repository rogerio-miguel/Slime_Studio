import { useId } from 'react';
import { Link } from 'react-router-dom';
// Re-exportado por components/LinhaDeEpisodio.jsx — `src/inicio/` não pode
// importar de `src/player/` direto (fronteira Clean Architecture documentada
// em paginas/Inicio.jsx, D5 do plano).
import { IconePlay } from '../components/LinhaDeEpisodio.jsx';
import { SOMBRA_SLIDE_ATIVO } from './CarrosselDestaques.jsx';
import { traduzirGenero } from './generos.js';
import { PADDING_TITULO } from './tamanhoDeCard.js';

// Card "destaque grande" da Home: banner de um lado, informações do anime do
// outro (título, sinopse, ano+gêneros, CTA de play). Seção ADICIONAL — não
// substitui o carrossel nem a fileira "Top 10 da semana"; 2 itens ALEATÓRIOS
// do Top 10 são reaproveitados aqui (repetição entre seções é aceitável,
// mesmo padrão de streaming; sorteio em `paginas/Inicio.jsx::amostraAleatoria`)
// e intercalados entre as fileiras temáticas via ./intercalarDestaques.js.
//
// Painel de imagem: SEMPRE `aspect-video` (16:9) — mesma proporção do card de
// "Continuar assistindo" (components/CartaoContinuarAssistindo.jsx →
// CartaoDeEpisodio modo grade), só maior, não o formato mais wide do
// billboard (CarrosselDestaques.jsx, ~7:3/1783:608). Fonte da imagem é o
// BANNER (paisagem), nunca o pôster (retrato) — quando `banner_url` falta, o
// fallback é o mesmo do header de PaginaDoAnime.jsx/CarrosselDestaques.jsx:
// `capa_cor` (cor dominante da AniList) como fundo, com a própria capa
// borrada/escurecida por cima como textura; sem `capa_cor` também, cai no
// `bg-surface` do container.
//
// `sinopse` chega já resolvida pelo caller (cruzamento com o catálogo local
// por `anime_id` — este componente não sabe de onde veio nem tenta buscar).
// Ausente (anime não catalogado, ou sinopse não veio) → parágrafo
// simplesmente não renderiza, mesma disciplina de exibição silenciosa do
// resto da página.
//
// CTA (ChamadaParaAcao): três estados, decididos pelo caller e recebidos já
// resolvidos —
//   1. catalogado + entrada em "Continuar assistindo" → <Link> pro player,
//      "Continuar assistindo" (mesmo `state` que CartaoContinuarAssistindo.jsx
//      passa: `{ episodio: { numero, animeId, animeTitulo, titulo } }`);
//   2. catalogado sem entrada → <Link> pra `/anime/:id`, "Assistir agora";
//   3. não catalogado → <button> que materializa (`aoMaterializar`, mesma
//      função dos outros cards do feed), desabilitado durante
//      `materializando` (gate GLOBAL — `chaveEmMaterializacao != null` em
//      Inicio.jsx, não por item; mesmo comportamento de AnimeCard/
//      CarrosselDestaques nos cards do feed), rótulo "Adicionando…" nesse
//      estado (mesmo texto de DestaquePrincipal.jsx).
// Nos três casos o `IconePlay` acompanha o texto.

const CLASSE_CTA =
  'mt-1 inline-flex w-fit items-center gap-2 rounded-md bg-neon px-6 py-3 text-sm font-semibold text-black outline-none transition-colors hover:bg-neon/90 focus-visible:ring-2 focus-visible:ring-neon focus-visible:ring-offset-2 focus-visible:ring-offset-black disabled:cursor-not-allowed disabled:opacity-50';

function ChamadaParaAcao({ item, titulo, continuarEm, aoMaterializar, materializando }) {
  if (item.anime_id != null && continuarEm) {
    return (
      <Link
        to={`/assistir/${continuarEm.episodio_id}`}
        state={{
          episodio: {
            numero: continuarEm.numero,
            animeId: continuarEm.anime_id,
            animeTitulo: continuarEm.anime_titulo,
            titulo: continuarEm.titulo,
          },
        }}
        aria-label={`Continuar assistindo ${titulo} — episódio ${continuarEm.numero}`}
        className={CLASSE_CTA}
      >
        <IconePlay width={16} height={16} />
        Continuar assistindo
      </Link>
    );
  }

  if (item.anime_id != null) {
    return (
      <Link to={`/anime/${item.anime_id}`} aria-label={`${titulo} — assistir agora`} className={CLASSE_CTA}>
        <IconePlay width={16} height={16} />
        Assistir agora
      </Link>
    );
  }

  return (
    <button
      type="button"
      onClick={() => aoMaterializar(item)}
      disabled={materializando}
      aria-label={materializando ? undefined : `Adicionar ${titulo} ao catálogo e assistir`}
      className={CLASSE_CTA}
    >
      <IconePlay width={16} height={16} />
      {materializando ? 'Adicionando…' : 'Assistir agora'}
    </button>
  );
}

export default function DestaqueGrande({ item, sinopse, continuarEm, aoMaterializar, materializando }) {
  const idTitulo = useId();
  const titulo = item.titulo_romaji || item.titulo_ingles;
  const temBanner = Boolean(item.banner_url);
  const generosTraduzidos = (item.generos ?? []).slice(0, 3).map((genero) => traduzirGenero(genero));
  const meta = [item.ano_estreia, generosTraduzidos.join(', ')].filter(Boolean).join(' • ');

  return (
    <section aria-labelledby={idTitulo} style={{ paddingInline: PADDING_TITULO }}>
      <article
        className="flex flex-col overflow-hidden rounded-2xl bg-surface sm:flex-row"
        style={{ boxShadow: SOMBRA_SLIDE_ATIVO }}
      >
        <div className="relative aspect-video w-full shrink-0 overflow-hidden bg-surface sm:w-2/5">
          {temBanner ? (
            <img
              src={item.banner_url}
              alt=""
              loading="lazy"
              className="absolute inset-0 h-full w-full object-cover"
            />
          ) : (
            <div
              className="absolute inset-0"
              style={item.capa_cor ? { backgroundColor: item.capa_cor } : undefined}
            >
              {item.capa_url && (
                <img
                  src={item.capa_url}
                  alt=""
                  loading="lazy"
                  className="absolute inset-0 h-full w-full object-cover scale-125 blur-lg brightness-[0.5] opacity-70"
                />
              )}
            </div>
          )}
        </div>

        <div className="flex flex-1 flex-col justify-center gap-3 p-6 sm:p-8">
          <h2 id={idTitulo} className="text-2xl font-bold text-white sm:text-3xl">
            {titulo}
          </h2>
          {sinopse && <p className="line-clamp-4 text-sm text-ink-muted sm:text-base">{sinopse}</p>}
          {meta && <p className="text-xs text-ink-muted sm:text-sm">{meta}</p>}
          <ChamadaParaAcao
            item={item}
            titulo={titulo}
            continuarEm={continuarEm}
            aoMaterializar={aoMaterializar}
            materializando={materializando}
          />
        </div>
      </article>
    </section>
  );
}

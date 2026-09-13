import { useId } from 'react';
import { Link } from 'react-router-dom';
// Re-exportado por components/LinhaDeEpisodio.jsx — `src/inicio/` não pode
// importar de `src/player/` direto (fronteira Clean Architecture documentada
// em paginas/Inicio.jsx, D5 do plano).
import { IconePlay } from '../components/LinhaDeEpisodio.jsx';
import {
  CLASSE_BOTAO_HERO,
  CLASSE_PILL_HERO,
  IconeEmAlta,
  SOMBRA_SLIDE_ATIVO,
  textoProximoEpisodio,
} from './CarrosselDestaques.jsx';
import { traduzirGenero } from './generos.js';
import { PADDING_TITULO } from './tamanhoDeCard.js';

// Card "destaque grande" da Home: banner de um lado, painel de informações do
// outro. Seção ADICIONAL — não substitui o carrossel hero nem a fileira "Top
// 10 da semana". Os 2 itens vêm de uma amostra ALEATÓRIA do feed
// `GET /api/animes/em-alta` INTEIRO (até 50) EXCLUINDO o recorte que o
// carrossel exibe agora (inicio/janelaDeDestaques.js::recorteVisivelDoCarrossel,
// cruzado em paginas/Inicio.jsx::destaquesGrandes) — as duas seções não
// repetem os mesmos animes. Sorteio em `paginas/Inicio.jsx::amostraAleatoria`;
// os cards ficam intercalados ao longo de TODAS as fileiras da home
// (`paginas/Inicio.jsx::fileirasDaHome`, não só as temáticas) via
// ./intercalarDestaques.js.
//
// O painel de info espelha o bloco de conteúdo do carrossel hero
// (CarrosselDestaques.jsx): pills (`#N em alta` / "Anime no Catálogo"), título
// grande (link pra `/anime/:id` quando catalogado), título alternativo, meta
// (ano • gêneros), linha do próximo episódio e UM CTA em pílula branca. As
// classes (`CLASSE_PILL_HERO`, `CLASSE_BOTAO_HERO`), o `IconeEmAlta` e
// `textoProximoEpisodio` são importados de lá — fonte única. Sem sinopse: o
// bloco do carrossel também não tem.
//
// Painel de imagem: SEMPRE `aspect-video` (16:9) — mesma proporção do card de
// "Continuar assistindo" (components/CartaoContinuarAssistindo.jsx →
// CartaoDeEpisodio modo grade), só maior, não o formato mais wide do
// billboard (CarrosselDestaques.jsx). Fonte da imagem é o BANNER (paisagem),
// nunca o pôster (retrato) — quando `banner_url` falta, o fallback é o mesmo
// do header de PaginaDoAnime.jsx/CarrosselDestaques.jsx: `capa_cor` (cor
// dominante da AniList) como fundo, com a própria capa borrada/escurecida por
// cima como textura; sem `capa_cor` também, cai no `bg-surface` do container.
//
// CTA (ChamadaParaAcao): três estados, decididos pelo caller e recebidos já
// resolvidos —
//   1. catalogado + entrada em "Continuar assistindo" → <Link> pro player,
//      "Continuar assistindo" (mesmo `state` que CartaoContinuarAssistindo.jsx
//      passa: `{ episodio: { numero, animeId, animeTitulo, titulo } }`);
//   2. catalogado sem entrada → <Link> pra `/anime/:id`, "Assistir agora";
//   3. não catalogado → <button> que materializa (`aoMaterializar`, mesma
//      função dos outros cards do feed), desabilitado durante `materializando`
//      (gate GLOBAL — `chaveEmMaterializacao != null` em Inicio.jsx, não por
//      item), rótulo "Adicionando…"/"Adicionar ao Catálogo" (mesmo texto do
//      carrossel).
// Nos três casos o `IconePlay` acompanha o texto (mesmo tamanho do carrossel).

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
        className={CLASSE_BOTAO_HERO}
      >
        <IconePlay width={20} height={20} fill="currentColor" />
        Continuar assistindo
      </Link>
    );
  }

  if (item.anime_id != null) {
    return (
      <Link
        to={`/anime/${item.anime_id}`}
        aria-label={`${titulo} — assistir agora`}
        className={CLASSE_BOTAO_HERO}
      >
        <IconePlay width={20} height={20} fill="currentColor" />
        Assistir agora
      </Link>
    );
  }

  return (
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
  );
}

export default function DestaqueGrande({ item, rank, continuarEm, aoMaterializar, materializando }) {
  const idTitulo = useId();
  const titulo = item.titulo_romaji || item.titulo_ingles;
  const catalogado = item.anime_id != null;
  const tituloAlternativo =
    titulo === item.titulo_romaji ? item.titulo_ingles : item.titulo_romaji;
  const mostrarAlternativo = Boolean(tituloAlternativo) && tituloAlternativo !== titulo;
  const generosTraduzidos = (item.generos ?? []).slice(0, 3).map((g) => traduzirGenero(g));
  const meta = [item.ano_estreia, generosTraduzidos.join(', ')].filter(Boolean).join(' • ');
  const proximoEpisodio = textoProximoEpisodio(item);
  const temBanner = Boolean(item.banner_url);

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

        <div className="flex flex-1 flex-col justify-center gap-4 p-6 sm:p-8">
          {(rank > 0 || catalogado) && (
            <div className="flex flex-wrap items-center gap-2">
              {rank > 0 && (
                <span className={CLASSE_PILL_HERO}>
                  <IconeEmAlta />
                  {`#${rank} em alta`}
                </span>
              )}
              {catalogado && <span className={CLASSE_PILL_HERO}>Anime no Catálogo</span>}
            </div>
          )}

          <div>
            <h2
              id={idTitulo}
              className="mb-1 line-clamp-2 text-2xl font-extrabold text-white sm:text-3xl lg:text-4xl"
            >
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
            </h2>
            {mostrarAlternativo && (
              <p className="line-clamp-1 text-base font-bold text-ink-muted sm:text-lg">
                {tituloAlternativo}
              </p>
            )}
          </div>

          {(meta || proximoEpisodio) && (
            <div className="flex flex-col items-start gap-1">
              {meta && <p className="text-xs text-ink-muted sm:text-sm">{meta}</p>}
              {proximoEpisodio && <p className="text-xs text-white/70 sm:text-sm">{proximoEpisodio}</p>}
            </div>
          )}

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

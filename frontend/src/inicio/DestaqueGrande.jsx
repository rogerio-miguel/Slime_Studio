import { Link } from 'react-router-dom';
import { IconePlay } from '../components/LinhaDeEpisodio.jsx';
import {
  CLASSE_BOTAO_HERO,
  gradienteSuave,
  imagemEmAltaResolucao,
} from './CarrosselDestaques.jsx';

// Banner promocional único da Home, logo após "Top 10 em alta"
// (`paginas/Inicio.jsx::fileirasDaHome`). Era só a imagem, sem nenhum texto
// (estilo "feed-banner" da Crunchyroll) — pedido explícito do usuário
// (2026-09-20) trouxe de volta um bloco de conteúdo sobreposto à imagem.
//
// Redesign (2026-09-23, pedido explícito do usuário): referência é o card do
// topo de anthropic.com — conteúdo CENTRALIZADO (não mais ancorado à
// esquerda), título grande, subtítulo curto e UM único CTA. O botão em si
// (`CLASSE_BOTAO_HERO` + `IconePlay`) voltou a ser o MESMO do carrossel —
// pedido explícito do usuário logo em seguida — só o layout ao redor
// (centralizado, sem pills/fatos) segue a referência da Anthropic.
// Deixou de usar `./BlocoConteudoHero.jsx` (compartilhado com
// `CarrosselDestaques.jsx` e o header de `paginas/PaginaDoAnime.jsx`) — "por
// enquanto deixa sem esse bloco" — então as pills de rank/catalogado e o grid
// de fatos (ano/gêneros/próximo episódio) que ele carregava não têm
// equivalente aqui neste layout próprio.
//
// Geometria da caixa: peek da fileira vizinha via overlap negativo, `-z-10`/
// `z-10`, `pointer-events-none` na `<section>` continuam a mesma técnica do
// layout anterior — motivo estrutural (sobreposição com as fileiras
// vizinhas), não estético. Altura e sombra MUDARAM (pedido explícito do
// usuário, 2026-09-23): não é mais `h-svh` (tela cheia, herdado do
// carrossel) — virou um banner bem mais baixo, já que aqui é só um bloco de
// texto centralizado, sem o painel de fatos/sinopse que ocupava o
// `BlocoConteudoHero` do carrossel e precisava da altura toda.
//
// `-mt-16 -mb-16` (64px, ERA `-mt-28 -mb-28`/112px do layout h-svh): reduzido
// na mesma proporção da altura — 112px era ~12% de uma caixa de tela cheia;
// mantido em pixels cheios o overlap virava ~25-30% da caixa bem mais baixa,
// cobrindo de forma abrupta (sem gradiente por baixo, já que é a fileira
// VIZINHA por cima da imagem, não um overlay) um pedaço grande demais dela —
// bug relatado pelo usuário ("os cards por cima da imagem").
//
// Overlay: primeira tentativa usava `rgba(0,0,0,0.55/0.7)` (alfa < 1) nas
// pontas — ficava "sem sombra nenhuma" (feedback do usuário) porque a ponta
// nunca chegava no PRETO SÓLIDO da `bg-black` da página/fileiras, só um cinza
// translúcido sobre a arte; a emenda com o fundo ficava visível em vez de
// dissolver. 2ª tentativa: `#000` puro nas pontas via 2 stops crus
// (`linear-gradient(#000, transparent X%)`) — chegava a opaco de verdade, mas
// a queda linear parecia "brusca" perto da ponta opaca (o olho não percebe
// opacidade de forma linear, ver `ESTAGIOS_ALFA_SUAVE` em
// CarrosselDestaques.jsx). Versão atual reusa a MESMA curva suave do
// carrossel (`gradienteSuave`, exportada de lá) em vez de reinventar — só 2
// camadas (topo/base), sem as 4 empilhadas de `gradienteHeroTopoEBase`
// (calibradas pro hero cheio com texto ancorado embaixo à esquerda, que
// deixavam esta caixa mais baixa "muito escura", 1º feedback do usuário).
//
// Fonte da imagem: `item.banner_url` — já passa pelo overlay TMDB do backend
// (`integrations/servico.py::_sobrepor_arte_em_lote`) antes de chegar aqui, e
// `imagemEmAltaResolucao` sobe um backdrop TMDB de `w1280` pra `original`
// (mesmo upscale do carrossel). Sem `banner_url`, não renderiza nada
// (`null`).
export default function DestaqueGrande({ item, aoAtivar, desabilitado }) {
  if (!item.banner_url) return null;

  const titulo = item.titulo_romaji || item.titulo_ingles;
  const tituloAlternativo =
    titulo === item.titulo_romaji ? item.titulo_ingles : item.titulo_romaji;
  const mostrarAlternativo = Boolean(tituloAlternativo) && tituloAlternativo !== titulo;
  const catalogado = item.anime_id != null;

  return (
    <section className="relative -mt-16 mb-10 pointer-events-none">
      <div className="relative -z-10 h-[55vh] min-h-[320px] w-full overflow-hidden bg-surface sm:h-[65vh] lg:h-[80vh]">
        <img
          src={imagemEmAltaResolucao(item.banner_url)}
          alt=""
          loading="lazy"
          className="absolute inset-0 h-full w-full object-cover"
        />
        <div
          className="pointer-events-none absolute inset-0"
          style={{
            background: `${gradienteSuave('to bottom', '#000', 25)}, ${gradienteSuave('to top', '#000', 62)}`,
          }}
        />
      </div>

      {/* Conteúdo centralizado — título, subtítulo e UM CTA em pill, tudo
          alinhado ao centro horizontal (referência: card do topo de
          anthropic.com). Irmão da caixa `-z-10` acima, não filho — mesmo
          motivo do layout anterior: fica por cima de QUALQUER fileira
          vizinha, mesmo se uma ponta do fade invadir a área do texto. */}
      <div className="pointer-events-none absolute inset-x-0 bottom-0 z-10 flex flex-col items-center gap-4 px-6 pb-8 text-center sm:pb-10 lg:pb-12">
        <h3 className="line-clamp-2 max-w-3xl text-3xl font-extrabold text-white sm:text-5xl lg:text-6xl">
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

        {mostrarAlternativo && (
          <p className="line-clamp-1 max-w-2xl text-lg font-bold text-ink-muted sm:text-2xl">
            {tituloAlternativo}
          </p>
        )}

        {catalogado ? (
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
        )}
      </div>
    </section>
  );
}

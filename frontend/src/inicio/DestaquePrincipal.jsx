import { Link } from 'react-router-dom';

// Destaque principal da Inicio — desde a Fase 4 recebe o primeiro item do
// feed "em alta" (`GET /api/animes/em-alta`, provedor externo) em vez de uma
// linha do catálogo local: fetch derivado de episódios (pra montar "N
// episódios disponíveis") foi removido, sem substituto — o feed hoje não
// traz sinopse (`AnimeEmAltaSaida` em `backend/api/esquemas.py` não tem esse
// campo), então a linha de descrição só aparece se algum dia vier
// preenchida.
//
// CTA depende de o item já estar catalogado localmente (`anime_id`
// preenchido pelo servidor, cruzado por `anilist_id`): se sim, leva pra
// página do anime; se não, dispara `aoMaterializar` (função injetada pelo
// caller — `POST /api/admin/animes` + navegação — compartilhada com os
// cards da faixa "No ar nesta temporada", mesma ação em dois lugares).
export default function DestaquePrincipal({ item, aoMaterializar, materializando }) {
  if (!item) return null;

  return (
    <section aria-labelledby="titulo-destaque" className="mx-auto max-w-6xl px-6 pb-16 pt-10">
      <span className="mb-3 inline-block w-fit rounded border border-neon-soft bg-neon/5 px-2 py-0.5 text-[10px] font-bold uppercase tracking-widest text-neon">
        Em destaque
      </span>
      <h1
        id="titulo-destaque"
        className="mb-3 max-w-2xl text-4xl font-bold leading-tight text-white sm:text-5xl"
      >
        {item.titulo_romaji}
      </h1>
      {item.sinopse && (
        <p className="mb-6 max-w-2xl text-sm text-ink-muted">{item.sinopse}</p>
      )}
      {item.anime_id != null ? (
        <Link
          to={`/anime/${item.anime_id}`}
          className="inline-block rounded-md bg-neon px-6 py-3 text-sm font-semibold text-on-neon outline-none transition-colors hover:bg-neon/90"
        >
          Ver episódios
        </Link>
      ) : (
        <button
          type="button"
          onClick={() => aoMaterializar(item)}
          disabled={materializando}
          className="inline-block rounded-md bg-neon px-6 py-3 text-sm font-semibold text-on-neon outline-none transition-colors hover:bg-neon/90 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {materializando ? 'Adicionando…' : 'Adicionar e assistir'}
        </button>
      )}
    </section>
  );
}

import { Link } from 'react-router-dom';
import { listarEpisodios } from '../api/recursos.js';
import { useRecurso } from '../api/useRecurso.js';

// Destaque principal da Inicio — decisão do usuário sobre dados faltantes
// (não existe sinopse/gêneros no modelo hoje): mostra uma linha derivada
// ("{ano} · {N} episódios disponíveis") no lugar de descrição, em vez de
// placeholder. "Assistir agora" aponta pro primeiro episódio com
// status "pronto" (mesmo padrão de components/LinhaDeEpisodio.jsx); sem
// nenhum pronto, vira link secundário pra página do anime (não um botão
// morto).
export default function DestaquePrincipal({ anime }) {
  const animeId = anime?.id ?? null;
  const { dados: episodios } = useRecurso(
    () => (animeId != null ? listarEpisodios(animeId) : Promise.resolve([])),
    [animeId]
  );

  if (!anime) return null;

  const episodiosProntos = (episodios ?? []).filter((episodio) => episodio.status === 'pronto');
  const primeiroPronto = [...episodiosProntos].sort((a, b) => a.numero - b.numero)[0] ?? null;
  const linhaDerivada = [
    anime.ano ?? null,
    `${episodiosProntos.length} episódio${episodiosProntos.length === 1 ? '' : 's'} disponíve${
      episodiosProntos.length === 1 ? 'l' : 'is'
    }`,
  ]
    .filter(Boolean)
    .join(' · ');

  return (
    <section aria-labelledby="titulo-destaque" className="mx-auto max-w-6xl px-6 pb-16 pt-10">
      <span className="mb-3 inline-block w-fit rounded border border-neon-soft bg-neon/5 px-2 py-0.5 text-[10px] font-bold uppercase tracking-widest text-neon">
        Em destaque
      </span>
      <h1
        id="titulo-destaque"
        className="mb-3 max-w-2xl text-4xl font-bold leading-tight text-white sm:text-5xl"
      >
        {anime.titulo}
      </h1>
      <p className="mb-6 text-sm text-ink-muted">{linhaDerivada}</p>
      {primeiroPronto ? (
        <Link
          to={`/assistir/${primeiroPronto.id}`}
          state={{
            episodio: {
              numero: primeiroPronto.numero,
              animeId: anime.id,
              animeTitulo: anime.titulo,
              titulo: primeiroPronto.titulo,
            },
          }}
          className="inline-block rounded-md bg-neon px-6 py-3 text-sm font-semibold text-black outline-none transition-colors hover:bg-neon/90 focus-visible:ring-2 focus-visible:ring-neon focus-visible:ring-offset-2 focus-visible:ring-offset-black"
        >
          Assistir agora
        </Link>
      ) : (
        <Link
          to={`/anime/${anime.id}`}
          className="inline-block rounded-md border border-border-chrome px-6 py-3 text-sm font-semibold text-ink-muted outline-none transition-colors hover:border-neon-soft hover:text-white focus-visible:ring-2 focus-visible:ring-neon"
        >
          Ver detalhes
        </Link>
      )}
    </section>
  );
}

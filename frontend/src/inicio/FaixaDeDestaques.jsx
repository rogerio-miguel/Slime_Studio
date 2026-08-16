import AnimeCard from '../components/AnimeCard.jsx';

// Faixa horizontal de animes em destaque — reaproveita AnimeCard.jsx
// (mesmo componente da Galeria em /animes), sem duplicar a linguagem
// visual do card. Mostra o restante do catálogo (exceto o já exibido em
// DestaquePrincipal), na mesma ordem que a API devolve (por título).
export default function FaixaDeDestaques({ animes, idDestacado }) {
  const lista = (animes ?? []).filter((anime) => anime.id !== idDestacado);

  if (lista.length === 0) return null;

  return (
    <section aria-labelledby="titulo-faixa-destaques" className="mx-auto max-w-6xl px-6 pb-16">
      <h2 id="titulo-faixa-destaques" className="mb-4 text-lg font-semibold text-white">
        Em destaque no catálogo
      </h2>
      <div className="flex gap-4 overflow-x-auto pb-2">
        {lista.map((anime) => (
          <div key={anime.id} className="w-40 flex-none sm:w-48">
            <AnimeCard anime={anime} />
          </div>
        ))}
      </div>
    </section>
  );
}

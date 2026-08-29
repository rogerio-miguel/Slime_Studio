import { Link } from 'react-router-dom';

// Card da seção "Vídeos locais" (paginas/Galeria.jsx) — mesmo motivo de
// CartaoContinuarAssistindo.jsx pra não reaproveitar AnimeCard.jsx: alvo de
// navegação é o player direto (`/assistir-local/:slug`, ver
// paginas/PaginaDoPlayerLocal.jsx), não a página do anime, e não há
// `anime.id`/capa de provedor aqui — é só `videosLocais.js`. Sem capa: o
// arquivo local não carrega imagem nenhuma, então cai sempre no layout
// tipográfico (borda neon, título ancorado embaixo) que AnimeCard.jsx já usa
// como fallback pra "sem capa" — mesmas classes, sem duplicar a decisão
// visual.
export default function CartaoDeVideoLocal({ video }) {
  return (
    <Link
      to={`/assistir-local/${video.slug}`}
      className="relative flex aspect-[2/3] w-full flex-col justify-between overflow-hidden rounded-xl border border-neon-soft bg-surface p-4 text-left outline-none transition-all duration-200 hover:-translate-y-1 hover:border-neon hover:bg-surface-hover focus-visible:-translate-y-1 focus-visible:border-neon focus-visible:ring-2 focus-visible:ring-neon"
    >
      <h2 className="mt-auto line-clamp-2 text-sm font-semibold leading-snug text-white transition-colors hover:text-neon lg:text-base">
        {video.titulo}
      </h2>
    </Link>
  );
}

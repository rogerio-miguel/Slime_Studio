import { Link } from 'react-router-dom';

// Card da seção "Vídeos locais" (paginas/Galeria.jsx) — mesmo motivo de
// CartaoContinuarAssistindo.jsx pra não reaproveitar AnimeCard.jsx: alvo de
// navegação é o player direto (`/assistir-local/:slug`, ver
// paginas/PaginaDoPlayerLocal.jsx), não a página do anime, e não há
// `anime.id`/capa de provedor aqui — é só `videosLocais.js`.
//
// Sem capa: o arquivo local não carrega imagem nenhuma, então usa o mesmo
// layout tipográfico do fallback "sem capa" de AnimeCard.jsx — e a MESMA
// mecânica de hover do catálogo: escala no wrapper `group/card`
// (`hover:scale-105` + `focus-within:scale-105`, `hover:z-10` pra crescer por
// cima dos vizinhos) e borda neon de 4px via overlay `aria-hidden` que acende
// no HOVER, em vez de `border` real sempre visível. Classes copiadas de
// AnimeCard.jsx pra ficar pixel-idêntico. Sem indicador de FOCO de teclado
// por decisão explícita do usuário (2026-09-13) — a borda daqui já não reage
// mais a `group-focus-within/card`, só a `group-hover/card`.
export default function CartaoDeVideoLocal({ video }) {
  return (
    <div className="group/card relative transition-transform duration-300 ease-out motion-reduce:transition-none hover:z-10 hover:scale-105 focus-within:z-10 focus-within:scale-105">
      <Link
        to={`/assistir-local/${video.slug}`}
        className="relative flex aspect-[2/3] w-full flex-col justify-between overflow-hidden rounded-xl bg-surface p-4 text-left outline-none transition-all duration-200 hover:bg-surface-hover"
      >
        <h2 className="relative mt-auto line-clamp-2 text-sm font-semibold leading-snug text-white transition-colors group-hover/card:text-neon lg:text-base">
          {video.titulo}
        </h2>
        {/* Borda neon: overlay por cima do conteúdo (mesma técnica do
            AnimeCard e do CarrosselDestaques) — `border` real encolheria o
            content-box e deixaria uma moldura sempre visível ao redor. Só
            HOVER (sem `group-focus-within`, removido junto com o resto do
            indicador de foco do sistema, 2026-09-13). */}
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 rounded-xl border-4 border-transparent transition-colors duration-300 ease-out group-hover/card:border-neon motion-reduce:transition-none"
        />
      </Link>
    </div>
  );
}

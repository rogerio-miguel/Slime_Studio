import { Link } from 'react-router-dom';

// Card da seção "Vídeos locais" (paginas/Galeria.jsx) — mesmo motivo de
// CartaoContinuarAssistindo.jsx pra não reaproveitar AnimeCard.jsx: alvo de
// navegação é o player direto (`/assistir-local/:slug`, ver
// paginas/PaginaDoPlayerLocal.jsx), não a página do anime, e não há
// `anime.id` aqui — é só `videosLocais.js`.
//
// Layout portado do ramo "com capa" de AnimeCard.jsx (pedido explícito do
// usuário, 2026-09-17, pra seguir o MESMO padrão dos outros cards do
// catálogo): pôster 2:3 + legenda (só título — sem tags/badges, que não
// existem pra vídeo local) abaixo, uma caixa de hover só (`p-3 -m-3`
// cancelando o padding, `group-hover/card:bg-surface-hover`) cobrindo
// pôster+legenda, Link como camada `absolute inset-0` IRMÃ do conteúdo (não
// mais pai dele) — mesmo "stretched link" do AnimeCard catalogado. Sem
// escala/borda neon (removidas do AnimeCard a pedido do usuário, 2026-09-13,
// ver o comentário lá) — este card acompanha.
export default function CartaoDeVideoLocal({ video }) {
  return (
    <div className="group/card relative">
      <div className="relative flex w-full flex-col gap-2 p-3 -m-3 text-left transition-colors duration-300 ease-out group-hover/card:bg-surface-hover motion-reduce:transition-none">
        <div className="relative aspect-[2/3] w-full overflow-hidden bg-surface">
          <img
            src={video.capa}
            alt=""
            loading="lazy"
            className="absolute inset-0 h-full w-full object-cover"
          />
        </div>
        <div className="relative flex flex-col gap-1">
          <h2 className="line-clamp-2 text-sm font-semibold leading-snug text-white lg:text-base">
            {video.titulo}
          </h2>
        </div>
      </div>
      <Link
        to={`/assistir-local/${video.slug}`}
        className="absolute inset-0 outline-none"
        aria-label={video.titulo}
      />
    </div>
  );
}

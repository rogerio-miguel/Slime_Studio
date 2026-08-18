import { Link } from 'react-router-dom';

// Item da prateleira "Continuar assistindo" (paginas/Inicio.jsx) — cartão de
// POSIÇÃO em episódio, não de anime: por isso não reaproveita AnimeCard.jsx
// diretamente (alvo de navegação é o player de um episódio específico, com
// barra de progresso, não a página do anime). Linguagem visual portada de lá
// só como referência (superfície escura, borda neon, hover translate leve,
// capa cobrindo o cartão com gradiente, proporção 2:3 de capa de provedor).
//
// `state` do Link segue o MESMO formato que LinhaDeEpisodio.jsx já passa pro
// player (`{ episodio: { numero, animeId, animeTitulo, titulo } }`) — sem
// isso o cabeçalho do player perderia o link "voltar"/título de imediato
// (só recuperaria número/animeId depois, via o fallback de
// `GET /api/episodios/{id}` em PaginaDoPlayer.jsx).
export default function CartaoContinuarAssistindo({ item }) {
  // `duracao_s` pode ser `null` (worker não conseguiu sondar) — sem ele não
  // dá pra calcular fração, a barra fica zerada em vez de quebrar o layout.
  const percentual = item.duracao_s
    ? Math.min(100, Math.round((item.progresso_s / item.duracao_s) * 100))
    : 0;

  return (
    <Link
      to={`/assistir/${item.episodio_id}`}
      state={{
        episodio: {
          numero: item.numero,
          animeId: item.anime_id,
          animeTitulo: item.anime_titulo,
          titulo: item.titulo,
        },
      }}
      className="group relative flex aspect-[2/3] w-full flex-col justify-end overflow-hidden rounded-xl border border-neon-soft bg-surface text-left outline-none transition-all duration-200 hover:-translate-y-1 hover:border-neon hover:bg-surface-hover focus-visible:-translate-y-1 focus-visible:border-neon focus-visible:ring-2 focus-visible:ring-neon"
    >
      {item.capa_path && (
        <img src={item.capa_path} alt="" className="absolute inset-0 h-full w-full object-cover" />
      )}
      <div className="absolute inset-0 bg-gradient-to-t from-black/90 via-black/30 to-transparent" />
      <div className="relative flex flex-col gap-1.5 p-4">
        <h3 className="line-clamp-2 text-sm font-semibold leading-snug text-white transition-colors group-hover:text-neon lg:text-base">
          {item.anime_titulo}
        </h3>
        <p className="text-xs text-ink-muted">Episódio {item.numero}</p>
        <span
          role="progressbar"
          aria-label="progresso de reprodução"
          aria-valuenow={percentual}
          aria-valuemin={0}
          aria-valuemax={100}
          className="h-1 w-full overflow-hidden rounded-full bg-border-chrome"
        >
          <span style={{ width: `${percentual}%` }} className="block h-full rounded-full bg-neon" />
        </span>
      </div>
    </Link>
  );
}

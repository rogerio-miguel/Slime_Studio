import { Link } from 'react-router-dom';

// Item da prateleira "Continuar assistindo" (paginas/Inicio.jsx) — cartão de
// POSIÇÃO em episódio, não de anime: por isso não reaproveita AnimeCard.jsx
// diretamente (alvo de navegação é o player de um episódio específico, com
// barra de progresso, não a página do anime).
//
// Mesma mecânica de hover/foco do AnimeCard (Disney+): o card CRESCE em escala
// no wrapper (`scale-105`, 0,3s ease-out) e a borda neon de 4px acende via
// overlay dedicado (`group-hover/card`/`group-focus-within/card` — grupo
// NOMEADO pelo mesmo motivo do AnimeCard: a fileira horizontal tem `group`
// próprio pras setas). `group/card` no wrapper pra a badge/escala pegarem os
// irmãos; a borda no overlay, não `border`/`ring` no Link (encolheria o
// content-box / ficaria atrás dos filhos `absolute inset-0`).
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
    <div className="group/card relative transition-transform duration-300 ease-out motion-reduce:transition-none hover:z-10 hover:scale-105 focus-within:z-10 focus-within:scale-105">
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
        className="relative flex aspect-[2/3] w-full flex-col justify-end overflow-hidden rounded-xl bg-surface text-left outline-none transition-colors duration-200 hover:bg-surface-hover"
      >
        {item.capa_path && (
          <img
            src={item.capa_path}
            alt=""
            loading="lazy"
            className="absolute inset-0 h-full w-full object-cover"
          />
        )}
        <div className="absolute inset-0 bg-gradient-to-t from-black/90 via-black/30 to-transparent" />
        <div className="relative flex flex-col gap-1.5 p-4">
          <h3 className="line-clamp-2 text-sm font-semibold leading-snug text-white transition-colors group-hover/card:text-neon lg:text-base">
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
        {/* Borda neon: overlay por cima da capa/degradê (mesma técnica do
            AnimeCard e do CarrosselDestaques). */}
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 rounded-xl border-4 border-transparent transition-colors duration-300 ease-out group-hover/card:border-neon group-focus-within/card:border-neon motion-reduce:transition-none"
        />
      </Link>
    </div>
  );
}

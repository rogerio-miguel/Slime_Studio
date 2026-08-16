import { useCallback, useEffect } from 'react';
import { Link, useLocation, useParams } from 'react-router-dom';
import { marcarAssistido } from '../api/recursos.js';
import { useFocoAoMontar } from '../hooks/useFocoAoMontar.js';
import Player from '../player/Player.jsx';

// Rota "/assistir/:episodioId". Sem `GET /api/episodios/{id}` no contrato
// confirmado (só playlist/assistido/CRUD admin) — título/número/anime vêm do
// `state` da navegação (LinhaDeEpisodio.jsx passa isso no `<Link>`). Em
// acesso direto/refresh a URL ainda toca o vídeo normalmente (a playlist só
// precisa do id), só perde o cabeçalho — degradação aceitável, não afeta
// playback.
export default function PaginaDoPlayer() {
  const { episodioId } = useParams();
  const location = useLocation();
  const metadados = location.state?.episodio;
  const focoTitulo = useFocoAoMontar(episodioId);

  // player.css define `--page-chrome` prevendo justamente esta faixa de
  // cabeçalho acima do palco; a classe abaixo é o que estava faltando pra
  // `html,body{overflow:hidden}` (index.css) só valer nesta rota, sem
  // quebrar o scroll da galeria/página do anime (bug corrigido na Fase 4).
  useEffect(() => {
    document.documentElement.classList.add('pagina-player');
    document.body.classList.add('pagina-player');
    return () => {
      document.documentElement.classList.remove('pagina-player');
      document.body.classList.remove('pagina-player');
    };
  }, []);

  const aoAtingirAssistido = useCallback(
    () => marcarAssistido(episodioId),
    [episodioId]
  );

  const titulo = metadados
    ? `${metadados.animeTitulo ?? 'Slime Studio'} — Episódio ${metadados.numero}`
    : 'Slime Studio';

  return (
    <main className="flex h-full flex-col">
      <header className="flex items-center gap-4 px-4 py-2">
        {metadados?.animeId != null && (
          <Link
            to={`/anime/${metadados.animeId}`}
            className="text-sm text-ink-muted underline outline-none focus-visible:ring-2 focus-visible:ring-neon"
          >
            ← voltar
          </Link>
        )}
        <h1
          ref={focoTitulo}
          tabIndex={-1}
          className="text-sm font-medium text-white outline-none"
        >
          {titulo}
        </h1>
      </header>
      <Player
        fonte={`/api/episodios/${episodioId}/playlist.m3u8`}
        titulo={titulo}
        aoAtingirAssistido={aoAtingirAssistido}
      />
    </main>
  );
}

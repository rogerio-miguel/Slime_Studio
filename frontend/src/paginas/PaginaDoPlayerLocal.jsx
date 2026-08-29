import { useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { VIDEOS_LOCAIS } from '../videosLocais.js';
import { useFocoAoMontar } from '../hooks/useFocoAoMontar.js';
import Player from '../player/Player.jsx';

// Rota "/assistir-local/:slug" — player pra vídeo local (videosLocais.js),
// sem episodio_id/backend por trás: nada de `obterEpisodio`,
// `marcarAssistido`, `salvarProgresso` ou `liberarEpisodio` (todos exigem um
// registro real de `Episodio`, que estes arquivos não têm). `Player` já
// tolera essas props ausentes — mesmo uso em `App.jsx` (RotaDebugFonte).
//
// Mesma classe `pagina-player` (tela cheia, sem scroll) que
// PaginaDoPlayer.jsx liga/desliga — ver comentário lá pro racional completo.
export default function PaginaDoPlayerLocal() {
  const { slug } = useParams();
  const video = VIDEOS_LOCAIS.find((item) => item.slug === slug);
  const focoTitulo = useFocoAoMontar(slug);

  useEffect(() => {
    document.documentElement.classList.add('pagina-player');
    document.body.classList.add('pagina-player');
    return () => {
      document.documentElement.classList.remove('pagina-player');
      document.body.classList.remove('pagina-player');
    };
  }, []);

  if (!video) {
    return (
      <main
        role="alert"
        className="mx-auto my-10 max-w-lg rounded-lg border border-[#600] bg-[#2a0000] px-6 py-5 text-center text-[#fdd]"
      >
        Vídeo local "{slug}" não encontrado.
      </main>
    );
  }

  return (
    <main className="flex h-full flex-col">
      <Player key={slug} fonte={video.arquivo} titulo={video.titulo} focoTituloRef={focoTitulo} />
    </main>
  );
}

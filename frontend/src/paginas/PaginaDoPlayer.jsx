import { useCallback, useEffect, useRef } from 'react';
import { Link, useLocation, useParams } from 'react-router-dom';
import { liberarEpisodio, marcarAssistido, obterEpisodio, salvarProgresso } from '../api/recursos.js';
import { useRecurso } from '../api/useRecurso.js';
import { useFocoAoMontar } from '../hooks/useFocoAoMontar.js';
import Player from '../player/Player.jsx';

// Rota "/assistir/:episodioId". título/número/anime vêm preferencialmente do
// `state` da navegação (LinhaDeEpisodio.jsx passa isso no `<Link>`) — mais
// rápido, sem round-trip. Em acesso direto/refresh (sem `state`),
// `GET /api/episodios/{id}` cobre `numero`/`animeId` (link "voltar" e número
// no cabeçalho); o título do ANIME em si fica fora do contrato de
// `EpisodioSaida` (só `anime_id`), então nesse caso o cabeçalho cai para o
// nome genérico "Slime Studio" — degradação parcial aceitável, não afeta
// playback. O mesmo fetch também traz `progresso_s` (Feature "continuar
// assistindo"), que o `state` de navegação nunca carrega.
export default function PaginaDoPlayer() {
  const { episodioId } = useParams();
  const location = useLocation();
  const metadados = location.state?.episodio;
  const episodio = useRecurso(() => obterEpisodio(episodioId), [episodioId]);
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

  // Handler de saída ÚNICO (D3) — cruzou o limiar de assistido (Feature
  // "liberar ao terminar") OU não cruzou (Feature "continuar assistindo"),
  // nunca os dois: `cruzouLimiarRef` é setado no mesmo callback que já marca
  // assistido; `ultimaPosicaoRef` guarda a última posição conhecida,
  // atualizada a cada `aoSalvarProgresso` (usePosicaoDeReproducao.js, via
  // Player). `jaSaiuRef` garante que só uma das duas ações dispare de fato
  // por saída, mesmo quando `pagehide` e o cleanup do efeito abaixo ocorrem
  // juntos (fechar aba vs. navegação interna do SPA).
  const cruzouLimiarRef = useRef(false);
  const jaSaiuRef = useRef(false);
  const ultimaPosicaoRef = useRef(null);
  useEffect(() => {
    cruzouLimiarRef.current = false;
    jaSaiuRef.current = false;
    ultimaPosicaoRef.current = null;
  }, [episodioId]);

  const aoAtingirAssistido = useCallback(() => {
    cruzouLimiarRef.current = true;
    return marcarAssistido(episodioId);
  }, [episodioId]);

  // Chamado periodicamente (throttle) e ao pausar por usePosicaoDeReproducao.js
  // — guarda a posição em `ultimaPosicaoRef` ANTES do POST fire-and-forget,
  // pra o handler de saída ter a posição mais recente mesmo se este POST
  // ainda estiver em voo quando a página fechar.
  const aoSalvarProgresso = useCallback(
    (segundos) => {
      ultimaPosicaoRef.current = segundos;
      return salvarProgresso(episodioId, segundos).catch((erro) =>
        console.error('falha ao salvar progresso de reprodução', erro)
      );
    },
    [episodioId]
  );

  // `pagehide` cobre fechar aba/navegar pra fora via URL; o cleanup do
  // efeito cobre sair pela navegação interna do SPA (React Router desmonta
  // sem disparar `pagehide`). Fire-and-forget: erro de rede aqui nunca deve
  // travar a navegação, só vai pro console (CLAUDE.md §4, nunca silencioso).
  useEffect(() => {
    function aoSairDaPagina() {
      if (jaSaiuRef.current) return;
      jaSaiuRef.current = true;
      if (cruzouLimiarRef.current) {
        liberarEpisodio(episodioId, { manterVivo: true }).catch((erro) =>
          console.error('falha ao liberar episódio ao sair do player', erro)
        );
      } else if (ultimaPosicaoRef.current != null) {
        salvarProgresso(episodioId, ultimaPosicaoRef.current, { manterVivo: true }).catch((erro) =>
          console.error('falha ao salvar progresso ao sair do player', erro)
        );
      }
    }
    window.addEventListener('pagehide', aoSairDaPagina);
    return () => {
      window.removeEventListener('pagehide', aoSairDaPagina);
      aoSairDaPagina();
    };
  }, [episodioId]);

  const numero = metadados?.numero ?? episodio.dados?.numero ?? null;
  const animeId = metadados?.animeId ?? episodio.dados?.anime_id ?? null;
  const animeTitulo = metadados?.animeTitulo ?? null;
  const titulo = numero != null ? `${animeTitulo ?? 'Slime Studio'} — Episódio ${numero}` : 'Slime Studio';

  return (
    <main className="flex h-full flex-col">
      <header className="flex items-center gap-4 px-4 py-2">
        {animeId != null && (
          <Link
            to={`/anime/${animeId}`}
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
        retomarDe={episodio.dados?.progresso_s ?? null}
        aoSalvarProgresso={aoSalvarProgresso}
      />
    </main>
  );
}

import { useCallback, useEffect, useRef } from 'react';
import { useLocation, useParams } from 'react-router-dom';
import { liberarEpisodio, marcarAssistido, obterEpisodio, salvarProgresso } from '../api/recursos.js';
import { useRecurso } from '../api/useRecurso.js';
import { useFocoAoMontar } from '../hooks/useFocoAoMontar.js';
import Player from '../player/Player.jsx';

// Rota "/assistir/:episodioId". título/número vêm preferencialmente do
// `state` da navegação (LinhaDeEpisodio.jsx passa isso no `<Link>`) — mais
// rápido, sem round-trip. Em acesso direto/refresh (sem `state`),
// `GET /api/episodios/{id}` cobre `numero` e o título do EPISÓDIO
// (`EpisodioSaida.titulo`, TMDB); só o título do ANIME fica fora do
// contrato (só `anime_id`), então nesse caso o cabeçalho cai para o nome
// genérico "Slime Studio" — degradação parcial aceitável, não afeta
// playback. O mesmo fetch também traz `progresso_s` (Feature "continuar
// assistindo"), que o `state` de navegação nunca carrega.
export default function PaginaDoPlayer() {
  const { episodioId } = useParams();
  const location = useLocation();
  const metadados = location.state?.episodio;
  const episodio = useRecurso(() => obterEpisodio(episodioId), [episodioId]);
  const focoTitulo = useFocoAoMontar(episodioId);

  // Classe que liga `html,body{overflow:hidden}` (index.css) só nesta rota
  // (tela cheia, sem scroll), sem quebrar o scroll da galeria/página do
  // anime (bug corrigido na Fase 4). Título é overlay dentro do player
  // (PlayerAtivo.jsx), não mais um <header> externo aqui.
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
  const animeTitulo = metadados?.animeTitulo ?? null;
  // Mesmo título do episódio (TMDB) que RotuloEpisodio já formata na página
  // do anime — via `state` (LinhaDeEpisodio.jsx) ou, em acesso direto/refresh,
  // do próprio GET /api/episodios/{id} (`EpisodioSaida.titulo`, ao contrário
  // do nome do anime, esse campo está no contrato).
  const tituloEpisodio = metadados?.titulo ?? episodio.dados?.titulo ?? null;
  // Só vem preenchido via `state` (PaginaDoAnime.jsx manda sempre que
  // `anime.numero_temporada` é conhecido, mesmo com uma única temporada
  // catalogada — diferente do H1/seletor de lá, que só mostra com 2+, ver
  // franquia.js::tituloBaseDeTemporada). Sem `numero_temporada` no contrato
  // de `EpisodioSaida`, acesso direto/refresh sempre omite — degradação
  // parcial, mesma natureza da de animeTitulo acima.
  const numeroTemporada = metadados?.numeroTemporada ?? null;
  const titulo =
    numero != null
      ? [
          animeTitulo ?? 'Slime Studio',
          numeroTemporada != null ? `| T.${numeroTemporada}` : null,
          `EP.${numero}${tituloEpisodio ? ` - ${tituloEpisodio}` : ''}`,
        ]
          .filter(Boolean)
          .join(' ')
      : 'Slime Studio';

  return (
    <main className="flex h-full flex-col">
      {/* `key={episodioId}`: trocar de episódio SEM sair da rota "/assistir/:episodioId"
          (ex. capturar um anime, voltar e capturar outro enquanto o player de um
          episódio anterior ainda está montado) não desmonta `PaginaDoPlayer` — o React
          Router só re-renderiza com o novo param. Sem esta `key`, `PlayerAtivo` e toda
          a árvore (vídeo/hls.js, pipeline WebGPU, grafo de áudio) sobrevivem à troca de
          rota; cada hook interno reage a `fonte`/`episodioId` individualmente, e basta
          UM deles ter uma dependência incompleta pra deixar conteúdo do episódio
          anterior sobrevivendo sob o título do novo — exatamente o sintoma relatado
          (título certo, vídeo de outro episódio). Forçar remonte completo aqui garante
          vídeo/áudio/WebGPU sempre partindo de zero por episódio, sem depender de cada
          hook (vários, alguns fora deste arquivo) acertar sua lista de dependências. */}
      <Player
        key={episodioId}
        fonte={`/api/episodios/${episodioId}/playlist.m3u8`}
        titulo={titulo}
        aoAtingirAssistido={aoAtingirAssistido}
        retomarDe={episodio.dados?.progresso_s ?? null}
        aoSalvarProgresso={aoSalvarProgresso}
        focoTituloRef={focoTitulo}
      />
    </main>
  );
}

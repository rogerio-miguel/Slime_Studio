import { useCallback, useId, useMemo, useState } from 'react';
import { ErroDeApi } from '../api/cliente.js';
import { listarAnimes, listarContinuarAssistindo, removerAnime } from '../api/recursos.js';
import { useRecurso } from '../api/useRecurso.js';
import AnimeCard from '../components/AnimeCard.jsx';
import BarraDeNavegacao from '../components/BarraDeNavegacao.jsx';
import CartaoContinuarAssistindo from '../components/CartaoContinuarAssistindo.jsx';
import CartaoDeVideoLocal from '../components/CartaoDeVideoLocal.jsx';
import DialogoDeConfirmacao from '../components/DialogoDeConfirmacao.jsx';
import { useFocoAoMontar } from '../hooks/useFocoAoMontar.js';
import { COLUNAS_GRID, estiloLarguraMaxCard, SlotDeCard } from '../inicio/GradeDeCards.jsx';
import { VIDEOS_LOCAIS } from '../videosLocais.js';

// Rota "/animes" — catálogo completo. Sem cadastro manual aqui: o catálogo
// é populado materializando itens do feed de provedor externo na Home
// (`paginas/Inicio.jsx`, `POST /api/admin/animes`), não por um formulário
// nesta página.
//
// Navbar renderizada com `fase="revelado"` fixo (mesma prop que
// `paginas/Inicio.jsx` deriva de `useIntroPorVideo`, aqui não há intro —
// a navbar já nasce totalmente visível/interativa). Busca é local: mesmo
// padrão de `termoBusca`/filtro em memória de `paginas/Inicio.jsx`, sem
// `?q=` na URL nem `aoSubmeterBusca` — esta página não busca em fontes
// externas, só filtra o catálogo já carregado (`GET /api/animes` não
// aceita query param de busca e a lista é pequena o bastante, uso pessoal,
// pra não justificar um endpoint novo).
//
// `<main>` sem `max-w`: `COLUNAS_GRID` (`inicio/GradeDeCards.jsx`) fixa a
// contagem de colunas por breakpoint de VIEWPORT, não de container — um
// `max-w-5xl` aqui encolheria as tracks abaixo de `--largura-max-card` nos
// breakpoints maiores, e os cards sairiam menores que os de "Destaques da
// temporada" no mesmo viewport. Mesmo `px-6 md:px-10` de
// `paginas/Inicio.jsx`, sem teto de largura, pra ficar pixel-idêntico.
export default function Galeria() {
  const idContinuarAssistindo = useId();
  const idVideosLocais = useId();
  const [termoBusca, setTermoBusca] = useState('');
  const termoBuscaNormalizado = termoBusca.trim().toLowerCase();
  const focoTitulo = useFocoAoMontar();
  const { dados: animes, carregando, erro, recarregar } = useRecurso(listarAnimes, []);
  // Seção "Continuar assistindo" — movida da Home (paginas/Inicio.jsx) pra
  // cá: mesma condição silenciosa de exibição que já existia lá (some em
  // loading/erro, some sem progresso salvo), sem UI nova de erro/loading.
  const continuarAssistindo = useRecurso(listarContinuarAssistindo, []);
  const animesFiltrados = useMemo(
    () =>
      termoBuscaNormalizado
        ? (animes ?? []).filter((anime) => anime.titulo.toLowerCase().includes(termoBuscaNormalizado))
        : animes,
    [animes, termoBuscaNormalizado]
  );

  const [animeParaRemover, setAnimeParaRemover] = useState(null);
  const [removendo, setRemovendo] = useState(false);
  const [erroRemocao, setErroRemocao] = useState(null);

  const confirmarRemocao = useCallback(async () => {
    if (!animeParaRemover) return;
    setRemovendo(true);
    setErroRemocao(null);
    try {
      await removerAnime(animeParaRemover.id);
      setAnimeParaRemover(null);
      recarregar();
    } catch (erroCapturado) {
      if (erroCapturado instanceof ErroDeApi && erroCapturado.detail?.motivo === 'job_em_execucao') {
        setErroRemocao('Este anime tem uma captura em andamento — aguarde terminar antes de remover.');
      } else {
        console.error('falha ao remover anime do catálogo', erroCapturado);
        setErroRemocao('Não foi possível remover este anime — tente novamente.');
      }
    } finally {
      setRemovendo(false);
    }
  }, [animeParaRemover, recarregar]);

  // Fecha o dialog (cancelar, ou Esc/backdrop via DialogoDeConfirmacao) e
  // limpa `erroRemocao` junto — sem isto, um erro de uma tentativa anterior
  // "vazaria" pra próxima abertura do dialog.
  const fecharDialogoRemocao = useCallback(() => {
    setAnimeParaRemover(null);
    setErroRemocao(null);
  }, []);

  return (
    <>
      <BarraDeNavegacao fase="revelado" termoBusca={termoBusca} aoMudarBusca={setTermoBusca} />
      <main className="px-6 pb-10 pt-24 md:px-10">

        {!continuarAssistindo.carregando &&
          !continuarAssistindo.erro &&
          (continuarAssistindo.dados ?? []).length > 0 && (
            <section aria-labelledby={idContinuarAssistindo} className="mb-8">
              <h2 id={idContinuarAssistindo} className="mb-4 text-2xl font-semibold text-white">
                Continuar assistindo
              </h2>
              <div style={estiloLarguraMaxCard} className={`grid gap-6 ${COLUNAS_GRID}`}>
                {continuarAssistindo.dados.map((item, indice) => (
                  <SlotDeCard key={item.episodio_id} indice={indice}>
                    <CartaoContinuarAssistindo item={item} />
                  </SlotDeCard>
                ))}
              </div>
            </section>
          )}

        <header className="mb-8 flex flex-wrap items-center justify-between gap-4">
          <h1 ref={focoTitulo} tabIndex={-1} className="text-2xl font-semibold text-white outline-none">
            Meu Catálogo
          </h1>
        </header>

        {carregando && <p className="text-sm text-ink-muted">Carregando catálogo…</p>}
        {erro && (
          <div
            role="alert"
            className="mb-6 rounded-md border border-red-500/40 bg-red-950/40 px-4 py-3 text-sm text-red-300"
          >
            Não foi possível carregar o catálogo.{' '}
            <button type="button" onClick={recarregar} className="underline">
              Tentar novamente
            </button>
          </div>
        )}
        {!carregando && !erro && animes?.length === 0 && (
          <p className="text-sm text-ink-muted">Nenhum anime cadastrado ainda.</p>
        )}
        {!carregando && !erro && animes?.length > 0 && animesFiltrados.length === 0 && (
          <p className="text-sm text-ink-muted">Nenhum anime encontrado para “{termoBusca.trim()}”.</p>
        )}

        <div style={estiloLarguraMaxCard} className={`grid gap-6 ${COLUNAS_GRID}`}>
          {animesFiltrados?.map((anime, indice) => (
            <SlotDeCard key={anime.id} indice={indice}>
              <AnimeCard anime={anime} aoRemover={() => setAnimeParaRemover(anime)} />
            </SlotDeCard>
          ))}
        </div>

        {/* Vídeos locais (videosLocais.js) — arquivos já em disco (public/
            videos-locais/), fora do catálogo/backend por completo: card
            leva direto pro player (`/assistir-local/:slug`), sem passar
            por materialização/captura. Depois da grade principal — não é
            catálogo de verdade, é um apêndice de arquivos soltos. Some
            quando a lista está vazia, mesma condição silenciosa de
            "Continuar assistindo" acima. */}
        {VIDEOS_LOCAIS.length > 0 && (
          <section aria-labelledby={idVideosLocais} className="mt-10">
            <h2 id={idVideosLocais} className="mb-4 text-2xl font-semibold text-white">
              Vídeos locais
            </h2>
            <div style={estiloLarguraMaxCard} className={`grid gap-6 ${COLUNAS_GRID}`}>
              {VIDEOS_LOCAIS.map((video, indice) => (
                <SlotDeCard key={video.slug} indice={indice}>
                  <CartaoDeVideoLocal video={video} />
                </SlotDeCard>
              ))}
            </div>
          </section>
        )}

        <DialogoDeConfirmacao
          aberto={animeParaRemover != null}
          titulo="Remover do catálogo"
          mensagem={`Remover "${animeParaRemover?.titulo}" do catálogo? Episódios e capturas associados serão apagados.`}
          erro={erroRemocao}
          aoConfirmar={confirmarRemocao}
          aoFechar={fecharDialogoRemocao}
          confirmando={removendo}
        />
      </main>
    </>
  );
}

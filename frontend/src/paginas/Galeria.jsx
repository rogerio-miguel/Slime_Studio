import { useCallback, useId, useMemo, useState } from 'react';
import { ErroDeApi } from '../api/cliente.js';
import { listarAnimes, removerAnime } from '../api/recursos.js';
import { useRecurso } from '../api/useRecurso.js';
import AnimeCard from '../components/AnimeCard.jsx';
import BarraDeNavegacao from '../components/BarraDeNavegacao.jsx';
import CartaoDeVideoLocal from '../components/CartaoDeVideoLocal.jsx';
import DialogoDeConfirmacao from '../components/DialogoDeConfirmacao.jsx';
import { useFocoAoMontar } from '../hooks/useFocoAoMontar.js';
import CartaoDeEstreia from '../inicio/CartaoDeEstreia.jsx';
import GradeDeCatalogo from '../inicio/GradeDeCatalogo.jsx';
import { PADDING_TITULO } from '../inicio/tamanhoDeCard.js';
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
// `<main>` sem padding horizontal e sem `max-w`: as duas grades
// (`inicio/GradeDeCatalogo.jsx`) já aplicam o gutter de 3.7% de cada lado
// (via `CLASSE_GUTTER`) medindo a viewport inteira, exatamente como as
// fileiras da Home (`inicio/FileiraDeCards.jsx`). Um `px` no `<main>`
// encolheria o container que o gutter mede e os cards sairiam mais
// estreitos que os da fileira "pequeno" da Home no mesmo viewport — o
// alinhamento título/card e o tamanho de card dependem de os dois medirem
// o mesmo container. Os títulos e os estados transitórios recuperam o
// alinhamento via `paddingInline: PADDING_TITULO` (gutter 3.7% + 10px do
// slot), não via `px` no `<main>`.
export default function Galeria() {
  const idMeuCatalogo = useId();
  const idVideosLocais = useId();
  const [termoBusca, setTermoBusca] = useState('');
  const termoBuscaNormalizado = termoBusca.trim().toLowerCase();
  const focoTitulo = useFocoAoMontar();
  const { dados: animes, carregando, erro, recarregar } = useRecurso(listarAnimes, []);
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
      <BarraDeNavegacao
        fase="revelado"
        transparente
        termoBusca={termoBusca}
        aoMudarBusca={setTermoBusca}
      />
      {/* `bg-[#17171b]` + `min-h-screen`: mesmo par de classes do `<main>` de
          paginas/Inicio.jsx (fonte da verdade lá — cor exata do `body` do
          Disney+). É esse fundo que faz a drop shadow dos cards da grade
          aparecer; sobre um preto mais fechado a sombra 69% preta some.
          `min-h-screen` evita o fundo não cobrir a viewport quando o catálogo
          é curto. */}
      <main className="min-h-screen bg-[#17171b] pb-10 pt-24">
        <section aria-labelledby={idMeuCatalogo}>
          {/* Sem `mb`: o respiro até os cards vem do `pt-[22px]` interno de
              GradeDeCatalogo, igual às fileiras da Home. `paddingInline`
              (não `px` no <main>) alinha o texto com a borda do CARD —
              gutter 3.7% + os 10px do slot da grade. */}
          <h1
            ref={focoTitulo}
            tabIndex={-1}
            id={idMeuCatalogo}
            style={{ paddingInline: PADDING_TITULO }}
            className="text-2xl font-semibold text-white outline-none"
          >
            Meu Catálogo
          </h1>

          {/* Estados transitórios (carregando / erro / catálogo vazio / busca
              sem resultado) — condições inalteradas. O wrapper só repõe o
              `paddingInline` que antes vinha do `px` do <main>; cada mensagem
              leva o próprio `mt-[22px]` (mesmo respiro título->conteúdo da
              grade). Altura zero quando nada aparece. */}
          <div style={{ paddingInline: PADDING_TITULO }}>
            {carregando && (
              <p className="mt-[22px] text-sm text-ink-muted">Carregando catálogo…</p>
            )}
            {erro && (
              <div
                role="alert"
                className="mt-[22px] rounded-md border border-red-500/40 bg-red-950/40 px-4 py-3 text-sm text-red-300"
              >
                Não foi possível carregar o catálogo.{' '}
                <button type="button" onClick={recarregar} className="underline">
                  Tentar novamente
                </button>
              </div>
            )}
            {!carregando && !erro && animes?.length === 0 && (
              <p className="mt-[22px] text-sm text-ink-muted">Nenhum anime cadastrado ainda.</p>
            )}
            {!carregando && !erro && animes?.length > 0 && animesFiltrados.length === 0 && (
              <p className="mt-[22px] text-sm text-ink-muted">
                Nenhum anime encontrado para “{termoBusca.trim()}”.
              </p>
            )}
          </div>

          {/* Card inerte de estreia (CartaoDeEstreia) SÓ quando o anime
              realmente ainda não estreou (`status_lancamento === 'nao_lancado'`)
              E não tem episódio capturado. Todo o resto — já com episódio, ou
              já lançado mas sem captura, ou com fonte pendente nas extratoras —
              usa AnimeCard navegável: um anime já lançado sem captura precisa
              chegar na PaginaDoAnime pra resolver fonte / enfileirar captura;
              só o bookmark de "Próximas estreias" é beco sem saída proposital. */}
          <GradeDeCatalogo
            itens={animesFiltrados}
            tamanho="pequeno"
            chaveDoItem={(anime) => anime.id}
            renderItem={(anime) =>
              !anime.tem_episodios && anime.status_lancamento === 'nao_lancado' ? (
                <CartaoDeEstreia item={anime} aoRemover={() => setAnimeParaRemover(anime)} />
              ) : (
                <AnimeCard anime={anime} aoRemover={() => setAnimeParaRemover(anime)} />
              )
            }
          />
        </section>

        {/* Vídeos locais (videosLocais.js) — arquivos já em disco (public/
            videos-locais/), fora do catálogo/backend por completo: card
            leva direto pro player (`/assistir-local/:slug`), sem passar
            por materialização/captura. Depois da grade principal — não é
            catálogo de verdade, é um apêndice de arquivos soltos. Guard
            `length > 0` aqui na <section> (não só na grade): sem ele a
            <section>/<h2> apareceriam com a grade vazia. */}
        {VIDEOS_LOCAIS.length > 0 && (
          <section aria-labelledby={idVideosLocais} className="mt-10">
            <h2
              id={idVideosLocais}
              style={{ paddingInline: PADDING_TITULO }}
              className="text-2xl font-semibold text-white"
            >
              Vídeos locais
            </h2>
            <GradeDeCatalogo
              itens={VIDEOS_LOCAIS}
              tamanho="pequeno"
              chaveDoItem={(video) => video.slug}
              renderItem={(video) => <CartaoDeVideoLocal video={video} />}
            />
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

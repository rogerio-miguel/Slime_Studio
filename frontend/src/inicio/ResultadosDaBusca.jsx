import AnimeCard from '../components/AnimeCard.jsx';
import BotaoDeEstado from '../components/mascote/BotaoDeEstado.jsx';
import EstadoComMascote from '../components/mascote/EstadoComMascote.jsx';
import { chaveDoItemDoFeed } from './fileiras.js';
import GradeDeCatalogo from './GradeDeCatalogo.jsx';
import { PADDING_TITULO_GRADE } from './tamanhoDeCard.js';

// Resultados da busca da navbar (Início e Descobrir), no lugar do conteúdo da página:
// a busca na AniList (`busca`, de hooks/useBuscaDeAnimes.js, só no Enter). Item ainda
// não catalogado materializa ao clicar (`materializacao`,
// hooks/useMaterializarAnime.js); item já catalogado (`item.anime_id`) vira <Link>
// direto no próprio `AnimeCard`, com a pill "Já no catálogo" (`indicarCatalogado`) —
// por isso não há uma seção separada com o catálogo local. Sem `aoRemover` nos
// resultados, de propósito: a gestão do catálogo fica em `Galeria.jsx`/
// `PaginaDoAnime.jsx`.
export default function ResultadosDaBusca({ busca, materializacao }) {
  const {
    termoBusca,
    termoBuscaSubmetido,
    buscaBiblioteca,
    resultadosBiblioteca,
    resultadosDesatualizados,
    buscaBibliotecaAtiva,
  } = busca;
  const { materializarEIrPara, chaveEmMaterializacao, erro: erroMaterializacao } = materializacao;

  // Antes do Enter (ou com o campo editado depois dele, caso em que os resultados
  // antigos não são mostrados): a página só convida a buscar o que está digitado.
  // Sem `role="status"` de propósito — o termo muda a cada tecla e seria anunciado
  // a cada uma.
  if (termoBuscaSubmetido === '' || resultadosDesatualizados) {
    return (
      <section
        aria-label="Resultados da busca"
        className="flex flex-col items-center gap-4 px-6 pb-20 pt-24 text-center"
      >
        <p className="max-w-xl break-words text-2xl font-semibold text-white">
          Buscar “{termoBusca.trim()}”
        </p>
        <p className="text-sm text-ink-muted">
          Aperte{' '}
          <kbd className="rounded-md bg-white/10 px-2 py-1 font-mono text-sm text-white">Enter</kbd>{' '}
          para buscar
        </p>
      </section>
    );
  }

  return (
    <section aria-label="Resultados da busca" className="pb-20">
      <h2
        style={{ paddingInline: PADDING_TITULO_GRADE }}
        className="mt-20 text-2xl font-semibold text-white"
      >
        Resultados
      </h2>
      {/* Textos de estado — wrapper só repõe o `paddingInline`; a grade
          de resultados fica FORA dele (o `paddingInline` dobraria o
          gutter dos cards). */}
      <div style={{ paddingInline: PADDING_TITULO_GRADE }}>
        {erroMaterializacao && (
          <div role="alert" className="mt-[22px]">
            <p className="text-sm text-red-400">{erroMaterializacao}</p>
          </div>
        )}
        {buscaBibliotecaAtiva && buscaBiblioteca.carregando && (
          <p className="mt-[22px] text-sm text-ink-muted">Buscando animes…</p>
        )}
        {buscaBibliotecaAtiva && buscaBiblioteca.erro && (
          <EstadoComMascote alerta compacto mensagem="Não foi possível buscar animes.">
            <BotaoDeEstado onClick={buscaBiblioteca.recarregar}>
              Tentar novamente
            </BotaoDeEstado>
          </EstadoComMascote>
        )}
        {buscaBibliotecaAtiva &&
          !buscaBiblioteca.carregando &&
          !buscaBiblioteca.erro &&
          resultadosBiblioteca.length === 0 && (
            <EstadoComMascote
              mensagem={`Nenhum anime encontrado para “${termoBuscaSubmetido}”.`}
            />
          )}
      </div>
      {buscaBibliotecaAtiva &&
        !buscaBiblioteca.carregando &&
        !buscaBiblioteca.erro &&
        resultadosBiblioteca.length > 0 && (
          <GradeDeCatalogo
            itens={resultadosBiblioteca}
            tamanho="pequeno"
            comSombra={false}
            comAnimacao={false}
            chaveDoItem={chaveDoItemDoFeed}
            renderItem={(item) => {
              const chave = chaveDoItemDoFeed(item);
              return (
                <AnimeCard
                  anime={{
                    titulo: item.titulo_romaji,
                    capa_url: item.capa_url,
                    anime_id: item.anime_id,
                  }}
                  aoAtivar={() => materializarEIrPara(item)}
                  desabilitado={chaveEmMaterializacao === chave}
                  indicarCatalogado
                />
              );
            }}
          />
        )}
  </section>
);
}

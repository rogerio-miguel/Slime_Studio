import { useCallback, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { criarAnime, listarAnimes, listarAnimesEmAlta } from '../api/recursos.js';
import { useRecurso } from '../api/useRecurso.js';
import AnimeCard from '../components/AnimeCard.jsx';
import BarraDeNavegacao from '../components/BarraDeNavegacao.jsx';
import CenarioDeEntrada from '../inicio/CenarioDeEntrada.jsx';
// DestaquePrincipal desativado temporariamente (pivot de produto, Fase 4) —
// o arquivo continua em inicio/DestaquePrincipal.jsx, não é código morto,
// só não é renderizado por enquanto.
import GradeRotativa from '../inicio/GradeRotativa.jsx';
import { ALTURA_INTRO_VH, useScrubDeVideo } from '../inicio/useScrubDeVideo.js';

// Rota "/" — hero cinematográfico controlado por scroll: o vídeo
// (inicio/CenarioDeEntrada.jsx) avança proporcionalmente ao scroll através
// de um spacer transparente de 300vh; ao final, a interface principal do
// streaming (navbar + grade "Destaques da temporada") aparece suavemente.
// Ver inicio/useScrubDeVideo.js para o mecanismo de scrub e as 3 fases
// (entrada/chegando/revelado).
//
// Conteúdo: por padrão só o feed do provedor externo (`GET /api/animes/em-alta`)
// — "Seu catálogo" como seção fixa foi retirado da Inicio a pedido do
// usuário; o catálogo local continua acessível por inteiro em
// `paginas/Galeria.jsx` (rota "/animes", linkada na navbar), inclusive com o
// botão de remover. `DestaquePrincipal` também não está nesta ordem (pivot
// de produto anterior) — ver import comentado abaixo.
//
// Busca ao vivo (navbar, controlada aqui): digitar substitui inteiramente
// "Destaques da temporada" por uma grade de resultados sobre o catálogo
// local (`listarAnimes`) — o feed de provedor não tem busca. Sem
// `aoRemover` nos resultados, de propósito: a gestão do catálogo (remover)
// fica centralizada em `Galeria.jsx`/`PaginaDoAnime.jsx`, esta página não
// duplica isso.
//
// Fronteira Clean Architecture (D5 do plano): esta página e tudo em
// src/inicio/ só importam de src/api/, components/ e react-router-dom —
// nada de src/player/ (a única ligação com o player é a rota
// "/assistir/:episodioId", string, não import).
export default function Inicio() {
  const navigate = useNavigate();
  const videoRef = useRef(null);
  const logoRef = useRef(null);
  const { fase, movimentoReduzido, pularIntroducao } = useScrubDeVideo(videoRef, logoRef);

  const emAlta = useRecurso(listarAnimesEmAlta, []);
  const catalogo = useRecurso(listarAnimes, []);

  const [chaveEmMaterializacao, setChaveEmMaterializacao] = useState(null);
  const [erroMaterializacao, setErroMaterializacao] = useState(null);

  const [termoBusca, setTermoBusca] = useState('');
  const termoBuscaNormalizado = termoBusca.trim().toLowerCase();
  const buscando = termoBuscaNormalizado !== '';

  // Mesmo padrão de filtro em memória de `Galeria.jsx` — sem endpoint de
  // busca no backend, a lista local já carregada é pequena o bastante (uso
  // pessoal) pra não justificar um novo endpoint.
  const animesFiltrados = useMemo(
    () => (catalogo.dados ?? []).filter((anime) => anime.titulo.toLowerCase().includes(termoBuscaNormalizado)),
    [catalogo.dados, termoBuscaNormalizado]
  );

  // Ação disparada pelos cards da grade "Destaques da temporada": materializa
  // o item do feed no catálogo local (`POST /api/admin/animes`, get-or-create
  // por slug no servidor — reenvio acidental não duplica) e navega pro anime
  // criado. Sem sinopse no payload: o feed "em alta" não a fornece (ver
  // DestaquePrincipal.jsx); ela é preenchida no primeiro carregamento de
  // `PaginaDoAnime`.
  const materializarEIrPara = useCallback(
    async (item) => {
      if (chaveEmMaterializacao != null) return;
      const chave = item.anilist_id ?? item.titulo_romaji;
      setChaveEmMaterializacao(chave);
      setErroMaterializacao(null);
      try {
        const criado = await criarAnime({
          titulo: item.titulo_romaji,
          anilistId: item.anilist_id ?? undefined,
          capaUrl: item.capa_url ?? item.banner_url ?? undefined,
        });
        navigate(`/anime/${criado.id}`);
      } catch (erroCapturado) {
        console.error('falha ao adicionar anime ao catálogo', erroCapturado);
        setErroMaterializacao('Não foi possível adicionar este anime ao catálogo — tente novamente.');
      } finally {
        setChaveEmMaterializacao(null);
      }
    },
    [chaveEmMaterializacao, navigate]
  );

  return (
    <>
      {fase !== 'revelado' && (
        <button
          type="button"
          onClick={pularIntroducao}
          className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-30 focus:rounded-md focus:border focus:border-neon-soft focus:bg-surface focus:px-4 focus:py-2 focus:text-sm focus:font-semibold focus:text-neon focus:outline-none focus-visible:ring-2 focus-visible:ring-neon"
        >
          Pular introdução
        </button>
      )}

      <CenarioDeEntrada videoRef={videoRef} logoRef={logoRef} fase={fase} />

      <div aria-hidden="true" style={{ height: movimentoReduzido ? 0 : `${ALTURA_INTRO_VH}vh` }} />

      <BarraDeNavegacao fase={fase} termoBusca={termoBusca} aoMudarBusca={setTermoBusca} />

      <main
        inert={fase !== 'revelado'}
        className={`relative z-10 pb-20 pt-24 transition-opacity duration-700 ease-out ${
          fase === 'revelado' ? 'opacity-100' : 'opacity-0'
        }`}
      >
        {buscando ? (
          <section aria-label="Resultados da busca" className="px-4 sm:px-6 lg:px-8">
            <h2 className="mb-4 mt-20 text-2xl font-semibold text-white">
              Resultados para “{termoBusca.trim()}”
            </h2>
            {catalogo.carregando && (
              <p className="text-sm text-ink-muted">Carregando catálogo…</p>
            )}
            {catalogo.erro && (
              <div
                role="alert"
                className="mb-6 rounded-md border border-red-500/40 bg-red-950/40 px-4 py-3 text-sm text-red-300"
              >
                Não foi possível carregar o catálogo.{' '}
                <button type="button" onClick={catalogo.recarregar} className="underline">
                  Tentar novamente
                </button>
              </div>
            )}
            {!catalogo.carregando && !catalogo.erro && animesFiltrados.length === 0 && (
              <p className="text-sm text-ink-muted">
                Nenhum anime encontrado para “{termoBusca.trim()}”.
              </p>
            )}
            {!catalogo.carregando && !catalogo.erro && animesFiltrados.length > 0 && (
              <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4">
                {animesFiltrados.map((anime) => (
                  <AnimeCard key={anime.id} anime={anime} />
                ))}
              </div>
            )}
          </section>
        ) : (
          <>
            {emAlta.carregando && (
              <p className="mx-auto max-w-6xl px-6 pb-16 pt-10 text-sm text-ink-muted">
                Carregando catálogo…
              </p>
            )}
            {emAlta.erro && (
              <div className="mx-auto max-w-6xl px-6 pb-16 pt-10">
                <div
                  role="alert"
                  className="rounded-md border border-red-500/40 bg-red-950/40 px-4 py-3 text-sm text-red-300"
                >
                  Não foi possível carregar o catálogo.{' '}
                  <button type="button" onClick={emAlta.recarregar} className="underline">
                    Tentar novamente
                  </button>
                </div>
              </div>
            )}
            {!emAlta.carregando && !emAlta.erro && (
              <>
                {/* Caber entre a navbar e o fim da viewport, centralizada, sem
                    estourar por baixo da navbar fixa: responsabilidade da
                    própria GradeRotativa (prop `encaixarNaTela`) — evita
                    duplicar o número mágico do `pt-24` de <main> (6rem) em dois
                    arquivos. */}
                {erroMaterializacao && (
                  <div role="alert" className="px-4 pb-8 sm:px-6 lg:px-8">
                    <p className="text-sm text-red-400">{erroMaterializacao}</p>
                  </div>
                )}

                {(emAlta.dados ?? []).length > 0 && (
                  // `ativa` faz o gate de quando o timer de rotação PODE começar
                  // (ver GradeRotativa.jsx): a fase só vira "revelado" quando
                  // <main> deixa de estar inert/opacity-0 — sem esse gate, a
                  // grade podia começar a trocar de lote enquanto ainda está
                  // invisível por trás da introdução.
                  <GradeRotativa
                    titulo="Destaques da temporada"
                    itens={emAlta.dados}
                    ativa={fase === 'revelado'}
                    renderItem={(item) => {
                      const chave = item.anilist_id ?? item.titulo_romaji;
                      return (
                        <AnimeCard
                          anime={item}
                          aoAtivar={() => materializarEIrPara(item)}
                          desabilitado={chaveEmMaterializacao === chave}
                        />
                      );
                    }}
                  />
                )}
              </>
            )}
          </>
        )}
      </main>
    </>
  );
}

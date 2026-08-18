import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  buscarEmFontes,
  confirmarFonte,
  criarAnime,
  listarAnimes,
  listarAnimesEmAlta,
} from '../api/recursos.js';
import { useRecurso } from '../api/useRecurso.js';
import AnimeCard from '../components/AnimeCard.jsx';
import BarraDeNavegacao from '../components/BarraDeNavegacao.jsx';
import CenarioDeEntrada from '../inicio/CenarioDeEntrada.jsx';
// DestaquePrincipal desativado temporariamente (pivot de produto, Fase 4) —
// o arquivo continua em inicio/DestaquePrincipal.jsx, não é código morto,
// só não é renderizado por enquanto.
import { COLUNAS_GRID, estiloLarguraMaxCard, SlotDeCard } from '../inicio/GradeDeCards.jsx';
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
  const idResultadosFontes = useId();
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

  // Busca em outras fontes (sites de extração, ainda não catalogados): ao
  // contrário do filtro local acima (ao vivo, a cada tecla), só dispara no
  // submit (Enter na navbar) — evita martelar sites externos a cada tecla.
  // Limpa junto com o campo pra não deixar resultado de busca antiga visível
  // depois que o usuário apaga tudo.
  const [termoBuscaSubmetido, setTermoBuscaSubmetido] = useState('');
  useEffect(() => {
    if (termoBuscaNormalizado === '') setTermoBuscaSubmetido('');
  }, [termoBuscaNormalizado]);

  const submeterBuscaEmFontes = useCallback(() => {
    setTermoBuscaSubmetido(termoBusca.trim());
  }, [termoBusca]);

  const buscaEmFontes = useRecurso(
    () =>
      termoBuscaSubmetido
        ? buscarEmFontes(termoBuscaSubmetido)
        : Promise.resolve({ resultados: [], fontes: [], termo_alternativo: null }),
    [termoBuscaSubmetido]
  );
  const resultadosFontes = buscaEmFontes.dados?.resultados ?? [];
  const fontesConsultadas = buscaEmFontes.dados?.fontes ?? [];
  // Preenchido quando a busca com o termo digitado veio vazia e os resultados
  // acima vieram de um título alternativo do mesmo anime (romaji/inglês) —
  // avisa o usuário em vez de trocar o resultado em silêncio (busca fuzzy do
  // provedor pode casar anime errado).
  const termoAlternativo = buscaEmFontes.dados?.termo_alternativo ?? null;
  const fontesIndisponiveis = fontesConsultadas.filter((fonte) => fonte.indisponivel);
  // Toda fonte consultada falhou/está em cooldown — "não consegui nem
  // tentar", diferente de "busquei e não achei nada" (pelo menos uma fonte
  // respondeu de fato). `fontesConsultadas.length > 0` evita marcar como
  // "nenhuma fonte disponível" antes da resposta chegar (array vazio inicial).
  const todasFontesIndisponiveis =
    fontesConsultadas.length > 0 && fontesIndisponiveis.length === fontesConsultadas.length;

  // Guarda contra o campo ter sido editado depois do último Enter: enquanto
  // `termoBusca` diverge de `termoBuscaSubmetido`, os cards de
  // `buscaEmFontes.dados` são de uma busca antiga e não devem ser renderizados
  // (risco de materializar o anime errado) — a seção mostra um aviso de
  // "desatualizado" no lugar até o usuário apertar Enter de novo.
  const resultadosDeFonteDesatualizados =
    termoBuscaSubmetido !== '' && termoBusca.trim() !== termoBuscaSubmetido;

  // Helper compartilhado por materializarEIrPara/materializarFonteEIrPara: os
  // dois fluxos só diferem na chave usada e na chamada que de fato cria/
  // confirma o anime — guard de concorrência, estado de erro e navegação pro
  // anime criado são idênticos.
  const materializar = useCallback(
    async (chave, criarEConfirmar) => {
      if (chaveEmMaterializacao != null) return;
      setChaveEmMaterializacao(chave);
      setErroMaterializacao(null);
      try {
        const criado = await criarEConfirmar();
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

  // Ação disparada pelos cards da grade "Destaques da temporada": materializa
  // o item do feed no catálogo local (`POST /api/admin/animes`, get-or-create
  // por slug no servidor — reenvio acidental não duplica) e navega pro anime
  // criado. Sem sinopse no payload: o feed "em alta" não a fornece (ver
  // DestaquePrincipal.jsx); ela é preenchida no primeiro carregamento de
  // `PaginaDoAnime`.
  const materializarEIrPara = useCallback(
    (item) =>
      materializar(item.anilist_id ?? item.titulo_romaji, () =>
        criarAnime({
          titulo: item.titulo_romaji,
          anilistId: item.anilist_id ?? undefined,
          capaUrl: item.capa_url ?? item.banner_url ?? undefined,
        })
      ),
    [materializar]
  );

  // Mesma lógica de materialização acima, mas para um candidato de site de
  // extração (subseção "Resultados em outras fontes"): cria o anime e já
  // confirma a fonte (`POST .../fontes/confirmar`) — sem isso, o job de
  // captura pediria confirmação de novo na página do anime.
  //
  // `capaUrl` precisa vir junto: `resultado.capa_url` já saiu resolvido do
  // backend (`api/servicos/busca.py::enriquecer_capas` cobre qualquer fonte
  // sem capa própria via AniList/Kitsu antes de chegar aqui) — sem repassar,
  // `criarAnime` chega sem capa nenhuma e força `enriquecer_anime_criado` a
  // reconsultar o provedor do zero por título, uma segunda tentativa
  // best-effort independente que pode falhar silenciosamente e descartar a
  // capa que já tínhamos em mãos.
  const materializarFonteEIrPara = useCallback(
    (resultado) =>
      materializar(`${resultado.dominio}:${resultado.identificador}`, async () => {
        const criado = await criarAnime({
          titulo: resultado.titulo_exibicao,
          capaUrl: resultado.capa_url ?? undefined,
        });
        await confirmarFonte(criado.id, {
          dominio: resultado.dominio,
          identificador: resultado.identificador,
          tituloExibicao: resultado.titulo_exibicao,
          url: resultado.url,
          versao: resultado.versao ?? null,
        });
        return criado;
      }),
    [materializar]
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

      <BarraDeNavegacao
        fase={fase}
        termoBusca={termoBusca}
        aoMudarBusca={setTermoBusca}
        aoSubmeterBusca={submeterBuscaEmFontes}
      />

      <main
        inert={fase !== 'revelado'}
        // `min-h-screen`: sem isto, trocar a grade "Destaques da temporada"
        // (alta) pela seção de resultados de busca (curta, às vezes só uma
        // linha de "nenhum anime encontrado") encolhe a altura total do
        // documento. Se encolher abaixo do limiar de scroll que
        // useScrubDeVideo.js usa pra decidir a fase ("revelado" a partir de
        // 300vh, ver ALTURA_INTRO_VH), o navegador força um clamp de
        // `scrollY` pra caber no novo max — o que dispara um evento de
        // `scroll` sintético e derruba `fase` de volta pra "chegando", que
        // esconde <main> e reexibe o hero/logo por trás. Documento curto
        // demais também torna esse estado irrecuperável por scroll manual
        // (não dá pra rolar além do que existe), daí só reload resolvia.
        // `min-h-screen` garante que a altura de <main> nunca cai abaixo de
        // 1 viewport, então o limiar de 300vh continua sempre alcançável.
        className={`relative z-10 min-h-screen pb-20 pt-24 transition-opacity duration-700 ease-out ${
          fase === 'revelado' ? 'opacity-100' : 'opacity-0'
        }`}
      >
        {buscando ? (
          <section aria-label="Resultados da busca" className="px-6 md:px-10">
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
              <div style={estiloLarguraMaxCard} className={`grid gap-6 ${COLUNAS_GRID}`}>
                {animesFiltrados.map((anime, indice) => (
                  <SlotDeCard key={anime.id} indice={indice}>
                    <AnimeCard anime={anime} />
                  </SlotDeCard>
                ))}
              </div>
            )}

            <section aria-labelledby={idResultadosFontes}>
              <h2 id={idResultadosFontes} className="mb-4 mt-12 text-2xl font-semibold text-white">
                Resultados em outras fontes
              </h2>
              {erroMaterializacao && (
                <div role="alert" className="mb-4">
                  <p className="text-sm text-red-400">{erroMaterializacao}</p>
                </div>
              )}
              {termoBuscaSubmetido === '' && (
                <p className="text-sm text-ink-muted">Aperte Enter para buscar em outras fontes.</p>
              )}
              {termoBuscaSubmetido !== '' && resultadosDeFonteDesatualizados && (
                <p className="text-sm text-ink-muted">
                  Aperte Enter para atualizar os resultados em outras fontes.
                </p>
              )}
              {termoBuscaSubmetido !== '' && !resultadosDeFonteDesatualizados && buscaEmFontes.carregando && (
                <p className="text-sm text-ink-muted">Buscando em outras fontes…</p>
              )}
              {termoBuscaSubmetido !== '' && !resultadosDeFonteDesatualizados && buscaEmFontes.erro && (
                <div
                  role="alert"
                  className="mb-6 rounded-md border border-red-500/40 bg-red-950/40 px-4 py-3 text-sm text-red-300"
                >
                  Não foi possível buscar em outras fontes.{' '}
                  <button type="button" onClick={buscaEmFontes.recarregar} className="underline">
                    Tentar novamente
                  </button>
                </div>
              )}
              {termoBuscaSubmetido !== '' &&
                !resultadosDeFonteDesatualizados &&
                !buscaEmFontes.carregando &&
                !buscaEmFontes.erro &&
                resultadosFontes.length === 0 &&
                todasFontesIndisponiveis && (
                  <div
                    role="alert"
                    className="mb-6 rounded-md border border-red-500/40 bg-red-950/40 px-4 py-3 text-sm text-red-300"
                  >
                    <p>
                      Nenhuma fonte está disponível agora
                      {fontesIndisponiveis.some((fonte) => fonte.motivo)
                        ? ': ' +
                          fontesIndisponiveis
                            .map((fonte) =>
                              fonte.motivo ? `${fonte.dominio} (${fonte.motivo})` : fonte.dominio
                            )
                            .join('; ')
                        : '.'}
                    </p>
                    <button type="button" onClick={buscaEmFontes.recarregar} className="underline">
                      Tentar novamente
                    </button>
                  </div>
                )}
              {termoBuscaSubmetido !== '' &&
                !resultadosDeFonteDesatualizados &&
                !buscaEmFontes.carregando &&
                !buscaEmFontes.erro &&
                resultadosFontes.length === 0 &&
                !todasFontesIndisponiveis && (
                  <p className="text-sm text-ink-muted">
                    Nenhum anime encontrado em outras fontes para “{termoBuscaSubmetido}”.
                  </p>
                )}
              {termoBuscaSubmetido !== '' &&
                !resultadosDeFonteDesatualizados &&
                !buscaEmFontes.carregando &&
                !buscaEmFontes.erro &&
                resultadosFontes.length > 0 && (
                  <>
                    {termoAlternativo && (
                      <p className="mb-4 text-sm text-ink-muted">
                        Nenhum resultado para “{termoBuscaSubmetido}”. Mostrando resultados para “
                        {termoAlternativo}”.
                      </p>
                    )}
                    <div style={estiloLarguraMaxCard} className={`grid gap-6 ${COLUNAS_GRID}`}>
                      {resultadosFontes.map((resultado, indice) => {
                        const chave = `${resultado.dominio}:${resultado.identificador}`;
                        return (
                          <SlotDeCard key={chave} indice={indice}>
                            <AnimeCard
                              anime={{ titulo: resultado.titulo_exibicao, capa_url: resultado.capa_url }}
                              aoAtivar={() => materializarFonteEIrPara(resultado)}
                              desabilitado={chaveEmMaterializacao === chave}
                            />
                            <p className="mt-1 text-xs text-ink-muted">{resultado.dominio}</p>
                          </SlotDeCard>
                        );
                      })}
                    </div>
                    {fontesIndisponiveis.length > 0 && (
                      <p className="mt-4 text-xs text-ink-muted">
                        Não foi possível consultar:{' '}
                        {fontesIndisponiveis.map((fonte) => fonte.dominio).join(', ')}.
                      </p>
                    )}
                  </>
                )}
            </section>
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

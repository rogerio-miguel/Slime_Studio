import { useMemo, useRef } from 'react';
import { listarAnimes } from '../api/recursos.js';
import { useRecurso } from '../api/useRecurso.js';
import BarraDeNavegacao from '../components/BarraDeNavegacao.jsx';
import CenarioDeEntrada from '../inicio/CenarioDeEntrada.jsx';
import DestaquePrincipal from '../inicio/DestaquePrincipal.jsx';
import FaixaDeDestaques from '../inicio/FaixaDeDestaques.jsx';
import { useScrubDeVideo } from '../inicio/useScrubDeVideo.js';

// Rota "/" — hero cinematográfico controlado por scroll: o vídeo
// (inicio/CenarioDeEntrada.jsx) avança proporcionalmente ao scroll através
// de um spacer transparente de 300vh; ao final, a interface principal do
// streaming (navbar + destaque + faixa) aparece suavemente. Ver
// inicio/useScrubDeVideo.js para o mecanismo de scrub e as 3 fases
// (entrada/chegando/revelado).
//
// Fronteira Clean Architecture (D5 do plano): esta página e tudo em
// src/inicio/ só importam de src/api/, components/ e react-router-dom —
// nada de src/player/ (a única ligação com o player é a rota
// "/assistir/:episodioId", string, não import).
export default function Inicio() {
  const videoRef = useRef(null);
  const { fase, movimentoReduzido, pularIntroducao } = useScrubDeVideo(videoRef);
  const { dados: animes, carregando, erro, recarregar } = useRecurso(listarAnimes, []);

  const animeEmDestaque = useMemo(() => escolherDestaque(animes), [animes]);

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

      <CenarioDeEntrada videoRef={videoRef} fase={fase} />

      <div aria-hidden="true" style={{ height: movimentoReduzido ? 0 : '300vh' }} />

      <BarraDeNavegacao fase={fase} />

      <main
        inert={fase !== 'revelado'}
        className={`relative z-10 bg-[#0a0a0f] pb-20 pt-24 transition-opacity duration-700 ease-out ${
          fase === 'revelado' ? 'opacity-100' : 'opacity-0'
        }`}
      >
        {carregando && (
          <p className="mx-auto max-w-6xl px-6 pb-16 pt-10 text-sm text-ink-muted">
            Carregando catálogo…
          </p>
        )}
        {erro && (
          <div
            role="alert"
            className="mx-auto max-w-6xl px-6 pb-16 pt-10"
          >
            <div className="rounded-md border border-red-500/40 bg-red-950/40 px-4 py-3 text-sm text-red-300">
              Não foi possível carregar o catálogo.{' '}
              <button type="button" onClick={recarregar} className="underline">
                Tentar novamente
              </button>
            </div>
          </div>
        )}
        {!carregando && !erro && (
          <>
            <DestaquePrincipal anime={animeEmDestaque} />
            <FaixaDeDestaques animes={animes} idDestacado={animeEmDestaque?.id} />
          </>
        )}
      </main>
    </>
  );
}

// "Mais recente" (criado_em desc, empate por id desc) — a API ordena por
// título (backend/api/rotas/animes.py::listar_animes), então "primeiro da
// lista" seria arbitrário; ordenar aqui, no client.
function escolherDestaque(animes) {
  if (!animes || animes.length === 0) return null;
  return [...animes].sort((a, b) => {
    const porData = new Date(b.criado_em) - new Date(a.criado_em);
    return porData !== 0 ? porData : b.id - a.id;
  })[0];
}

import { useCallback, useEffect, useMemo, useState } from 'react';
import { BrowserRouter, Route, Routes } from 'react-router-dom';
import SeletorDeFonteDemo from './SeletorDeFonteDemo.jsx';
import IndicadorDeAtencao from './components/IndicadorDeAtencao.jsx';
import Toasts from './components/Toasts.jsx';
import { useEventosDeJobs } from './eventos/useEventosDeJobs.js';
import Player from './player/Player.jsx';
import Galeria from './paginas/Galeria.jsx';
import PaginaDoAnime from './paginas/PaginaDoAnime.jsx';
import PaginaDoPlayer from './paginas/PaginaDoPlayer.jsx';
import { SessaoProvider, useSessao } from './sessao/SessaoContexto.jsx';
import TelaDeDesbloqueio from './sessao/TelaDeDesbloqueio.jsx';

export default function App() {
  return (
    <SessaoProvider>
      <BrowserRouter>
        <Shell />
      </BrowserRouter>
    </SessaoProvider>
  );
}

// SessaoProvider no topo, guard de rota pra tela de desbloqueio quando não
// autenticado — nenhuma rota (nem `/debug/fonte`) é alcançável sem token,
// mesmo modelo de uso pessoal/local do resto da API (CLAUDE.md/ESPECIFICACAO
// §8.2). WS único (`useEventosDeJobs`) sobe aqui, no nível do app, viva
// enquanto autenticado — o Map resultante desce por prop pra quem precisa
// (grade de episódios, indicador de atenção, toasts).
function Shell() {
  const { autenticado, carregando } = useSessao();
  const jobsPorEpisodio = useEventosDeJobs(autenticado);
  const jobsPrecisandoAtencao = useMemo(
    () => [...jobsPorEpisodio.values()].filter((job) => job.status === 'aguardando_intervencao'),
    [jobsPorEpisodio]
  );

  if (carregando) {
    return (
      <p role="status" className="px-6 py-20 text-center text-sm text-ink-muted">
        Carregando…
      </p>
    );
  }

  if (!autenticado) {
    return <TelaDeDesbloqueio />;
  }

  return (
    <>
      <IndicadorDeAtencao jobs={jobsPrecisandoAtencao} />
      <Toasts jobsPorEpisodio={jobsPorEpisodio} />
      <Routes>
        <Route path="/" element={<Galeria />} />
        <Route path="/anime/:id" element={<PaginaDoAnime jobsPorEpisodio={jobsPorEpisodio} />} />
        <Route path="/assistir/:episodioId" element={<PaginaDoPlayer />} />
        <Route path="/debug/fonte" element={<RotaDebugFonte />} />
      </Routes>
    </>
  );
}

// SeletorDeFonteDemo.jsx não é andaime descartável (ver comentário próprio)
// — vira rota permanente de debug/fallback pra tocar um arquivo local ou
// URL arbitrária sem depender do catálogo. Mesma lógica de troca de fonte
// que vivia direto em App.jsx antes do roteador existir.
function RotaDebugFonte() {
  const [fonte, setFonte] = useState(null);

  const aoEscolherFonte = useCallback((novaFonte) => {
    setFonte((fonteAnterior) => {
      if (fonteAnterior?.startsWith('blob:')) URL.revokeObjectURL(fonteAnterior);
      return novaFonte;
    });
  }, []);

  // Só trava o scroll do documento enquanto o player está de fato ativo —
  // a tela de seleção é um formulário normal, precisa scrollar.
  useEffect(() => {
    if (!fonte) return;
    document.documentElement.classList.add('pagina-player');
    document.body.classList.add('pagina-player');
    return () => {
      document.documentElement.classList.remove('pagina-player');
      document.body.classList.remove('pagina-player');
    };
  }, [fonte]);

  if (!fonte) {
    return <SeletorDeFonteDemo aoEscolherFonte={aoEscolherFonte} />;
  }

  return <Player fonte={fonte} titulo="Slime Studio (debug)" />;
}

import { useCallback, useEffect, useMemo, useState } from 'react';
import { BrowserRouter, Route, Routes } from 'react-router-dom';
import SeletorDeFonteDemo from './SeletorDeFonteDemo.jsx';
import IndicadorDeAtencao from './components/IndicadorDeAtencao.jsx';
import Toasts from './components/Toasts.jsx';
import { useEventosDeJobs } from './eventos/useEventosDeJobs.js';
import Player from './player/Player.jsx';
import Inicio from './paginas/Inicio.jsx';
import Galeria from './paginas/Galeria.jsx';
import PaginaDoAnime from './paginas/PaginaDoAnime.jsx';
import PaginaDoPlayer from './paginas/PaginaDoPlayer.jsx';
import PaginaDoPlayerLocal from './paginas/PaginaDoPlayerLocal.jsx';

export default function App() {
  return (
    <BrowserRouter>
      <Shell />
    </BrowserRouter>
  );
}

// Sem gate de autenticação (D5 do plano de remoção — API é de uso
// pessoal/local, CLAUDE.md): todas as rotas são alcançáveis direto. WS único
// (`useEventosDeJobs`) sobe aqui, no nível do app, sempre conectado — o Map
// resultante desce por prop pra quem precisa (grade de episódios, indicador
// de atenção, toasts).
function Shell() {
  const jobsPorEpisodio = useEventosDeJobs();
  const jobsPrecisandoAtencao = useMemo(
    () => [...jobsPorEpisodio.values()].filter((job) => job.status === 'aguardando_intervencao'),
    [jobsPorEpisodio]
  );

  return (
    <>
      <IndicadorDeAtencao jobs={jobsPrecisandoAtencao} />
      <Toasts jobsPorEpisodio={jobsPorEpisodio} />
      <Routes>
        <Route path="/" element={<Inicio />} />
        <Route path="/animes" element={<Galeria />} />
        <Route path="/anime/:id" element={<PaginaDoAnime jobsPorEpisodio={jobsPorEpisodio} />} />
        <Route path="/assistir/:episodioId" element={<PaginaDoPlayer />} />
        <Route path="/assistir-local/:slug" element={<PaginaDoPlayerLocal />} />
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

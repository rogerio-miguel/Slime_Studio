import { useEffect, useId, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';

// Seletor de temporada da página do anime (Fase 5) — vive na barra de ações
// abaixo do hero (`paginas/PaginaDoAnime.jsx`), como PRIMEIRO controle antes
// de "Trocar fonte". O gatilho usa a MESMA linguagem visual dos outros botões
// da barra (`rounded-md border-2 border-border-chrome px-3 py-1 text-xs`,
// hover neon) — só o chevron que gira ao abrir + o menu ancorado embaixo (com
// a temporada atual em destaque) o distinguem.
//
// `temporadas` é `anime.temporadas` (`AnimeDetalheSaida.temporadas`, já
// ordenada por número, inclui a atual). Trocar de temporada é NAVEGAÇÃO de
// rota (`/anime/:outroId`) — a página inteira re-chaveia em `animeId` via
// `useRecurso`, sem estado local novo. Só renderiza com 2+ temporadas
// catalogadas (o chamador também já checa, este é um segundo guard barato).
//
// Acessibilidade: `<button aria-haspopup="menu" aria-expanded>` + `role="menu"`
// / `role="menuitem"`; Esc fecha e devolve o foco ao gatilho, ↑/↓ andam pelos
// itens, Home/End vão pras pontas, clique fora fecha.
export default function SeletorDeTemporada({ temporadas, animeIdAtual }) {
  const navigate = useNavigate();
  const [aberto, setAberto] = useState(false);
  const [indiceAtivo, setIndiceAtivo] = useState(0);
  const idMenu = useId();
  const containerRef = useRef(null);
  const gatilhoRef = useRef(null);
  const itensRef = useRef([]);

  const temporadaAtual =
    temporadas.find((temporada) => temporada.id === animeIdAtual) ?? temporadas[0];

  const rotuloDe = (temporada) =>
    temporada.numero_temporada != null
      ? `Temporada ${temporada.numero_temporada}`
      : temporada.titulo;

  // Fecha ao clicar fora ou ao focar algo fora do componente.
  useEffect(() => {
    if (!aberto) return;
    const aoApontarFora = (evento) => {
      if (!containerRef.current?.contains(evento.target)) setAberto(false);
    };
    document.addEventListener('pointerdown', aoApontarFora);
    return () => document.removeEventListener('pointerdown', aoApontarFora);
  }, [aberto]);

  // Ao abrir, posiciona o foco no item da temporada atual.
  useEffect(() => {
    if (!aberto) return;
    const indiceAtual = temporadas.findIndex((temporada) => temporada.id === animeIdAtual);
    const inicial = indiceAtual >= 0 ? indiceAtual : 0;
    setIndiceAtivo(inicial);
    itensRef.current[inicial]?.focus();
  }, [aberto, temporadas, animeIdAtual]);

  const fechar = (devolverFoco = true) => {
    setAberto(false);
    if (devolverFoco) gatilhoRef.current?.focus();
  };

  const escolher = (temporada) => {
    fechar(false);
    if (temporada.id !== animeIdAtual) navigate(`/anime/${temporada.id}`);
  };

  const aoTeclarNoMenu = (evento) => {
    if (evento.key === 'Escape') {
      evento.preventDefault();
      fechar();
    } else if (evento.key === 'ArrowDown') {
      evento.preventDefault();
      const proximo = (indiceAtivo + 1) % temporadas.length;
      setIndiceAtivo(proximo);
      itensRef.current[proximo]?.focus();
    } else if (evento.key === 'ArrowUp') {
      evento.preventDefault();
      const anterior = (indiceAtivo - 1 + temporadas.length) % temporadas.length;
      setIndiceAtivo(anterior);
      itensRef.current[anterior]?.focus();
    } else if (evento.key === 'Home') {
      evento.preventDefault();
      setIndiceAtivo(0);
      itensRef.current[0]?.focus();
    } else if (evento.key === 'End') {
      evento.preventDefault();
      const ultimo = temporadas.length - 1;
      setIndiceAtivo(ultimo);
      itensRef.current[ultimo]?.focus();
    }
  };

  if (temporadas.length < 2) return null;

  return (
    <div ref={containerRef} className="relative">
      <button
        ref={gatilhoRef}
        type="button"
        aria-haspopup="menu"
        aria-expanded={aberto}
        aria-controls={aberto ? idMenu : undefined}
        onClick={() => setAberto((estava) => !estava)}
        onKeyDown={(evento) => {
          if (evento.key === 'ArrowDown' && !aberto) {
            evento.preventDefault();
            setAberto(true);
          }
        }}
        className="inline-flex items-center gap-2 rounded-md border-2 border-border-chrome px-3 py-1 text-xs text-ink-muted outline-none transition-colors hover:border-neon hover:text-white"
      >
        {rotuloDe(temporadaAtual)}
        <svg
          viewBox="0 0 24 24"
          width="14"
          height="14"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
          className={`transition-transform ${aberto ? 'rotate-180' : ''}`}
        >
          <path d="m6 9 6 6 6-6" />
        </svg>
      </button>

      {aberto && (
        <div
          id={idMenu}
          role="menu"
          aria-label="Temporada"
          onKeyDown={aoTeclarNoMenu}
          className="absolute left-0 top-full z-10 mt-1 min-w-[12rem] overflow-hidden rounded-md border border-border-chrome bg-[#1c1c22] py-1 shadow-xl shadow-black/50"
        >
          {temporadas.map((temporada, indice) => {
            const atual = temporada.id === animeIdAtual;
            return (
              <button
                key={temporada.id}
                ref={(no) => {
                  itensRef.current[indice] = no;
                }}
                type="button"
                role="menuitem"
                aria-current={atual ? 'true' : undefined}
                tabIndex={indice === indiceAtivo ? 0 : -1}
                onClick={() => escolher(temporada)}
                className={`block w-full px-4 py-2 text-left text-sm outline-none transition-colors focus-visible:bg-white/10 ${
                  atual
                    ? 'font-semibold text-white'
                    : 'text-ink-muted hover:bg-white/5 hover:text-white'
                }`}
              >
                {rotuloDe(temporada)}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

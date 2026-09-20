import { useEffect, useId, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ChevronDown } from 'lucide-react';

// Seletor de temporada da página do anime (Fase 5) — vive na barra de ações
// abaixo do hero (`paginas/PaginaDoAnime.jsx`), como PRIMEIRO controle antes
// de "Trocar fonte". O gatilho usa a MESMA linguagem visual dos outros botões
// da barra (`rounded-md border-2 border-border-chrome px-3 py-1 text-xs`,
// hover neon) — só o chevron que gira ao abrir + o menu ancorado embaixo (com
// a temporada atual em destaque) o distinguem.
//
// `temporadas` é `anime.temporadas` (`AnimeDetalheSaida.temporadas`, já
// ordenada por número, inclui a atual). Filme/OVA/ONA/especial da mesma
// franquia (`Anime.formato_midia` não nulo) entra nesta MESMA lista — se
// agrupa no anime original em vez de virar card solto no catálogo — só ganha
// um selo de formato ao lado do título (`formato_midia` por item). Contagem
// de episódios (`total_episodios`, total DECLARADO pela AniList — não
// progresso de captura local, que é `AnimeSaida.episodios_atuais`, outro
// campo) à direita, alinhada — some quando `null` (AniList ainda não fechou a
// contagem, comum em temporada recém-anunciada) OU quando há `formato_midia`:
// pra filme/OVA/ONA/especial o selo de formato já basta, "1 Episódio" ao lado
// de "Filme" é redundante (pedido explícito do usuário). Trocar de item é
// NAVEGAÇÃO de rota (`/anime/:outroId`) — a página inteira re-chaveia em
// `animeId` via `useRecurso`, sem estado local novo. `temporadas` vem `[]`
// quando o anime não tem irmã de franquia (backend só popula a lista com 2+
// itens) — nesse caso não há nada pra selecionar, mas o rótulo "Temporada N"
// ainda aparece como texto simples (sem seta, sem virar botão/menu): mantém a
// barra de ações com a MESMA referência visual em todo anime, catalogado com
// 1 ou várias temporadas. `numeroTemporadaAtual`/`tituloAtual` (de
// `anime.numero_temporada`/`anime.titulo`) alimentam só esse rótulo — o
// seletor com dropdown usa os campos homônimos de cada item de `temporadas`.
//
// Acessibilidade: `<button aria-haspopup="menu" aria-expanded>` + `role="menu"`
// / `role="menuitem"`; Esc fecha e devolve o foco ao gatilho, ↑/↓ andam pelos
// itens, Home/End vão pras pontas, clique fora fecha.
const RÓTULO_FORMATO = { MOVIE: 'Filme', OVA: 'OVA', ONA: 'ONA', SPECIAL: 'Especial' };

export default function SeletorDeTemporada({
  temporadas,
  animeIdAtual,
  numeroTemporadaAtual,
  tituloAtual,
}) {
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

  if (temporadas.length === 0) {
    return (
      <span className="inline-flex items-center h-8 text-[18px] text-ink-muted font-semibold">
        {numeroTemporadaAtual != null ? `Temporada ${numeroTemporadaAtual}` : tituloAtual}
      </span>
    );
  }

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
        className="inline-flex items-center gap-2 pr-2.5 h-8 text-[18px] text-ink-muted font-semibold outline-none transition-colors hover:border-neon hover:text-white cursor-pointer"
      >
        {rotuloDe(temporadaAtual)}
        <ChevronDown
          width={14}
          height={14}
          aria-hidden="true"
          stroke-width="4"
          className={`transition-transform ${aberto ? 'rotate-180' : ''}`}
        />
      </button>

      {aberto && (
        <div
          id={idMenu}
          role="menu"
          aria-label="Temporada"
          onKeyDown={aoTeclarNoMenu}
          className="absolute left-0 top-full z-10 mt-1 min-w-[20rem] overflow-hidden border border-border-chrome bg-[#0f0f10] shadow-xl shadow-black/50"
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
                className={`flex w-full items-center justify-between gap-2 px-4 py-2 text-left text-sm font-semibold outline-none transition-colors hover:bg-white/5 focus-visible:bg-white/10 cursor-pointer ${
                  atual ? 'text-white' : 'text-ink-muted hover:text-white'
                }`}
              >
                <span className="truncate">{rotuloDe(temporada)}</span>
                <span className="flex shrink-0 items-center gap-2">
                  {temporada.total_episodios != null && !temporada.formato_midia && (
                    <span className="text-[12px] tabular-nums">
                      {temporada.total_episodios} Episódio{temporada.total_episodios > 1 ? 's' : ''}
                    </span>
                  )}
                  {temporada.formato_midia && (
                    <span className="text-[12px] uppercase tracking-wide">
                      {RÓTULO_FORMATO[temporada.formato_midia] ?? temporada.formato_midia}
                    </span>
                  )}
                </span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

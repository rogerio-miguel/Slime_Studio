import { useEffect, useId, useRef, useState } from 'react';
import { Check, MoreVertical, RefreshCw, Trash2 } from 'lucide-react';

// Menu de ações da página do anime (`paginas/PaginaDoAnime.jsx`) — "Trocar
// fonte"/"Marcar como assistido"/"Remover do catálogo" saíram de botões
// soltos na barra e viraram itens deste menu, cujo gatilho (ícone de kebab)
// mora ao lado do alternador grade/lista (mesma geometria `h-8 w-8 border-2
// rounded-md` dos dois, pedido explícito do usuário — o menu completa esse
// grupo de controles secundários em vez de brigar por espaço com o seletor de
// temporada). Menu ancorado à DIREITA (`right-0`, não `left-0` como
// `SeletorDeTemporada`) porque o gatilho é o item mais à direita da barra —
// abrir pra esquerda evita vazar a viewport.
//
// Mesmo padrão de acessibilidade de `SeletorDeTemporada`: `<button
// aria-haspopup="menu" aria-expanded>` + `role="menu"`/`role="menuitem"`; Esc
// fecha e devolve o foco ao gatilho, ↑/↓ andam pelos itens, Home/End vão pras
// pontas, clique fora fecha.
export default function MenuDeAcoesDoAnime({
  aoTrocarFonte,
  aoMarcarAssistidos,
  marcandoAssistidos,
  tudoAssistido,
  aoRemover,
}) {
  const [aberto, setAberto] = useState(false);
  const [indiceAtivo, setIndiceAtivo] = useState(0);
  const idMenu = useId();
  const containerRef = useRef(null);
  const gatilhoRef = useRef(null);
  const itensRef = useRef([]);

  const itens = [
    {
      chave: 'trocar-fonte',
      rotulo: 'Trocar fonte',
      Icone: RefreshCw,
      aoClicar: aoTrocarFonte,
    },
    {
      chave: 'marcar-assistido',
      rotulo: marcandoAssistidos
        ? 'Marcando…'
        : tudoAssistido
          ? 'Tudo assistido'
          : 'Marcar como assistido',
      Icone: Check,
      aoClicar: aoMarcarAssistidos,
      desabilitado: marcandoAssistidos || tudoAssistido,
    },
    {
      chave: 'remover',
      rotulo: 'Remover do catálogo',
      Icone: Trash2,
      aoClicar: aoRemover,
      destrutivo: true,
    },
  ];

  // Fecha ao clicar fora ou ao focar algo fora do componente.
  useEffect(() => {
    if (!aberto) return;
    const aoApontarFora = (evento) => {
      if (!containerRef.current?.contains(evento.target)) setAberto(false);
    };
    document.addEventListener('pointerdown', aoApontarFora);
    return () => document.removeEventListener('pointerdown', aoApontarFora);
  }, [aberto]);

  // Ao abrir, posiciona o foco no primeiro item.
  useEffect(() => {
    if (!aberto) return;
    setIndiceAtivo(0);
    itensRef.current[0]?.focus();
  }, [aberto]);

  const fechar = (devolverFoco = true) => {
    setAberto(false);
    if (devolverFoco) gatilhoRef.current?.focus();
  };

  const escolher = (item) => {
    fechar(false);
    item.aoClicar();
  };

  const aoTeclarNoMenu = (evento) => {
    if (evento.key === 'Escape') {
      evento.preventDefault();
      fechar();
    } else if (evento.key === 'ArrowDown') {
      evento.preventDefault();
      const proximo = (indiceAtivo + 1) % itens.length;
      setIndiceAtivo(proximo);
      itensRef.current[proximo]?.focus();
    } else if (evento.key === 'ArrowUp') {
      evento.preventDefault();
      const anterior = (indiceAtivo - 1 + itens.length) % itens.length;
      setIndiceAtivo(anterior);
      itensRef.current[anterior]?.focus();
    } else if (evento.key === 'Home') {
      evento.preventDefault();
      setIndiceAtivo(0);
      itensRef.current[0]?.focus();
    } else if (evento.key === 'End') {
      evento.preventDefault();
      const ultimo = itens.length - 1;
      setIndiceAtivo(ultimo);
      itensRef.current[ultimo]?.focus();
    }
  };

  return (
    <div ref={containerRef} className="relative">
      <button
        ref={gatilhoRef}
        type="button"
        aria-haspopup="menu"
        aria-expanded={aberto}
        aria-controls={aberto ? idMenu : undefined}
        aria-label="Mais ações"
        onClick={() => setAberto((estava) => !estava)}
        onKeyDown={(evento) => {
          if (evento.key === 'ArrowDown' && !aberto) {
            evento.preventDefault();
            setAberto(true);
          }
        }}
        className={`flex h-8 w-8 items-center justify-center rounded-md border-2 outline-none transition-colors cursor-pointer ${
          aberto
            ? 'border-neon text-white'
            : 'border-border-chrome text-ink-muted hover:border-neon hover:text-white'
        }`}
      >
        <MoreVertical width={18} height={18} aria-hidden="true" />
      </button>

      {aberto && (
        <div
          id={idMenu}
          role="menu"
          aria-label="Mais ações"
          onKeyDown={aoTeclarNoMenu}
          className="absolute right-0 top-full z-10 mt-1 min-w-[13rem] overflow-hidden border border-border-chrome bg-[#0f0f10] shadow-xl shadow-black/50"
        >
          {itens.map((item, indice) => (
            <button
              key={item.chave}
              ref={(no) => {
                itensRef.current[indice] = no;
              }}
              type="button"
              role="menuitem"
              tabIndex={indice === indiceAtivo ? 0 : -1}
              disabled={item.desabilitado}
              onClick={() => escolher(item)}
              className={`flex w-full items-center gap-2 px-4 py-2 text-left text-sm font-semibold outline-none transition-colors focus-visible:bg-white/10 disabled:cursor-auto disabled:opacity-50 cursor-pointer ${
                item.destrutivo
                  ? 'text-red-300 hover:bg-red-500/10 hover:text-red-200'
                  : 'text-ink-muted hover:bg-white/5 hover:text-white'
              }`}
            >
              <item.Icone aria-hidden="true" className="h-4 w-4 shrink-0" />
              {item.rotulo}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

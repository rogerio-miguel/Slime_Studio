import { useEffect, useId, useRef, useState } from 'react';
import { ChevronDown } from 'lucide-react';

// Dropdown de valor único genérico — mesmo padrão de acessibilidade de
// `SeletorDeTemporada.jsx` (gatilho com chevron que gira + `role="menu"`/
// `role="menuitem"`, Esc fecha e devolve o foco ao gatilho, ↑/↓ andam pelos
// itens, Home/End vão pras pontas, clique fora fecha), generalizado pra
// `valor`/`aoMudar` em vez de navegação de rota — usado pelo filtro de
// `paginas/Galeria.jsx`, que antes usava `<select>` nativo e passou a seguir
// esta mesma linguagem visual (pedido do usuário). `opcoes`: [{valor, rotulo}].
//
// `prefixo` (opcional): igual ao gatilho de `SeletorDeTemporada.jsx`, o texto
// do botão É o rótulo — sem `<label>` externo separado. Quando passado,
// renderiza "PREFIXO | opção" (ex. "FILTRAR | Assistidos") em vez de só a
// opção; pedido explícito do usuário pra reduzir a pilha label-em-cima
// botão-embaixo de antes pra uma linha só.
export default function SeletorEmMenu({ id, opcoes, valor, aoMudar, rotuloAcessivel, prefixo }) {
  const [aberto, setAberto] = useState(false);
  const [indiceAtivo, setIndiceAtivo] = useState(0);
  const idMenu = useId();
  const containerRef = useRef(null);
  const gatilhoRef = useRef(null);
  const itensRef = useRef([]);

  const indiceSelecionado = Math.max(
    0,
    opcoes.findIndex((opcao) => opcao.valor === valor)
  );
  const opcaoSelecionada = opcoes[indiceSelecionado];

  useEffect(() => {
    if (!aberto) return undefined;
    const aoApontarFora = (evento) => {
      if (!containerRef.current?.contains(evento.target)) setAberto(false);
    };
    document.addEventListener('pointerdown', aoApontarFora);
    return () => document.removeEventListener('pointerdown', aoApontarFora);
  }, [aberto]);

  useEffect(() => {
    if (!aberto) return;
    setIndiceAtivo(indiceSelecionado);
    itensRef.current[indiceSelecionado]?.focus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [aberto]);

  const fechar = (devolverFoco = true) => {
    setAberto(false);
    if (devolverFoco) gatilhoRef.current?.focus();
  };

  const escolher = (opcao) => {
    fechar(false);
    if (opcao.valor !== valor) aoMudar(opcao.valor);
  };

  const aoTeclarNoMenu = (evento) => {
    if (evento.key === 'Escape') {
      evento.preventDefault();
      fechar();
    } else if (evento.key === 'ArrowDown') {
      evento.preventDefault();
      const proximo = (indiceAtivo + 1) % opcoes.length;
      setIndiceAtivo(proximo);
      itensRef.current[proximo]?.focus();
    } else if (evento.key === 'ArrowUp') {
      evento.preventDefault();
      const anterior = (indiceAtivo - 1 + opcoes.length) % opcoes.length;
      setIndiceAtivo(anterior);
      itensRef.current[anterior]?.focus();
    } else if (evento.key === 'Home') {
      evento.preventDefault();
      setIndiceAtivo(0);
      itensRef.current[0]?.focus();
    } else if (evento.key === 'End') {
      evento.preventDefault();
      const ultimo = opcoes.length - 1;
      setIndiceAtivo(ultimo);
      itensRef.current[ultimo]?.focus();
    }
  };

  return (
    // `inline-block` (não `relative` puro): o pai em paginas/Galeria.jsx é um
    // <div> de bloco cheio, e sem isto este container herdava a largura
    // inteira dele — aí o `min-w-full` do menu abaixo esticava pra cobrir a
    // área dos cards em vez de só acompanhar a largura do botão.
    <div ref={containerRef} className="relative inline-block">
      <button
        id={id}
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
        {prefixo ? `${prefixo} | ${opcaoSelecionada?.rotulo}` : opcaoSelecionada?.rotulo}
        <ChevronDown
          width={14}
          height={14}
          aria-hidden="true"
          stroke-width="4"
          className={`shrink-0 transition-transform ${aberto ? 'rotate-180' : ''}`}
        />
      </button>

      {aberto && (
        <div
          id={idMenu}
          role="menu"
          aria-label={rotuloAcessivel}
          onKeyDown={aoTeclarNoMenu}
          className="absolute left-0 top-full z-20 mt-1 min-w-full overflow-hidden border border-border-chrome bg-[#0f0f10] shadow-xl shadow-black/50"
        >
          {opcoes.map((opcao, indice) => {
            const atual = opcao.valor === valor;
            return (
              <button
                key={opcao.valor}
                ref={(no) => {
                  itensRef.current[indice] = no;
                }}
                type="button"
                role="menuitem"
                aria-current={atual ? 'true' : undefined}
                tabIndex={indice === indiceAtivo ? 0 : -1}
                onClick={() => escolher(opcao)}
                className={`block w-full whitespace-nowrap px-4 py-2 text-left text-sm font-semibold outline-none transition-colors hover:bg-white/5 focus-visible:bg-white/10 cursor-pointer ${
                  atual ? 'text-white' : 'text-ink-muted hover:text-white'
                }`}
              >
                {opcao.rotulo}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

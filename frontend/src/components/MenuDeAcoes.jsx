import { Fragment, useEffect, useId, useRef, useState } from 'react';
import { Check, MoreVertical } from 'lucide-react';
import { CLASSE_PAINEL_FLUTUANTE, FUNDO_DA_ILHA } from './painelFlutuante.js';
import { useFecharAoClicarFora } from '../hooks/useFecharAoClicarFora.js';

// Menu de ações genérico — extraído de `MenuDeAcoesDoAnime.jsx` (pedido do
// usuário: "Continuar assistindo" da Home ganhou o mesmo padrão de menu
// kebab da página do anime, só que com itens diferentes e ancorado sobre a
// miniatura do card em vez da barra de controles). Mantém intacta a lógica
// de acessibilidade original (`aria-haspopup`/`aria-expanded` + `role="menu"`/
// `role="menuitem"`, Esc fecha e devolve o foco ao gatilho, ↑/↓ andam pelos
// itens, Home/End vão pras pontas, clique fora fecha) — só o VISUAL do
// gatilho varia por chamador (`classeGatilho`, função de `aberto` porque o
// estado é interno a este componente e cada skin reage a ele de forma
// diferente).
//
// `larguraMinima`: classe `min-w-*` do painel (padrão serve ao card; o menu da
// página do anime é mais largo por causa da segunda linha de cada item).
// `itens`: [{chave, rotulo, descricao?, separadorAntes?, Icone, aoClicar,
// desabilitado, destrutivo, marcado?}] — `descricao` é uma segunda linha opcional;
// mesmo formato que `MenuDeAcoesDoAnime` já usava internamente. `marcado`
// (boolean) transforma o item em opção exclusiva (`menuitemradio`) com um ✓ no
// escolhido — usado pelo seletor de tema; `undefined` é item comum.
// `dica`: texto de uma dica ao passar o mouse/focar o gatilho (some com o menu
// aberto); o gatilho ganha `peer` pra isso, e a dica segue a mesma âncora e o
// mesmo alinhamento do painel. `gatilho` (padrão: ícone ⋯): conteúdo do botão no lugar do ícone — o logo da
// navbar é o gatilho do seletor de tema. `classeDoContainer` entra no wrapper
// `relative` (âncora do painel) quando ele precisa participar de um flex.
// `classeGatilho(aberto)`: className completa do botão-gatilho — cada
// chamador decide a própria skin (`MenuDeAcoesDoAnime`: quadrado com borda
// da barra de controles; card de "Continuar assistindo": ícone sem chip
// sobre a miniatura).
// `ancoragem`: lado que o painel abre (`'right'` por padrão) — evita vazar a
// viewport quando o gatilho é o item mais à direita do contexto. Só importa
// quando `posicao="baixo"` (painel abre abaixo do gatilho, `top-full`).
// `'centro'`: o wrapper deixa de ser `relative` e o painel centraliza no
// ancestral posicionado mais próximo — o logo, pra o menu ficar sob o nome todo.
// `tamanhoIcone` (default 18, mesmo valor de sempre pro botão quadrado de
// `MenuDeAcoesDoAnime`): pedido explícito do usuário pro ícone do card de
// "Continuar assistindo" (`CartaoContinuarAssistindo.jsx`) ficar maior — só
// esse chamador passa um valor diferente, a barra de controles da página do
// anime não muda.
// `posicao` (`'baixo'` padrão, mesmo comportamento de sempre — usado por
// `MenuDeAcoesDoAnime`): pedido do usuário pro card de "Continuar assistindo"
// (2026-09-21) ter uma posição diferente da página do anime — ali o menu
// some por baixo da miniatura em card pequeno de fileira, então `'lado'`
// ancora o painel à ESQUERDA do próprio gatilho (`right-full`, alinhado no
// topo), nunca embaixo — evita vazar por baixo da miniatura 16:9 e mantém o
// painel sobre o card. `ancoragem` é ignorado nesse modo (a lateral já
// resolve o vazamento de viewport que `ancoragem` resolveria no modo baixo).
const CLASSE_ALINHAMENTO = { right: 'right-0', centro: 'left-1/2 -translate-x-1/2' };

export default function MenuDeAcoes({
  itens,
  rotuloGatilho,
  classeGatilho,
  ancoragem = 'right',
  posicao = 'baixo',
  tamanhoIcone = 18,
  gatilho = null,
  dica = null,
  classeDoContainer = '',
  larguraMinima = 'min-w-[13rem]',
}) {
  const [aberto, setAberto] = useState(false);
  const [indiceAtivo, setIndiceAtivo] = useState(0);
  const idMenu = useId();
  const containerRef = useRef(null);
  const gatilhoRef = useRef(null);
  const itensRef = useRef([]);

  useFecharAoClicarFora(aberto, containerRef, () => setAberto(false));

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
    <div
      ref={containerRef}
      className={`${ancoragem === 'centro' ? '' : 'relative'} ${classeDoContainer}`}
    >
      <button
        ref={gatilhoRef}
        type="button"
        aria-haspopup="menu"
        aria-expanded={aberto}
        aria-controls={aberto ? idMenu : undefined}
        aria-label={rotuloGatilho}
        onClick={() => setAberto((estava) => !estava)}
        onKeyDown={(evento) => {
          if (evento.key === 'ArrowDown' && !aberto) {
            evento.preventDefault();
            setAberto(true);
          }
        }}
        className={`${classeGatilho(aberto)} ${dica ? 'peer' : ''}`}
      >
        {gatilho ?? <MoreVertical width={tamanhoIcone} height={tamanhoIcone} aria-hidden="true" />}
      </button>

      {dica && !aberto && (
        <span
          aria-hidden="true"
          className={`pointer-events-none absolute top-full z-10 mt-2.5 ${CLASSE_ALINHAMENTO[ancoragem] ?? 'left-0'} whitespace-nowrap rounded-lg border border-border-chrome ${FUNDO_DA_ILHA} px-2.5 py-1 text-xs font-semibold normal-case leading-normal text-white opacity-0 transition-opacity duration-150 peer-hover:opacity-100 peer-hover:delay-300 peer-focus-visible:opacity-100 motion-reduce:transition-none`}
        >
          {dica}
        </span>
      )}

      {aberto && (
        <div
          id={idMenu}
          role="menu"
          aria-label={rotuloGatilho}
          onKeyDown={aoTeclarNoMenu}
          className={`absolute z-10 ${larguraMinima} ${CLASSE_PAINEL_FLUTUANTE} ${
            posicao === 'lado'
              ? 'right-full top-0 mr-2'
              : `top-full mt-2 ${CLASSE_ALINHAMENTO[ancoragem] ?? 'left-0'}`
          }`}
        >
          {itens.map((item, indice) => (
            <Fragment key={item.chave}>
            {item.separadorAntes && (
              <div role="separator" className="border-t border-[#23262e]" />
            )}
            <button
              ref={(no) => {
                itensRef.current[indice] = no;
              }}
              type="button"
              role={item.marcado === undefined ? 'menuitem' : 'menuitemradio'}
              aria-checked={item.marcado}
              tabIndex={indice === indiceAtivo ? 0 : -1}
              disabled={item.desabilitado}
              onClick={() => escolher(item)}
              className={`flex w-full items-center ${item.descricao ? 'gap-3 py-2.5' : 'gap-2 py-2'} px-4 text-left text-sm font-semibold outline-none transition-colors focus-visible:bg-white/10 disabled:cursor-auto disabled:opacity-50 cursor-pointer ${
                item.destrutivo
                  ? 'text-red-300 hover:bg-red-500/10 hover:text-red-200'
                  : `${item.marcado ? 'text-white' : 'text-ink-muted'} hover:bg-white/5 hover:text-white`
              }`}
            >
              <item.Icone aria-hidden="true" className="h-4 w-4 shrink-0" />
              {item.descricao ? (
                <span className="flex min-w-0 flex-col leading-snug">
                  {item.rotulo}
                  <span className="text-xs font-normal text-ink-muted">{item.descricao}</span>
                </span>
              ) : (
                item.rotulo
              )}
              {item.marcado && <Check aria-hidden="true" className="ml-auto h-4 w-4 shrink-0 text-neon" />}
            </button>

      {dica && !aberto && (
        <span
          aria-hidden="true"
          className={`pointer-events-none absolute top-full z-10 mt-2.5 ${CLASSE_ALINHAMENTO[ancoragem] ?? 'left-0'} whitespace-nowrap rounded-lg border border-border-chrome ${FUNDO_DA_ILHA} px-2.5 py-1 text-xs font-semibold normal-case leading-normal text-white opacity-0 transition-opacity duration-150 peer-hover:opacity-100 peer-hover:delay-300 peer-focus-visible:opacity-100 motion-reduce:transition-none`}
        >
          {dica}
        </span>
      )}
            </Fragment>
          ))}
        </div>
      )}
    </div>
  );
}

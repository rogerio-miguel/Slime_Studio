import { useEffect, useId, useRef, useState } from 'react';
import { ChevronLeft, ChevronRight, X, Sparkles, Keyboard, AudioLines, Activity, Sun } from 'lucide-react';
import { PRESETS } from './presets.js';
import { IconeEngrenagem } from './Icones.jsx';
import { FUNDO_DO_MENU_DO_PLAYER } from '../components/painelFlutuante.js';

// Ordem de EXIBIÇÃO do dropdown (maior custo de GPU primeiro, pedido do
// usuário 2026-09-24) — não é a mesma coisa que ESCADA_DE_DEGRADACAO de
// presets.js: aquela é a escada de DEGRADAÇÃO manual/automática (só os
// degraus da mesma família visual, ESPECIFICACAO.md §11.3), esta é só a
// ordenação da lista pro usuário escolher. `aa-vl-denoise` fica fora da
// escada de degradação (muda o *look*, não só o custo — é o knob pra fontes
// com grão), mas custa quase o mesmo que `aa-vl-deblur` (mesma base
// clamp+restoreVL+x2VL+restoreM, só o passe final — deblur ou denoise, ~20
// de custo cada — muda), então entra logo ao lado dele aqui, não jogado no
// fim da lista como estava antes.
const ORDEM_DE_EXIBICAO = ['aa-vl-deblur', 'aa-vl-denoise', 'aa-vl', 'a-vl', 'b-vl', 'c-vl', 'a-vl-1x', 'a-m', 'original'];

const opcoesDeQualidade = [
  { valor: 'auto', rotulo: 'Automático (ajusta à GPU)' },
  ...ORDEM_DE_EXIBICAO.map((id) => ({ valor: id, rotulo: PRESETS[id].label })),
];

// Espelha 1:1 os atalhos reais de useAtalhosDeTeclado.js — lista só
// informativa (tela "Controles" abaixo), sem estado pra selecionar, então
// não precisa ficar em sincronia automática com o hook; se um atalho novo
// entrar lá, entra aqui também.
const ATALHOS_DE_TECLADO = [
  { tecla: 'Espaço', acao: 'Reproduzir / pausar' },
  { tecla: '←', acao: 'Retroceder 5 segundos' },
  { tecla: '→', acao: 'Avançar 5 segundos' },
  { tecla: '↑', acao: 'Aumentar volume' },
  { tecla: '↓', acao: 'Diminuir volume' },
  { tecla: 'F', acao: 'Tela cheia' },
  { tecla: 'M', acao: 'Mudo' },
  { tecla: 'C', acao: 'Áudio cinema' },
  { tecla: 'H', acao: 'Estatísticas' },
  { tecla: 'P', acao: 'Avançar 1 minuto e 30 segundos' },
];

// Interruptor visual (pílula + bolinha deslizante) no lugar do texto
// "Ligado/Desligado" de antes — pedido do usuário 2026-09-24. `aria-hidden`:
// o estado acessível continua no `aria-checked` do <button
// role="menuitemcheckbox"> que envolve isto, este span é só a cara do
// estado, não uma segunda fonte de verdade.
function Interruptor({ ligado }) {
  return (
    <span
      aria-hidden="true"
      className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors ${
        ligado ? 'bg-neon' : 'bg-white/20'
      }`}
    >
      <span
        className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
          ligado ? 'translate-x-6' : 'translate-x-1'
        }`}
      />
    </span>
  );
}

// Botão pequeno de header (voltar/fechar) — ghost, sem pill de fundo no
// hover: conferido ao vivo no player real do Disney+ (2026-09-13) que nem
// o fechar nem os ícones do trio central acendem fundo, só o item de lista
// (abaixo) tem destaque de hover.
const classeBotaoHeader =
  'inline-flex h-8 w-8 items-center justify-center rounded-full text-white/80 transition hover:text-white ' +
  'focus-visible:outline focus-visible:outline-2 focus-visible:outline-white focus-visible:outline-offset-2 motion-reduce:transition-none';

// Painel de configurações com 2 telas (raiz → "Qualidade" → lista de
// presets), no mesmo formato do painel de configurações do Disney+
// referenciado pelo usuário: cabeçalho com título + botão de fechar, e a
// tela raiz lista itens de menu — "Qualidade" navega pra sub-tela
// (label à esquerda, sublabel+caret à direita), "Áudio cinema" alterna
// direto sem navegar (label à esquerda, estado Ligado/Desligado à direita).
// Mesmo padrão de acessibilidade do já existente SeletorDeTemporada.jsx
// (aria-haspopup/expanded/controls, role=menu/menuitem, roving tabindex,
// ↑/↓/Home/End, Esc fecha e devolve foco, clique fora fecha) —
// reaproveitado, não reinventado (Escada de Minimalismo + CLAUDE.md §3
// "Reaproveitamento").
export default function MenuDeConfiguracoes({
  presetAtual,
  aoTrocar,
  cinemaHabilitado,
  cinemaFalhou,
  aoAlternarCinema,
  // HUD (telemetria) — era um botão à parte na barra (Activity, lucide-react),
  // movido pra cá 2026-09-24 (pedido do usuário): mesmo toggle role=menuitemcheckbox
  // do "Áudio cinema" abaixo, sem exceção (HUD não tem estado "indisponível").
  hudVisivel,
  aoAlternarHud,
  glowLigado,
  aoAlternarGlow,
}) {
  const [aberto, setAberto] = useState(false);
  const [tela, setTela] = useState('raiz'); // 'raiz' | 'qualidade' | 'controles'
  const [indiceAtivo, setIndiceAtivo] = useState(0);
  const idMenu = useId();
  const containerRef = useRef(null);
  const gatilhoRef = useRef(null);
  const itensRef = useRef([]);

  const opcaoAtual = opcoesDeQualidade.find((opcao) => opcao.valor === presetAtual);
  const rotuloAtual = presetAtual === 'auto' ? 'Automático' : (opcaoAtual?.rotulo ?? presetAtual);
  // Tela 'raiz' tem 5 itens focáveis ("Qualidade" + "Controles" + "Áudio
  // cinema" + "Brilho ambiente" + "Estatísticas"); 'qualidade' tem uma linha por opção;
  // 'controles' é só leitura (ATALHOS_DE_TECLADO, sem seleção) — 0 itens
  // focáveis, a navegação por seta/Home/End não se aplica lá (guarda em
  // aoTeclarNoMenu abaixo). O botão de voltar do cabeçalho fica fora da
  // navegação por seta em qualquer sub-tela (mesmo tratamento do botão de
  // fechar), não entra na contagem.
  const totalDeItens = tela === 'raiz' ? 5 : tela === 'qualidade' ? opcoesDeQualidade.length : 0;

  const fechar = (devolverFoco = true) => {
    setAberto(false);
    setTela('raiz');
    if (devolverFoco) gatilhoRef.current?.focus();
  };

  // Fecha ao clicar fora ou ao focar algo fora do componente — mesmo
  // listener de pointerdown do SeletorDeTemporada.
  useEffect(() => {
    if (!aberto) return;
    const aoApontarFora = (evento) => {
      if (!containerRef.current?.contains(evento.target)) fechar(false);
    };
    document.addEventListener('pointerdown', aoApontarFora);
    return () => document.removeEventListener('pointerdown', aoApontarFora);
  }, [aberto]);

  // Ao abrir ou trocar de tela, foca o primeiro item da tela atual — os refs
  // já estão montados nesse ponto (o efeito roda depois do commit).
  useEffect(() => {
    if (!aberto) return;
    setIndiceAtivo(0);
    itensRef.current[0]?.focus();
  }, [aberto, tela]);

  const escolherQualidade = (valor) => {
    aoTrocar(valor);
    fechar();
  };

  const aoTeclarNoMenu = (evento) => {
    if (evento.key === 'Escape') {
      evento.preventDefault();
      fechar();
    } else if (totalDeItens === 0) {
      // Tela 'controles': nada focável pra navegar (ver comentário acima) —
      // só Esc funciona aqui, o resto passa direto.
    } else if (evento.key === 'ArrowDown') {
      evento.preventDefault();
      const proximo = (indiceAtivo + 1) % totalDeItens;
      setIndiceAtivo(proximo);
      itensRef.current[proximo]?.focus();
    } else if (evento.key === 'ArrowUp') {
      evento.preventDefault();
      const anterior = (indiceAtivo - 1 + totalDeItens) % totalDeItens;
      setIndiceAtivo(anterior);
      itensRef.current[anterior]?.focus();
    } else if (evento.key === 'Home') {
      evento.preventDefault();
      setIndiceAtivo(0);
      itensRef.current[0]?.focus();
    } else if (evento.key === 'End') {
      evento.preventDefault();
      setIndiceAtivo(totalDeItens - 1);
      itensRef.current[totalDeItens - 1]?.focus();
    }
  };

  return (
    // Sem `relative` aqui de propósito: o painel abaixo (`absolute right-0`)
    // precisa ancorar no grupo de botões inteiro (BarraDeControles.jsx), não
    // neste wrapper pequeno — ver comentário lá. `containerRef` continua só
    // pra detecção de clique fora (contains), não depende de position.
    <div ref={containerRef}>
      <button
        ref={gatilhoRef}
        type="button"
        aria-haspopup="menu"
        aria-expanded={aberto}
        aria-controls={aberto ? idMenu : undefined}
        aria-label="Configurações"
        onClick={() => (aberto ? fechar() : setAberto(true))}
        className="inline-flex h-12 min-w-12 items-center justify-center rounded-full text-white/90 transition hover:bg-white/15 hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-white focus-visible:outline-offset-2 motion-reduce:transition-none"
      >
        <IconeEngrenagem width={26} height={26} />
      </button>

      {aberto && (
        <div
          id={idMenu}
          role="menu"
          aria-label="Configurações"
          onKeyDown={aoTeclarNoMenu}
          // `mb-10` (não `mb-2`): "bottom-full" some referência à caixa do
          // próprio botão (56px), então uma margem pequena deixava o painel
          // nascer colado no topo do botão — cobrindo a LINHA DE PROGRESSO
          // (acima dele em BarraDeControles.jsx) e um pedaço do vídeo, em vez
          // de aparecer inteiro por cima da barra inteira, como pedido. 80px
          // cobre a linha de progresso + o respiro entre as duas linhas da
          // barra (pt-8 do container + altura do texto/slider da linha 1 +
          // gap-3 ≈ 68px), sobrando ~12px de vão real entre painel e barra.
          className={`absolute bottom-full right-0 z-10 mb-12 w-96 overflow-hidden rounded-2xl ${FUNDO_DO_MENU_DO_PLAYER} shadow-xl shadow-black/50`}
        >
          {/* Cabeçalho — título alinhado à ESQUERDA (não centralizado: era o
              que estava errado antes), fechar sempre à direita, sem borda
              divisória — assim mesmo no painel real do Disney+. A tela
              "qualidade" acrescenta o voltar à esquerda do título. */}
          <div className="flex items-center gap-3 px-5 py-4">
            {tela !== 'raiz' && (
              <button type="button" aria-label="Voltar" onClick={() => setTela('raiz')} className={classeBotaoHeader}>
                <ChevronLeft width={20} height={20} aria-hidden="true" />
              </button>
            )}
            <h2 className="flex-1 text-left text-lg font-semibold text-white">
              {tela === 'raiz' ? 'Configurações' : tela === 'qualidade' ? 'Qualidade' : 'Controles'}
            </h2>
            <button type="button" aria-label="Fechar" onClick={() => fechar()} className={classeBotaoHeader}>
              <X width={20} height={20} aria-hidden="true" />
            </button>
          </div>

          {tela === 'raiz' ? (
            <div className="px-2 pb-2">
              <button
                ref={(no) => {
                  itensRef.current[0] = no;
                }}
                type="button"
                role="menuitem"
                tabIndex={indiceAtivo === 0 ? 0 : -1}
                onClick={() => setTela('qualidade')}
                className="flex w-full items-center justify-between gap-3 rounded-lg px-3 py-3.5 text-left text-base text-white outline-none transition-colors focus-visible:bg-white/10 hover:bg-white/10"
              >
                <span className="flex items-center gap-3">
                  <Sparkles width={18} height={18} aria-hidden="true" className="text-ink-muted" />
                  <span>Qualidade</span>
                </span>
                <span className="flex items-center gap-1 text-ink-muted">
                  {rotuloAtual}
                  <ChevronRight width={16} height={16} aria-hidden="true" />
                </span>
              </button>
              {/* Controles logo após Qualidade — os dois navegam pra
                  sub-tela (chevron), agrupados antes dos dois toggles
                  abaixo (Áudio cinema/Estatísticas, sem chevron): pedido do
                  usuário 2026-09-24, agrupar por tipo de afordância em vez
                  de intercalar. */}
              <button
                ref={(no) => {
                  itensRef.current[1] = no;
                }}
                type="button"
                role="menuitem"
                tabIndex={indiceAtivo === 1 ? 0 : -1}
                onClick={() => setTela('controles')}
                className="flex w-full items-center justify-between gap-3 rounded-lg px-3 py-3.5 text-left text-base text-white outline-none transition-colors focus-visible:bg-white/10 hover:bg-white/10"
              >
                <span className="flex items-center gap-3">
                  <Keyboard width={18} height={18} aria-hidden="true" className="text-ink-muted" />
                  <span>Controles</span>
                </span>
                <ChevronRight width={16} height={16} aria-hidden="true" className="text-ink-muted" />
              </button>
              {/* Toggle, não navega pra sub-tela (sem chevron) — por isso
                  role="menuitemcheckbox" (booleano), diferente do
                  role="menuitemradio" da lista de qualidade abaixo (opções
                  mutuamente exclusivas). `aria-disabled` (não `disabled`) e o
                  guard dentro do onClick: um <button disabled> sai da ordem
                  de foco e quebra a navegação por seta (roving tabindex)
                  deste menu — aqui só precisa ficar inerte ao clique/Enter,
                  continuando alcançável pelo teclado como qualquer item. */}
              <button
                ref={(no) => {
                  itensRef.current[2] = no;
                }}
                type="button"
                role="menuitemcheckbox"
                aria-checked={!cinemaFalhou && cinemaHabilitado}
                aria-disabled={cinemaFalhou || undefined}
                tabIndex={indiceAtivo === 2 ? 0 : -1}
                onClick={() => {
                  if (!cinemaFalhou) aoAlternarCinema();
                }}
                title={
                  cinemaFalhou
                    ? 'Áudio cinema indisponível: a cadeia de áudio falhou ao montar, seguindo com áudio nativo'
                    : undefined
                }
                className={`flex w-full items-center justify-between gap-3 rounded-lg px-3 py-3.5 text-left text-base outline-none transition-colors focus-visible:bg-white/10 hover:bg-white/10 ${
                  cinemaFalhou ? 'cursor-not-allowed text-ink-muted opacity-50' : 'text-white'
                }`}
              >
                <span className="flex items-center gap-3">
                  <AudioLines width={18} height={18} aria-hidden="true" className="text-ink-muted" />
                  <span>Áudio cinema</span>
                </span>
                {cinemaFalhou ? (
                  <span className="text-ink-muted">Indisponível</span>
                ) : (
                  <Interruptor ligado={cinemaHabilitado} />
                )}
              </button>
              <button
                ref={(no) => {
                  itensRef.current[3] = no;
                }}
                type="button"
                role="menuitemcheckbox"
                aria-checked={glowLigado}
                tabIndex={indiceAtivo === 3 ? 0 : -1}
                onClick={aoAlternarGlow}
                className="flex w-full items-center justify-between gap-3 rounded-lg px-3 py-3.5 text-left text-base text-white outline-none transition-colors focus-visible:bg-white/10 hover:bg-white/10"
              >
                <span className="flex items-center gap-3">
                  <Sun width={18} height={18} aria-hidden="true" className="text-ink-muted" />
                  <span>Brilho ambiente</span>
                </span>
                <Interruptor ligado={glowLigado} />
              </button>
              <button
                ref={(no) => {
                  itensRef.current[4] = no;
                }}
                type="button"
                role="menuitemcheckbox"
                aria-checked={hudVisivel}
                tabIndex={indiceAtivo === 4 ? 0 : -1}
                onClick={aoAlternarHud}
                className="flex w-full items-center justify-between gap-3 rounded-lg px-3 py-3.5 text-left text-base text-white outline-none transition-colors focus-visible:bg-white/10 hover:bg-white/10"
              >
                <span className="flex items-center gap-3">
                  <Activity width={18} height={18} aria-hidden="true" className="text-ink-muted" />
                  <span>Estatísticas</span>
                </span>
                <Interruptor ligado={hudVisivel} />
              </button>
            </div>
          ) : tela === 'controles' ? (
            // Só leitura (ATALHOS_DE_TECLADO acima) — nenhum <button>/role de
            // item de menu aqui de propósito: não há nada pra clicar ou
            // selecionar, e a navegação por seta já fica de fora dessa tela
            // (totalDeItens === 0, ver aoTeclarNoMenu). Sai só pelo Esc ou
            // pelo botão "Voltar" do cabeçalho, os dois fora da contagem.
            <div className="max-h-72 overflow-y-auto px-2 pb-2">
              {ATALHOS_DE_TECLADO.map(({ tecla, acao }) => (
                <div key={tecla} className="flex items-center justify-between gap-3 rounded-lg px-3 py-2.5 text-base text-white">
                  <span>{acao}</span>
                  <kbd className="rounded-md bg-white/10 px-2 py-1 font-mono text-sm text-ink-muted">{tecla}</kbd>
                </div>
              ))}
            </div>
          ) : (
            <div className="max-h-72 overflow-y-auto px-2 pb-2">
              {opcoesDeQualidade.map((opcao, indice) => {
                const selecionada = opcao.valor === presetAtual;
                return (
                  <button
                    key={opcao.valor}
                    ref={(no) => {
                      itensRef.current[indice] = no;
                    }}
                    type="button"
                    role="menuitemradio"
                    aria-checked={selecionada}
                    tabIndex={indiceAtivo === indice ? 0 : -1}
                    onClick={() => escolherQualidade(opcao.valor)}
                    className={`block w-full rounded-lg px-3 py-2.5 text-left text-base outline-none transition-colors focus-visible:bg-white/10 hover:bg-white/10 ${
                      selecionada ? 'font-semibold text-white' : 'text-ink-muted hover:text-white'
                    }`}
                  >
                    {opcao.rotulo}
                  </button>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

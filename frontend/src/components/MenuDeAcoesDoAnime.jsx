import { Check, RefreshCw, Trash2 } from 'lucide-react';
import MenuDeAcoes from './MenuDeAcoes.jsx';

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
// Lógica de acessibilidade/interação (foco, teclado, clique fora) mora em
// `MenuDeAcoes.jsx` (extraído quando `components/CartaoContinuarAssistindo.jsx`
// ganhou o mesmo padrão de menu, pedido do usuário) — este componente só
// monta a lista de itens e a skin do gatilho (quadrado com borda, mesma
// geometria dos outros controles secundários da barra).
export default function MenuDeAcoesDoAnime({
  aoTrocarFonte,
  aoMarcarAssistidos,
  marcandoAssistidos,
  tudoAssistido,
  aoRemover,
}) {
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

  return (
    <MenuDeAcoes
      itens={itens}
      rotuloGatilho="Mais ações"
      classeGatilho={(aberto) =>
        `flex h-8 w-8 items-center justify-center rounded-md border-2 outline-none transition-colors cursor-pointer ${
          aberto
            ? 'border-neon text-white'
            : 'border-border-chrome text-ink-muted hover:border-neon hover:text-white'
        }`
      }
    />
  );
}
